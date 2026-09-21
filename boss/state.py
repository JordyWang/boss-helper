"""运行状态持久化:记录每日已投递数与已处理职位,支持跨运行去重与每日限额。"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import date
from typing import Iterable, List, Union

_WS = re.compile(r"\s+")


def normalize(s: str) -> str:
    """统一全/半角并去掉所有空白,避免同一职位因卡片/详情页文本微差被当作两条记录。"""
    if not s:
        return ""
    return _WS.sub("", unicodedata.normalize("NFKC", s)).strip("&@・·")


def make_key(title: str, salary: str = "", company: str = "") -> str:
    parts = [normalize(title), normalize(salary), normalize(company)]
    if not any(parts):
        return ""
    return "|".join(parts)


class State:
    def __init__(self, path: str = ".state/state.json"):
        self.path = path
        self.data = self._load()
        today = date.today().isoformat()
        if self.data.get("date") != today:
            self.data = {
                "date": today,
                "applied_today": 0,
                "applied_keys": [],
                "skipped_keys": [],
            }
            self.save()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    data.setdefault("skipped_keys", [])
                    self._migrate(data)
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "date": date.today().isoformat(),
            "applied_today": 0,
            "applied_keys": [],
            "skipped_keys": [],
        }

    @staticmethod
    def _migrate(data: dict) -> None:
        """把老版本未规范化的 key 就地规范化,避免历史条目匹配不上。"""
        for field in ("applied_keys", "skipped_keys"):
            seen, out = set(), []
            for k in data.get(field, []):
                nk = "|".join(normalize(p) for p in str(k).split("|"))
                if nk and nk not in seen:
                    seen.add(nk)
                    out.append(nk)
            data[field] = out

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=2)

    @property
    def applied_today(self) -> int:
        return int(self.data.get("applied_today", 0))

    def applied_keys(self) -> List[str]:
        return list(self.data.get("applied_keys", []))

    @staticmethod
    def _as_keys(keys: Union[str, Iterable[str]]) -> List[str]:
        """规范化一组 key(允许包含 '|',按分段各自规范)。"""
        if isinstance(keys, str):
            keys = [keys]
        out = []
        for k in keys:
            if not k:
                continue
            nk = "|".join(normalize(seg) for seg in k.split("|"))
            if nk.strip("|"):
                out.append(nk)
        return out

    def is_applied(self, key: str) -> bool:
        return key in self.data.get("applied_keys", [])

    def is_seen(self, key: str) -> bool:
        """已投递或已评估跳过的职位都算见过,避免重复处理。"""
        if not key:
            return False
        return key in self.data.get("applied_keys", []) or key in self.data.get(
            "skipped_keys", []
        )

    def seen_any(self, keys: Union[str, Iterable[str]]) -> bool:
        return any(self.is_seen(k) for k in self._as_keys(keys))

    def mark_applied(self, keys: Union[str, Iterable[str]]) -> None:
        """登记为已沟通。接受一组等价 key(卡片版+详情页版),只自增一次计数。"""
        keys = self._as_keys(keys)
        if not keys:
            return
        applied = self.data.setdefault("applied_keys", [])
        added = False
        for k in keys:
            if k not in applied:
                applied.append(k)
                added = True
        if added:
            self.data["applied_today"] = self.applied_today + 1
        self.save()

    def mark_skipped(self, keys: Union[str, Iterable[str]]) -> None:
        keys = self._as_keys(keys)
        if not keys:
            return
        skipped = self.data.setdefault("skipped_keys", [])
        for k in keys:
            if k not in skipped:
                skipped.append(k)
        self.save()
