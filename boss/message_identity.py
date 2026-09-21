"""聊天消息的身份和去重规则。

Boss 的 UI hierarchy 在当前版本不会把服务端消息 ID 暴露给
uiautomator。这个模块因此把两种情况明确区分开：

* 有 ``message_id``/``messageId`` 等字段时，使用服务端 ID（并绑定会话）；
* 没有 ID 时，使用会话、发送方、类型、文本和时间戳生成本地内容指纹。

内容指纹是 best-effort 标识，不等同于服务端 ID。两个完全相同且没有时间戳
的消息无法仅靠 UI 可靠地区分，调用方不应把这种情况下的去重结果当成事实。
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any, Dict, List, Optional, Tuple


_WHITESPACE_RE = re.compile(r"\s+")

# 这些名字兼容常见的 API/序列化命名；当前 ChatPage 不会填充它们，但保存
# 层可以直接处理将来接入接口返回的消息对象，而不需要再改去重逻辑。
_MESSAGE_ID_FIELDS = (
    "message_id",
    "messageId",
    "msg_id",
    "msgId",
    "server_id",
    "serverId",
    "id",
)
_TIMESTAMP_FIELDS = (
    "timestamp",
    "time",
    "created_at",
    "createdAt",
    "sent_at",
    "sentAt",
)


def normalize_message_value(value: object) -> str:
    """规范化用于身份计算的值，但保留单词之间的空格。"""
    if value is None:
        return ""
    # 某些对象（例如 mock）可能把 id 暴露成方法；方法本身不是消息 ID。
    if callable(value):
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return _WHITESPACE_RE.sub(" ", text).strip()


def message_value(message: object, name: str, default: object = "") -> object:
    """从 dict 或对象读取字段，供归档层复用。"""
    if isinstance(message, Mapping):
        return message.get(name, default)
    return getattr(message, name, default)


def _first_value(message: object, names: Iterable[str]) -> str:
    for name in names:
        value = normalize_message_value(message_value(message, name, ""))
        if value:
            return value
    return ""


def message_id_value(message: object) -> str:
    """读取并规范化常见命名下的服务端消息 ID。"""
    return _first_value(message, _MESSAGE_ID_FIELDS)


def message_timestamp_value(message: object) -> str:
    """读取并规范化常见命名下的消息时间戳。"""
    return _first_value(message, _TIMESTAMP_FIELDS)


def _digest(payload: Dict[str, str]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def message_identity(
    message: object,
    conversation_id: object = "",
    occurrence: Optional[int] = None,
) -> Tuple[str, str]:
    """返回 ``(去重键, 来源)``。

    ``来源`` 为 ``server_id`` 或 ``content``。默认不加入 occurrence，因为
    列表序号会随着滚动而变化；只有调用方明确知道序号具有语义时才传入。
    """
    conversation = normalize_message_value(conversation_id)
    server_id = message_id_value(message)
    if server_id:
        payload = {"conversation": conversation, "message_id": server_id}
        return f"id:{_digest(payload)}", "server_id"

    payload = {
        "conversation": conversation,
        "sender": normalize_message_value(message_value(message, "sender", "")),
        "kind": normalize_message_value(message_value(message, "kind", "")),
        "text": normalize_message_value(message_value(message, "text", "")),
    }
    timestamp = message_timestamp_value(message)
    if timestamp:
        payload["timestamp"] = timestamp
    if occurrence is not None:
        payload["occurrence"] = str(occurrence)
    return f"content:{_digest(payload)}", "content"


def message_fingerprint(
    message: object,
    conversation_id: object = "",
    occurrence: Optional[int] = None,
) -> str:
    """只返回去重键的便捷函数。"""
    return message_identity(message, conversation_id, occurrence)[0]


def deduplicate_messages(
    messages: Iterable[Any], conversation_id: object = ""
) -> List[Any]:
    """按消息身份保留首次出现的消息，保持输入顺序。"""
    result: List[Any] = []
    seen = set()
    for message in messages:
        key = message_fingerprint(message, conversation_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(message)
    return result


__all__ = [
    "deduplicate_messages",
    "message_fingerprint",
    "message_id_value",
    "message_identity",
    "message_timestamp_value",
    "message_value",
    "normalize_message_value",
]
