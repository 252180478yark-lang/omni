"""Transparent P0 execution-content to audience alignment evidence.

This is deliberately a small, inspectable proxy rather than a hidden model or
a purchase prediction.  It exposes the exact text, visual-prompt and audio
inputs that an owner can review before generation and again after composition.
The resulting number is useful for ordering a human review, never for choosing
a winner or bypassing the three P0 gates.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.services.video_production_contract import P0_CONTRACT_VERSION, content_hash


_CJK_BLOCK = re.compile(r"[\u4e00-\u9fff]{2,}")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}")
_WHITESPACE = re.compile(r"\s+")


def _as_mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_text(value: object, *, limit: int = 6000) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _WHITESPACE.sub(" ", value).strip()[:limit]
    if isinstance(value, Mapping):
        return _as_text(" ".join(_as_text(item, limit=1000) for item in value.values()), limit=limit)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return _as_text(" ".join(_as_text(item, limit=1000) for item in value), limit=limit)
    return str(value).strip()[:limit]


def _excerpt(value: object, *, limit: int = 320) -> str:
    text = _as_text(value, limit=limit + 1)
    return text if len(text) <= limit else f"{text[:limit]}…"


def _terms(value: object) -> set[str]:
    """Return bounded, readable tokens for a visible overlap check.

    Chinese segmentation is intentionally conservative: contiguous 2--6 char
    blocks and short n-grams are enough to explain overlap without pretending
    this is a semantic embedding model.
    """

    text = _as_text(value).lower()
    found: set[str] = set(_LATIN_WORD.findall(text))
    for block in _CJK_BLOCK.findall(text):
        if len(block) <= 6:
            found.add(block)
        else:
            for width in (2, 3, 4):
                for start in range(0, len(block) - width + 1):
                    found.add(block[start : start + width])
    return {term for term in found if len(term) >= 2}


def _shared_terms(left: object, right: object, *, limit: int = 8) -> list[str]:
    shared = _terms(left) & _terms(right)
    return sorted(shared, key=lambda item: (-len(item), item))[:limit]


def _prompt_source_sections(value: object) -> dict[str, Any]:
    envelope = _as_mapping(value)
    source = _as_mapping(envelope.get("prompt_source") or envelope)
    return source


def _audio_alignment(audio_plan: Mapping[str, Any]) -> tuple[dict[str, Any], float, list[str]]:
    plan = _as_mapping(audio_plan)
    bgm = _as_mapping(plan.get("bgm"))
    mode = str(plan.get("mode") or "unknown")
    bgm_mode = str(bgm.get("mode") or bgm.get("status") or "not_supplied")
    authorization = bool(
        bgm.get("authorization_note")
        or bgm.get("authorization_basis")
        or bgm_mode in {"none_scope_confirmed", "not_required"}
    )
    has_source = bool(bgm.get("source_sha256"))
    warnings: list[str] = []
    if bgm_mode == "authorized" and not (authorization and has_source):
        warnings.append("authorized_bgm_manifest_incomplete")
    if bgm_mode in {"not_supplied", "none"}:
        warnings.append("bgm_not_configured")
    if bgm_mode == "none_scope_confirmed" and not authorization:
        warnings.append("no_bgm_scope_confirmation_missing")
    audio_ok = authorization and (bgm_mode != "authorized" or has_source)
    if mode in {"planned_native_audio", "native", "owner_supplied"}:
        audio_ok = audio_ok or bool(plan.get("native_audio_requested") or plan.get("source_sha256"))
    return (
        {
            "mode": mode,
            "native_audio_requested": bool(plan.get("native_audio_requested")),
            "bgm_mode": bgm_mode,
            "bgm_source_sha256": bgm.get("source_sha256"),
            "bgm_authorization_note": bgm.get("authorization_note") or bgm.get("authorization_basis"),
            "scope_confirmation": bgm.get("scope_note"),
        },
        1.0 if audio_ok else 0.0,
        warnings,
    )


def build_execution_content_match_report(
    *,
    stage: str,
    truth_snapshot: Mapping[str, Any],
    candidate: Mapping[str, Any],
    prompt_source: Mapping[str, Any],
    reference_manifest: Mapping[str, Any],
    audio_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an auditable planned/final P0 alignment report.

    ``stage`` is constrained by the persistence migration.  The report uses
    exact source excerpts and a documented lexical proxy so a human can see
    what aligned, what did not, and which inputs remain unverified.
    """

    if stage not in {"planned", "final"}:
        raise ValueError("execution_content_match_stage_invalid")

    truth = _as_mapping(truth_snapshot)
    audience = _as_mapping(truth.get("audience_record"))
    portrait = _as_mapping(truth.get("audience_portrait"))
    audience_text = _as_text(
        [
            audience.get("name"),
            audience.get("raw_md_segment"),
            audience.get("match_reasons"),
            portrait.get("portrait_md"),
        ]
    )
    script_text = _as_text(
        [
            candidate.get("opening_hook_3s"),
            candidate.get("body"),
            candidate.get("spoken_copy"),
            candidate.get("product_action"),
        ]
    )
    source = _prompt_source_sections(prompt_source)
    visual_text = _as_text(
        [
            source.get("identity_product_anchor"),
            source.get("product_solution_action"),
            source.get("scene_detail"),
            source.get("decorative_detail"),
            source.get("reference_instruction"),
        ]
    )
    text_shared = _shared_terms(audience_text, script_text)
    visual_shared = _shared_terms(audience_text, visual_text)
    audio, audio_component, audio_warnings = _audio_alignment(audio_plan)
    manifest = _as_mapping(reference_manifest)
    items = manifest.get("items")
    reference_ids = [
        str(item.get("id"))
        for item in items
        if isinstance(item, Mapping) and str(item.get("id") or "").strip()
    ] if isinstance(items, Sequence) and not isinstance(items, (str, bytes, bytearray)) else []

    # This score is intentionally simple and shown with its components.  It
    # cannot determine creative quality, truthfulness or conversion.
    text_component = min(len(text_shared), 4) / 4
    visual_component = min(len(visual_shared), 4) / 4
    proxy_score = round((text_component * 50 + visual_component * 30 + audio_component * 20), 1)
    warnings = list(audio_warnings)
    if not text_shared:
        warnings.append("text_audience_overlap_not_observed")
    if not visual_shared:
        warnings.append("visual_audience_overlap_not_observed")
    if not reference_ids:
        warnings.append("reference_manifest_empty")

    input_payload = {
        "contract_version": P0_CONTRACT_VERSION,
        "stage": stage,
        "truth_snapshot": truth,
        "candidate": dict(candidate),
        "prompt_source": dict(prompt_source),
        "reference_manifest": manifest,
        "audio_plan": dict(audio_plan),
    }
    return {
        "contract_version": P0_CONTRACT_VERSION,
        "schema_version": "p0.execution-content-match.v1",
        "stage": stage,
        "input_hash": content_hash(input_payload),
        "audience": {
            "name": audience.get("name"),
            "excerpt": _excerpt(audience_text),
            "source_hash": content_hash(audience_text),
        },
        "execution_content": {
            "text": {
                "excerpt": _excerpt(script_text),
                "shared_terms": text_shared,
            },
            "visual": {
                "excerpt": _excerpt(visual_text),
                "shared_terms": visual_shared,
                "reference_asset_ids": reference_ids,
            },
            "audio": audio,
        },
        "transparent_proxy": {
            "algorithm": "transparent_lexical_overlap.v1",
            "proxy_score_0_100": proxy_score,
            "components": {
                "text_overlap": round(text_component, 3),
                "visual_overlap": round(visual_component, 3),
                "audio_contract_present": round(audio_component, 3),
            },
            "only_for": "showing review evidence; never selects a script, provider or winner",
        },
        "warnings": sorted(set(warnings)),
        "disclaimer": (
            "这是可见词面与已冻结执行输入的投前代理，不代表用户会购买，也不能替代"
            "真实投放的完播率、转化率或人工审核。"
        ),
    }


__all__ = ["build_execution_content_match_report"]
