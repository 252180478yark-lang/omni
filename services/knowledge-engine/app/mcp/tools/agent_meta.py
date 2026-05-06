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
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.database import get_pool
from app.mcp import prompts
from app.mcp.audit import tool_with_audit
from app.mcp.model_config import get_model_for_tool
from app.mcp.server import mcp
from app.mcp.trace import build_trace
from app.services.ai_hub_client import AIHubClient

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


# ─── T4: codify_pattern_to_skill ───────────────────────────────────────────


_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,49}$")


def _codify_summary(args: dict) -> str:
    return (f"codify_pattern_to_skill: skill_name={args.get('skill_name')} "
            f"tool_sequence={args.get('tool_sequence')}")


async def _codify_impl(
    *,
    skill_name: str,
    description: str,
    tool_sequence: list[str],
) -> dict:
    """codify 真业务（无 audit/gate）。给测试 mock 用，也给 tool 包装函数调。"""
    if not _SKILL_NAME_RE.match(skill_name or ""):
        return {
            "ok": False,
            "error": "invalid_skill_name",
            "hint": "skill_name 必须 a-z 0-9 - 组成、2-50 字符、首位字母数字",
        }
    if not tool_sequence or not isinstance(tool_sequence, list):
        return {
            "ok": False,
            "error": "invalid_tool_sequence",
            "hint": "tool_sequence 必须是非空 list[str]",
        }
    description = (description or "").strip()
    if not description:
        return {"ok": False, "error": "missing_description",
                "hint": "description 不能为空"}

    # 渲染 prompts
    tool_seq_block = "\n".join(f"- {t}" for t in tool_sequence)
    system_prompt = prompts.load("codify_skill.system")
    user_prompt = prompts.render(
        "codify_skill.user",
        skill_name=skill_name,
        description=description,
        tool_sequence_block=tool_seq_block,
    )

    cfg = get_model_for_tool("codify_pattern_to_skill")
    client = AIHubClient()
    try:
        resp = await client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            provider=cfg["provider"],
            model=cfg["model"],
            temperature=cfg.get("temperature", 0.3),
            max_tokens=cfg.get("max_tokens", 2048),
            enforce_human_voice=True,
        )
    except Exception as exc:
        logger.exception("codify chat failed")
        return {
            "ok": False,
            "error": "llm_call_failed",
            "hint": f"ai-hub /chat 调用失败: {exc}",
        }

    md = (resp.get("content") or "").strip()
    if not md.startswith("---"):
        return {
            "ok": False,
            "error": "bad_llm_output",
            "hint": "LLM 没返回带 frontmatter 的 markdown，重跑或换模型",
        }

    # 写草稿（已存在则加时间戳）
    draft_dir = SKILL_DRAFTS_DIR / skill_name
    if draft_dir.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        draft_dir = SKILL_DRAFTS_DIR / f"{skill_name}__{ts}"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "SKILL.md"
    draft_path.write_text(md, encoding="utf-8")

    effective_provider = resp.get("provider") or cfg["provider"]
    effective_model = resp.get("model") or cfg["model"]
    trace = build_trace(
        provider=effective_provider,
        model=effective_model,
        prompt=f"[system]\n{system_prompt}\n\n[user]\n{user_prompt[:500]}...",
        params={
            "temperature": cfg.get("temperature", 0.3),
            "max_tokens": cfg.get("max_tokens", 2048),
            "tool_sequence_len": len(tool_sequence),
        },
        cost_estimate="~1k tokens",
    )
    trace["provider"] = effective_provider  # alias 让 testers/读者两边都能拿

    return {
        "ok": True,
        "result": {
            "skill_name": skill_name,
            "draft_path": str(draft_path),
            "host_hint": (
                f"草稿已写到 {draft_path}（host 路径 "
                f"data/agent_state/skill_drafts/{draft_dir.name}/SKILL.md）。"
                "审过后 host 侧手动 `cp -r data/agent_state/skill_drafts/"
                f"{draft_dir.name} ~/.claude/skills/{skill_name}` 启用。"
            ),
            "markdown": md,
        },
        "trace": trace,
    }


@tool_with_audit(
    mcp,
    require_approval=True,
    summary_fn=_codify_summary,
)
async def codify_pattern_to_skill(
    skill_name: str,
    description: str,
    tool_sequence: list[str],
) -> dict:
    """把一个高频 tool 调用序列升级成 skill markdown 草稿（require_approval=True）。

    Args:
        skill_name: skill 名（kebab-case，2-50 字符）
        description: 一句话描述触发场景
        tool_sequence: tool 名序列（list[str]，至少 1 个）

    Returns:
        {ok, result: {skill_name, draft_path, host_hint, markdown}, trace}
    """
    return await _codify_impl(
        skill_name=skill_name,
        description=description,
        tool_sequence=tool_sequence,
    )
