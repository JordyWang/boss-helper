"""运行状态持久化:记录每日已投递数与已处理职位,支持跨运行去重与每日限额。"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import List


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
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "date": date.today().isoformat(),
            "applied_today": 0,
            "applied_keys": [],
            "skipped_keys": [],
        }

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=2)

    @property
    def applied_today(self) -> int:
        return int(self.data.get("applied_today", 0))

    def applied_keys(self) -> List[str]:
        return list(self.data.get("applied_keys", []))

    def is_applied(self, key: str) -> bool:
        return key in self.data.get("applied_keys", [])

    def is_seen(self, key: str) -> bool:
        """已投递或已评估跳过的职位都算见过,避免重复处理。"""
        return key in self.data.get("applied_keys", []) or key in self.data.get(
            "skipped_keys", []
        )

    def mark_applied(self, key: str) -> None:
        if key not in self.data.setdefault("applied_keys", []):
            self.data["applied_keys"].append(key)
        self.data["applied_today"] = self.applied_today + 1
        self.save()

    def mark_skipped(self, key: str) -> None:
        if key not in self.data.setdefault("skipped_keys", []):
            self.data["skipped_keys"].append(key)
        self.save()
