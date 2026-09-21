"""职位过滤规则。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

from .config import Filters

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
        m = _SALARY_RE.search(text)
        if not m:
            return None
        num = float(m.group(1))
        unit = m.group(2)
        if unit in ("万",):
            num *= 10
        elif unit == "千":
            num = num  # 已是 K
        return int(num)

    def check(self, title: str, salary_text: str = "") -> Decision:
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
