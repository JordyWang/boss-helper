"""运行状态持久化。

``State`` 是批量流程唯一的去重和限额来源。这里把文件格式的兼容、key
规范化和状态变更集中在一个小对象里，让引擎不需要直接操作内部 dict。
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from typing import Iterable, List, Optional, Union

from .identity import make_key, normalize


class State:
    def __init__(self, path: str = ".state/state.json", *, read_only: bool = False):
        self.path = os.fspath(path) if path else ".state/state.json"
        self.read_only = bool(read_only)
        self._needs_save = False
        self.data = self._load()
        today = date.today().isoformat()
        if self.data.get("date") != today:
            self.data = self._empty(today)
            self._needs_save = True
        if self._needs_save and not self.read_only:
            self.save()

    @staticmethod
    def _empty(day: Optional[str] = None) -> dict:
        return {
            "date": day or date.today().isoformat(),
            "applied_today": 0,
            "applied_keys": [],
            "skipped_keys": [],
        }

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if not isinstance(data, dict):
                    raise ValueError("state root is not an object")
                data.setdefault("date", date.today().isoformat())
                data.setdefault("applied_today", 0)
                data.setdefault("applied_keys", [])
                data.setdefault("skipped_keys", [])
                if self._migrate(data):
                    self._needs_save = True
                return data
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                self._needs_save = True
        return self._empty()

    @staticmethod
    def _migrate(data: dict) -> bool:
        """把老版本未规范化的 key 就地规范化,避免历史条目匹配不上。"""
        changed = False
        for field in ("applied_keys", "skipped_keys"):
            original = data.get(field, [])
            seen, out = set(), []
            values = original
            if isinstance(values, str) or not isinstance(values, (list, tuple, set)):
                values = []
            for k in values:
                nk = "|".join(normalize(p) for p in str(k).split("|"))
                if nk.strip("|") and nk not in seen:
                    seen.add(nk)
                    out.append(nk)
            data[field] = out
            if isinstance(original, (list, tuple, set)):
                changed = changed or list(original) != out
            else:
                changed = changed or original != out
        return changed

    def save(self) -> None:
        if self.read_only:
            raise RuntimeError("只读状态仓库不能写入")
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    @property
    def applied_today(self) -> int:
        try:
            return max(0, int(self.data.get("applied_today", 0)))
        except (TypeError, ValueError):
            return 0

    def applied_keys(self) -> List[str]:
        return list(self.data.get("applied_keys", []))

    def skipped_keys(self) -> List[str]:
        return list(self.data.get("skipped_keys", []))

    @staticmethod
    def _as_keys(keys: Union[str, Iterable[str]]) -> List[str]:
        """规范化一组 key(允许包含 '|',按分段各自规范)。"""
        if isinstance(keys, str):
            keys = [keys]
        out = []
        try:
            iterator = iter(keys)
        except TypeError:
            iterator = iter([keys])
        for k in iterator:
            if not k:
                continue
            nk = "|".join(normalize(seg) for seg in str(k).split("|"))
            if nk.strip("|"):
                if nk not in out:
                    out.append(nk)
        return out

    def is_applied(self, key: str) -> bool:
        normalized = self._as_keys(key)
        return bool(normalized and normalized[0] in self.data.get("applied_keys", []))

    def is_seen(self, key: str) -> bool:
        """已投递或已评估跳过的职位都算见过,避免重复处理。"""
        normalized = self._as_keys(key)
        if not normalized:
            return False
        key = normalized[0]
        return key in self.data.get("applied_keys", []) or key in self.data.get("skipped_keys", [])

    def seen_any(self, keys: Union[str, Iterable[str]]) -> bool:
        return any(self.is_seen(k) for k in self._as_keys(keys))

    def mark_applied(self, keys: Union[str, Iterable[str]]) -> None:
        """登记为已沟通。接受一组等价 key(卡片版+详情页版),只自增一次计数。"""
        if self.read_only:
            raise RuntimeError("只读状态仓库不能写入")
        keys = self._as_keys(keys)
        if not keys:
            return
        applied = self.data.setdefault("applied_keys", [])
        skipped = self.data.setdefault("skipped_keys", [])
        was_applied = any(k in applied for k in keys)
        added = False
        for k in keys:
            if k not in applied:
                applied.append(k)
                added = True
            if k in skipped:
                skipped.remove(k)
        # 卡片 key 和详情 key 可能不同；只要其中一个已经投递过，就不能
        # 再次增加每日计数。
        if added and not was_applied:
            self.data["applied_today"] = self.applied_today + 1
        self.save()

    def mark_skipped(self, keys: Union[str, Iterable[str]]) -> None:
        if self.read_only:
            raise RuntimeError("只读状态仓库不能写入")
        keys = self._as_keys(keys)
        if not keys:
            return
        skipped = self.data.setdefault("skipped_keys", [])
        for k in keys:
            if k not in self.data.get("applied_keys", []) and k not in skipped:
                skipped.append(k)
        self.save()

    def reset_today(self) -> None:
        """重置当日计数，但保留去重 key，避免同一天重复处理同一职位。"""
        if self.read_only:
            raise RuntimeError("只读状态仓库不能写入")
        self.data["applied_today"] = 0
        self.save()
