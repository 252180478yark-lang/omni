"""W3a T10：sku 全链路 SOP 编排辅助 tool。

`gather_brief_context(sku_id, channel)`：
- 用 sku_id + channel 拼检索 query
- 按 kb_role 检索 3 类 KB：
  - authoritative（渠道运营手册类）
  - template（爆款拆解 / 钩子结构）
  - private_doc（公司产品/历史 brief 类）
- 拼成结构化 kb_context（markdown 子区段 + 引用标注）
- next_step_hint 指 generate_brief，suggested_args 含 kb_context

不调 LLM；require_approval=False（纯检索）。
"""
from __future__ import annotations

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.mcp.trace import attach_next_step
from app.services import ingestion, rag_chain


_ROLE_LABELS = {
    "authoritative": "【官方/运营手册】",
    "template": "【爆款拆解 / 模板】",
    "private_doc": "【公司产品 / 历史 brief】",
    "methodology": "【方法论】",
    "personal_log": "【个人录音】",
    "general": "【通用】",
}

_ROLES_FOR_BRIEF = ("authoritative", "template", "private_doc")


@tool_with_audit(mcp, require_approval=False)
async def gather_brief_context(
    sku_id: str,
    channel: str,
    top_k_per_role: int = 3,
) -> dict:
    """聚合三类 KB 上下文，给 generate_brief 喂料。

    Args:
        sku_id: SKU id（拼 query 用）
        channel: 渠道（拼 query 用）
        top_k_per_role: 每个 role 最多返几条 chunk（默认 3）

    Returns:
        {
            "ok": True,
            "result": {
                "kb_context": "## ... 拼好的 markdown",
                "sources": [{kb_id, title, score, role}, ...]
            },
            "next_step_hint": {
                "suggested_tool": "generate_brief",
                "suggested_args": {sku_id, channel, kb_context, extra_context: ""},
                "human_text": "用这堆上下文出 brief"
            }
        }
    """
    all_kbs = await ingestion.list_kbs()
    by_role: dict[str, list[str]] = {}
    name_map: dict[str, str] = {}
    for k in all_kbs:
        by_role.setdefault(k.get("kb_role") or "general", []).append(k["id"])
        name_map[k["id"]] = k.get("name", k["id"])

    query = f"{sku_id} {channel} 渠道 brief 钩子 卖点 分镜"

    sections: list[str] = []
    sources: list[dict] = []
    for role in _ROLES_FOR_BRIEF:
        ids = by_role.get(role) or []
        if not ids:
            continue
        try:
            hits = await rag_chain.retrieve_multi_kb(
                query, ids,
                top_k_per_kb=max(2, top_k_per_role // max(1, len(ids))),
                min_per_kb=0,
                score_threshold=0.0,
                total_limit=top_k_per_role,
                kb_name_map=name_map,
            )
        except TypeError:
            # retrieve_multi_kb 签名兼容（不同版本可能少 kw）
            hits = await rag_chain.retrieve_multi_kb(query, ids)
        if not hits:
            continue

        sections.append(f"### {_ROLE_LABELS.get(role, role)}")
        for h in hits[:top_k_per_role]:
            title = h.get("title") or h.get("kb_id") or "?"
            content = (h.get("content") or "").strip()
            sections.append(f"- 来源「{title}」：{content[:400]}")
            sources.append({
                "kb_id": h.get("kb_id"),
                "title": title,
                "score": h.get("score"),
                "role": role,
            })

    if not sections:
        kb_context = "（KB 检索无命中）"
    else:
        kb_context = "\n".join(sections)

    result = {
        "ok": True,
        "result": {"kb_context": kb_context, "sources": sources},
    }
    return attach_next_step(
        result,
        suggested_tool="generate_brief",
        suggested_args={
            "sku_id": sku_id,
            "channel": channel,
            "kb_context": kb_context,
            "extra_context": "",
        },
        human_text=(
            f"基于 {len(sources)} 条 KB 上下文出 brief；"
            f"如要加临时要求，往 extra_context 塞"
        ),
    )
