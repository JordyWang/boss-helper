"""会话 / 聊天页。每个方法都是一个可单独调用的原子操作。"""
from __future__ import annotations

import random
import re
import time
from typing import List, Optional

from .base import BasePage
from .. import selectors as S


class ChatPage(BasePage):
    def in_chat(self) -> bool:
        """是否处于会话页(以输入框存在为准)。"""
        return self.exists(S.CHAT["chat_flag"], timeout=4.0)

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

    def handle_resume_dialog(self, send_resume: bool) -> bool:
        """招聘者索要附件简历弹窗:send_resume=true 点"同意",否则点"拒绝"。
        弹窗存在则处理后返回 True,不存在返回 False。"""
        agree = S.DETAIL["resume_agree_btn"]
        reject = S.DETAIL["resume_reject_btn"]
        if not self.exists(agree, timeout=1.5):
            return False
        btn = agree if send_resume else reject
        label = "同意" if send_resume else "拒绝"
        self.log.info("检测到索要简历弹窗 → 点 %s", label)
        self.click(btn, timeout=3.0)
        return True

    def send_greeting(self, messages: List[str]) -> bool:
        """随机选一条招呼语并发送。"""
        if not messages:
            self.log.info("未配置招呼语,跳过发送(App 可能已自动发送预设招呼语)")
            return False
        return self.send_message(random.choice(messages))
