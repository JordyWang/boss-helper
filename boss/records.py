"""本地记录:把每条投递动作追加写入 CSV,便于事后审查。"""
from __future__ import annotations

import csv
import os
from datetime import datetime

_HEADER = ["时间", "动作", "职位", "薪资", "公司", "说明"]


class Recorder:
    """动作类型:applied(已沟通)/filtered(被规则过滤)/duplicate(重复跳过)/error(出错)。"""

    def __init__(self, path: str = ".state/records.csv"):
        self.path = path
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        is_new = not os.path.exists(path)
        # utf-8-sig 让 Excel 正确识别中文
        self._fh = open(path, "a", newline="", encoding="utf-8-sig")
        self._writer = csv.writer(self._fh)
        if is_new:
            self._writer.writerow(_HEADER)
            self._fh.flush()

    def add(
        self,
        action: str,
        title: str = "",
        salary: str = "",
        company: str = "",
        note: str = "",
    ) -> None:
        self._writer.writerow(
            [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), action, title, salary, company, note]
        )
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass
