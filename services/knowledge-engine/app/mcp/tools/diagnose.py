"""诊断官 MCP tools（蓝图 §6.2 能力即工具 §1.2）。

把 feedback_digest 从被动 cron 升级成可调用能力：
- diagnose: 跑一轮诊断，content 聚类两路反馈 / analysis 聚类趋势异动 → 产出《改进提议》入库
  （带 R-14 分层 / R-15 样本量 / R-20 生命周期），返本周 Top 3 最值钱的。
- list_proposals: 看待办提议（默认 open，按优先级）+ 消化率。
- resolve_proposal: 老板拍板三态（接受 / 忽略=不再提醒同类 / snooze）。
- explain_anomaly: 问数——解释某条趋势异动（分层归因 + 近 28 天序列）。
- query_metric_trend: 问数——某指标近 N 天趋势序列 + 基线 mean/std。

均为**数据工具**（确定性生成/查询，不调 LLM）→ 不返 trace、无 token 成本、不走 Human Gate。
归因走模板化映射（R-14 禁伪因果——LLM 最会编"逻辑自洽实则编造"的归因）。
诊断官只提议不碰开关（§6.2 越界红线：经营/人事/放量拍板权 100% 在老板）。
"""
from __future__ import annotations

import logging

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services import diagnose_service as svc

logger = logging.getLogger(__name__)


@tool_with_audit(mcp, require_approval=False)
async def diagnose(
    mode: str = "content",
    lookback_days: int = 7,
    persist: bool = True,
    platform: str = "douyin",
) -> dict:
    """跑一轮诊断官，产出《改进提议》（只提议不碰开关，蓝图 §6.2）。

    - mode='content'（作战面/内容改进）：读体感路（消息级 👎 by 分类 +
      工具级 👎 by tool）+ 数据路（投后 ad_metrics），确定性生成结构化提议。
    - mode='analysis'（分析面/趋势归因，**§8.5 单平台抖音最小可用**）：读近 N 天 unhandled
      异动（mvp_anomaly + as_of/baseline/today/delta），按 metric 聚合出归因提议。
      归因走**模板化映射**（R-14 禁伪因果，不调 LLM）：按 metric/rule 映射拆解方向，每条标
      "假设 + 未排除混杂因子 + 要证实需对比 X"，禁"主因是 X"断言。跨平台/含自然流量口径
      未拉通（京东淘天数据待入库）→ 单平台下钻；platform 参数选平台（暂只 douyin 有数据）。
    - persist=True：提议入 mcp.improvement_proposals，按 dedupe_key 去重（同议题刷新不堆叠），
      过期 open 自动归档（R-20）。

    归因严格分层（R-14）：observation=客观相关带数据；hypothesis=标"假设"+未排除混杂+证伪条件，
    禁"主因是 X"断言。样本不足（n<5）标 preliminary（R-15）。

    老板话术触发：'看看哪里该改' / '诊断一下' / '最近反馈有啥模式' / '本周改进建议' /
    '分析一下趋势' / '为啥指标掉了'（mode='analysis'）。

    Returns:
        {ok, mode, generated, created, refreshed, total_open, top:[Top3], digestion_rate_7d, note}
    """
    result = await svc.run_diagnose(
        mode=mode, lookback_days=lookback_days, persist=persist, platform=platform,
    )
    if result.get("ok"):
        logger.info(
            "diagnose %s: generated=%d open=%d digestion_7d=%s",
            result.get("mode"), result.get("generated", 0), result.get("total_open", 0),
            result.get("digestion_rate_7d"),
        )
    return result


@tool_with_audit(mcp, require_approval=False)
async def explain_anomaly(anomaly_id: int) -> dict:
    """问数：解释某条趋势异动（分层归因，确定性不调 LLM，R-14 禁伪因果）。

    读该异动（mvp_anomaly + 039 列 as_of/baseline_value/today_value/delta_pct）+ 它对应
    指标近 28 天趋势序列，返：
    - observation：客观相关（带 delta / 今值 vs 基线 / 数据新鲜度 as_of），不含因果断言。
    - hypothesis：模板化假设（按 metric/rule 映射拆解方向，如 gmv 跌→拆 UV×转化×客单）。
    - unaddressed_confounders：未排除的混杂因子（季节性/竞品/自然流量…）。
    - falsification：要证实需对比 X（一句话可证伪）。
    - recent_series + baseline：近 28 天真实序列 + mean/std（库内原样，非编造）。

    老板话术触发：'为啥这条异动' / '解释下这个异常' / '这指标咋掉的'。

    Returns:
        {ok, anomaly:{...}, observation, hypothesis, unaddressed_confounders,
         falsification, recent_series:[...], baseline:{...}, note}
    """
    return await svc.explain_anomaly(anomaly_id=anomaly_id)


@tool_with_audit(mcp, require_approval=False)
async def query_metric_trend(
    metric_name: str,
    sku_id: str | None = None,
    platform: str = "douyin",
    days: int = 28,
) -> dict:
    """问数：某指标近 days 天趋势序列 + 基线 mean/std（确定性，不调 LLM）。

    读 mvp_daily_metric 真实序列原样返回（不编造、不归因）：
    - sku_id 省略 = 同日聚合全 SKU（大盘口径）；给值 = 单 SKU 序列。
    - platform 暂只 douyin 有数据（§8.5 多平台待接入）。
    - baseline：该窗口 mean/std/min/max/latest（统计基线，非滚动基线）。

    老板话术触发：'看看 X 指标最近趋势' / 'gmv 这个月走势' / 'XX 的曲线'。

    Returns:
        {ok, metric_name, sku_id, platform, days, series:[{date,value,sku_n}], baseline:{...}, note}
    """
    return await svc.query_metric_trend(
        metric_name=metric_name, sku_id=sku_id, platform=platform, days=days,
    )


@tool_with_audit(mcp, require_approval=False)
async def list_proposals(
    status: str = "open",
    mode: str | None = None,
    limit: int = 50,
) -> dict:
    """列诊断官《改进提议》（默认 open，按优先级倒序）+ 7 天消化率（R-20）。

    status: open（默认）/ accepted / ignored / snoozed / expired / all。
    列出前自动把过期 open 归档（保持 inbox 干净，防 backlog 淹没）。

    老板话术触发：'有哪些改进建议' / '待办提议' / '看看诊断官攒了啥'。

    Returns:
        {ok, proposals:[...], count, open_count, digestion_rate_7d, digestion_detail_7d}
    """
    return await svc.list_proposals(status=status, mode=mode, limit=limit)


@tool_with_audit(mcp, require_approval=False)
async def resolve_proposal(
    proposal_id: str,
    action: str,
    note: str | None = None,
    snooze_days: int = 7,
) -> dict:
    """老板对某条《改进提议》拍板（R-20 三态）—— 诊断官只提议，落地全靠这一下。

    - action='accept'：采纳（老板会去改 prompt/skill；提议归档为 accepted，不自动改任何东西）。
    - action='ignore'：忽略 = **不再提醒同类**（静音该 dedupe_key，diagnose 重跑不再生成同议题）。
    - action='snooze'：暂时不看（snooze_days 天后 diagnose 重跑会 resurface）。

    老板话术触发：'接受第 N 条' / '这条忽略别再提' / '这条先放放'。

    Returns:
        {ok, id, status, action, dedupe_key}
    """
    return await svc.resolve_proposal(
        proposal_id=proposal_id, action=action, note=note, snooze_days=snooze_days,
    )
