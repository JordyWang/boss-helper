"""设备连接与 App 生命周期。"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional


def connect(serial: str = "", log: Optional[logging.Logger] = None) -> Any:
    log = log or logging.getLogger("boss")
    try:
        import uiautomator2 as u2
    except ImportError as exc:
        raise RuntimeError(
            "缺少 uiautomator2 依赖，请先执行: pip install -r requirements.txt"
        ) from exc
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


def ensure_app(d: Any, package: str, log: Optional[logging.Logger] = None) -> None:
    log = log or logging.getLogger("boss")
    current = d.app_current().get("package")
    if current == package:
        log.info("App 已在前台: %s", package)
        return
    log.info("启动 App: %s", package)
    d.app_start(package, wait=True)
    d.sleep(3.0)


def health(d: Any, package: str = "") -> Dict[str, Any]:
    """读取设备和当前页面的只读诊断信息。

    诊断接口尽量逐项容错，避免某个机型的 RPC 异常掩盖其他信息。
    """
    result: Dict[str, Any] = {"package_expected": package or ""}
    try:
        current = d.app_current() or {}
        result["package"] = current.get("package", "")
        result["activity"] = current.get("activity", "")
    except Exception as exc:
        result["app_current_error"] = repr(exc)
    try:
        result["window_size"] = tuple(d.window_size())
    except Exception as exc:
        result["window_size_error"] = repr(exc)
    try:
        info = d.device_info or {}
        result["android_version"] = info.get("version", "")
        result["model"] = info.get("model", "")
    except Exception as exc:
        result["device_info_error"] = repr(exc)
    if package:
        result["package_ok"] = result.get("package") == package
    return result
