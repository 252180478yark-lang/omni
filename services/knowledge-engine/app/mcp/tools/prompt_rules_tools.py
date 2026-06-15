"""sku-pipeline prompt 反馈飞轮搭桥 tool（2026-06-15 loop engineering 第一件事）。

把【新世界 mcp.tool_calls 的差评 + rating_note】读 → 主大脑提炼 → 写成【旧世界
knowledge.prompt_rules 的规则】，下次同工具生成时经 render_rules_suffix（已在
migration 051 给 5 个 sku-pipeline 工具补好注入口）自动注入 prompt 末尾。

闭环唯一真断点是"提炼"——老飞轮的 distill_feedback 只读 prompt_feedbacks，从不碰
mcp.tool_calls，于是 sku-pipeline 的点评永远变不成下次生效的规则。本文件补这座桥。

4 个 tool（全 F 类 require_approval=False）：
  - list_unprocessed_complaints  拉尚未提炼成规则的 sku-pipeline 差评（提炼的原料）
  - prompt_rule_save             把一条提炼好的规则草稿落库（默认 enabled=False）
  - prompt_rule_list             看某节点的规则（含 enabled/hit_count，便于点亮/排查没命中）
  - prompt_rule_set_enabled      点亮/熄灭一条规则（老板审完草稿后生效）

"草稿先 enabled=FALSE、老板逐条点亮"本身就是闸门（可证伪、防 LLM 自嗨直接污染线上
prompt），故不走 Human Gate。

提炼按需触发（老板拍板的节奏）：老板说"提炼一下最近的差评" → 主大脑调
list_unprocessed_complaints → 在对话里按 distill 要求拟草稿（可复用通用约束 / 祈使句 /
15-50 字 / 一次性吐槽或用户输入错误 → 跳过）→ 给老板挑 → prompt_rule_save(enabled=False)
→ 老板"点亮第 N 条" → prompt_rule_set_enabled。
"""
from __future__ import annotations

import json
import logging

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services import prompt_rules as pr

logger = logging.getLogger(__name__)

# sku-pipeline 5 个生成工具 → prompt_nodes.node_id（migration 051 建的节点）
PIPELINE_TOOL_TO_NODE = {
    "generate_selling_points_matrix": "pipeline.selling_points_matrix",
    "generate_audience_match": "pipeline.audience_match",
    "generate_audience_portrait": "pipeline.audience_portrait",
    "generate_director_brief": "pipeline.director_brief",
    "generate_creative_pack": "pipeline.creative_pack",
}


def _parse_scope(scope):
    """asyncpg 未注册 jsonb codec → scope 读回是 str；显示前解析回 dict。"""
    if isinstance(scope, str):
        try:
            return json.loads(scope)
        except Exception:
            return scope
    return scope


@tool_with_audit(mcp, require_approval=False)
async def list_unprocessed_complaints(
    tool_name: str | None = None,
    limit: int = 20,
) -> dict:
    """拉 sku-pipeline 工具里"被点👎且写了原因、但还没被提炼成规则"的差评（提炼的原料）。

    只覆盖 5 个 sku-pipeline 生成工具：generate_selling_points_matrix /
    generate_audience_match / generate_audience_portrait / generate_director_brief /
    generate_creative_pack。"还没被提炼"= mcp.tool_calls 里 user_rating='bad' 且有
    rating_note，且没有任何 prompt_rules.source_tool_call_id 指向它。

    Args:
        tool_name: 只看某个工具的差评（5 选 1）；None=全部 5 个
        limit: 最多返回几条（默认 20，按时间倒序）

    Returns:
        {ok, result:{complaints:[{tool_call_id, tool_name, node_id, rating_category,
          rating_note, final_prompt_excerpt, created_at}], count}}

    提炼流程：主大脑读这些差评 → 按"可复用通用约束/祈使句/15-50字/一次性或输入错误跳过"
    拟规则草稿 → 给老板挑 → prompt_rule_save(node_id=该条 node_id, source_tool_call_id=该条
    tool_call_id, enabled=False)。
    """
    if tool_name and tool_name not in PIPELINE_TOOL_TO_NODE:
        return {
            "ok": False,
            "error": f"tool_name 必须是 sku-pipeline 5 工具之一：{list(PIPELINE_TOOL_TO_NODE)}",
        }
    tool_names = [tool_name] if tool_name else list(PIPELINE_TOOL_TO_NODE.keys())

    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT tc.id, tc.tool_name, tc.rating_category, tc.rating_note,
               tc.result->'trace'->>'final_prompt' AS final_prompt,
               tc.created_at
        FROM mcp.tool_calls tc
        WHERE tc.tool_name = ANY($1::text[])
          AND tc.user_rating = 'bad'
          AND tc.rating_note IS NOT NULL AND btrim(tc.rating_note) <> ''
          AND NOT EXISTS (
              SELECT 1 FROM knowledge.prompt_rules r
              WHERE r.source_tool_call_id = tc.id
          )
        ORDER BY tc.created_at DESC
        LIMIT $2
        """,
        tool_names, max(1, min(100, int(limit))),
    )
    complaints = []
    for r in rows:
        fp = r["final_prompt"] or ""
        complaints.append({
            "tool_call_id": str(r["id"]),
            "tool_name": r["tool_name"],
            "node_id": PIPELINE_TOOL_TO_NODE[r["tool_name"]],
            "rating_category": r["rating_category"],
            "rating_note": r["rating_note"],
            "final_prompt_excerpt": fp[:2000],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })
    return {"ok": True, "result": {"complaints": complaints, "count": len(complaints)}}


@tool_with_audit(mcp, require_approval=False)
async def prompt_rule_save(
    node_id: str,
    rule_text: str,
    scope: dict | None = None,
    enabled: bool = False,
    source_tool_call_id: str | None = None,
) -> dict:
    """把一条提炼好的修正规则落库。默认 enabled=False——先入库不生效，等老板点亮。

    Args:
        node_id: 规则挂哪个生成节点。sku-pipeline 5 节点：
            pipeline.selling_points_matrix / pipeline.audience_match /
            pipeline.audience_portrait / pipeline.director_brief / pipeline.creative_pack
            （也可挂老飞轮 19 节点之一，如 content.copy / briefs.draft）
        rule_text: 规则正文（可复用通用约束、祈使句"必须../禁止../优先.."、建议 15-50 字）
        scope: 可选细分，默认 None=对该节点所有场景生效；
            如 {"sku_id":"SKU-X"} 只对该 SKU、{"kind":"video_planting"} 只对种草素材
        enabled: 默认 False（草稿先不生效，老板审完用 prompt_rule_set_enabled 点亮）
        source_tool_call_id: 该规则源自哪条差评（list_unprocessed_complaints 给的
            tool_call_id）——填了之后该差评不再被重复捞，也便于后续规则效果回溯

    Returns:
        {ok, result:{rule_id, node_id, enabled}}
    """
    rule_text = (rule_text or "").strip()
    if not node_id or not rule_text:
        return {"ok": False, "error": "node_id 和 rule_text 必填"}

    pool = get_pool()
    exists = await pool.fetchval(
        "SELECT 1 FROM knowledge.prompt_nodes WHERE id = $1", node_id,
    )
    if not exists:
        return {
            "ok": False,
            "error": f"node_id 不存在：{node_id}",
            "hint": "sku-pipeline 5 节点见本 tool docstring；其余看 knowledge.prompt_nodes",
        }

    rule = await pr.create_rule(
        node_id, rule_text,
        scope=scope,
        enabled=bool(enabled),
        source_tool_call_id=source_tool_call_id,
    )
    logger.info(
        "prompt_rule_save node=%s enabled=%s src=%s text=%.40s",
        node_id, enabled, (source_tool_call_id or "")[:8], rule_text,
    )
    return {
        "ok": True,
        "result": {"rule_id": str(rule["id"]), "node_id": node_id, "enabled": bool(enabled)},
    }


@tool_with_audit(mcp, require_approval=False)
async def prompt_rule_list(
    node_id: str | None = None,
    include_disabled: bool = True,
) -> dict:
    """看 prompt 修正规则（含 enabled 状态 + hit_count 命中次数）。

    Args:
        node_id: 只看某节点（如 pipeline.creative_pack）；None=全部节点
        include_disabled: 默认 True 连未点亮（enabled=False）的草稿一起看；
            False 只看已生效的

    Returns:
        {ok, result:{rules:[{rule_id, node_id, rule_text, scope, enabled, hit_count,
          source_tool_call_id, created_at, last_hit_at}], count}}

    排查提示：已点亮但 hit_count=0 的规则 = 从没命中（scope 写窄了、或该工具还没接
    注入口）；enabled=False 的是待你点亮的草稿。
    """
    rules = await pr.list_rules(node_id, enabled_only=not include_disabled)
    out = []
    for r in rules:
        out.append({
            "rule_id": str(r["id"]),
            "node_id": r["node_id"],
            "rule_text": r["rule_text"],
            "scope": _parse_scope(r.get("scope")),
            "enabled": r.get("enabled"),
            "hit_count": r.get("hit_count"),
            "source_tool_call_id": (
                str(r["source_tool_call_id"]) if r.get("source_tool_call_id") else None
            ),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            "last_hit_at": r["last_hit_at"].isoformat() if r.get("last_hit_at") else None,
        })
    return {"ok": True, "result": {"rules": out, "count": len(out)}}


@tool_with_audit(mcp, require_approval=False)
async def prompt_rule_set_enabled(rule_id: str, enabled: bool) -> dict:
    """点亮/熄灭一条规则。老板审完草稿说"点亮第 N 条" → enabled=True 下次生成即生效。

    Args:
        rule_id: prompt_rule_save / prompt_rule_list 返的 rule_id
        enabled: True 点亮生效 / False 熄灭

    Returns:
        {ok, result:{rule_id, enabled}}
    """
    updated = await pr.set_rule_enabled(rule_id, bool(enabled))
    if not updated:
        return {"ok": False, "error": f"规则不存在：{rule_id}"}
    return {
        "ok": True,
        "result": {"rule_id": str(updated["id"]), "enabled": updated["enabled"]},
    }
