"""月度成本总账 REST router（蓝图 §4 L0-2【R-28】成本闸 = 单次 + 月度总账）。

接通 cost_ledger_service（migration 033 的 mcp.monthly_spend）的写侧 + 读侧：
- POST /api/v1/mcp/spend/record —— 前端 ws-handler 在 Claude Code 会话 task_done 时
  fire-and-forget 把 total_cost_usd 归集进总账（不走 Human Gate，记账不阻断业务）。
- GET  /api/v1/mcp/spend/month  —— 某月累计 + 软上限超额检测（前端"运行成本"看板读）。

写侧防御：cost 非法/负数 → service 返 ok=False，router 200 透传（前端 fire-and-forget
不该因脏数据 5xx）。读侧把"累计 + 上限 + 是否超 + usage_ratio"一把返给 UI。
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import cost_ledger_service as svc

router = APIRouter(prefix="/api/v1/mcp/spend", tags=["mcp-spend"])


class SpendRecordRequest(BaseModel):
    total_cost_usd: float | int | str
    session_id: str | None = None          # uuid 或 claude_session_id 文本均可
    claude_session_id: str | None = None
    client: str | None = None              # desktop / web / orch
    source: str = "claude_session"
    actor_id: str = "yark"
    note: str | None = None


@router.post("/record")
async def record_spend_endpoint(payload: SpendRecordRequest) -> dict:
    """记一笔会话成本进月度总账（前端 task_done 调；fire-and-forget 友好）。"""
    return await svc.record_spend(
        cost_usd=payload.total_cost_usd,
        session_id=payload.session_id,
        claude_session_id=payload.claude_session_id,
        source=payload.source,
        client=payload.client,
        actor_id=payload.actor_id,
        note=payload.note,
    )


@router.get("/month")
async def month_summary_endpoint(
    month: str | None = None,
    actor_id: str | None = None,
) -> dict:
    """某月累计成本 + 软上限超额检测（运行成本看板读）。

    month: 'YYYY-MM' / 'YYYY-MM-DD' / 省略=当前月。
    返 {ok, spend_month, total_cost_usd, cap_usd, over_cap, remaining_usd,
        overage_usd, usage_ratio, entry_count}。
    """
    totals = await svc.get_month_total(month=month, actor_id=actor_id)
    if not totals.get("ok"):
        return totals
    # 复用同一快照算超额（precomputed_total），避免两次查库间并发写入致 total 与 entry_count 不自洽
    over = await svc.check_over_cap(
        month=month, actor_id=actor_id, precomputed_total=totals["total_cost_usd"],
    )
    over.update({"entry_count": totals.get("entry_count", 0)})
    return over
