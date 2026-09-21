"""日志:同时输出到控制台与 logs/run.log。"""
from __future__ import annotations

import logging
import os
import sys


def setup_logger(name: str = "boss") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    os.makedirs("logs", exist_ok=True)
    fileh = logging.FileHandler("logs/run.log", encoding="utf-8")
    fileh.setFormatter(fmt)
    logger.addHandler(fileh)

    return logger
