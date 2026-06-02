"""月度成本查询 MCP tool（蓝图 §4 L0-2 + §6.1 "omni 自身月成本进 BI 看板当一等指标"）。

agent 侧可调用的"读账"工具——老板问"这个月 omni 自己烧了多少钱 / 超预算没"时调。
写侧（每次会话归集）走前端 ws-handler → POST /api/v1/mcp/spend/record（REST），不在此处。

纯读、无副作用、不走 Human Gate；数据工具不返 trace（非 LLM 生成）。
"""
from __future__ import annotations

import logging

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services import cost_ledger_service as svc

logger = logging.getLogger(__name__)


@tool_with_audit(mcp, require_approval=False)
async def query_monthly_spend(
    month: str | None = None,
    actor_id: str | None = None,
) -> dict:
    """查 omni 自身某月运行成本（美元）+ 月度软上限超额检测。

    把每次 Claude Code 会话跑完报的 total_cost_usd 按月累计（mcp.monthly_spend）。
    - month: 'YYYY-MM' / 'YYYY-MM-DD'，省略 = 当前自然月。
    - actor_id: 省略 = 全月合计；给值 = 只看某操作者（团队期）。

    软上限读 env OMNI_MONTHLY_SPEND_CAP_USD（缺/非法回退默认 500 美元，老板可改）。
    over_cap=True 表示当月已超软上限（只提示，不拦业务）。

    老板话术触发：'这个月 omni 花了多少' / 'omni 自己烧了多少钱' / '超预算没'。

    Returns:
        {ok, spend_month, total_cost_usd, cap_usd, over_cap, remaining_usd,
         overage_usd, usage_ratio, entry_count}
    """
    totals = await svc.get_month_total(month=month, actor_id=actor_id)
    if not totals.get("ok"):
        return totals
    result = await svc.check_over_cap(
        month=month, actor_id=actor_id, precomputed_total=totals["total_cost_usd"],
    )
    result["entry_count"] = totals.get("entry_count", 0)
    if result.get("over_cap"):
        logger.warning(
            "query_monthly_spend %s 已超软上限：累计 $%.2f / 上限 $%.2f（超 $%.2f）",
            result.get("spend_month"),
            result.get("total_cost_usd", 0.0),
            result.get("cap_usd", 0.0),
            result.get("overage_usd", 0.0),
        )
    return result
