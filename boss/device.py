"""设备连接与 App 生命周期。"""
from __future__ import annotations

import logging

import uiautomator2 as u2


def connect(serial: str = "", log: logging.Logger | None = None) -> u2.Device:
    log = log or logging.getLogger("boss")
    d = u2.connect(serial or None)
    # 注意:部分机型 d.info(deviceInfo RPC)会抛 ApplicationSharedMemory 异常,
    # 这里改用稳定可用的 device_info + window_size 探测设备。
    w, h = d.window_size()
    log.info(
        "已连接设备: Android %s, 分辨率 %sx%s",
        d.device_info.get("version", "?"),
        w,
        h,
    )
    return d


def ensure_app(d: u2.Device, package: str, log: logging.Logger | None = None) -> None:
    log = log or logging.getLogger("boss")
    current = d.app_current().get("package")
    if current == package:
        log.info("App 已在前台: %s", package)
        return
    log.info("启动 App: %s", package)
    d.app_start(package, wait=True)
    d.sleep(3.0)
