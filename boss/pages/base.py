"""页面对象基类:封装 uiautomator2 常用操作 + 人类化随机延时。"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List, Optional

from ..artifacts import RunArtifacts
from ..config import Timing


class BasePage:
    def __init__(
        self,
        d: Any,
        timing: Timing,
        log: logging.Logger,
        artifacts: Optional[RunArtifacts] = None,
    ):
        self.d = d
        self.timing = timing
        self.log = log
        self.artifacts = (
            artifacts if artifacts is not None else getattr(log, "run_artifacts", None)
        )
        self._owns_artifacts = False

    def close(self) -> None:
        if self._owns_artifacts and self.artifacts is not None:
            artifacts, self.artifacts = self.artifacts, None
            artifacts.close()

    def __del__(self):  # pragma: no cover - 仅作为直接使用页面对象时的兜底。
        try:
            self.close()
        except Exception:
            pass

    # ---------- 基础动作 ----------
    def el(self, sel: Dict):
        return self.d(**sel)

    @staticmethod
    def _wait_result(element: Any, timeout: float) -> bool:
        """统一处理 UiObject.wait 的返回值。

        uiautomator2 在等待超时时返回 ``False``；旧代码用
        ``is not None`` 判断，结果会把 False 当成成功。
        """
        return bool(element.wait(timeout=timeout))

    def exists(self, sel: Dict, timeout: float = 2.0) -> bool:
        return self._wait_result(self.d(**sel), timeout)

    def wait(self, sel: Dict, timeout: float = 8.0) -> bool:
        return self._wait_result(self.d(**sel), timeout)

    def text_of(self, sel: Dict, timeout: float = 5.0, default: str = "") -> str:
        e = self.d(**sel)
        if self._wait_result(e, timeout):
            return e.get_text() or default
        return default

    def click(self, sel: Dict, timeout: float = 8.0) -> bool:
        e = self.d(**sel)
        if not self._wait_result(e, timeout):
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
    def dismiss_popups(self, close_selectors: List[Dict]) -> int:
        """尝试关闭页面上出现的各种弹窗(广告/权限/评分等)。"""
        dismissed = 0
        for sel in close_selectors:
            if self.exists(sel, timeout=0.8):
                self.log.info("关闭弹窗: %s", sel)
                if self.click(sel, timeout=1.5):
                    dismissed += 1
        return dismissed

    def swipe_up(self) -> None:
        self.d.swipe_ext("up", scale=0.8)
        self.human_delay()

    def swipe_down(self) -> None:
        self.d.swipe_ext("down", scale=0.8)
        self.human_delay()

    def screenshot(self, name: Optional[str] = None) -> str:
        if self.artifacts is None:
            # 兼容直接构造页面对象的旧代码，同时仍保证截图归档到独立目录。
            self.artifacts = RunArtifacts.create()
            self._owns_artifacts = True
        return self.artifacts.save_screenshot(self.d, name)

    def dump(self, name: Optional[str] = None) -> str:
        """保存当前 UI 层级到本次运行目录。"""
        if self.artifacts is None:
            self.artifacts = RunArtifacts.create()
            self._owns_artifacts = True
        return self.artifacts.save_dump(self.d, name)
