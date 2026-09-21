"""运行级日志配置。

日志器不再写一个会被下一次执行覆盖/混用的固定 ``logs/run.log``，而是
绑定到 :class:`~boss.artifacts.RunArtifacts` 当前实例的目录。
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from .artifacts import RunArtifacts


def setup_logger(
    name: str = "boss", artifacts: Optional[RunArtifacts] = None
) -> logging.Logger:
    """返回绑定到本次执行目录的 logger。

    为了兼容旧调用，未传 ``artifacts`` 时会复用当前 logger 的上下文；若
    第一次调用则自动创建一个执行目录。
    """
    logger = logging.getLogger(name)
    current = getattr(logger, "run_artifacts", None)
    if artifacts is None and isinstance(current, RunArtifacts):
        artifacts = current
    if artifacts is None:
        artifacts = RunArtifacts.create()

    # 同一进程中可能连续调用 CLI（例如测试或调度器），需要切换文件而
    # 不能因为旧 handler 存在就继续写上一轮日志。
    if current is artifacts and any(
        getattr(handler, "_boss_managed", False) for handler in logger.handlers
    ):
        return logger

    for handler in list(logger.handlers):
        if getattr(handler, "_boss_managed", False):
            logger.removeHandler(handler)
            handler.close()
    if isinstance(current, RunArtifacts) and current is not artifacts:
        current.close()

    logger.setLevel(logging.INFO)
    logger.propagate = False
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"
    )

    # 保留旧版 CLI 的控制台行为：日志同时显示在 stdout 和本次运行文件中。
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console._boss_managed = True
    logger.addHandler(console)

    fileh = logging.FileHandler(str(artifacts.log_path), encoding="utf-8")
    fileh.setFormatter(fmt)
    fileh._boss_managed = True
    logger.addHandler(fileh)
    logger.run_artifacts = artifacts

    return logger


def close_logger(name: str = "boss") -> None:
    """关闭由 ``setup_logger`` 创建的 handler。"""
    logger = logging.getLogger(name)
    for handler in list(logger.handlers):
        if getattr(handler, "_boss_managed", False):
            logger.removeHandler(handler)
            handler.close()
    artifacts = getattr(logger, "run_artifacts", None)
    if hasattr(logger, "run_artifacts"):
        delattr(logger, "run_artifacts")
    if isinstance(artifacts, RunArtifacts):
        artifacts.close()
