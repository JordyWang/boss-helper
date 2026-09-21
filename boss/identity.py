"""职位身份和文本规范化规则。

身份规则属于领域层，不应依赖 JSON 状态存储；状态仓库会复用这里的函数
并继续从 ``boss.state`` 导出兼容名称。
"""
from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize(value: object) -> str:
    """统一全/半角、删除空白和卡片标题末尾的图标占位符。"""
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    return _WS.sub("", unicodedata.normalize("NFKC", text)).strip("&@・·")


def make_key(title: object, salary: object = "", company: object = "") -> str:
    parts = [normalize(title), normalize(salary), normalize(company)]
    if not any(parts):
        return ""
    return "|".join(parts)


__all__ = ["make_key", "normalize"]
