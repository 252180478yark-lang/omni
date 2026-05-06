"""W4-A T3/T4/T5：agent_self_review + codify_pattern_to_skill + refresh_project_context。

design doc §7（5 层进化 + 7.2 草稿审批流 + 7.4 反馈循环）。

- agent_self_review(period_days?) — 纯 SQL 统计，不调 LLM。返反思报告 +
  candidate_patterns（滑窗 3 找高频 tool 序列）
- codify_pattern_to_skill(skill_name, description, tool_sequence) — 调 LLM 写
  SKILL.md 草稿到 /app/agent_state/skill_drafts/<name>/SKILL.md（require_approval=True）
- refresh_project_context() — 渲染 dynamic_block.md 到 /app/agent_state/
  让老板手动复制粘进 omni CLAUDE.md 的 marker 区块（require_approval=True）
"""
from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp

logger = logging.getLogger(__name__)

AGENT_STATE_DIR = Path("/app/agent_state")
SKILL_DRAFTS_DIR = AGENT_STATE_DIR / "skill_drafts"


# ─── T3: agent_self_review ─────────────────────────────────────────────────


@tool_with_audit(mcp, require_approval=False)
async def agent_self_review(period_days: int = 7) -> dict:
    """反思周报：读最近 N 天 mcp.tool_calls 出统计 + 候选 pattern。

    Args:
        period_days: 时间窗（默认 7 天）

    Returns:
        {ok, result: {
            period_days,
            total_calls,
            by_tool: {tool_name: count, ...},
            by_status: {completed/error/rejected: count, ...},
            by_rating: {good/bad/redo/null: count, ...},
            candidate_patterns: [{sequence: [str, str, str], occurrences: int}, ...]
        }}
    """
    if period_days <= 0:
        return {"ok": False, "error": "invalid_period",
                "hint": "period_days 必须 > 0"}

    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, tool_name, status, user_rating, created_at
          FROM mcp.tool_calls
         WHERE created_at >= NOW() - ($1 || ' days')::interval
         ORDER BY created_at ASC
        """,
        str(period_days),
    )
    total = len(rows)
    by_tool = Counter(r["tool_name"] for r in rows)
    by_status = Counter(r["status"] for r in rows)
    by_rating = Counter(r["user_rating"] or "null" for r in rows)

    # 滑窗 3 找 candidate_patterns
    seq_counter: Counter[tuple[str, ...]] = Counter()
    if total >= 3:
        names = [r["tool_name"] for r in rows]
        for i in range(len(names) - 2):
            seq_counter[(names[i], names[i+1], names[i+2])] += 1
    candidates = [
        {"sequence": list(seq), "occurrences": cnt}
        for seq, cnt in seq_counter.most_common()
        if cnt >= 3
    ]

    return {
        "ok": True,
        "result": {
            "period_days": period_days,
            "total_calls": total,
            "by_tool": dict(by_tool),
            "by_status": dict(by_status),
            "by_rating": dict(by_rating),
            "candidate_patterns": candidates,
            "next_step_hint": (
                f"找到 {len(candidates)} 个候选 pattern。下一步：调 "
                "codify_pattern_to_skill(skill_name=..., description=..., "
                "tool_sequence=[...]) 把高频组合升级成 skill 草稿。"
                if candidates else
                "未找到 ≥3 次重复的 3-tool 序列；继续累积调用数据后再 review。"
            ),
        },
    }
