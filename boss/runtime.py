"""应用启动组装。

把设备连接、App 前台检查、状态仓库和引擎创建集中在这里，CLI 只负责参数
和退出码；其他入口（定时任务、GUI）也可以复用同一工厂。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .artifacts import RunArtifacts
from .config import AppConfig
from .engine import ApplyEngine
from .state import State


def create_engine(
    cfg: AppConfig,
    log: logging.Logger,
    artifacts: Optional[RunArtifacts] = None,
    device: Optional[Any] = None,
    state: Optional[State] = None,
) -> ApplyEngine:
    """连接设备并创建一个可运行的引擎。"""
    if device is None:
        from .device import connect

        device = connect(cfg.serial, log)

    from .device import ensure_app, record_app_version

    # 先记录安装基线，再按需要把 App 切到前台；版本未变化时不会重复写入。
    record_app_version(device, cfg.package, cfg.safety.app_version_path, log)
    ensure_app(device, cfg.package, log)
    if state is None:
        state = State(cfg.safety.state_path)
    return ApplyEngine(device, cfg, state, log, artifacts=artifacts)


__all__ = ["create_engine"]
