"""Prompt 反馈飞轮 — 核心服务。

提供以下能力供其他模块 / BFF 调用：

    业务侧调用（所有 19 个 LLM 节点必装）：
    ───────────────────────────────────────────
    render_rules_suffix(node_id, scope) → str
        渲染当前节点的所有启用规则为"## 使用者累积的修正规则"段落。
        在每次生成前拼到 prompt 末尾。顺便更新 hit_count / last_hit_at。

    log_feedback(node_id, input_ref, full_prompt, output, rating, ...) → feedback_id
        每次 LLM 生成完毕后调用，把 (prompt, output) 留痕。即使用户没点反馈
        也先留底，供事后回溯。

    反馈侧调用（BFF / 前端触发）：
    ───────────────────────────────────────────
    update_feedback(id, complaint, severity) → dict
        用户在 UI 写吐槽时调用。

    distill_feedback(id) → str
        用 LLM meta-prompt 把 complaint 提炼为一条可复用规则草稿。

    规则管理：
    ───────────────────────────────────────────
    create_rule / list_rules / update_rule / disable_rule / delete_rule
    list_nodes / get_node_stats
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from app.config import settings
from app.database import get_pool

logger = logging.getLogger(__name__)


_HUB_CHAT_URL = f"{settings.ai_provider_hub_url.rstrip('/')}/api/v1/ai/chat"

# 拉到 prompt 里的规则条数上限，防止 prompt 爆炸
_MAX_RULES_PER_RENDER = 30


# ═══════════════════════════════════════════════════════════
# 1. 业务侧：渲染规则 + 记录反馈
# ═══════════════════════════════════════════════════════════

async def render_rules_suffix(
    node_id: str,
    scope: dict | None = None,
) -> str:
    """渲染指定节点的启用规则为 prompt 末尾段落。

    Scope 匹配策略：
      - rule.scope 为 NULL       → 对该节点所有场景生效
      - rule.scope 非 NULL       → 必须是入参 scope 的子集（JSONB @>）才命中

    调用开销：一次 DB 查询 + 一次异步 UPDATE（fire-and-forget）。
    若 DB 不可用，返回空字符串，保证主流程不被阻塞。
    """
    try:
        pool = get_pool()
    except Exception:
        return ""

    try:
        if scope:
            scope_json = json.dumps(scope, ensure_ascii=False)
            rows = await pool.fetch(
                """
                SELECT id, rule_text
                FROM knowledge.prompt_rules
                WHERE node_id = $1 AND enabled = TRUE
                  AND (scope IS NULL OR $2::jsonb @> scope)
                ORDER BY created_at DESC
                LIMIT $3
                """,
                node_id, scope_json, _MAX_RULES_PER_RENDER,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT id, rule_text
                FROM knowledge.prompt_rules
                WHERE node_id = $1 AND enabled = TRUE AND scope IS NULL
                ORDER BY created_at DESC
                LIMIT $2
                """,
                node_id, _MAX_RULES_PER_RENDER,
            )
    except Exception as exc:
        logger.warning("render_rules_suffix query failed node=%s: %s", node_id, exc)
        return ""

    if not rows:
        return ""

    rule_ids = [r["id"] for r in rows]
    lines = [f"{i + 1}. {r['rule_text']}" for i, r in enumerate(rows)]

    # Fire-and-forget 更新 hit_count（不等待、失败不影响主流程）
    import asyncio
    async def _bump_hits() -> None:
        try:
            await pool.execute(
                """
                UPDATE knowledge.prompt_rules
                SET hit_count = hit_count + 1, last_hit_at = NOW()
                WHERE id = ANY($1::uuid[])
                """,
                rule_ids,
            )
        except Exception as exc:
            logger.debug("hit_count bump failed: %s", exc)

    asyncio.create_task(_bump_hits())

    return (
        "\n\n## 使用者累积的修正规则（最高优先级，必须遵守）\n"
        + "\n".join(lines)
    )


async def log_feedback(
    node_id: str,
    *,
    input_ref: dict | None = None,
    full_prompt: str | None = None,
    output: str | None = None,
    rating: int | None = None,
    severity: str | None = None,
    complaint: str | None = None,
) -> str | None:
    """每次 LLM 生成完毕后调用，留痕（rating 可 None，表示还没收到用户反馈）。

    返回 feedback_id（UUID 字符串）。DB 不可用时返回 None 不阻塞主流程。
    """
    try:
        pool = get_pool()
    except Exception:
        return None

    try:
        row = await pool.fetchrow(
            """
            INSERT INTO knowledge.prompt_feedbacks
                (node_id, input_ref, full_prompt, output, rating, severity, complaint)
            VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            node_id,
            json.dumps(input_ref or {}, ensure_ascii=False),
            (full_prompt or "")[:50000],   # 防止超长 prompt 撑爆
            (output or "")[:20000],
            rating,
            severity,
            complaint,
        )
        return str(row["id"])
    except Exception as exc:
        logger.warning("log_feedback failed node=%s: %s", node_id, exc)
        return None


# ═══════════════════════════════════════════════════════════
# 2. 反馈侧：更新反馈 + LLM 提炼规则
# ═══════════════════════════════════════════════════════════

async def update_feedback(
    feedback_id: str,
    *,
    rating: int | None = None,
    severity: str | None = None,
    complaint: str | None = None,
) -> dict | None:
    """用户在 UI 点 👎 / 写吐槽时调用。允许多次更新同一条反馈。"""
    pool = get_pool()
    row = await pool.fetchrow(
        """
        UPDATE knowledge.prompt_feedbacks
        SET rating    = COALESCE($1, rating),
            severity  = COALESCE($2, severity),
            complaint = COALESCE($3, complaint)
        WHERE id = $4
        RETURNING *
        """,
        rating, severity, complaint, uuid.UUID(feedback_id),
    )
    return dict(row) if row else None


_DISTILL_META_PROMPT = """你是 prompt 调优专家。基于以下一次 LLM 生成的原始 prompt、生成结果、以及使用者的吐槽，请提炼出**一条可复用的通用规则**，供后续同类生成任务的 prompt 末尾使用。

## 原始 prompt（节选）
{prompt_excerpt}

## 生成结果（节选）
{output_excerpt}

## 使用者吐槽
{complaint}

## 提炼要求
1. **规则必须是可复用的通用约束**，不得提及具体产品名、具体数字、本次特定情境。
2. **规则必须是祈使句**（"必须..." / "禁止..." / "优先..."），不要描述现象。
3. **规则长度 15-50 字**，一句话说清楚。
4. 如果吐槽是一次性的、无可复用结论（例如"这次运气不好"），返回 "SKIP"。
5. 如果吐槽其实是用户的使用错误（例如产品信息输错了），返回 "SKIP"。

## 输出
直接输出一行规则文本（或 "SKIP"），不要加引号、前缀、解释。
"""


async def distill_feedback(feedback_id: str) -> str | None:
    """用小模型把用户吐槽提炼为一条可复用规则草稿，并写回 feedback.distilled 字段。

    返回草稿文本；若 LLM 认为无可复用结论则返回 None。
    """
    pool = get_pool()
    fb = await pool.fetchrow(
        "SELECT full_prompt, output, complaint FROM knowledge.prompt_feedbacks WHERE id = $1",
        uuid.UUID(feedback_id),
    )
    if not fb or not (fb.get("complaint") or "").strip():
        return None

    prompt = _DISTILL_META_PROMPT.format(
        prompt_excerpt=(fb.get("full_prompt") or "")[:2000],
        output_excerpt=(fb.get("output") or "")[:2000],
        complaint=fb["complaint"],
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                _HUB_CHAT_URL,
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 200,
                },
            )
            resp.raise_for_status()
            raw = (resp.json().get("content") or "").strip().strip('"').strip("'")
    except Exception as exc:
        logger.warning("distill_feedback LLM call failed: %s", exc)
        return None

    if not raw or raw.upper() == "SKIP" or len(raw) > 200:
        # 无可复用结论或模型偏航
        await pool.execute(
            "UPDATE knowledge.prompt_feedbacks SET distilled = $1 WHERE id = $2",
            raw, uuid.UUID(feedback_id),
        )
        return None

    await pool.execute(
        "UPDATE knowledge.prompt_feedbacks SET distilled = $1 WHERE id = $2",
        raw, uuid.UUID(feedback_id),
    )
    return raw


# ═══════════════════════════════════════════════════════════
# 3. 规则管理 CRUD
# ═══════════════════════════════════════════════════════════

async def create_rule(
    node_id: str,
    rule_text: str,
    *,
    scope: dict | None = None,
    created_from: str | None = None,
    enabled: bool = True,
    source_tool_call_id: str | None = None,
    source_experiment_id: str | None = None,
    source_round_var: str | None = None,
) -> dict:
    """新建一条修正规则。

    source_tool_call_id：若规则源自 mcp.tool_calls 的某条差评（新世界反馈→规则的桥），
    记该 tool_call_id（migration 051）；老飞轮 prompt_feedbacks 来源走 created_from。
    source_experiment_id + source_round_var：若规则源自某实验沉淀（experiment_distill，
    migration 052），记 experiment_id + 变量名（同实验同变量判重）。三类来源互不冲突、
    可都为 None（手动建）。
    """
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO knowledge.prompt_rules
            (node_id, rule_text, scope, created_from, enabled, source_tool_call_id,
             source_experiment_id, source_round_var)
        VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8)
        RETURNING *
        """,
        node_id,
        rule_text.strip(),
        json.dumps(scope, ensure_ascii=False) if scope else None,
        uuid.UUID(created_from) if created_from else None,
        enabled,
        uuid.UUID(source_tool_call_id) if source_tool_call_id else None,
        uuid.UUID(source_experiment_id) if source_experiment_id else None,
        source_round_var,
    )
    # 若 rule 来自某条 feedback，把它标记为 applied_as
    if created_from:
        try:
            await pool.execute(
                "UPDATE knowledge.prompt_feedbacks SET applied_as = $1 WHERE id = $2",
                row["id"], uuid.UUID(created_from),
            )
        except Exception:
            pass
    return dict(row)


async def list_rules(
    node_id: str | None = None,
    *,
    enabled_only: bool = False,
) -> list[dict]:
    pool = get_pool()
    where = []
    args: list = []
    if node_id:
        args.append(node_id)
        where.append(f"node_id = ${len(args)}")
    if enabled_only:
        where.append("enabled = TRUE")
    sql = "SELECT * FROM knowledge.prompt_rules"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY hit_count DESC, created_at DESC"
    rows = await pool.fetch(sql, *args)
    return [dict(r) for r in rows]


async def get_rule(rule_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM knowledge.prompt_rules WHERE id = $1",
        uuid.UUID(rule_id),
    )
    return dict(row) if row else None


async def update_rule(rule_id: str, payload: dict) -> dict | None:
    pool = get_pool()
    cur = await get_rule(rule_id)
    if not cur:
        return None

    rule_text = payload.get("rule_text", cur["rule_text"])
    scope = payload.get("scope", cur.get("scope"))
    enabled = payload.get("enabled", cur.get("enabled", True))

    row = await pool.fetchrow(
        """
        UPDATE knowledge.prompt_rules
        SET rule_text = $1,
            scope     = $2::jsonb,
            enabled   = $3
        WHERE id = $4
        RETURNING *
        """,
        rule_text,
        json.dumps(scope, ensure_ascii=False) if scope else None,
        bool(enabled),
        uuid.UUID(rule_id),
    )
    return dict(row) if row else None


async def disable_rule(rule_id: str) -> dict | None:
    return await update_rule(rule_id, {"enabled": False})


async def set_rule_enabled(rule_id: str, enabled: bool) -> dict | None:
    """只切 enabled 标志，不触碰 scope。

    专为"草稿先 enabled=FALSE、老板逐条点亮"流程做：走 update_rule 会把 cur.scope
    （asyncpg 未注册 jsonb codec 时是 str）再 json.dumps 一次造成双重编码，故这里
    单独 UPDATE enabled 一列绕开。
    """
    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE knowledge.prompt_rules SET enabled = $1 WHERE id = $2 RETURNING *",
        bool(enabled), uuid.UUID(rule_id),
    )
    return dict(row) if row else None


async def delete_rule(rule_id: str) -> bool:
    pool = get_pool()
    result = await pool.execute(
        "DELETE FROM knowledge.prompt_rules WHERE id = $1",
        uuid.UUID(rule_id),
    )
    return result.endswith("1")


# ═══════════════════════════════════════════════════════════
# 4. 反馈查询
# ═══════════════════════════════════════════════════════════

async def list_feedbacks(
    node_id: str | None = None,
    *,
    limit: int = 50,
    only_with_complaint: bool = False,
) -> list[dict]:
    pool = get_pool()
    where = []
    args: list = []
    if node_id:
        args.append(node_id)
        where.append(f"node_id = ${len(args)}")
    if only_with_complaint:
        where.append("complaint IS NOT NULL AND complaint <> ''")
    sql = """
        SELECT id, node_id, input_ref, rating, severity, complaint, distilled,
               applied_as, created_at,
               LEFT(full_prompt, 800) AS prompt_preview,
               LEFT(output, 1200) AS output_preview
        FROM knowledge.prompt_feedbacks
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    args.append(limit)
    sql += f" ORDER BY created_at DESC LIMIT ${len(args)}"
    rows = await pool.fetch(sql, *args)
    return [dict(r) for r in rows]


async def get_feedback(feedback_id: str) -> dict | None:
    """返回单条反馈的完整 full_prompt / output，供"查看本次 prompt"用。"""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM knowledge.prompt_feedbacks WHERE id = $1",
        uuid.UUID(feedback_id),
    )
    return dict(row) if row else None


# ═══════════════════════════════════════════════════════════
# 5. 节点元数据 + 统计
# ═══════════════════════════════════════════════════════════

async def list_nodes() -> list[dict]:
    """返回所有节点 + 每个节点的规则数 / 7 天反馈统计。

    用于 /prompt-lab 仪表盘。
    """
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT
            n.id, n.title, n.description, n.page, n.category, n.enabled,
            COALESCE(r.rule_count, 0)        AS rule_count,
            COALESCE(r.hits_7d, 0)           AS hits_7d,
            COALESCE(f.fb_total_7d, 0)       AS fb_total_7d,
            COALESCE(f.fb_negative_7d, 0)    AS fb_negative_7d,
            COALESCE(f.fb_total_prev_7d, 0)  AS fb_total_prev_7d,
            COALESCE(f.fb_negative_prev_7d,0) AS fb_negative_prev_7d,
            r.last_hit_at
        FROM knowledge.prompt_nodes n
        LEFT JOIN LATERAL (
            SELECT
                COUNT(*) FILTER (WHERE enabled) AS rule_count,
                SUM(CASE WHEN last_hit_at > NOW() - INTERVAL '7 days' THEN hit_count ELSE 0 END) AS hits_7d,
                MAX(last_hit_at) AS last_hit_at
            FROM knowledge.prompt_rules
            WHERE node_id = n.id
        ) r ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') AS fb_total_7d,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days' AND rating = -1) AS fb_negative_7d,
                COUNT(*) FILTER (WHERE created_at <= NOW() - INTERVAL '7 days' AND created_at > NOW() - INTERVAL '14 days') AS fb_total_prev_7d,
                COUNT(*) FILTER (WHERE created_at <= NOW() - INTERVAL '7 days' AND created_at > NOW() - INTERVAL '14 days' AND rating = -1) AS fb_negative_prev_7d
            FROM knowledge.prompt_feedbacks
            WHERE node_id = n.id
        ) f ON TRUE
        ORDER BY n.category, n.id
        """
    )
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        # 计算 👎 率变化：本周 vs 上周
        total_cur = int(d["fb_total_7d"] or 0)
        neg_cur = int(d["fb_negative_7d"] or 0)
        total_prev = int(d["fb_total_prev_7d"] or 0)
        neg_prev = int(d["fb_negative_prev_7d"] or 0)
        d["neg_rate_7d"] = (neg_cur / total_cur) if total_cur else None
        d["neg_rate_prev_7d"] = (neg_prev / total_prev) if total_prev else None
        out.append(d)
    return out


async def get_node_detail(node_id: str) -> dict | None:
    pool = get_pool()
    node = await pool.fetchrow(
        "SELECT * FROM knowledge.prompt_nodes WHERE id = $1", node_id,
    )
    if not node:
        return None
    rules = await list_rules(node_id)
    feedbacks = await list_feedbacks(node_id, limit=30)
    return {
        "node": dict(node),
        "rules": rules,
        "recent_feedbacks": feedbacks,
    }
