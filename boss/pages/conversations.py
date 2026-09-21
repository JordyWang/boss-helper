"""会话列表页：只负责导航和读取会话摘要，不执行发送类动作。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Set, Tuple

from ..message_identity import make_conversation_id, normalize_message_value
from .. import selectors as S
from .base import BasePage


@dataclass
class ConversationPreview:
    """会话列表中的一行摘要及其可点击 UI 行对象。"""

    index: int
    name: str = ""
    company: str = ""
    job_title: str = ""
    salary: str = ""
    preview: str = ""
    time: str = ""
    row: Any = None
    # 目前真机列表没有暴露官方 conversationId；保留这个字段供以后接入
    # 接口或新版本 UI 时使用。若存在，conversation_id 优先返回它。
    server_id: str = ""

    @property
    def key(self) -> str:
        """本地列表去重键；不把可变的列表 index 纳入身份。"""
        values = [self.name, self.company, self.job_title, self.preview]
        key = "|".join(normalize_message_value(value) for value in values)
        return key or f"row:{self.index}"

    @property
    def local_id(self) -> str:
        """由列表稳定字段组成的本地会话 ID。"""
        return make_conversation_id(
            company=self.company,
            job_title=self.job_title,
            recruiter=self.name,
        )

    @property
    def conversation_id(self) -> str:
        """用于匹配和归档的会话 ID。

        新版本若提供服务端 ID，优先使用 ``server:<id>`` 命名空间；当前
        APK 没有该字段时返回 ``company=...|job_title=...|recruiter=...``。
        """
        server_id = normalize_message_value(self.server_id)
        return f"server:{server_id}" if server_id else self.local_id

    @property
    def context_id(self) -> str:
        """旧调用方兼容别名；新代码请使用 :attr:`conversation_id`。"""
        return self.conversation_id

    def match_ids(self) -> Tuple[str, ...]:
        """返回可用于精确匹配的 ID 别名，去重后保持顺序。"""
        values = [self.conversation_id, self.local_id]
        server_id = normalize_message_value(self.server_id)
        if server_id:
            values.extend((server_id, f"server:{server_id}"))
        result = []
        seen = set()
        for value in values:
            value = normalize_message_value(value)
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return tuple(result)

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "company": self.company,
            "job_title": self.job_title,
            "salary": self.salary,
            "preview": self.preview,
            "time": self.time,
            "key": self.key,
            "conversation_id": self.conversation_id,
            "local_id": self.local_id,
            "server_id": normalize_message_value(self.server_id),
        }


class ConversationListPage(BasePage):
    """Boss 消息列表。

    该页面只打开已有会话并读取内容，不调用发送、简历或交换联系方式操作。
    """

    @staticmethod
    def _split_position(value: str):
        text = normalize_message_value(value)
        parts = re.split(r"\s*[|｜·•]\s*", text, maxsplit=1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return "", text

    @staticmethod
    def _child_text(row: Any, selector: dict) -> str:
        try:
            element = row.child(**selector)
            if hasattr(element, "wait") and not element.wait(timeout=1.0):
                return ""
            return normalize_message_value(element.get_text() or "")
        except Exception:
            return ""

    def open_list(self) -> bool:
        """进入底部消息 Tab 并等待会话列表。"""
        # 已经在列表页时不要重复点击 Tab；如果调用方从聊天页启动，先用
        # 有限次数返回，避免把设备退回 App 外部或其他应用。
        if self.in_list():
            return True
        tab = self.d(**S.CONVERSATIONS["tab"])
        if not self._wait_result(tab, timeout=2.0):
            for _ in range(3):
                try:
                    self.d.press("back")
                    self.human_delay()
                except Exception:
                    break
                if self.in_list():
                    return True
                tab = self.d(**S.CONVERSATIONS["tab"])
                if self._wait_result(tab, timeout=1.0):
                    break
        if not self._wait_result(tab, timeout=5.0):
            self.log.warning("未找到底部'消息'导航")
            return False
        try:
            tab.click()
            self.human_delay()
        except Exception as exc:
            self.log.warning("打开消息列表失败: %r", exc)
            return False
        return self._wait_list(timeout=8.0)

    def _wait_list(self, timeout: float = 8.0) -> bool:
        return self.wait(S.CONVERSATIONS["list"], timeout=timeout)

    def in_list(self) -> bool:
        try:
            return self.d(**S.CONVERSATIONS["list"]).count > 0
        except Exception:
            return False

    def visible(self) -> List[ConversationPreview]:
        """读取当前屏幕可见会话，不滚动、不点击。"""
        container = self.d(**S.CONVERSATIONS["list"])
        if not self._wait_result(container, timeout=5.0):
            return []
        try:
            rows = container.child(**S.CONVERSATIONS["row"])
            count = rows.count
        except Exception as exc:
            self.log.debug("读取会话行失败: %r", exc)
            return []

        result: List[ConversationPreview] = []
        for index in range(count):
            try:
                row = rows[index]
                info = row.info
                if info.get("clickable") is False or info.get("enabled") is False:
                    continue
            except Exception:
                continue
            name = self._child_text(row, S.CONVERSATIONS["name"])
            position = self._child_text(row, S.CONVERSATIONS["position"])
            # 空行/装饰行不是会话，避免误点。
            if not name and not position:
                continue
            company, job_title = self._split_position(position)
            result.append(
                ConversationPreview(
                    index=index,
                    name=name,
                    company=company,
                    job_title=job_title,
                    salary=self._child_text(row, S.CONVERSATIONS["salary"]),
                    preview=self._child_text(row, S.CONVERSATIONS["preview"]),
                    time=self._child_text(row, S.CONVERSATIONS["time"]),
                    row=row,
                )
            )
        return result

    @staticmethod
    def _matches(preview: ConversationPreview, conversation_id: str) -> bool:
        target = normalize_message_value(conversation_id)
        if not target:
            return False
        return target in preview.match_ids()

    @staticmethod
    def _screen_signature(entries: Iterable[ConversationPreview]) -> Tuple[str, ...]:
        """生成滚动去重签名，不依赖会变化的行号或最近消息时间。"""
        values = []
        for entry in entries:
            ids = entry.match_ids()
            values.append(ids[0] if ids else entry.key)
        return tuple(values)

    def find_by_id(
        self,
        conversation_id: str,
        max_scrolls: int = 8,
    ) -> Optional[ConversationPreview]:
        """在当前列表及有限滚动范围内查找会话，不打开任何聊天。

        ``max_scrolls`` 是安全上限，防止列表加载异常时无限滑动；默认只查
        当前屏和少量后续屏，不会为了一个 ID 自动遍历全部历史会话。
        """
        target = normalize_message_value(conversation_id)
        if not target:
            return None
        try:
            max_scrolls = max(0, int(max_scrolls))
        except (TypeError, ValueError):
            max_scrolls = 0

        seen_screens: Set[Tuple[str, ...]] = set()
        for _round in range(max_scrolls + 1):
            entries = self.visible()
            for entry in entries:
                if self._matches(entry, target):
                    return entry
            signature = self._screen_signature(entries)
            if signature in seen_screens:
                # 滑动没有带来新内容，继续请求只会重复点击/滑动。
                break
            seen_screens.add(signature)
            if _round >= max_scrolls or not entries:
                break
            self.scroll()
        return None

    def open_conversation(self, preview: ConversationPreview) -> bool:
        """点击列表行；只允许点击 visible() 返回的可点击行对象。"""
        row = preview.row
        if row is None:
            return False
        try:
            row.click()
            self.human_delay()
            return True
        except Exception as exc:
            self.log.warning("打开会话失败[%s]: %r", preview.name, exc)
            return False

    def scroll(self) -> None:
        """向上加载下一屏会话。"""
        self.swipe_up()
        self._wait_list(timeout=5.0)

    def back_to_list(self, max_backs: int = 3) -> bool:
        """从聊天页返回消息列表，避免误回到其他 Tab。"""
        for _ in range(max_backs):
            if self.in_list():
                return True
            self.d.press("back")
            self.human_delay()
        return self.in_list()


__all__ = ["ConversationListPage", "ConversationPreview"]
