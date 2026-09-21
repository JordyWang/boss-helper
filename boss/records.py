"""本地记录:把每条投递动作写入 SQLite,便于事后审查与查询。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Tuple

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  ts      TEXT    NOT NULL,
  action  TEXT    NOT NULL,
  title   TEXT,
  salary  TEXT,
  company TEXT,
  note    TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_ts     ON records(ts);
CREATE INDEX IF NOT EXISTS idx_records_action ON records(action);
"""


class Recorder:
    """动作类型:applied / filtered / skipped / error。"""

    def __init__(self, path: str = ".state/records.db"):
        self.path = path
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def add(
        self,
        action: str,
        title: str = "",
        salary: str = "",
        company: str = "",
        note: str = "",
    ) -> None:
        self._conn.execute(
            "INSERT INTO records(ts,action,title,salary,company,note) VALUES(?,?,?,?,?,?)",
            (self._now(), action, title, salary, company, note),
        )
        self._conn.commit()

    def recent(self, n: int = 20) -> List[Tuple[str, str, str, str, str, str]]:
        """返回最近 n 条,时间正序。"""
        cur = self._conn.execute(
            "SELECT ts,action,title,salary,company,note FROM records ORDER BY id DESC LIMIT ?",
            (n,),
        )
        return list(reversed(cur.fetchall()))

    def counts(self) -> Dict[str, int]:
        cur = self._conn.execute("SELECT action, COUNT(*) FROM records GROUP BY action")
        return {row[0]: row[1] for row in cur.fetchall()}

    def total(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM records")
        return int(cur.fetchone()[0])

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
