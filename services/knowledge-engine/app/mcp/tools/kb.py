"""W1: search_kb, list_kbs（design doc §3.2 W1 行 3-4）。
W3b T6: kb_upload_doc（require_approval=True，Gate 批后才调 ingestion）。
W3b T7: kb_set_role（require_approval=True，Gate 批后改 KB 角色）。

list_kbs：thin wrapper over services.ingestion.list_kbs，可选按 kb_role 过滤。
search_kb：thin wrapper over services.rag_chain.retrieve_multi_kb；支持
  - kb_ids: 直接指定
  - kb_roles: 按 role 自动解析为 kb_ids
  - 都没传 → 用全量 KB（可能很慢，hint 提醒）
"""
from __future__ import annotations

import os

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services import ingestion, rag_chain
from app.services.ingestion import _VALID_KB_ROLES


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


def _kb_upload_summary(args: dict) -> str:
    """Gate 卡片摘要：上传 X 入 KB Y"""
    fp = args.get("file_path", "?")
    base = os.path.basename(fp) if fp != "?" else "?"
    kb = str(args.get("kb_id", "?"))[:8]
    return f"上传 {base} 入 KB={kb}"


@tool_with_audit(
    mcp,
    require_approval=True,
    summary_fn=_kb_upload_summary,
    timeout_seconds=3600,
)
async def kb_upload_doc(
    kb_id: str,
    file_path: str,
    title: str | None = None,
    source_type: str = "doc",
) -> dict:
    """上传文件入 KB（require_approval=True，CLI 批后才执行 ingestion）。

    内部走 services.ingestion.submit_ingestion_task，跟 router /ingest 一致。

    Args:
        kb_id: KB id（uuid str）
        file_path: 文件绝对路径（容器内可访问）
        title: 文档标题，None 自动用文件名
        source_type: doc/manual/runbook 等

    Returns:
        {ok, result: {task_id, kb_id, title, ...}, trace}
    """
    # 校验 KB
    kb = await ingestion.get_kb(kb_id)
    if not kb:
        return {
            "ok": False,
            "error": "kb_not_found",
            "hint": f"kb_id={kb_id} 不存在；用 list_kbs 查可用 id",
        }

    # 校验文件
    if not os.path.exists(file_path):
        return {
            "ok": False,
            "error": "file_not_found",
            "hint": f"file_path={file_path} 容器内不存在；确认 bind mount 路径",
        }
    if os.path.isdir(file_path):
        return {
            "ok": False,
            "error": "is_directory",
            "hint": f"file_path={file_path} 是目录不是文件",
        }
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    except UnicodeDecodeError:
        return {
            "ok": False,
            "error": "binary_file_unsupported",
            "hint": (
                "kb_upload_doc 当前只支持 UTF-8 文本（.txt/.md/.json）。"
                "二进制（PDF/DOCX）请走前端 /api/v1/knowledge/documents/ingest 上传。"
            ),
        }

    auto_title = title or os.path.basename(file_path)
    task_id = await ingestion.submit_ingestion_task(
        kb_id=kb_id,
        title=auto_title,
        text=text,
        source_url=f"file://{file_path}",
        source_type=source_type,
    )

    return {
        "ok": True,
        "result": {
            "task_id": task_id,
            "kb_id": kb_id,
            "kb_name": kb.get("name"),
            "title": auto_title,
            "source_type": source_type,
            "char_count": len(text),
        },
        "trace": {
            "ingestion_task_id": task_id,
            "submit_via": "ingestion.submit_ingestion_task",
        },
    }


def _kb_set_role_summary(args: dict) -> str:
    """Gate 卡片摘要：改 KB=X → role=Y"""
    kb = str(args.get("kb_id", "?"))[:8]
    role = args.get("kb_role", "?")
    return f"改 KB={kb} → role={role}"


@tool_with_audit(
    mcp,
    require_approval=True,
    summary_fn=_kb_set_role_summary,
    timeout_seconds=3600,
)
async def kb_set_role(kb_id: str, kb_role: str) -> dict:
    """改 KB 角色（require_approval=True）。

    合法角色：authoritative / methodology / personal_log /
    template / private_doc / general

    Args:
        kb_id: KB id（uuid str）
        kb_role: 新角色

    Returns:
        {ok, result: {kb_id, kb_role, name, old_kb_role}, trace}
    """
    if kb_role not in _VALID_KB_ROLES:
        return {
            "ok": False,
            "error": "invalid_kb_role",
            "hint": f"kb_role 必须是 {sorted(_VALID_KB_ROLES)} 之一，给的是 {kb_role!r}",
        }

    # 校验 KB 存在
    existing = await ingestion.get_kb(kb_id)
    if not existing:
        return {
            "ok": False,
            "error": "kb_not_found",
            "hint": f"kb_id={kb_id} 不存在；用 list_kbs 查可用 id",
        }

    updated = await ingestion.update_kb_role(kb_id, kb_role)
    if not updated:
        return {
            "ok": False,
            "error": "update_failed",
            "hint": "ingestion.update_kb_role 返回 None；DB 写入失败",
        }

    return {
        "ok": True,
        "result": {
            "kb_id": kb_id,
            "kb_role": kb_role,
            "name": updated.get("name"),
            "old_kb_role": existing.get("kb_role"),
        },
        "trace": {
            "db_query": "UPDATE knowledge.knowledge_bases SET kb_role=$1 WHERE id=$2",
            "old_role": existing.get("kb_role"),
            "new_role": kb_role,
        },
    }
