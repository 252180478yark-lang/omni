"""Tool 返回类型约定（design doc §2.3）。

所有 tool 必须返回 dict，含 `ok: bool`：
- 成功：`ok=True` + 业务字段
- 失败：`ok=False` + `error`（机器码）+ `hint`（给 LLM 的下一步建议）+ 可选 `note`（给人看的）
"""
from __future__ import annotations

from typing import Literal, TypedDict


class ToolSuccess(TypedDict, total=False):
    ok: Literal[True]
    # 业务字段由各 tool 自己加


class ToolError(TypedDict, total=False):
    ok: Literal[False]
    error: str   # 机器可读 code，例如 "sku_not_found"
    hint: str    # 给 LLM 的下一步建议
    note: str    # 给人看的补充（可选）
