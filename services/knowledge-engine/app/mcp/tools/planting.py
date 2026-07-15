"""Evidence-grounded planting pain-to-solution bridge generation."""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Mapping
from typing import Any

from app.mcp import prompts
from app.mcp.audit import tool_with_audit
from app.mcp.model_config import get_model_for_tool
from app.mcp.server import mcp
from app.mcp.trace import attach_next_step, build_trace
from app.services.ai_hub_client import AIHubClient
from app.services.pain_solution_bridge import (
    extract_response_text,
    load_planting_bridge_context,
    parse_bridge_payload,
    validate_bridge_pair,
)

logger = logging.getLogger(__name__)

_TOOL_NAME = "generate_planting_pain_solution_bridge"
_PROVIDER = "gemini"
_MODEL = "gemini-3.1-pro-preview"
_TEMPERATURE = 0.2
_MAX_TOKENS = 4000
_SYSTEM_PROMPT = "planting_pain_solution_bridge.system"
_USER_PROMPT = "planting_pain_solution_bridge.user"
_SENTINELS = {
    "@@SKU_FACTS_JSON@@": "sku_facts",
    "@@MATRIX_EVIDENCE_JSON@@": "matrix_evidence",
    "@@PORTRAIT_RECORD_EVIDENCE_JSON@@": "portrait_record_evidence",
    "@@PACK_CALIBRATION_JSON@@": "pack_calibration",
}


def _json_block(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        default=str,
    )


def _render_bridge_prompts(facts: Mapping[str, Any]) -> tuple[str, str]:
    """Load literal-brace-safe templates and replace unique sentinels."""

    system_prompt = prompts.load(_SYSTEM_PROMPT)
    user_prompt = prompts.load(_USER_PROMPT)
    for sentinel, facts_key in _SENTINELS.items():
        user_prompt = user_prompt.replace(sentinel, _json_block(facts.get(facts_key)))

    unresolved = [
        sentinel
        for sentinel in _SENTINELS
        if sentinel in system_prompt or sentinel in user_prompt
    ]
    if unresolved:
        raise ValueError(f"unresolved prompt sentinels: {unresolved}")
    return system_prompt, user_prompt


def _model_config_errors(config: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if config.get("provider") != _PROVIDER:
        errors.append(f"provider must be {_PROVIDER!r}")
    if config.get("model") != _MODEL:
        errors.append(f"model must be {_MODEL!r}")

    temperature = config.get("temperature")
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        errors.append(f"temperature must be exactly {_TEMPERATURE}")
    elif float(temperature) != _TEMPERATURE:
        errors.append(f"temperature must be exactly {_TEMPERATURE}")

    max_tokens = config.get("max_tokens")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
        errors.append(f"max_tokens must be exactly {_MAX_TOKENS}")
    elif max_tokens != _MAX_TOKENS:
        errors.append(f"max_tokens must be exactly {_MAX_TOKENS}")

    expected_prompts = {"system": _SYSTEM_PROMPT, "user": _USER_PROMPT}
    if config.get("prompts") != expected_prompts:
        errors.append(f"prompts must be exactly {expected_prompts!r}")
    return errors


def _bridge_trace(
    *,
    final_prompt: str,
    upstream_fact_hash: str | None,
) -> dict[str, Any]:
    return build_trace(
        provider=_PROVIDER,
        model=_MODEL,
        prompt=final_prompt,
        params={
            "temperature": _TEMPERATURE,
            "max_tokens": _MAX_TOKENS,
            "upstream_fact_hash": upstream_fact_hash,
        },
        cost_estimate="1 Gemini Pro call",
    )


def _invalid_result(
    *,
    errors: list[str],
    final_prompt: str,
    upstream_fact_hash: str | None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "pain_solution_bridge_invalid",
        "errors": errors,
        "trace": _bridge_trace(
            final_prompt=final_prompt,
            upstream_fact_hash=upstream_fact_hash,
        ),
    }


async def _generate_planting_pain_solution_bridge_impl(
    sku_id: str,
    audience_record_id: str,
    portrait_id: str,
    audience_pack_id: str | None = None,
) -> dict[str, Any]:
    """Generate exactly two grounded bridge candidates with one Pro call."""

    config = get_model_for_tool(_TOOL_NAME)
    config_errors = _model_config_errors(config)
    if config_errors:
        return {
            "ok": False,
            "error": "pain_solution_bridge_model_misconfigured",
            "detail": "; ".join(config_errors),
        }

    upstream = await load_planting_bridge_context(
        sku_id,
        audience_record_id,
        portrait_id,
        audience_pack_id,
    )
    if not upstream.get("ok"):
        return upstream

    facts = upstream.get("facts")
    upstream_fact_hash = upstream.get("upstream_fact_hash")
    if not isinstance(facts, Mapping):
        return {
            "ok": False,
            "error": "upstream_lineage_incomplete",
            "reason": "facts_missing",
        }

    try:
        system_prompt, user_prompt = _render_bridge_prompts(facts)
    except Exception as exc:
        return {
            "ok": False,
            "error": "pain_solution_bridge_invalid",
            "errors": [f"prompt_render_failed: {exc}"],
        }
    final_prompt = f"[system]\n{system_prompt}\n\n[user]\n{user_prompt}"

    try:
        response = await AIHubClient(timeout=360).chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            provider=_PROVIDER,
            model=_MODEL,
            temperature=_TEMPERATURE,
            max_tokens=_MAX_TOKENS,
            enforce_human_voice=False,
        )
    except Exception as exc:
        logger.exception("planting pain-solution bridge generation failed")
        return {
            "ok": False,
            "error": "pain_solution_bridge_generation_failed",
            "detail": str(exc),
            "trace": _bridge_trace(
                final_prompt=final_prompt,
                upstream_fact_hash=str(upstream_fact_hash),
            ),
        }

    try:
        bridges = parse_bridge_payload(extract_response_text(response))
    except (TypeError, ValueError) as exc:
        return _invalid_result(
            errors=[str(exc)],
            final_prompt=final_prompt,
            upstream_fact_hash=str(upstream_fact_hash),
        )

    raw_catalog = facts.get("eligible_evidence_catalog")
    evidence_catalog = copy.deepcopy(raw_catalog) if isinstance(raw_catalog, Mapping) else {}
    pack_catalog = facts.get("pack_calibration_catalog")
    if isinstance(pack_catalog, str) and pack_catalog:
        evidence_catalog["pack"] = pack_catalog

    validation = validate_bridge_pair(bridges, evidence_catalog=evidence_catalog)
    if not validation.get("ok"):
        validation_errors = [str(error) for error in validation.get("errors") or []]
        if any("must be identical across both bridges" in error for error in validation_errors):
            validation_errors.insert(0, "cross_candidate_drift")
        return _invalid_result(
            errors=validation_errors,
            final_prompt=final_prompt,
            upstream_fact_hash=str(upstream_fact_hash),
        )

    result: dict[str, Any] = {
        "ok": True,
        "result": {
            "bridges": bridges,
            "upstream_fact_hash": upstream_fact_hash,
        },
        "trace": _bridge_trace(
            final_prompt=final_prompt,
            upstream_fact_hash=str(upstream_fact_hash),
        ),
    }
    return attach_next_step(
        result,
        suggested_tool=None,
        human_text=(
            "请先人工审阅两条痛点→产品解决桥；本工具不会自动生成或采纳脚本，"
            "也不会自动挂接实验臂。"
        ),
    )


@tool_with_audit(mcp, require_approval=False)
async def generate_planting_pain_solution_bridge(
    sku_id: str,
    audience_record_id: str,
    portrait_id: str,
    audience_pack_id: str | None = None,
) -> dict[str, Any]:
    """Generate two review-only, evidence-grounded planting bridge candidates."""

    return await _generate_planting_pain_solution_bridge_impl(
        sku_id,
        audience_record_id,
        portrait_id,
        audience_pack_id,
    )


__all__ = [
    "_generate_planting_pain_solution_bridge_impl",
    "_render_bridge_prompts",
    "generate_planting_pain_solution_bridge",
]
