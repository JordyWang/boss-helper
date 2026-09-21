"""真实设备适配的投递引擎。

业务编排位于 :mod:`boss.application`；本模块只负责把设备和页面对象组装
成应用服务，并保留原来的 ``ApplyEngine`` 导入路径。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .application import ApplyService
from .artifacts import RunArtifacts
from .config import AppConfig
from .filters import JobFilter  # 兼容旧调用方从 engine 读取该策略类。
from .pages.chat import ChatPage
from .pages.home import HomePage
from .pages.job_detail import JobDetailPage
from .ports import StatePort
from .records import Recorder
from .state import State, make_key  # make_key 也曾经是该模块的导出名称。


class ApplyEngine(ApplyService):
    """使用 uiautomator2 页面对象运行批处理。

    ``home/detail/chat/recorder`` 可注入，便于集成测试或替换 UI 适配层；不
    传入时按真实设备创建默认实现。
    """

    def __init__(
        self,
        d: Any,
        cfg: AppConfig,
        state: StatePort,
        log: logging.Logger,
        artifacts: Optional[RunArtifacts] = None,
        home: Optional[Any] = None,
        detail: Optional[Any] = None,
        chat: Optional[Any] = None,
        recorder: Optional[Any] = None,
    ):
        self.d = d
        self.artifacts = (
            artifacts if artifacts is not None else getattr(log, "run_artifacts", None)
        )
        if home is None:
            home = HomePage(d, cfg.timing, log, self.artifacts)
        if detail is None:
            detail = JobDetailPage(d, cfg.timing, log, self.artifacts)
        if chat is None:
            chat = ChatPage(d, cfg.timing, log, self.artifacts)
        if recorder is None and cfg.safety.records_db:
            recorder = Recorder(cfg.safety.records_db)
        super().__init__(
            home=home,
            detail=detail,
            chat=chat,
            cfg=cfg,
            state=state,
            log=log,
            recorder=recorder,
            recover=self._recover_ui,
        )

    def _recover_ui(self) -> None:
        """设备端异常后的最小恢复动作。"""
        self.d.press("back")
        self.home.human_delay()
        self.home.back_to_list()


__all__ = ["ApplyEngine", "ApplyService", "JobFilter", "State", "make_key"]
