"""本地 SQLite 记录与采集数据存储。

历史版本的 ``Recorder`` 只保存投递动作。现在它同时承担运行期间的
数据快照存储：职位卡片、会话摘要和聊天消息一旦被页面层读取，就可以
立即写入同一个 SQLite 文件。所有写入方法都会在返回前提交事务，因此
即使设备操作中途异常，已经读到的数据也不会只停留在内存或 JSON 归档
里。

``records`` 表保持原有字段和查询行为；新增表只使用标准 SQLite，不需要
额外依赖。写入采用主键/去重键幂等更新，重复刷新页面不会产生重复消息。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .identity import make_key
from .message_identity import (
    make_conversation_id,
    message_id_value,
    message_identity,
    message_timestamp_value,
    message_value,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  ts      TEXT    NOT NULL,
  action  TEXT    NOT NULL,
  title   TEXT,
  salary  TEXT,
  company TEXT,
  note    TEXT,
  run_id  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_records_ts     ON records(ts);
CREATE INDEX IF NOT EXISTS idx_records_action ON records(action);

CREATE TABLE IF NOT EXISTS runs (
  run_id      TEXT PRIMARY KEY,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  status      TEXT NOT NULL DEFAULT 'running',
  source      TEXT NOT NULL DEFAULT '',
  log_path    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);

CREATE TABLE IF NOT EXISTS jobs (
  job_key       TEXT PRIMARY KEY,
  title         TEXT NOT NULL DEFAULT '',
  salary        TEXT NOT NULL DEFAULT '',
  company       TEXT NOT NULL DEFAULT '',
  source        TEXT NOT NULL DEFAULT '',
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  last_run_id   TEXT NOT NULL DEFAULT '',
  payload       TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen ON jobs(last_seen_at);

CREATE TABLE IF NOT EXISTS conversations (
  conversation_id TEXT PRIMARY KEY,
  server_id       TEXT NOT NULL DEFAULT '',
  recruiter       TEXT NOT NULL DEFAULT '',
  company         TEXT NOT NULL DEFAULT '',
  job_title       TEXT NOT NULL DEFAULT '',
  salary          TEXT NOT NULL DEFAULT '',
  preview         TEXT NOT NULL DEFAULT '',
  last_time       TEXT NOT NULL DEFAULT '',
  subtitle        TEXT NOT NULL DEFAULT '',
  first_seen_at   TEXT NOT NULL,
  last_seen_at    TEXT NOT NULL,
  last_run_id     TEXT NOT NULL DEFAULT '',
  payload         TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_conversations_last_seen
  ON conversations(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_conversations_server_id
  ON conversations(server_id);

CREATE TABLE IF NOT EXISTS messages (
  conversation_id TEXT NOT NULL,
  dedup_key       TEXT NOT NULL,
  dedup_source    TEXT NOT NULL DEFAULT '',
  message_id      TEXT NOT NULL DEFAULT '',
  sender          TEXT NOT NULL DEFAULT '',
  kind            TEXT NOT NULL DEFAULT '',
  text            TEXT NOT NULL DEFAULT '',
  timestamp       TEXT NOT NULL DEFAULT '',
  first_seen_at   TEXT NOT NULL,
  last_seen_at    TEXT NOT NULL,
  last_run_id     TEXT NOT NULL DEFAULT '',
  payload         TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (conversation_id, dedup_key)
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation
  ON messages(conversation_id, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_messages_message_id
  ON messages(message_id);

CREATE TABLE IF NOT EXISTS observations (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  captured_at   TEXT NOT NULL,
  run_id        TEXT NOT NULL DEFAULT '',
  entity_type   TEXT NOT NULL,
  entity_id     TEXT NOT NULL,
  payload       TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_observations_run
  ON observations(run_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_observations_entity
  ON observations(entity_type, entity_id);
"""


class Recorder:
    """动作、运行和设备采集数据的 SQLite 仓库。

    ``run_id``/``log_path`` 可选。命令入口传入后会自动登记一条运行记录，
    所有后续写入默认关联这次运行。数据库连接使用进程内互斥锁；项目的
    ``.run.lock`` 负责跨进程串行化，这里再保证同一连接不会被交错写入。
    """

    def __init__(
        self,
        path: str = ".state/records.db",
        *,
        run_id: str = "",
        source: str = "",
        log_path: str = "",
    ):
        self.path = path
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # ``check_same_thread=False`` 让本地 Web 服务未来切换为线程模型时仍
        # 可复用同一个仓库；所有操作都经过 ``self._lock`` 串行化。
        self._conn: Optional[sqlite3.Connection] = sqlite3.connect(
            path, timeout=30.0, check_same_thread=False
        )
        self._conn.execute("PRAGMA busy_timeout = 30000")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        self.run_id = str(run_id or "")
        self.source = str(source or "")
        self._conn.executescript(_SCHEMA)
        self._migrate_records_table()
        self._conn.commit()
        if self.run_id:
            self.start_run(self.run_id, source=self.source, log_path=log_path)

    def __enter__(self) -> "Recorder":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close(status="error" if exc_type is not None else "completed")

    @staticmethod
    def _now() -> str:
        # 保留旧 records 表的时间格式，避免现有导出/脚本失效；消息查询
        # 同一秒内的顺序由 SQLite rowid 作为第二排序键保证。
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _migrate_records_table(self) -> None:
        """给旧版 records.db 增加 run_id 列，已有数据原样保留。"""
        conn = self._require_conn()
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(records)").fetchall()
        }
        if "run_id" not in columns:
            conn.execute(
                "ALTER TABLE records ADD COLUMN run_id TEXT NOT NULL DEFAULT ''"
            )

    def _require_conn(self) -> sqlite3.Connection:
        conn = self._conn
        if conn is None:
            raise RuntimeError("SQLite 记录器已经关闭")
        return conn

    @staticmethod
    def _json(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return json.dumps(str(value), ensure_ascii=False)

    @staticmethod
    def _mapping(value: Any) -> Dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        if is_dataclass(value) and not isinstance(value, type):
            try:
                return dict(asdict(value))
            except (TypeError, ValueError):
                pass
        return {}

    def _run_value(self, run_id: str = "") -> str:
        return str(run_id or self.run_id or "")

    def _merged_payload_locked(
        self, table: str, key_column: str, key: str, payload: Any
    ) -> Any:
        """把稀疏的新快照和已有 JSON 合并，避免列表刷新覆盖聊天上下文。"""
        incoming = payload if isinstance(payload, Mapping) else None
        if incoming is None:
            return payload
        # table/key_column 只由内部固定调用方传入，不接受外部 SQL 片段。
        row = self._require_conn().execute(
            f"SELECT payload FROM {table} WHERE {key_column}=?", (key,)
        ).fetchone()
        if not row:
            return dict(incoming)
        try:
            previous = json.loads(row[0] or "{}")
        except (TypeError, ValueError):
            previous = {}
        if not isinstance(previous, Mapping):
            previous = {}
        merged = dict(previous)
        for name, value in incoming.items():
            # 空字符串/空对象是 UI 未提供字段时的常见占位，不覆盖已有值；
            # 非空列表（例如 messages）则始终采用最新快照。
            if value not in ("", None, [], {}):
                merged[name] = value
            elif name not in merged:
                merged[name] = value
        return merged

    def _commit(self) -> None:
        conn = self._require_conn()
        try:
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def rollback(self) -> None:
        """回滚当前未提交事务，供可选采集适配器在异常后复位连接。"""
        with self._lock:
            self._require_conn().rollback()

    def start_run(
        self,
        run_id: str,
        *,
        source: str = "",
        log_path: str = "",
        started_at: str = "",
    ) -> None:
        """登记一次运行；重复调用只更新日志路径/来源，不覆盖开始时间。"""
        run_id = str(run_id or "").strip()
        if not run_id:
            return
        now = started_at or self._now()
        with self._lock:
            conn = self._require_conn()
            conn.execute(
                """
                INSERT INTO runs(run_id, started_at, status, source, log_path)
                VALUES(?, ?, 'running', ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                  source=excluded.source,
                  log_path=excluded.log_path
                """,
                (run_id, now, str(source or self.source or ""), str(log_path or "")),
            )
            self._commit()

    def finish_run(self, status: str = "completed", *, run_id: str = "") -> None:
        run_id = self._run_value(run_id)
        if not run_id:
            return
        with self._lock:
            conn = self._require_conn()
            conn.execute(
                "UPDATE runs SET finished_at=?, status=? WHERE run_id=?",
                (self._now(), str(status or "completed"), run_id),
            )
            self._commit()

    def add(
        self,
        action: str,
        title: str = "",
        salary: str = "",
        company: str = "",
        note: str = "",
    ) -> None:
        if not action or not str(action).strip():
            raise ValueError("记录动作不能为空")
        with self._lock:
            conn = self._require_conn()
            conn.execute(
                """
                INSERT INTO records(ts,action,title,salary,company,note,run_id)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    self._now(),
                    str(action),
                    str(title or ""),
                    str(salary or ""),
                    str(company or ""),
                    str(note or ""),
                    self.run_id,
                ),
            )
            self._commit()

    # ---------- 运行期间的采集数据 ----------

    def save_job(
        self,
        job: Any = None,
        *,
        title: Any = "",
        salary: Any = "",
        company: Any = "",
        source: str = "",
        run_id: str = "",
        payload: Any = None,
    ) -> str:
        """立即保存一份职位快照，返回稳定的职位 key。

        ``job`` 可以是 ``Job``、``JobCard``、字典或任意带有 title/salary/company
        属性的对象。相同职位会更新 ``last_seen_at``，不会重复插入。
        """
        values = self._mapping(job)
        if not values and job is not None:
            values = {
                "title": getattr(job, "title", ""),
                "salary": getattr(job, "salary", ""),
                "company": getattr(job, "company", ""),
            }
        title = str(values.get("title", title) or "").strip()
        salary = str(values.get("salary", salary) or "").strip()
        company = str(values.get("company", company) or "").strip()
        key = str(values.get("job_key", "") or "").strip() or make_key(
            title, salary, company
        )
        if not key:
            return ""
        observed = self._now()
        row_payload = values if payload is None else payload
        run_value = self._run_value(run_id)
        source_value = str(source or values.get("source", "") or "")
        with self._lock:
            conn = self._require_conn()
            row_payload = self._merged_payload_locked(
                "jobs", "job_key", key, row_payload
            )
            conn.execute(
                """
                INSERT INTO jobs(
                  job_key,title,salary,company,source,first_seen_at,last_seen_at,
                  last_run_id,payload
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_key) DO UPDATE SET
                  title=CASE WHEN excluded.title <> '' THEN excluded.title
                             ELSE jobs.title END,
                  salary=CASE WHEN excluded.salary <> '' THEN excluded.salary
                              ELSE jobs.salary END,
                  company=CASE WHEN excluded.company <> '' THEN excluded.company
                               ELSE jobs.company END,
                  source=CASE WHEN excluded.source <> '' THEN excluded.source
                              ELSE jobs.source END,
                  last_seen_at=excluded.last_seen_at,
                  last_run_id=excluded.last_run_id,
                  payload=excluded.payload
                """,
                (
                    key,
                    title,
                    salary,
                    company,
                    source_value,
                    observed,
                    observed,
                    run_value,
                    self._json(row_payload),
                ),
            )
            self._observe_locked("job", key, row_payload, run_value, observed)
            self._commit()
        return key

    @staticmethod
    def _conversation_fallback(values: Mapping[str, Any]) -> str:
        company = values.get("company", "")
        job_title = values.get("job_title", values.get("jobTitle", ""))
        recruiter = values.get("recruiter", values.get("name", ""))
        subtitle = values.get("subtitle", "")
        generated = make_conversation_id(company, job_title, recruiter, subtitle)
        if generated:
            return generated
        digest = sha256(
            json.dumps(dict(values), ensure_ascii=False, sort_keys=True, default=str).encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        return f"unknown:{digest}"

    def _conversation_values(self, conversation: Any) -> Tuple[str, Dict[str, Any]]:
        if conversation is None:
            return "", {}
        values = self._mapping(conversation)
        if not values and conversation is not None:
            as_dict = getattr(conversation, "as_dict", None)
            if callable(as_dict):
                try:
                    candidate = as_dict()
                    if isinstance(candidate, Mapping):
                        values = dict(candidate)
                except Exception:
                    values = {}
        if not values and conversation is not None:
            # 兼容外部页面适配器只暴露属性、不提供 as_dict() 的情况。
            field_names = (
                "conversation_id",
                "local_id",
                "server_id",
                "name",
                "recruiter",
                "company",
                "job_title",
                "salary",
                "preview",
                "time",
                "subtitle",
                "messages",
            )
            values = {}
            for name in field_names:
                try:
                    values[name] = getattr(conversation, name)
                except Exception:
                    continue
        if not values:
            return "", {}
        context = values.get("context")
        if isinstance(context, Mapping):
            merged = dict(context)
            merged.update(values)
            values = merged
        preview = values.get("list_preview")
        if isinstance(preview, Mapping):
            merged = dict(preview)
            merged.update(values)
            values = merged
        explicit_id = str(values.get("conversation_id") or "").strip()
        local_id = str(values.get("local_id") or "").strip()
        chat_id = str(values.get("chat_conversation_id") or "").strip()
        server_id = str(values.get("server_id") or "").strip()
        server_identifier = f"server:{server_id}" if server_id else ""
        if explicit_id.startswith("server:"):
            conversation_id = explicit_id
        elif server_identifier:
            # 服务端 ID 优先于列表本地组合 ID，避免职位标题变化造成新行。
            conversation_id = server_identifier
        else:
            conversation_id = explicit_id or local_id or chat_id
        if not conversation_id:
            conversation_id = self._conversation_fallback(values)
        return conversation_id, values

    def save_conversation_preview(
        self,
        conversation: Any,
        *,
        run_id: str = "",
        source: str = "list",
    ) -> str:
        """保存刚从会话列表读到的摘要，不需要打开聊天。"""
        return self.save_conversation(
            conversation,
            run_id=run_id,
            source=source,
            include_messages=False,
        )

    def save_conversation(
        self,
        conversation: Any,
        *,
        run_id: str = "",
        source: str = "chat",
        include_messages: bool = True,
    ) -> str:
        """幂等保存会话摘要，并在需要时立即保存其中的消息。"""
        conversation_id, values = self._conversation_values(conversation)
        if not conversation_id:
            return ""
        observed = self._now()
        run_value = self._run_value(run_id)
        server_id = str(values.get("server_id", "") or "").strip()
        if not server_id and conversation_id.startswith("server:"):
            server_id = conversation_id.split(":", 1)[1]
        recruiter = str(values.get("recruiter", values.get("name", "")) or "").strip()
        company = str(values.get("company", "") or "").strip()
        job_title = str(values.get("job_title", values.get("jobTitle", "")) or "").strip()
        salary = str(values.get("salary", "") or "").strip()
        preview = str(values.get("preview", "") or "").strip()
        last_time = str(values.get("time", values.get("last_time", "")) or "").strip()
        subtitle = str(values.get("subtitle", "") or "").strip()
        with self._lock:
            conn = self._require_conn()
            values = self._merged_payload_locked(
                "conversations", "conversation_id", conversation_id, values
            )
            conn.execute(
                """
                INSERT INTO conversations(
                  conversation_id,server_id,recruiter,company,job_title,salary,
                  preview,last_time,subtitle,first_seen_at,last_seen_at,last_run_id,
                  payload
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                  server_id=CASE WHEN excluded.server_id <> '' THEN excluded.server_id
                                 ELSE conversations.server_id END,
                  recruiter=CASE WHEN excluded.recruiter <> '' THEN excluded.recruiter
                                 ELSE conversations.recruiter END,
                  company=CASE WHEN excluded.company <> '' THEN excluded.company
                               ELSE conversations.company END,
                  job_title=CASE WHEN excluded.job_title <> '' THEN excluded.job_title
                                 ELSE conversations.job_title END,
                  salary=CASE WHEN excluded.salary <> '' THEN excluded.salary
                              ELSE conversations.salary END,
                  preview=CASE WHEN excluded.preview <> '' THEN excluded.preview
                               ELSE conversations.preview END,
                  last_time=CASE WHEN excluded.last_time <> '' THEN excluded.last_time
                                 ELSE conversations.last_time END,
                  subtitle=CASE WHEN excluded.subtitle <> '' THEN excluded.subtitle
                                ELSE conversations.subtitle END,
                  last_seen_at=excluded.last_seen_at,
                  last_run_id=excluded.last_run_id,
                  payload=excluded.payload
                """,
                (
                    conversation_id,
                    server_id,
                    recruiter,
                    company,
                    job_title,
                    salary,
                    preview,
                    last_time,
                    subtitle,
                    observed,
                    observed,
                    run_value,
                    self._json(values),
                ),
            )
            self._observe_locked(
                "conversation", conversation_id, values, run_value, observed
            )
            if include_messages:
                messages = values.get("messages") or []
                for message in messages:
                    self._save_message_locked(
                        message, conversation_id, run_value, observed
                    )
            self._commit()
        return conversation_id

    def _save_message_locked(
        self,
        message: Any,
        conversation_id: str,
        run_id: str,
        observed: Optional[str] = None,
    ) -> str:
        conversation_id = str(conversation_id or "").strip() or "unknown"
        observed = observed or self._now()
        dedup_key, dedup_source = message_identity(message, conversation_id)
        text = str(message_value(message, "text", "") or "")
        sender = str(message_value(message, "sender", "") or "")
        kind = str(message_value(message, "kind", "") or "")
        timestamp = message_timestamp_value(message)
        message_id = message_id_value(message)
        payload = {
            "text": text,
            "sender": sender,
            "kind": kind,
            "timestamp": timestamp,
            "message_id": message_id,
            "conversation_id": conversation_id,
            "dedup_key": dedup_key,
            "dedup_source": dedup_source,
        }
        conn = self._require_conn()
        conn.execute(
            """
            INSERT INTO messages(
              conversation_id,dedup_key,dedup_source,message_id,sender,kind,text,
              timestamp,first_seen_at,last_seen_at,last_run_id,payload
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(conversation_id,dedup_key) DO UPDATE SET
              dedup_source=excluded.dedup_source,
              message_id=CASE WHEN excluded.message_id <> '' THEN excluded.message_id
                               ELSE messages.message_id END,
              sender=excluded.sender,
              kind=excluded.kind,
              text=excluded.text,
              timestamp=CASE WHEN excluded.timestamp <> '' THEN excluded.timestamp
                             ELSE messages.timestamp END,
              last_seen_at=excluded.last_seen_at,
              last_run_id=excluded.last_run_id,
              payload=excluded.payload
            """,
            (
                conversation_id,
                dedup_key,
                dedup_source,
                message_id,
                sender,
                kind,
                text,
                timestamp,
                observed,
                observed,
                run_id,
                self._json(payload),
            ),
        )
        self._observe_locked("message", dedup_key, payload, run_id, observed)
        return dedup_key

    def save_message(
        self,
        message: Any,
        conversation_id: str = "",
        *,
        run_id: str = "",
    ) -> str:
        """立即保存一条消息，返回其去重键。"""
        with self._lock:
            key = self._save_message_locked(
                message, conversation_id, self._run_value(run_id)
            )
            self._commit()
            return key

    def save_messages(
        self,
        messages: Iterable[Any],
        conversation_id: str = "",
        *,
        run_id: str = "",
    ) -> int:
        """立即保存一批刚读取的消息，返回输入条数。

        每次调用都在同一个短事务中提交；消息以会话 + dedup_key 幂等更新，
        因此滚动/刷新导致的重复读取不会污染消息表。
        """
        rows = list(messages or [])
        if not rows:
            return 0
        with self._lock:
            run_value = self._run_value(run_id)
            for message in rows:
                self._save_message_locked(message, conversation_id, run_value)
            self._commit()
        return len(rows)

    def record_observation(
        self,
        entity_type: str,
        entity_id: str = "",
        payload: Any = None,
        *,
        run_id: str = "",
    ) -> None:
        """记录任意已获取数据（设备健康、截图路径等）的原始观测。"""
        entity_type = str(entity_type or "unknown").strip() or "unknown"
        entity_id = str(entity_id or "").strip()
        with self._lock:
            self._observe_locked(
                entity_type,
                entity_id,
                payload if payload is not None else {},
                self._run_value(run_id),
                self._now(),
            )
            self._commit()

    def _observe_locked(
        self,
        entity_type: str,
        entity_id: str,
        payload: Any,
        run_id: str,
        captured_at: str,
    ) -> None:
        self._require_conn().execute(
            """
            INSERT INTO observations(captured_at,run_id,entity_type,entity_id,payload)
            VALUES(?,?,?,?,?)
            """,
            (
                captured_at,
                str(run_id or ""),
                str(entity_type or "unknown"),
                str(entity_id or ""),
                self._json(payload),
            ),
        )

    def counts_by_table(self) -> Dict[str, int]:
        """返回采集表行数，便于 CLI/健康检查快速确认落库状态。"""
        with self._lock:
            conn = self._require_conn()
            result = {}
            for table in ("records", "runs", "jobs", "conversations", "messages", "observations"):
                result[table] = int(
                    conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
            return result

    def recent_conversations(self, n: int = 20) -> List[Dict[str, Any]]:
        """返回最近读取的会话摘要，供 CLI/Web 查询使用。"""
        try:
            n = max(1, min(int(n), 500))
        except (TypeError, ValueError):
            n = 20
        with self._lock:
            cur = self._require_conn().execute(
                """
                SELECT conversation_id,server_id,recruiter,company,job_title,
                       salary,preview,last_time,subtitle,first_seen_at,last_seen_at,
                       last_run_id,payload
                FROM conversations ORDER BY last_seen_at DESC LIMIT ?
                """,
                (n,),
            )
            columns = [item[0] for item in cur.description]
            rows = []
            for row in cur.fetchall():
                item = dict(zip(columns, row))
                try:
                    item["payload"] = json.loads(item["payload"] or "{}")
                except (TypeError, ValueError):
                    pass
                rows.append(item)
            return rows

    def messages_for(
        self, conversation_id: str, n: int = 500
    ) -> List[Dict[str, Any]]:
        """按会话 ID返回去重后的消息，时间正序。"""
        conversation_id = str(conversation_id or "").strip()
        if not conversation_id:
            return []
        try:
            n = max(1, min(int(n), 5000))
        except (TypeError, ValueError):
            n = 500
        with self._lock:
            cur = self._require_conn().execute(
                """
                SELECT conversation_id,dedup_key,dedup_source,message_id,sender,
                       kind,text,timestamp,first_seen_at,last_seen_at,last_run_id,
                       payload
                FROM messages WHERE conversation_id=?
                ORDER BY first_seen_at ASC, rowid ASC LIMIT ?
                """,
                (conversation_id, n),
            )
            columns = [item[0] for item in cur.description]
            rows = []
            for row in cur.fetchall():
                item = dict(zip(columns, row))
                try:
                    item["payload"] = json.loads(item["payload"] or "{}")
                except (TypeError, ValueError):
                    pass
                rows.append(item)
            return rows

    def recent(self, n: int = 20) -> List[Tuple[str, str, str, str, str, str]]:
        """返回最近 n 条,时间正序。"""
        try:
            n = int(n)
        except (TypeError, ValueError) as exc:
            raise ValueError("n 必须是整数") from exc
        if n <= 0:
            return []
        with self._lock:
            cur = self._require_conn().execute(
                "SELECT ts,action,title,salary,company,note FROM records ORDER BY id DESC LIMIT ?",
                (n,),
            )
            return list(reversed(cur.fetchall()))

    def counts(self) -> Dict[str, int]:
        with self._lock:
            cur = self._require_conn().execute(
                "SELECT action, COUNT(*) FROM records GROUP BY action"
            )
            return {row[0]: row[1] for row in cur.fetchall()}

    def total(self) -> int:
        with self._lock:
            cur = self._require_conn().execute("SELECT COUNT(*) FROM records")
            return int(cur.fetchone()[0])

    def close(self, *, status: str = "completed") -> None:
        """关闭连接；若有关联运行则补写结束状态。"""
        conn = self._conn
        if conn is None:
            return
        with self._lock:
            try:
                if self.run_id:
                    conn.execute(
                        "UPDATE runs SET finished_at=?, status=? WHERE run_id=?",
                        (self._now(), str(status or "completed"), self.run_id),
                    )
                    conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
                self._conn = None


__all__ = ["Recorder"]
