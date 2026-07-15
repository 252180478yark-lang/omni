"""Evidence-grounded planting pain-to-solution bridge generation."""

from __future__ import annotations

import copy
import json
import logging
import re
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
_SENTINEL_PATTERN = re.compile(
    "|".join(re.escape(sentinel) for sentinel in _SENTINELS)
)


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
    user_template = prompts.load(_USER_PROMPT)
    system_hits = [sentinel for sentinel in _SENTINELS if sentinel in system_prompt]
    bad_user_counts = {
        sentinel: user_template.count(sentinel)
        for sentinel in _SENTINELS
        if user_template.count(sentinel) != 1
    }
    if system_hits or bad_user_counts:
        raise ValueError(
            "prompt sentinel contract violated: "
            f"system_hits={system_hits}, user_counts={bad_user_counts}"
        )

    replacements = {
        sentinel: _json_block(facts.get(facts_key))
        for sentinel, facts_key in _SENTINELS.items()
    }
    user_prompt = _SENTINEL_PATTERN.sub(
        lambda match: replacements[match.group(0)],
        user_template,
    )
    return system_prompt, user_prompt


def _validated_model_config(
    config: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    provider = config.get("provider")
    model = config.get("model")
    if provider != _PROVIDER:
        errors.append(f"provider must be {_PROVIDER!r}")
    if model != _MODEL:
        errors.append(f"model must be {_MODEL!r}")

    raw_temperature = config.get("temperature")
    try:
        if isinstance(raw_temperature, bool):
            raise TypeError
        temperature = float(raw_temperature)
    except (TypeError, ValueError):
        temperature = None
        errors.append(f"temperature must be exactly {_TEMPERATURE}")
    else:
        if temperature != _TEMPERATURE:
            errors.append(f"temperature must be exactly {_TEMPERATURE}")

    raw_max_tokens = config.get("max_tokens")
    if isinstance(raw_max_tokens, bool):
        max_tokens = None
    elif isinstance(raw_max_tokens, int):
        max_tokens = raw_max_tokens
    elif isinstance(raw_max_tokens, str) and raw_max_tokens.strip().isdigit():
        max_tokens = int(raw_max_tokens.strip())
    else:
        max_tokens = None
    if max_tokens != _MAX_TOKENS:
        errors.append(f"max_tokens must be exactly {_MAX_TOKENS}")

    expected_prompts = {"system": _SYSTEM_PROMPT, "user": _USER_PROMPT}
    if config.get("prompts") != expected_prompts:
        errors.append(f"prompts must be exactly {expected_prompts!r}")

    if errors:
        return None, errors
    return {
        "provider": provider,
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }, []


def _bridge_trace(
    *,
    final_prompt: str,
    upstream_fact_hash: str | None,
    model_config: Mapping[str, Any],
) -> dict[str, Any]:
    return build_trace(
        provider=model_config["provider"],
        model=model_config["model"],
        prompt=final_prompt,
        params={
            "temperature": model_config["temperature"],
            "max_tokens": model_config["max_tokens"],
            "upstream_fact_hash": upstream_fact_hash,
        },
        cost_estimate="1 Gemini Pro call",
    )


def _invalid_result(
    *,
    errors: list[str],
    missing_or_invalid: list[str],
    final_prompt: str,
    upstream_fact_hash: str | None,
    model_config: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "pain_solution_bridge_invalid",
        "missing_or_invalid": list(dict.fromkeys(missing_or_invalid)),
        "errors": errors,
        "trace": _bridge_trace(
            final_prompt=final_prompt,
            upstream_fact_hash=upstream_fact_hash,
            model_config=model_config,
        ),
    }


async def _generate_planting_pain_solution_bridge_impl(
    sku_id: str,
    audience_record_id: str,
    portrait_id: str,
    audience_pack_id: str | None = None,
) -> dict[str, Any]:
    """Generate exactly two grounded bridge candidates with one Pro call."""

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

    config = get_model_for_tool(_TOOL_NAME)
    model_config, config_errors = _validated_model_config(config)
    if model_config is None:
        return {
            "ok": False,
            "error": "pain_solution_bridge_model_misconfigured",
            "detail": "; ".join(config_errors),
        }

    try:
        system_prompt, user_prompt = _render_bridge_prompts(facts)
    except Exception as exc:
        return {
            "ok": False,
            "error": "pain_solution_bridge_invalid",
            "missing_or_invalid": ["prompt"],
            "errors": [f"prompt_render_failed: {exc}"],
        }
    final_prompt = f"[system]\n{system_prompt}\n\n[user]\n{user_prompt}"

    try:
        response = await AIHubClient(timeout=360).chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            provider=model_config["provider"],
            model=model_config["model"],
            temperature=model_config["temperature"],
            max_tokens=model_config["max_tokens"],
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
                model_config=model_config,
            ),
        }

    try:
        bridges = parse_bridge_payload(extract_response_text(response))
    except (TypeError, ValueError) as exc:
        return _invalid_result(
            errors=[str(exc)],
            missing_or_invalid=["payload"],
            final_prompt=final_prompt,
            upstream_fact_hash=str(upstream_fact_hash),
            model_config=model_config,
        )

    raw_catalog = facts.get("eligible_evidence_catalog")
    evidence_catalog = (
        dict(copy.deepcopy(raw_catalog)) if isinstance(raw_catalog, Mapping) else {}
    )
    pack_catalog = facts.get("pack_calibration_catalog")
    if isinstance(pack_catalog, Mapping) and pack_catalog:
        evidence_catalog["pack"] = dict(copy.deepcopy(pack_catalog))

    validation = validate_bridge_pair(bridges, evidence_catalog=evidence_catalog)
    if not validation.get("ok"):
        validation_errors = [str(error) for error in validation.get("errors") or []]
        missing_or_invalid = [
            str(field) for field in validation.get("missing_or_invalid") or []
        ]
        if any("must be identical across both bridges" in error for error in validation_errors):
            validation_errors.insert(0, "cross_candidate_drift")
            missing_or_invalid.insert(0, "cross_candidate_drift")
        return _invalid_result(
            errors=validation_errors,
            missing_or_invalid=missing_or_invalid or ["bridges"],
            final_prompt=final_prompt,
            upstream_fact_hash=str(upstream_fact_hash),
            model_config=model_config,
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
            model_config=model_config,
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


@tool_with_audit(mcp, require_approval=False)
async def register_product_reference_asset(
    sku_id: str,
    file_ref: str,
) -> dict[str, Any]:
    """Register one readable local product image as the current SKU's reference."""

    from app.services import pipeline_lineage
    from app.services.media_reference_manifest import resolve_reference_path

    if not isinstance(sku_id, str) or not sku_id.strip():
        return {"ok": False, "error": "product_ref_invalid_or_mismatch"}
    try:
        canonical_file = str(resolve_reference_path(file_ref))
    except (OSError, ValueError):
        return {"ok": False, "error": "product_ref_invalid_or_mismatch"}

    existing = await pipeline_lineage.get_product_reference_by_file(canonical_file)
    if existing:
        if existing.get("sku_id") != sku_id:
            return {"ok": False, "error": "product_ref_invalid_or_mismatch"}
        return {
            "ok": True,
            "result": {
                "asset_id": existing.get("id"),
                "sku_id": sku_id,
                "file_ref": canonical_file,
                "reused": True,
            },
        }

    asset_id = await pipeline_lineage.save_product_reference_asset(
        sku_id=sku_id,
        file_ref=canonical_file,
    )
    if not asset_id:
        return {"ok": False, "error": "product_ref_invalid_or_mismatch"}
    return {
        "ok": True,
        "result": {
            "asset_id": asset_id,
            "sku_id": sku_id,
            "file_ref": canonical_file,
            "reused": False,
        },
    }


__all__ = [
    "_generate_planting_pain_solution_bridge_impl",
    "_render_bridge_prompts",
    "generate_planting_pain_solution_bridge",
    "register_product_reference_asset",
]
