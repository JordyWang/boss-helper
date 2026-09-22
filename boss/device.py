"""设备连接与 App 生命周期。"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
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


def app_version(d: Any, package: str) -> Dict[str, Any]:
    """读取已安装 APK 的版本信息，不启动或切换 App。"""
    if not package:
        raise ValueError("package 不能为空")
    info = d.app_info(package)
    if not isinstance(info, dict):
        raise RuntimeError("设备返回的 APK 信息不是对象")
    version_name = info.get("versionName", info.get("version_name", ""))
    version_name = str(version_name or "").strip()
    raw_code = info.get("versionCode", info.get("version_code"))
    try:
        version_code = int(raw_code) if raw_code is not None else None
    except (TypeError, ValueError):
        version_code = str(raw_code).strip() if raw_code else None
    if not version_name and version_code is None:
        raise RuntimeError("设备未返回有效的 APK 版本")
    return {
        "package": package,
        "version_name": version_name,
        "version_code": version_code,
    }


def _atomic_json_write(path: str, payload: Dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".app-version-", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def record_app_version(
    d: Any,
    package: str,
    path: str = ".state/app_version.json",
    log: Optional[logging.Logger] = None,
) -> Optional[Dict[str, Any]]:
    """首次检测或版本变化时记录 APK 基线，版本未变则不重复写入。

    记录文件独立于每次运行的 ``run.log``，避免每次启动都重复刷版本信息。
    读取失败只记 debug 并返回 ``None``，不阻断后续的设备/App 操作。
    """
    log = log or logging.getLogger("boss")
    if not path:
        return None
    try:
        current = app_version(d, package)
    except Exception as exc:
        log.debug("读取 APK 版本失败(%s): %s", package, repr(exc))
        return None

    record_path = os.fspath(path)
    previous: Optional[Dict[str, Any]] = None
    try:
        with open(record_path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            previous = loaded
    except (OSError, ValueError, TypeError):
        previous = None

    same = bool(
        previous
        and previous.get("package") == current["package"]
        and previous.get("version_name") == current["version_name"]
        and previous.get("version_code") == current["version_code"]
    )
    if same:
        return current

    now = datetime.now().isoformat(timespec="seconds")
    payload: Dict[str, Any] = dict(current)
    payload["detected_at"] = now
    if previous:
        payload["previous"] = {
            key: previous.get(key)
            for key in ("package", "version_name", "version_code", "detected_at")
            if key in previous
        }
    _atomic_json_write(record_path, payload)

    if previous:
        log.info(
            "检测到 APK 版本变化: %s/%s -> %s/%s",
            previous.get("version_name", "?"),
            previous.get("version_code", "?"),
            current["version_name"] or "?",
            current["version_code"] or "?",
        )
    else:
        log.info(
            "首次记录 APK 版本: %s %s/%s",
            package,
            current["version_name"] or "?",
            current["version_code"] or "?",
        )
    return current


def version_baseline_changed(path: str, current: Optional[Dict[str, Any]]) -> bool:
    """判断版本基线是否会被本次检测更新。

    ``record_app_version`` 为兼容旧调用始终返回当前版本；运行采集层使用
    这个轻量检查，只把首次安装检测或版本变化写入观测表，避免每次启动
    都重复记录相同 APK。
    """
    if not path or not isinstance(current, dict):
        return False
    try:
        with open(os.fspath(path), "r", encoding="utf-8") as fh:
            previous = json.load(fh)
    except (OSError, ValueError, TypeError):
        return True
    if not isinstance(previous, dict):
        return True
    return version_values_changed(previous, current)


def version_values_changed(
    previous: Optional[Dict[str, Any]], current: Optional[Dict[str, Any]]
) -> bool:
    """比较两个 APK 版本对象，忽略检测时间和 previous 字段。"""
    if not isinstance(current, dict) or not isinstance(previous, dict):
        return True
    return not all(
        previous.get(key) == current.get(key)
        for key in ("package", "version_name", "version_code")
    )


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


__all__ = [
    "app_version",
    "connect",
    "ensure_app",
    "health",
    "record_app_version",
    "version_baseline_changed",
    "version_values_changed",
]
