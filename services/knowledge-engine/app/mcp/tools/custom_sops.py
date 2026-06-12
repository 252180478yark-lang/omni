"""自建 SOP 存储 MCP tools（2026-06-12）。

老板要"自建 SOP"：桌面说需求 → chat claude 拟 SOP → 老板确认 →
sop_save_custom 入库（mcp.custom_sops，migration 050）→ 桌面菜单「我的 SOP」
展示复用（sop_list_custom）→ 不要了 sop_archive_custom 下架。

约定：
- 同名 active 唯一（partial unique index）；重存同名 = UPDATE version+1 全量覆盖
- archive 不物理删（留痕），同名可再建新 active 行
- 三 tool 都 @tool_with_audit、require_approval=False（纯存储不烧钱不碰外部）
"""
from __future__ import annotations

import json
import logging
import uuid as _uuid

import asyncpg

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp

logger = logging.getLogger(__name__)

_DEFAULT_DOMAIN = "🧩 我的 SOP"


def _validate_steps(steps: list | None) -> tuple[list, str | None]:
    """steps 每项必须是含非空 tool 字段的 dict；返回 (规范化列表, 错误信息或 None)。"""
    if steps is None:
        return [], None
    if not isinstance(steps, list):
        return [], "steps 必须是 list"
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            return [], f"steps[{i}] 必须是 dict（含 tool 字段）"
        tool = step.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            return [], f"steps[{i}] 缺非空 tool 字段"
    return steps, None


def _row_to_sop(row: asyncpg.Record) -> dict:
    """DB 行 → 可序列化 dict（steps jsonb 解码、时间转 iso 字符串）。"""
    steps_raw = row["steps"]
    try:
        steps = json.loads(steps_raw) if isinstance(steps_raw, str) else (steps_raw or [])
    except Exception:
        steps = []
    return {
        "sop_id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "domain": row["domain"],
        "steps": steps,
        "sop_md": row["sop_md"],
        "status": row["status"],
        "version": row["version"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@tool_with_audit(mcp, require_approval=False)
async def sop_save_custom(
    name: str,
    sop_md: str,
    description: str = "",
    steps: list | None = None,
    domain: str = "🧩 我的 SOP",
    sop_id: str | None = None,
) -> dict:
    """保存一条老板自建 SOP（新建或覆盖更新）。

    桌面拟稿确认后调它入库；给了 sop_id 或同名 active 已存在 → UPDATE
    （version+1 全量覆盖），否则 INSERT 新行。steps 每项须含 tool 字段
    （形如 [{"tool": "query_costs", "note": "先拿成本"}, ...]，可空）。

    Args:
        name: SOP 名（同名 active 唯一，重存同名 = 更新覆盖）
        sop_md: SOP 全文 markdown（必填）
        description: 一句话描述（菜单卡片用）
        steps: 结构化步骤列表，每项 dict 至少含 tool 字段
        domain: 菜单分组，默认 '🧩 我的 SOP'
        sop_id: 给了就定点更新这条（uuid 字符串）

    Returns:
        {ok, sop_id, version, mode: 'created'|'updated'}
    """
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "name_required", "hint": "SOP 名不能为空"}
    if not (sop_md or "").strip():
        return {"ok": False, "error": "sop_md_required", "hint": "SOP 正文 markdown 不能为空"}
    steps, steps_err = _validate_steps(steps)
    if steps_err:
        return {
            "ok": False, "error": "steps_invalid",
            "hint": f"{steps_err}；steps 形如 [{{'tool': 'query_costs', 'note': '...'}}]",
        }
    domain = (domain or "").strip() or _DEFAULT_DOMAIN
    steps_json = json.dumps(steps, ensure_ascii=False)

    pool = get_pool()

    # 定更新目标：显式 sop_id 优先；否则查同名 active
    target_id: str | None = None
    if sop_id:
        try:
            _uuid.UUID(sop_id)
        except (ValueError, AttributeError, TypeError):
            return {"ok": False, "error": "bad_sop_id", "hint": f"sop_id 不是合法 uuid：{sop_id}"}
        exists = await pool.fetchval(
            "SELECT 1 FROM mcp.custom_sops WHERE id = $1::uuid", sop_id
        )
        if not exists:
            return {"ok": False, "error": "sop_not_found", "hint": f"没有这条 SOP：{sop_id}（调 sop_list_custom 看清单）"}
        target_id = sop_id
    else:
        row = await pool.fetchrow(
            "SELECT id FROM mcp.custom_sops WHERE name = $1 AND status = 'active'", name
        )
        if row:
            target_id = str(row["id"])

    try:
        if target_id:
            updated = await pool.fetchrow(
                """
                UPDATE mcp.custom_sops
                   SET name = $2, description = $3, domain = $4,
                       steps = $5::jsonb, sop_md = $6,
                       version = version + 1, updated_at = NOW()
                 WHERE id = $1::uuid
                 RETURNING id, version
                """,
                target_id, name, description or "", domain, steps_json, sop_md,
            )
            out_id, out_version, mode = str(updated["id"]), updated["version"], "updated"
        else:
            inserted = await pool.fetchrow(
                """
                INSERT INTO mcp.custom_sops (name, description, domain, steps, sop_md)
                VALUES ($1, $2, $3, $4::jsonb, $5)
                RETURNING id, version
                """,
                name, description or "", domain, steps_json, sop_md,
            )
            out_id, out_version, mode = str(inserted["id"]), inserted["version"], "created"
    except asyncpg.UniqueViolationError:
        return {
            "ok": False, "error": "name_conflict",
            "hint": f"已有同名 active SOP「{name}」；不传 sop_id 重存会自动更新它，或先 sop_archive_custom 下架",
        }

    logger.info("sop_save_custom %s name=%s version=%d id=%s", mode, name[:30], out_version, out_id[:8])
    return {"ok": True, "sop_id": out_id, "version": out_version, "mode": mode}


@tool_with_audit(mcp, require_approval=False)
async def sop_list_custom(include_archived: bool = False) -> dict:
    """列出老板自建的 SOP（桌面菜单「我的 SOP」数据源）。

    默认只看 active（在用的）；include_archived=True 把下架的也带上。
    返回全字段含 sop_md 全文，按 updated_at 倒序（最近改的在前）。

    Returns:
        {ok, count, sops: [{sop_id, name, description, domain, steps, sop_md,
                            status, version, created_at, updated_at}, ...]}
    """
    pool = get_pool()
    where = "" if include_archived else "WHERE status = 'active'"
    rows = await pool.fetch(
        f"""
        SELECT id, name, description, domain, steps, sop_md,
               status, version, created_at, updated_at
          FROM mcp.custom_sops
          {where}
         ORDER BY updated_at DESC
        """
    )
    sops = [_row_to_sop(r) for r in rows]
    return {"ok": True, "count": len(sops), "sops": sops}


@tool_with_audit(mcp, require_approval=False)
async def sop_archive_custom(sop_id: str) -> dict:
    """下架一条自建 SOP（不物理删，留痕；菜单默认不再展示）。

    老板说"这个 SOP 不要了 / 删掉 X"时调；之后同名可再建新的。

    Returns:
        {ok, sop_id, name, status: 'archived'}
    """
    try:
        _uuid.UUID(sop_id or "")
    except (ValueError, AttributeError, TypeError):
        return {"ok": False, "error": "bad_sop_id", "hint": f"sop_id 不是合法 uuid：{sop_id}"}

    pool = get_pool()
    row = await pool.fetchrow(
        """
        UPDATE mcp.custom_sops
           SET status = 'archived', updated_at = NOW()
         WHERE id = $1::uuid
         RETURNING id, name
        """,
        sop_id,
    )
    if not row:
        return {"ok": False, "error": "sop_not_found", "hint": f"没有这条 SOP：{sop_id}（调 sop_list_custom 看清单）"}
    logger.info("sop_archive_custom id=%s name=%s", sop_id[:8], row["name"][:30])
    return {"ok": True, "sop_id": str(row["id"]), "name": row["name"], "status": "archived"}
