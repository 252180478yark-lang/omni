"""W2 T2：tool 通用 utils。

- decimal_to_jsonable：递归把 Decimal 转 str（compute_margin 算账输出 Decimal，
  必须转 str 才能进 mcp.tool_calls.result jsonb）
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def decimal_to_jsonable(obj: Any) -> Any:
    """递归把 Decimal → str；其他类型透传。"""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: decimal_to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decimal_to_jsonable(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(decimal_to_jsonable(v) for v in obj)
    return obj
