#!/usr/bin/env python3
"""兼容入口；命令实现位于 :mod:`boss.cli`。

常用命令：``run``、``conversations``、``dump``、``status``、``records``、
``reset-today`` 和 ``op <name>``。
"""
from __future__ import annotations

import sys

from boss.cli import (
    build_parser,
    cmd_conversations,
    cmd_dump,
    cmd_op,
    cmd_records,
    cmd_reset_today,
    cmd_run,
    cmd_status,
    main,
)
# 兼容旧脚本中从 main 模块导入这些名称的调用方。
from boss.config import ConfigError, load_config
from boss.logger import close_logger, setup_logger
from boss.state import State

__all__ = [
    "build_parser",
    "cmd_conversations",
    "cmd_dump",
    "cmd_op",
    "cmd_records",
    "cmd_reset_today",
    "cmd_run",
    "cmd_status",
    "ConfigError",
    "State",
    "close_logger",
    "load_config",
    "main",
    "setup_logger",
]


if __name__ == "__main__":
    sys.exit(main())
