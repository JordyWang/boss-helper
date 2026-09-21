"""会话 / 聊天页。每个方法都是一个可单独调用的原子操作。"""
from __future__ import annotations

import html
import random
import re
import time
from typing import List

from ..domain import Message
from ..message_identity import (
    conversation_id_component,
    make_conversation_id,
    normalize_message_value,
)
from .base import BasePage
from .. import selectors as S

_NODE_RE = re.compile(r'<node\b[^>]*?/>')
_BOUNDS_RE = re.compile(r'bounds="\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]"')
_TIME_LABEL_RE = re.compile(
    r"^(?:\d{1,4}[/-]\d{1,2}(?:[/-]\d{1,2})?(?:\s+\d{1,2}:\d{2})?|\d{1,2}:\d{2})$"
)

# 聊天页顶部快捷操作、卡片按钮和已读状态都有文本节点，但它们不是
# 对话内容。按 resource-id 优先过滤，兼容同一文字出现在真实消息中的情况。
_NON_MESSAGE_RESOURCE_IDS = {
    "mtextview",
    "tv_button",
    "tv_dialog_btn_left",
    "tv_dialog_btn_right",
    "mmsgtvstatus",
    "tv_title",
    "tv_sub_title",
}
_NON_MESSAGE_TEXTS = {
    "换电话",
    "查看微信",
    "发简历",
    "不感兴趣",
    "复制微信号",
    "已读",
}


class ChatPage(BasePage):
    def in_chat(self) -> bool:
        """是否处于会话页(以输入框存在为准)。"""
        return self.exists(S.CHAT["chat_flag"], timeout=4.0)

    @staticmethod
    def _split_conversation_subtitle(subtitle: str):
        """拆分当前版本标题栏的“公司 · 职位”格式。

        不认识分隔符时不猜测公司名，把整段保留为 ``subtitle``，避免把
        单独的职位名称错误记录成公司。
        """
        value = normalize_message_value(subtitle)
        parts = re.split(r"\s*[·•｜|]\s*", value, maxsplit=1)
        if len(parts) == 2 and all(parts):
            return parts[0], parts[1], ""
        return "", "", value

    @staticmethod
    def _conversation_component(label: str, value: str) -> str:
        """兼容旧调用方，实际编码委托给统一会话 ID 工具。"""
        return conversation_id_component(label, value)

    def conversation_context(self) -> dict:
        """读取会话栏上下文：公司、职位和招聘者名称。

        APK 当前没有服务端 conversationId；副标题通常是“公司 · 职位”，
        因此这里仅生成本地上下文，不宣称它是官方 ID。
        """
        try:
            recruiter = self.text_of(S.CHAT["conversation_title"], timeout=1.0)
            subtitle = self.text_of(S.CHAT["conversation_subtitle"], timeout=1.0)
        except Exception:
            return {"company": "", "job_title": "", "recruiter": "", "subtitle": ""}
        company, job_title, fallback = self._split_conversation_subtitle(subtitle)
        return {
            "company": company,
            "job_title": job_title,
            "recruiter": normalize_message_value(recruiter),
            "subtitle": fallback,
        }

    def conversation_id(self) -> str:
        """返回包含公司、职位和招聘者的本地会话上下文标识。

        示例：``company=梦虎网络|job_title=ceo|recruiter=尚先生``。
        这不是 Boss 官方 conversationId；调用方仍可用 CLI 的
        ``--conversation-id`` 显式覆盖。
        """
        context = self.conversation_context()
        return make_conversation_id(
            company=context["company"],
            job_title=context["job_title"],
            recruiter=context["recruiter"],
            subtitle=context["subtitle"],
        )

    def _input(self):
        box = self.el(S.CHAT["input"])
        if not box.wait(timeout=5.0):
            self.log.warning("未找到聊天输入框")
            return None
        return box

    def _fill_text(self, box, text: str) -> bool:
        """稳健写入文字:先聚焦,send_keys 为主、set_text 兜底,带重试。
        该机型 uiautomator 服务偶发丢目标,故多次重试。"""
        for attempt in range(3):
            try:
                box.click()
                time.sleep(0.5)
            except Exception:
                pass
            # 主路径:FastInput 输入法直接输入到当前聚焦框,不依赖二次查找元素
            try:
                self.d.send_keys(text, clear=True)
                time.sleep(0.6)
                if self._input_contains(text):
                    return True
            except Exception as exc:
                self.log.debug("send_keys 失败(第%d次): %s", attempt + 1, repr(exc)[:60])
            # 兜底:对元素 set_text
            try:
                box.set_text(text)
                time.sleep(0.6)
                if self._input_contains(text):
                    return True
            except Exception as exc:
                self.log.debug("set_text 失败(第%d次): %s", attempt + 1, repr(exc)[:60])
            time.sleep(1.0)
        return self._input_contains(text)

    def _input_contains(self, text: str) -> bool:
        """从层级中读取输入框的 text 属性,确认目标文字已写入。"""
        try:
            xml = self.d.dump_hierarchy()
        except Exception:
            return False
        m = re.search(
            r'<node[^>]*resource-id="com\.hpbr\.bosszhipin:id/editText_with_scrollbar"[^>]*>',
            xml,
        )
        if not m:
            return False
        node = m.group(0)
        tm = re.search(r'text="([^"]*)"', node)
        return bool(tm) and text[:8] in tm.group(1)

    def _find_send_button(self, input_bounds: dict):
        """发送按钮无 resource-id:输入行内、输入框右侧、可点击的最右 ImageView。
        必须在已输入文字时调用(空输入时该位置是 +号 mMoreIcon)。"""
        cy = (input_bounds["top"] + input_bounds["bottom"]) // 2
        best = None
        for e in self.d(className="android.widget.ImageView", clickable=True):
            b = e.info["bounds"]
            if b["left"] > input_bounds["right"] - 5 and b["top"] <= cy <= b["bottom"]:
                if best is None or b["right"] > best.info["bounds"]["right"]:
                    best = e
        return best

    def type_text(self, text: str) -> bool:
        """仅输入文字,不发送(可用于校验/草稿)。"""
        box = self._input()
        if box is None:
            return False
        return self._fill_text(box, text)

    def send_message(self, text: str) -> bool:
        """在会话框输入并发送一条消息。返回是否成功点击发送。"""
        if not text:
            return False
        box = self._input()
        if box is None:
            return False

        if not self._fill_text(box, text):
            self.log.error("文字写入失败,放弃发送(避免发出空/错消息)")
            return False

        # 重新取输入框边界(键盘弹起后位置会变)
        try:
            bounds = self.el(S.CHAT["input"]).info["bounds"]
        except Exception:
            self.log.error("无法获取输入框边界,放弃发送")
            return False

        btn = self._find_send_button(bounds)
        if btn is None:
            self.log.warning("未定位到发送按钮,改用 IME send 动作兜底")
            self.d.send_action("send")
            self.human_delay()
        else:
            btn.click()
            self.human_delay()

        self.log.info("已发送消息: %s", text)
        return True

    @staticmethod
    def _node_attrs(node_xml: str) -> dict:
        out = {}
        for key in (
            "text",
            "content-desc",
            "resource-id",
            "class",
            "bounds",
            # 目前 APK 的 hierarchy 没有这些属性；保留读取能力，若后续
            # 版本把业务 ID 放到可访问性节点，就能直接升级为服务端去重。
            "message-id",
            "message_id",
            "data-id",
            "id",
            "timestamp",
            "time",
        ):
            # 要求属性名前有边界；否则读取 ``id`` 会误匹配
            # ``resource-id``，把控件类型错误地当成消息 ID。
            m = re.search(rf'(?:^|\s){re.escape(key)}="([^"]*)"', node_xml)
            out[key] = m.group(1) if m else ""
        return out

    def read_messages(self, settle_seconds: float = 1.2) -> List[Message]:
        """解析会话气泡列表。以输入框顶部为界,消息区内的可见文本节点即气泡;
        依据水平位置判定发送方(右 55%+ = 我方,左 45%- = 对方,中间 = 系统)。
        Boss 无稳定的消息 resource-id,故此启发式跨版本更耐用。"""
        try:
            inp = self.el(S.CHAT["input"])
            if not inp.wait(timeout=3.0):
                return []
            input_top = inp.info["bounds"]["top"]
        except Exception:
            return []
        try:
            screen_w, _ = self.d.window_size()
        except Exception:
            return []
        try:
            xml = self.d.dump_hierarchy()
        except Exception as exc:
            self.log.debug("dump_hierarchy 失败: %r", exc)
            return []
        if settle_seconds:
            time.sleep(settle_seconds)
            try:
                xml = self.d.dump_hierarchy()
            except Exception:
                pass

        msgs: List[Message] = []
        for m in _NODE_RE.finditer(xml):
            node = m.group(0)
            a = self._node_attrs(node)
            label = html.unescape((a["text"] or a["content-desc"]).strip())
            if not label:
                continue
            b = _BOUNDS_RE.search(node)
            if not b:
                continue
            x1, y1, x2, y2 = map(int, b.groups())
            cy = (y1 + y2) // 2
            # 消息区:输入框之上,排除顶部标题/按钮(粗略 y>180)
            if not (180 < cy < input_top - 10):
                continue
            rid_lc = a["resource-id"].lower().rsplit("/", 1)[-1]
            if rid_lc in _NON_MESSAGE_RESOURCE_IDS:
                continue
            if label in _NON_MESSAGE_TEXTS or _TIME_LABEL_RE.fullmatch(label):
                continue
            # 过滤整个容器/整行:宽度覆盖大半个屏幕的节点视为容器,不是气泡
            if (x2 - x1) > screen_w * 0.9:
                continue
            cx = (x1 + x2) // 2
            if cx > screen_w * 0.55:
                sender = "me"
            elif cx < screen_w * 0.45:
                sender = "them"
            else:
                sender = "system"
            kind = "text"
            if "resume" in rid_lc or "附件简历" in label or "已发送简历" in label:
                kind = "resume"
            message_id = (
                a["message-id"] or a["message_id"] or a["data-id"] or a["id"]
            )
            timestamp = a["timestamp"] or a["time"]
            msgs.append(
                Message(
                    text=label,
                    sender=sender,
                    kind=kind,
                    timestamp=timestamp,
                    message_id=message_id,
                )
            )
        return msgs

    def summarize(self, msgs: List[Message]) -> str:
        mine = sum(1 for m in msgs if m.sender == "me")
        theirs = sum(1 for m in msgs if m.sender == "them")
        return f"我方 {mine} / 对方 {theirs} / 领先 {mine - theirs}"

    def lead(self, msgs: List[Message]) -> int:
        mine = sum(1 for m in msgs if m.sender == "me")
        theirs = sum(1 for m in msgs if m.sender == "them")
        return mine - theirs

    def has_sent_resume(self, msgs: List[Message]) -> bool:
        return any(m.sender == "me" and m.kind == "resume" for m in msgs)

    def should_send_greeting(self, msgs: List[Message], max_lead: int = 1) -> bool:
        """兜底:我方领先不超过 max_lead 条;若已领先或已发过任何我方文本消息则跳过。"""
        mine_text = [m for m in msgs if m.sender == "me" and m.kind == "text"]
        if mine_text:
            return False
        return self.lead(msgs) < max_lead

    def handle_resume_dialog(self, send_resume: bool, already_sent: bool = False) -> bool:
        """招聘者索要附件简历弹窗:
        - send_resume=true 且未曾发过 → 点'同意'
        - 其他情况 → 点'拒绝'(避免重复发)
        弹窗存在则处理后返回 True,不存在返回 False。"""
        action = "agree" if send_resume and not already_sent else "reject"
        return self.handle_resume_action(action, reason="已发过简历" if already_sent else "策略")

    def resume_dialog_visible(self) -> bool:
        """是否存在索要附件简历弹窗。"""
        return self.exists(S.DETAIL["resume_agree_btn"], timeout=1.5)

    def handle_resume_action(self, action: str, reason: str = "") -> bool:
        """显式处理简历弹窗：``agree`` 或 ``reject``。"""
        if action not in ("agree", "reject"):
            raise ValueError("action 必须是 agree 或 reject")
        agree = S.DETAIL["resume_agree_btn"]
        reject = S.DETAIL["resume_reject_btn"]
        if not self.exists(agree, timeout=1.5):
            return False
        selector = agree if action == "agree" else reject
        label = "同意" if action == "agree" else "拒绝"
        suffix = f"（{reason}）" if reason else ""
        self.log.info("检测到索要简历弹窗 → 点 %s%s", label, suffix)
        return self.click(selector, timeout=3.0)

    def send_greeting(self, messages: List[str]) -> bool:
        """随机选一条招呼语并发送。"""
        if not messages:
            self.log.info("未配置招呼语,跳过发送(App 可能已自动发送预设招呼语)")
            return False
        return self.send_message(random.choice(messages))
