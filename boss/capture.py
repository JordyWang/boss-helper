"""运行期间的数据采集适配器。

页面/应用层允许注入轻量 fake，因此不能假定每个测试记录器都已经实现
完整的 SQLite API。本模块把可选的 ``save_*`` 调用统一封装：真实
``Recorder`` 会立即落库；旧版或测试记录器没有对应方法时则安全跳过，
不会改变原有设备流程。
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional


def _method(store: Any, name: str):
    if store is None:
        return None
    candidate = getattr(store, name, None)
    return candidate if callable(candidate) else None


def _rollback(store: Any) -> None:
    method = _method(store, "rollback")
    if method is not None:
        try:
            method()
        except Exception:
            pass


def save_job(
    store: Any,
    job: Any,
    *,
    source: str = "",
    run_id: str = "",
    log: Optional[logging.Logger] = None,
) -> str:
    method = _method(store, "save_job")
    if method is None:
        return ""
    try:
        return str(method(job, source=source, run_id=run_id) or "")
    except Exception as exc:  # 采集失败不应阻断真实操作
        _rollback(store)
        if log is not None:
            log.warning("职位数据写入 SQLite 失败: %s", exc)
        return ""


def save_messages(
    store: Any,
    messages: Iterable[Any],
    conversation_id: str = "",
    *,
    run_id: str = "",
    log: Optional[logging.Logger] = None,
) -> int:
    rows = list(messages or [])
    if not rows:
        return 0
    method = _method(store, "save_messages")
    if method is None:
        return 0
    try:
        value = method(rows, conversation_id=conversation_id, run_id=run_id)
        return int(value if value is not None else len(rows))
    except TypeError:
        # 兼容外部注入的旧记录器只接受两个位置参数。
        try:
            value = method(rows, conversation_id)
            return int(value if value is not None else len(rows))
        except Exception as exc:
            _rollback(store)
            if log is not None:
                log.warning("聊天消息写入 SQLite 失败: %s", exc)
            return 0
    except Exception as exc:
        _rollback(store)
        if log is not None:
            log.warning("聊天消息写入 SQLite 失败: %s", exc)
        return 0


def save_conversation(
    store: Any,
    conversation: Any,
    *,
    run_id: str = "",
    source: str = "list",
    include_messages: bool = False,
    log: Optional[logging.Logger] = None,
) -> str:
    """保存会话摘要；``include_messages`` 用于一次性完整归档。"""
    method_name = "save_conversation" if include_messages else "save_conversation_preview"
    method = _method(store, method_name)
    if method is None and not include_messages:
        method = _method(store, "save_conversation")
    if method is None:
        return ""
    try:
        value = method(conversation, run_id=run_id, source=source)
        return str(value or "")
    except TypeError:
        try:
            value = method(conversation)
            return str(value or "")
        except Exception as exc:
            _rollback(store)
            if log is not None:
                log.warning("会话摘要写入 SQLite 失败: %s", exc)
            return ""
    except Exception as exc:
        _rollback(store)
        if log is not None:
            log.warning("会话摘要写入 SQLite 失败: %s", exc)
        return ""


def record_observation(
    store: Any,
    entity_type: str,
    entity_id: str = "",
    payload: Any = None,
    *,
    run_id: str = "",
    log: Optional[logging.Logger] = None,
) -> None:
    method = _method(store, "record_observation")
    if method is None:
        return
    try:
        method(entity_type, entity_id, payload, run_id=run_id)
    except TypeError:
        try:
            method(entity_type, entity_id, payload)
        except Exception as exc:
            _rollback(store)
            if log is not None:
                log.warning("运行观测写入 SQLite 失败: %s", exc)
    except Exception as exc:
        _rollback(store)
        if log is not None:
            log.warning("运行观测写入 SQLite 失败: %s", exc)


__all__ = [
    "record_observation",
    "save_conversation",
    "save_job",
    "save_messages",
]
