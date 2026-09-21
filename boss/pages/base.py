"""页面对象基类:封装 uiautomator2 常用操作 + 人类化随机延时。"""
from __future__ import annotations

import logging
import os
import random
import time
from typing import Dict, List, Optional

from uiautomator2 import Device

from ..config import Timing


class BasePage:
    def __init__(self, d: Device, timing: Timing, log: logging.Logger):
        self.d = d
        self.timing = timing
        self.log = log

    # ---------- 基础动作 ----------
    def el(self, sel: Dict):
        return self.d(**sel)

    def exists(self, sel: Dict, timeout: float = 2.0) -> bool:
        return self.d(**sel).wait(timeout=timeout) is not None

    def wait(self, sel: Dict, timeout: float = 8.0) -> bool:
        return self.d(**sel).wait(timeout=timeout) is not None

    def text_of(self, sel: Dict, timeout: float = 5.0, default: str = "") -> str:
        e = self.d(**sel)
        if e.wait(timeout=timeout):
            return e.get_text() or default
        return default

    def click(self, sel: Dict, timeout: float = 8.0) -> bool:
        e = self.d(**sel)
        if not e.wait(timeout=timeout):
            self.log.debug("点击目标未出现: %s", sel)
            return False
        e.click()
        self.human_delay()
        return True

    def human_delay(self) -> None:
        lo, hi = self.timing.action_delay
        time.sleep(random.uniform(lo, hi))

    def job_delay(self) -> None:
        lo, hi = self.timing.between_jobs
        time.sleep(random.uniform(lo, hi))

    def back(self) -> None:
        self.d.press("back")
        self.human_delay()

    # ---------- 弹窗处理 ----------
    def dismiss_popups(self, close_selectors: List[Dict]) -> None:
        """尝试关闭页面上出现的各种弹窗(广告/权限/评分等)。"""
        for sel in close_selectors:
            if self.exists(sel, timeout=0.8):
                self.log.info("关闭弹窗: %s", sel)
                self.click(sel, timeout=1.5)

    def swipe_up(self) -> None:
        self.d.swipe_ext("up", scale=0.8)
        self.human_delay()

    def screenshot(self, name: Optional[str] = None) -> str:
        os.makedirs("logs", exist_ok=True)
        name = name or f"screen_{int(time.time())}.png"
        path = os.path.join("logs", name)
        self.d.screenshot(path)
        return path
