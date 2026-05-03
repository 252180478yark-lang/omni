"""Human Gate（design doc §5）。

W1：5 个 tool 全是只读，require_approval=False，本模块仅留接口骨架。
W2 起在算账/编排/媒体生成 tool 上启用：写入 mcp.human_gates 表 → 推 /inbox →
等批/驳/超时（默认 3600s）。

接口签名稳定（W2 改实现，不改签名）。
"""
from __future__ import annotations

from typing import TypedDict


class GateDecision(TypedDict):
    decision: str          # approved | rejected | timeout
    decision_note: str | None


async def request_approval(
    *,
    tool_call_id: str,
    summary: str,
    timeout_seconds: int = 3600,
) -> GateDecision:
    """W1 stub：调到时报错。W2 起真实现：写表 → 等待 → 返回决策。"""
    raise NotImplementedError(
        "Human Gate 在 W1 未实现。当前 5 个 tool 应全部 require_approval=False。"
        " W2 起在 compute_margin / run_sku_orch / generate_brief 等 tool 落地。"
    )
