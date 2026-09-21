"""职位过滤规则。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Union

from .config import Filters
from .domain import Job

# 形如 "15-25K"、"15-25K·13薪"、"8千-1.2万"
_SALARY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([Kk千万]?)")


@dataclass
class Decision:
    accept: bool
    reason: str


class JobFilter:
    def __init__(self, cfg: Filters):
        self.cfg = cfg

    def parse_min_salary_k(self, text: str) -> Optional[int]:
        """把薪资文本归一化为最低月薪(单位 K)。无法解析返回 None。"""
        if not text:
            return None
        matches = list(_SALARY_RE.finditer(text))
        if not matches:
            return None
        first = matches[0]
        num = float(first.group(1))
        unit = first.group(2)
        # 中文/英文薪资范围常把单位只写在第二个端点（如 15-25K、
        # 1.5-2万），第一段需要继承后续显式单位。
        if not unit:
            unit = next(
                (match.group(2) for match in matches if match.group(2)),
                "K",
            )
        if unit in ("万",):
            num *= 10
        elif unit == "千":
            num = num  # 已是 K
        return int(num)

    def check(self, title: Union[str, Job], salary_text: str = "") -> Decision:
        if isinstance(title, Job):
            job = title
            title, salary_text = job.title, job.salary
        else:
            title = title or ""

        for kw in self.cfg.exclude_keywords:
            if kw and kw in title:
                return Decision(False, f"命中排除词『{kw}』")

        if self.cfg.include_keywords:
            if not any(kw and kw in title for kw in self.cfg.include_keywords):
                return Decision(False, "未命中任何包含词")

        if self.cfg.min_salary > 0:
            low = self.parse_min_salary_k(salary_text)
            if low is not None and low < self.cfg.min_salary:
                return Decision(False, f"薪资 {low}K < 门槛 {self.cfg.min_salary}K")

        return Decision(True, "通过")

    def check_job(self, job: Job) -> Decision:
        """面向领域对象的显式入口。"""
        return self.check(job)
