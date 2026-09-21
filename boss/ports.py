"""应用层依赖的端口（Protocol）。

真实设备页面对象实现这些端口；测试或其他客户端可以提供轻量 fake，应用
编排无需知道 uiautomator2 的细节。
"""
from __future__ import annotations

from typing import Any, Iterable, List, Protocol, Sequence

from .domain import Message


class HomePort(Protocol):
    def open_recommend(self) -> bool: ...

    def job_cards(self) -> Sequence[Any]: ...

    def scroll(self, direction: str = "up") -> None: ...

    def job_delay(self) -> None: ...

    def human_delay(self) -> None: ...

    def back_to_list(self) -> bool: ...


class DetailPort(Protocol):
    def title(self) -> str: ...

    def salary(self) -> str: ...

    def communicate(self) -> bool: ...

    def handle_after_communicate(self) -> None: ...


class ChatPort(Protocol):
    def in_chat(self) -> bool: ...

    def read_messages(self, settle_seconds: float = 1.2) -> List[Message]: ...

    def summarize(self, msgs: List[Message]) -> str: ...

    def should_send_greeting(self, msgs: List[Message]) -> bool: ...

    def send_greeting(self, messages: List[str]) -> bool: ...

    def has_sent_resume(self, msgs: List[Message]) -> bool: ...

    def handle_resume_dialog(self, send_resume: bool, already_sent: bool = False) -> bool: ...


class StatePort(Protocol):
    @property
    def applied_today(self) -> int: ...

    def is_seen(self, key: str) -> bool: ...

    def mark_skipped(self, keys: Iterable[str]) -> None: ...

    def mark_applied(self, keys: Iterable[str]) -> None: ...


class RecorderPort(Protocol):
    def add(
        self,
        action: str,
        title: str = "",
        salary: str = "",
        company: str = "",
        note: str = "",
    ) -> None: ...

    def close(self) -> None: ...


__all__ = [
    "ChatPort",
    "DetailPort",
    "HomePort",
    "RecorderPort",
    "StatePort",
]
