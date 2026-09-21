"""配置加载。

配置文件是这个项目和运行环境之间的边界。以前的实现把所有值直接交给
``int``/``bool``，导致例如 ``send_manual: "false"`` 会被解析成 ``True``，
而一个错误的 YAML section 只会在很后面的 UI 操作中暴露出来。本模块把
解析和轻量校验集中起来，同时保留缺省配置可直接运行的行为。
"""
from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

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
    records_db: str = ".state/records.db"
    state_path: str = ".state/state.json"


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


class ConfigError(ValueError):
    """配置结构或数值不合法。"""


def _section(raw: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = raw.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"配置 section {name!r} 必须是对象")
    return value


def _bool(value: Any, default: bool = False) -> bool:
    """解析 YAML 中的布尔值，避免 ``bool('false')`` 的陷阱。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "on", "1"}:
            return True
        if normalized in {"false", "no", "n", "off", "0"}:
            return False
    raise ConfigError(f"无法解析布尔值: {value!r}")


def _int(value: Any, default: int, *, minimum: int = 0) -> int:
    if value is None:
        return default
    try:
        # 拒绝 1.5 这种容易造成误解的隐式截断，但允许 YAML 的整数。
        number = int(value)
        if isinstance(value, float) and value != number:
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ConfigError(f"无效整数 {value!r}") from exc
    if number < minimum:
        raise ConfigError(f"整数 {number} 不能小于 {minimum}")
    return number


def _pair(value: Any, default: Tuple[float, float]) -> Tuple[float, float]:
    if value is None:
        return default
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ConfigError("时间区间必须是包含两个数字的数组")
    try:
        pair = (float(value[0]), float(value[1]))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ConfigError(f"无效时间区间: {value!r}") from exc
    if any(not math.isfinite(item) or item < 0 for item in pair):
        raise ConfigError(f"时间区间必须是非负有限数字: {value!r}")
    if pair[0] > pair[1]:
        raise ConfigError(f"时间区间下限不能大于上限: {value!r}")
    return pair


def _string_list(value: Any, default: Optional[List[str]] = None) -> List[str]:
    if value is None:
        return list(default or [])
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ConfigError("关键词/消息必须是字符串数组")
    return [str(item).strip() for item in value if str(item).strip()]


def _path(value: Any, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, (str, os.PathLike)):
        raise ConfigError(f"路径必须是字符串: {value!r}")
    return os.fspath(value).strip()


def _text(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def load_config(path: str = "config.yaml") -> AppConfig:
    if not os.path.exists(path):
        return AppConfig()

    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 解析失败: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件: {exc}") from exc
    if raw is None:
        raw = {}

    if not isinstance(raw, Mapping):
        raise ConfigError("配置根节点必须是对象")

    app = _section(raw, "app")
    dev = _section(raw, "device")
    greet = _section(raw, "greeting")
    lim = _section(raw, "limits")
    saf = _section(raw, "safety")
    fil = _section(raw, "filters")
    tim = _section(raw, "timing")

    return AppConfig(
        package=_text(app.get("package"), "com.hpbr.bosszhipin"),
        serial=str(dev.get("serial", "") or "").strip(),
        greeting=Greeting(
            messages=_string_list(greet.get("messages"), []),
            send_manual=_bool(greet.get("send_manual"), False),
            send_resume=_bool(greet.get("send_resume"), False),
        ),
        limits=Limits(
            max_apply_per_run=_int(lim.get("max_apply_per_run"), 30, minimum=0),
            max_apply_per_day=_int(lim.get("max_apply_per_day"), 100, minimum=0),
        ),
        safety=Safety(
            confirm_before_apply=_bool(saf.get("confirm_before_apply"), False),
            records_db=_path(saf.get("records_db"), ".state/records.db"),
            state_path=_path(saf.get("state_path"), ".state/state.json"),
        ),
        filters=Filters(
            include_keywords=_string_list(fil.get("include_keywords"), []),
            exclude_keywords=_string_list(fil.get("exclude_keywords"), []),
            min_salary=_int(fil.get("min_salary"), 0, minimum=0),
        ),
        timing=Timing(
            action_delay=_pair(tim.get("action_delay"), (0.8, 2.0)),
            between_jobs=_pair(tim.get("between_jobs"), (3.0, 8.0)),
        ),
    )
