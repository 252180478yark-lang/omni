"""综合经营分析 + 临时问数 MCP tools（蓝图 §6 分析半 · §6.1 老板/操盘手两面）。

- generate_business_analysis: 读 mvp_daily_metric + mvp_industry_benchmark + mvp_anomaly，
  产出《综合经营分析》（R-14 强制分层：观察到的 vs 可能的原因；R-15 样本量；R-17 口径）。
  按两面分别出（owner=经营诊断 / operator=投放选品建议）。确定性为主，可选 LLM 润色（过 R-14）。
- query_metric_nl: 临时问数。口语问句 → metric_name + 时间窗 + 维度 → 查序列 + 简述。

均为**数据/分析工具**（确定性为主，不强依赖 LLM）。generate_business_analysis 的 polish=True
路径会调 hub 润色，但确定性骨架是 ground truth（fail-open 回退）；query_metric_nl 全确定性。
归因走 diagnose_service 的模板化映射（R-14 禁伪因果——LLM 最会编"逻辑自洽实则编造"的归因）。
逻辑全在 business_analysis_service（与 REST 共用同一份函数，禁漂移）。
"""
from __future__ import annotations

import logging

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services import business_analysis_service as svc

logger = logging.getLogger(__name__)


@tool_with_audit(mcp, require_approval=False)
async def generate_business_analysis(
    face: str = "owner",
    days: int = 28,
    platform: str = "douyin",
    polish: bool = False,
    focus: str | None = None,
) -> dict:
    """产出一份《综合经营分析》（确定性为主，R-14 强制分层，蓝图 §6.1 两面）。

    读 mvp_daily_metric(近 N 天序列) + mvp_industry_benchmark(同行) + mvp_anomaly(异动)，
    模板化映射成结构化分析：
    - 第一部分「观察到的」：客观事实带数据（哪些指标涨跌多少、vs 同行什么位置、哪些异动）——不含因果。
    - 第二部分「异动」：异动引擎检出的未处理/非预期异常。
    - 第三部分「可能的原因」：**模板化假设**（R-14 禁伪因果，不调 LLM 编断言），每条标
      "假设 + 未排除混杂因子 + 要证实需对比 X"，禁"主因是 X"断言。
    - 第四部分「口径与样本量警示」：R-15 样本不足标待验证 / R-17 单平台抖音口径。

    face：
    - 'owner'（老板面/经营诊断）：北极星（gmv/buyer/转化/uv/体验分/行业排名/搜索SOV）+ 同行分位 + 异动。
    - 'operator'（操盘手面/投放选品建议）：5A 分层（A1-A5/新增/流失/排名）+ 货品结构（爆款/常规品占比）
      + 商品卡 + 搜索排名。
    days：分析窗口（默认 28 天，[1,365]）。platform：暂只 douyin 有数据（§8.5）。
    polish：True 时在确定性骨架之上再跑 LLM 叙事层（外置提示词 business_analysis.{system,user}.md，
      骨架为 ground truth，禁新增数值/因果；失败 fail-open 回退骨架）。默认 False（纯确定性、零 token）。
    focus：老板临时关注点，注入叙事提示词让总览优先回应（仅 polish=True 生效）。

    老板话术触发：'出一份经营分析' / '综合分析一下' / '这个月经营咋样'（owner）；
    '投放选品建议' / '操盘手看一下' / '5A 货品结构怎么样'（operator）。

    Returns:
        {ok, face, window_days, platform, observed:{metrics, movers, anomalies},
         hypotheses:[{metric, cn, hypothesis}], sample_caveats, confidence, markdown,
         sections, as_of, narrated, polished, note}
    """
    result = await svc.generate_business_analysis(
        face=face, days=days, platform=platform, polish=polish, focus=focus,
    )
    if result.get("ok"):
        logger.info(
            "generate_business_analysis face=%s days=%d confidence=%s polished=%s",
            result.get("face"), result.get("window_days"), result.get("confidence"),
            result.get("polished"),
        )
    return result


@tool_with_audit(mcp, require_approval=False)
async def query_metric_nl(
    question: str,
    default_days: int = 28,
    platform: str = "douyin",
) -> dict:
    """临时问数：口语问句 → 指标序列 + 一句话简述（确定性，不调 LLM，不归因）。

    解析（全确定性）：
    - metric：精确 metric_name / 完整中文名 / alias 子串（resolve_metric）。已支持落库的 29 指标。
    - 时间窗：'近 N 天/周/月' + '本周/本月/今天/昨天…'，默认 default_days。
    - 维度：问句含 'SKU-xxxx' → 该 SKU；否则全店 '_SHOP_'。
    解析不出 metric → 返 ok=False + 29 指标候选清单（让老板再说清）。

    口径：库内真实序列原样返回（mvp_daily_metric），不编造、不归因；单平台抖音（§8.5）；
    金额已 ÷100 为元、rate/占比 0-1、rank 越小越好。

    老板话术触发：'最近 gmv 多少' / '本月转化率走势' / '看下 SKU-X 近 7 天点击人数' /
    '5A 总资产这周咋样'。

    Returns:
        {ok, question, metric_name, metric_cn, sku_id, platform, days,
         parse:{resolved_metric, window, dimension}, series:[{date,value}], summary,
         baseline:{...}, benchmark, note}
        或 {ok:false, error:'metric_not_resolved', supported:[...]}（没听出指标时）。
    """
    return await svc.query_metric_nl(
        question=question, default_days=default_days, platform=platform,
    )
