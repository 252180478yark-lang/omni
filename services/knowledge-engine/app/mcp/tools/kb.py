"""W1: search_kb, list_kbs（design doc §3.2 W1 行 3-4）。

list_kbs：thin wrapper over services.ingestion.list_kbs，可选按 kb_role 过滤。
search_kb：thin wrapper over services.rag_chain.retrieve_multi_kb；支持
  - kb_ids: 直接指定
  - kb_roles: 按 role 自动解析为 kb_ids
  - 都没传 → 用全量 KB（可能很慢，hint 提醒）
"""
from __future__ import annotations

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services import ingestion, rag_chain


@tool_with_audit(mcp, require_approval=False)
async def list_kbs(role: str | None = None) -> dict:
    """列出所有知识库。

    Args:
        role: 可选 kb_role 过滤（authoritative / methodology / personal_log /
              template / private_doc / general）

    Returns:
        {"ok": True, "count": N, "kbs": [{id, name, description, kb_role,
            embedding_provider, embedding_model, dimension, created_at}, ...]}
    """
    kbs = await ingestion.list_kbs()
    if role:
        kbs = [k for k in kbs if k.get("kb_role") == role]
    return {"ok": True, "count": len(kbs), "kbs": kbs}


@tool_with_audit(mcp, require_approval=False)
async def search_kb(
    query: str,
    kb_ids: list[str] | None = None,
    kb_roles: list[str] | None = None,
    top_k: int = 8,
) -> dict:
    """KB 检索；返回排序后的 chunks。

    Args:
        query: 自然语言查询
        kb_ids: 显式指定 KB id 列表
        kb_roles: 按角色筛 KB（自动解析为 kb_ids）；与 kb_ids 同时给则取并集
        top_k: 总返回上限（默认 8）

    Returns:
        {"ok": True, "count": N, "hits": [{source, kb_id, id, score, content,
            title}, ...]}
    """
    resolved_ids: set[str] = set(kb_ids or [])
    if kb_roles:
        all_kbs = await ingestion.list_kbs()
        wanted = set(kb_roles)
        resolved_ids.update(
            k["id"] for k in all_kbs if k.get("kb_role") in wanted
        )
    if not resolved_ids and kb_ids is None and not kb_roles:
        # 都没给 → 全量 KB（小数据量场景下 OK；大库时 hint 用户限定）
        all_kbs = await ingestion.list_kbs()
        resolved_ids = {k["id"] for k in all_kbs}

    if not resolved_ids:
        return {"ok": True, "count": 0, "hits": []}

    name_map = {k["id"]: k["name"] for k in (await ingestion.list_kbs())}
    hits = await rag_chain.retrieve_multi_kb(
        query,
        list(resolved_ids),
        top_k_per_kb=max(3, top_k // max(1, len(resolved_ids))),
        min_per_kb=0,
        score_threshold=0.0,
        total_limit=top_k,
        kb_name_map=name_map,
    )
    return {"ok": True, "count": len(hits), "hits": hits}
