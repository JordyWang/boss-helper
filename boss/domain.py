"""与设备/UI 无关的领域对象。

这些对象让过滤、去重和会话策略可以在没有真机的情况下执行，也避免业务
层在各处散落 ``title/salary/company`` 三元组。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from .identity import make_key


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
