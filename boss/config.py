"""配置加载:把 config.yaml 解析成强类型对象。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Tuple

import yaml


@dataclass
class Timing:
    action_delay: Tuple[float, float] = (0.8, 2.0)
    between_jobs: Tuple[float, float] = (3.0, 8.0)


@dataclass
class Limits:
    max_apply_per_run: int = 30
    max_apply_per_day: int = 100


@dataclass
class Safety:
    confirm_before_apply: bool = False
    records_csv: str = ".state/records.csv"


@dataclass
class Filters:
    include_keywords: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    min_salary: int = 0


@dataclass
class Greeting:
    messages: List[str] = field(default_factory=list)
    send_manual: bool = False
    send_resume: bool = False


@dataclass
class AppConfig:
    package: str = "com.hpbr.bosszhipin"
    serial: str = ""
    greeting: Greeting = field(default_factory=Greeting)
    limits: Limits = field(default_factory=Limits)
    safety: Safety = field(default_factory=Safety)
    filters: Filters = field(default_factory=Filters)
    timing: Timing = field(default_factory=Timing)


def _pair(value, default: Tuple[float, float]) -> Tuple[float, float]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (float(value[0]), float(value[1]))
    return default


def load_config(path: str = "config.yaml") -> AppConfig:
    if not os.path.exists(path):
        return AppConfig()

    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    app = raw.get("app", {}) or {}
    dev = raw.get("device", {}) or {}
    greet = raw.get("greeting", {}) or {}
    lim = raw.get("limits", {}) or {}
    saf = raw.get("safety", {}) or {}
    fil = raw.get("filters", {}) or {}
    tim = raw.get("timing", {}) or {}

    return AppConfig(
        package=app.get("package", "com.hpbr.bosszhipin"),
        serial=str(dev.get("serial", "") or ""),
        greeting=Greeting(
            messages=list(greet.get("messages", []) or []),
            send_manual=bool(greet.get("send_manual", False)),
            send_resume=bool(greet.get("send_resume", False)),
        ),
        limits=Limits(
            max_apply_per_run=int(lim.get("max_apply_per_run", 30)),
            max_apply_per_day=int(lim.get("max_apply_per_day", 100)),
        ),
        safety=Safety(
            confirm_before_apply=bool(saf.get("confirm_before_apply", False)),
            records_csv=str(saf.get("records_csv", ".state/records.csv")),
        ),
        filters=Filters(
            include_keywords=list(fil.get("include_keywords", []) or []),
            exclude_keywords=list(fil.get("exclude_keywords", []) or []),
            min_salary=int(fil.get("min_salary", 0) or 0),
        ),
        timing=Timing(
            action_delay=_pair(tim.get("action_delay"), (0.8, 2.0)),
            between_jobs=_pair(tim.get("between_jobs"), (3.0, 8.0)),
        ),
    )
