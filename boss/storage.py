"""SQLite 数据存储兼容入口。

项目早期把动作记录类命名为 :class:`boss.records.Recorder`。为便于新的
调用方按职责理解，这里提供语义更明确的 ``SQLiteStore``/``DataStore``
别名；实现和数据库文件仍然完全共用 ``Recorder``，不会产生第二套 schema。
"""
from .records import Recorder

SQLiteStore = Recorder
DataStore = Recorder

__all__ = ["DataStore", "Recorder", "SQLiteStore"]
