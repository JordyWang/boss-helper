"""与设备/UI 无关的领域对象。

这些对象让过滤、去重和会话策略可以在没有真机的情况下执行，也避免业务
层在各处散落 ``title/salary/company`` 三元组。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from .identity import make_key
from .message_identity import message_fingerprint


@dataclass(frozen=True)
class Job:
    title: str
    salary: str = ""
    company: str = ""

    @property
    def key(self) -> str:
        return make_key(self.title, self.salary, self.company)

    @property
    def valid(self) -> bool:
        return bool(self.title.strip())

    @classmethod
    def from_values(cls, title: object = "", salary: object = "", company: object = "") -> "Job":
        return cls(str(title or "").strip(), str(salary or "").strip(), str(company or "").strip())


class Message(NamedTuple):
    text: str
    sender: str  # 'me' | 'them' | 'system'
    kind: str  # 'text' | 'resume'
    # 当前 UI 解析器没有这些字段；保留可选槽位，接入服务端/API 数据后
    # 可以无损升级到真正的消息 ID/时间戳，而不改变上层端口。
    timestamp: str = ""
    message_id: str = ""

    @property
    def fingerprint(self) -> str:
        """当前会话未知时的本地 best-effort 去重指纹。"""
        return message_fingerprint(self)

    def conversation_fingerprint(self, conversation_id: str = "") -> str:
        """带会话上下文的去重指纹；有服务端 ID 时优先使用它。"""
        return message_fingerprint(self, conversation_id)


@dataclass(frozen=True)
class RunSummary:
    """一次批处理的可观测结果。"""

    applied: int = 0
    filtered: int = 0
    skipped: int = 0
    errors: int = 0
    stopped: bool = False


@dataclass(frozen=True)
class JobPreview:
    """dry-run 扫描到的职位及其决策，不会修改状态。"""

    job: Job
    accepted: bool
    reason: str
    seen: bool


__all__ = ["Job", "JobPreview", "Message", "RunSummary"]
