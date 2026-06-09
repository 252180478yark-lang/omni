"""人群包投前诊断 + 提纯 MCP tool（蓝图 §6 分析半 · 方法论沉淀）。

diagnose_audience_pack：投前诊断一个候选人群包——逐维度算候选 vs 行业 A4（真需求标尺）的
相对方向，出《投前诊断卡》（漏斗定位 + 内容策略定调）+ 可选《提纯施工单》（三刀法落到真实
可勾的巨量云图标签）。

**数据/分析工具**（确定性为主）：observation 全是画像真值；定位/定调走确定性规则映射（R-14
分层禁伪因果）；polish=True 才在确定性骨架上跑巨量云图 KB grounded 的 LLM 叙事层（fail-open
回退骨架）。逻辑全在 audience_pack_service（禁漂移）。

关键口径（写进每份诊断卡 + 此处提醒）：**画像比对只是投前的冷启动代理**——能判断圈选合不
合理、生成"先测哪些细分"的假设，但**判断不了真实投放价值**（真实价值只有 CTR/CVR/ROI/GMV
说了算）。A4 = 真需求标尺，不是提纯工具/模仿对象。
"""
from __future__ import annotations

import logging

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services import audience_pack_service as svc

logger = logging.getLogger(__name__)


@tool_with_audit(mcp, require_approval=False)
async def diagnose_audience_pack(
    candidate: str,
    baseline: str = "baseline_a4",
    with_purify_plan: bool = True,
    polish: bool = False,
    focus: str | None = None,
) -> dict:
    """投前诊断一个候选人群包（《02 对比诊断》+《01 提纯施工单》，确定性为主）。

    背景（《和田宽人群包评估方法论》）：和田宽高端日式发酵调味品，**打不了价格战**，投放靠
    "做用户喜欢的内容 → 软植入 → 深度种草 → 收割"。所以做内容/投放**之前**必须判断一个包
    适不适合——这群"会被内容打动"的人必须是**真需求**。

    引擎逐维度比对候选 vs 行业 A4（一个月内真买过酱油的人 = 真需求标尺），**比对看方向、不算
    总相似分**（R-14 强制分层）：
    - **价值维（付得起：消费力/城市/手机价位）** → 期望正向偏离 A4 高端尾部（贴近 A4 均值是反的，
      A4 大多价格敏感，恰是最打不动的人）。
    - **购买行为维（线上客单/频次）** → 比 A4 软 = 种草信号（非扣分，定漏斗位）。
    - **需求维（品类成交/品牌/兴趣/触点）** → 期望重叠 A4 真需求指纹（品类锚 TGI 1300+ /
      兴趣锚 220–280 / 触点锚 300–490），重叠高 = 真需求强。
    - **身份维（八大消费群体/年龄/性别/职业/人生阶段/地域）** → 差异不计（构成不同 ≠ 质量缺口）。
    → 输出**漏斗定位**（种草型 / 即投收割型 / 价值流失警告）+ **内容策略定调**。

    参数：
    - candidate：候选包画像。可传内置/dropbox 文件名（'diyu_xunwei'、'x.csv'）/ 容器可达
      绝对路径 / 原始 CSV 文本。CSV 结构 `标签类型,标签,占比,tgi`（巨量引擎/云图人群分析导出）。
      老板新包导出 CSV 丢进 `config/audience/`（或 OMNI_AUDIENCE_PACK_DIR）即可按文件名调。
    - baseline：基准包，默认 'baseline_a4'（内置行业 A4 真需求标尺）。
    - with_purify_plan：True 附《提纯施工单·优先级阶梯》——不限刀数、**按漏斗定位排序**（种草型
      先非电商需求/内容，收割型先高客单/品类成交），每刀落到真实可勾标签 + 标 ✅非电商/⚠电商
      资格（⚠电商刀只能上品牌广告，不能上非品牌广告）+ **预计收窄力度（强/中/弱，粗估自画像占比、
      非云图真实覆盖人数）**。老板想快掉一个量级先挑「强」刀，按刀序一刀一刀切、每刀看云图真实覆盖
      人数，不满意把缩窄后画像重导出再跑做二次提纯。
    - polish：True 在确定性骨架上跑 LLM 叙事层（巨量云图 KB grounding；骨架为 ground truth，
      禁新增数值/伪因果；失败 fail-open 回退骨架）。默认 False（纯确定性、零 token）。
    - focus：老板临时关注点，注入叙事（仅 polish 生效）。

    老板话术触发：'诊断一下 X 这个包' / 'X 包适不适合投' / '帮我看看地域寻味人这个包' /
    '提纯一下 X 包' / 'X 包该怎么收窄'。

    **铁律**：画像是投前冷启动代理，判断不了真实投放价值——按定调小预算测，看 CTR/CVR/ROI 再放量。

    Returns:
        {ok, candidate, baseline, value_verdict, behavior_verdict, demand_verdict,
         position:{label, why, funnel}, value_axis, behavior_axis, demand_axis, identity_axis,
         purify_plan, markdown, sections, narrated, source, note}
        或 {ok:false, error, available:[内置包名], dropbox}。
    """
    result = await svc.diagnose_audience_pack(
        candidate=candidate, baseline=baseline,
        with_purify_plan=with_purify_plan, polish=polish, focus=focus,
    )
    if result.get("ok"):
        logger.info(
            "diagnose_audience_pack cand=%s value=%s demand=%s position=%s narrated=%s",
            result.get("candidate"), result.get("value_verdict"),
            result.get("demand_verdict"),
            (result.get("position") or {}).get("label"), result.get("narrated"),
        )
    return result
