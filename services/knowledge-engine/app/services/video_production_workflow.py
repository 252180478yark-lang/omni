"""Executable workflow for the isolated P0 planting-video production atom.

P0 shares the existing SKU, audience, asset, prompt and audit foundations, but
keeps its own small order state machine.  In particular it does not create an
experiment arm or a video-generation set merely to satisfy historical video,
ecommerce or insert-video constraints.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import re
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.database import get_pool
from app.mcp import prompts
from app.mcp.model_config import get_model_for_tool
from app.mcp.trace import build_trace
from app.services.ai_hub_client import AIHubClient, HubError, prepare_video_reference_images
from app.services.asset_storage import ASSETS_ROOT, PUBLIC_URL_PREFIX, _safe_sku_dir
from app.services.media_reference_manifest import (
    ReferenceManifestError,
    assert_reference_manifest_matches,
    resolve_reference_path,
    sha256_reference,
)
from app.services.pain_solution_bridge import (
    canonical_upstream_fact_hash,
    validate_bridge_pair,
    validate_pain_solution_bridge,
)
from app.services.pipeline_lineage import save_storyboard_asset
from app.services.triangle_match import audit_content_triangle
from app.services.video_content_gate import evaluate_planting_content_gate
from app.services.video_production_match import build_execution_content_match_report
from app.services.video_production_vector_match import (
    P0_VECTOR_MATCHER_VERSION,
    assess_execution_vector_match,
    candidate_prompt_preview,
    frozen_prompt_execution_source,
)
from app.services.video_production_contract import (
    P0_CONTRACT_VERSION,
    P0_PACK_REQUIRED_CONTRACT_VERSIONS,
    P0_STRONG_LINEAGE_CONTRACT_VERSIONS,
    build_generation_approval_payload,
    build_p0_prompt_source,
    build_subtitle_timeline,
    canonical_json,
    content_hash,
    deterministic_script_gate,
    validate_candidate_pair,
    validate_media_probe,
    validate_subtitle_timeline,
    validate_transition,
)
from app.services.video_prompt_compiler import compile_final_prompt_segment


logger = logging.getLogger(__name__)

P0_PROMPT_ADAPTER_VERSION = "p0.seedance.adapter.v1"
P0_WRITER_TOOL = "p0_video_script_writer"
P0_CRITIC_TOOL = "p0_video_script_critic"
P0_GENERATION_TOOL = "p0_generate_video"
P0_QA_TOOL = "p0_video_qa"

# This is deliberately a small, closed response shape.  The raw-video QA gate
# must receive a complete decision object; a visible `decision: passed` inside
# a truncated response is not evidence enough to pass the asset.
RAW_SEMANTIC_QA_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["passed", "failed"]},
        "reason_codes": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decision", "reason_codes", "evidence"],
}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _content(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def _public_row(row: Mapping[str, Any], *, json_fields: Sequence[str] = ()) -> dict[str, Any]:
    """Return an MCP-safe row with JSONB objects decoded for callers.

    The asyncpg pool can surface JSONB as either mappings or JSON strings,
    depending on the process-level codec registration.  P0's public read
    endpoint must not make its UI/API consumers guess which representation
    they received.
    """

    result = dict(row)
    for field in json_fields:
        if field in result and result[field] is not None:
            result[field] = _content(result[field])
    return result


def _extract_json_object(response: object) -> dict[str, Any] | None:
    """Accept hub ``content`` JSON, including a fenced response, fail closed."""

    if not isinstance(response, Mapping):
        return None
    raw = response.get("content")
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return dict(parsed) if isinstance(parsed, Mapping) else None


def _candidate_script_markdown(candidate: Mapping[str, Any], slot: int) -> str:
    return "\n".join(
        (
            f"# P0 种草视频候选 {slot}",
            "",
            f"- 仅变量：前 3 秒钩子 — {candidate['opening_hook_3s']}",
            f"- 统一正文：{candidate['body']}",
            f"- 产品动作：{candidate['product_action']}",
            f"- 口播：{candidate['spoken_copy']}",
            f"- 时长：{candidate['duration_seconds']} 秒",
            f"- 事实声明：{'；'.join(str(item) for item in candidate['factual_claims'])}",
        )
    )


async def _load_context(conn, production_order_id: str, *, lock: bool = False) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if lock else ""
    order = await conn.fetchrow(
        f"""
        SELECT order_row.id::text AS id, order_row.sku_id, order_row.audience_record_id::text,
               order_row.audience_portrait_id::text,
               to_jsonb(order_row)->>'audience_pack_id' AS audience_pack_id,
               status, intent, contract_version, baseline_manifest, created_at, updated_at
        FROM pipeline.production_orders AS order_row WHERE order_row.id=$1::uuid{suffix}
        """,
        production_order_id,
    )
    if not order:
        return None
    truth = await conn.fetchrow(
        """
        SELECT id::text AS id, snapshot, snapshot_hash, created_at
        FROM pipeline.order_truth_snapshots
        WHERE production_order_id=$1::uuid
        """,
        production_order_id,
    )
    spec = await conn.fetchrow(
        """
        SELECT id::text AS id, version, spec, spec_hash, created_at
        FROM pipeline.production_content_specs
        WHERE production_order_id=$1::uuid
        ORDER BY version DESC LIMIT 1
        """,
        production_order_id,
    )
    return {
        "order": dict(order),
        "truth": dict(truth) if truth else None,
        "spec": dict(spec) if spec else None,
    }


def _require_context(
    context: dict[str, Any] | None, *, require_spec: bool = True
) -> dict[str, Any] | None:
    if context is None:
        return {"ok": False, "error": "production_order_not_found"}
    order = context.get("order")
    if not isinstance(order, Mapping) or str(order.get("contract_version") or "") != P0_CONTRACT_VERSION:
        return {
            "ok": False,
            "error": "production_order_contract_superseded",
            "order_contract_version": str(order.get("contract_version") or "") if isinstance(order, Mapping) else None,
            "current_contract_version": P0_CONTRACT_VERSION,
            "next_action": "create_a_new_order",
        }
    if not context.get("truth"):
        return {"ok": False, "error": "truth_snapshot_not_found"}
    if require_spec and not context.get("spec"):
        return {"ok": False, "error": "content_spec_not_found"}
    return None


def _is_p0_strong_lineage_order(order: Mapping[str, Any]) -> bool:
    """Identify versioned portrait/bridge orders without weakening legacy audit reads."""

    version = str(order.get("contract_version") or "").strip()
    return version in P0_STRONG_LINEAGE_CONTRACT_VERSIONS


def _bridge_evidence_catalog(
    bridge_context: Mapping[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Reconstruct the canonical validator catalog from one frozen strong-lineage context."""

    facts = _content(bridge_context.get("facts"))
    # v3/v4 freeze the already-normalized catalog at the context top level.
    # Prefer it exactly, including a frozen ``pack`` source; only retain the
    # nested-facts fallback for readable transitional snapshots.
    raw_catalog = bridge_context.get("eligible_evidence_catalog")
    if not isinstance(raw_catalog, Mapping):
        raw_catalog = facts.get("eligible_evidence_catalog")
    catalog = _content(raw_catalog)
    pack_catalog = facts.get("pack_calibration_catalog")
    if "pack" not in catalog and isinstance(pack_catalog, Mapping) and pack_catalog:
        catalog["pack"] = dict(pack_catalog)
    require_pack = bridge_context.get("require_pack_evidence")
    if not isinstance(require_pack, bool):
        require_pack = bool(catalog.get("pack"))
    return catalog, require_pack


def _frozen_strong_lineage_planting_context(
    context: Mapping[str, Any], *, require_spec: bool
) -> dict[str, Any]:
    """Validate the P0 v3/v4 portrait/bridge freeze before creative actions.

    This is deliberately a local read of the immutable order snapshot.  It
    never chooses a latest portrait or rebuilds the bridge context from mutable
    upstream tables.  Canonical bridge generation may independently re-read
    sources, but its returned hash is compared to this frozen hash before a
    candidate can be shown or selected.
    """

    order = _mapping(context.get("order"))
    truth_row = _mapping(context.get("truth"))
    truth = _content(truth_row.get("snapshot"))
    if not _is_p0_strong_lineage_order(order):
        return {
            "ok": False,
            "error": "p0_strong_lineage_contract_required",
            "order_contract_version": order.get("contract_version"),
            "first_blocker": "p0_strong_lineage_contract_required",
        }
    if require_spec and not isinstance(context.get("spec"), Mapping):
        return {
            "ok": False,
            "error": "content_spec_not_found",
            "first_blocker": "content_spec_not_found",
        }

    order_portrait_id = str(order.get("audience_portrait_id") or "").strip()
    portrait = _content(truth.get("audience_portrait"))
    snapshot_portrait_id = str(portrait.get("id") or "").strip()
    portrait_text = str(portrait.get("portrait_md") or "").strip()
    if not order_portrait_id or not snapshot_portrait_id or not portrait_text:
        return {
            "ok": False,
            "error": "frozen_audience_portrait_required",
            "first_blocker": "frozen_audience_portrait_required",
        }
    if snapshot_portrait_id != order_portrait_id:
        return {
            "ok": False,
            "error": "frozen_audience_portrait_mismatch",
            "first_blocker": "frozen_audience_portrait_mismatch",
            "expected_portrait_id": order_portrait_id,
            "snapshot_portrait_id": snapshot_portrait_id,
        }
    if str(portrait.get("status") or "") != "adopted":
        return {
            "ok": False,
            "error": "frozen_audience_portrait_not_adopted",
            "first_blocker": "frozen_audience_portrait_not_adopted",
        }

    bridge_context = _content(truth.get("planting_bridge_context"))
    facts = _content(bridge_context.get("facts"))
    upstream_fact_hash = str(bridge_context.get("upstream_fact_hash") or "").strip()
    if not facts or not upstream_fact_hash:
        return {
            "ok": False,
            "error": "frozen_pain_solution_bridge_context_required",
            "first_blocker": "frozen_pain_solution_bridge_context_required",
        }
    try:
        calculated_hash = canonical_upstream_fact_hash(facts)
    except (TypeError, ValueError) as exc:
        return {
            "ok": False,
            "error": "frozen_pain_solution_bridge_context_invalid",
            "first_blocker": "frozen_pain_solution_bridge_context_invalid",
            "detail": str(exc)[:300],
        }
    if calculated_hash != upstream_fact_hash:
        return {
            "ok": False,
            "error": "frozen_pain_solution_bridge_context_hash_mismatch",
            "first_blocker": "frozen_pain_solution_bridge_context_hash_mismatch",
            "expected_upstream_fact_hash": upstream_fact_hash,
            "actual_upstream_fact_hash": calculated_hash,
        }

    facts_lineage = _content(facts.get("lineage"))
    if (
        str(facts_lineage.get("sku_id") or "") != str(order.get("sku_id") or "")
        or str(facts_lineage.get("audience_record_id") or "")
        != str(order.get("audience_record_id") or "")
        or str(facts_lineage.get("portrait_id") or "") != order_portrait_id
    ):
        return {
            "ok": False,
            "error": "frozen_pain_solution_bridge_lineage_mismatch",
            "first_blocker": "frozen_pain_solution_bridge_lineage_mismatch",
        }

    catalog, require_pack = _bridge_evidence_catalog(bridge_context)
    if str(order.get("contract_version") or "") in P0_PACK_REQUIRED_CONTRACT_VERSIONS:
        order_pack_id = str(order.get("audience_pack_id") or "").strip()
        snapshot_pack_id = str(facts_lineage.get("audience_pack_id") or "").strip()
        pack_calibration = _content(facts.get("pack_calibration"))
        if not order_pack_id or not snapshot_pack_id:
            return {
                "ok": False,
                "error": "frozen_audience_pack_required",
                "first_blocker": "frozen_audience_pack_required",
            }
        if snapshot_pack_id != order_pack_id:
            return {
                "ok": False,
                "error": "frozen_audience_pack_mismatch",
                "first_blocker": "frozen_audience_pack_mismatch",
                "expected_audience_pack_id": order_pack_id,
                "snapshot_audience_pack_id": snapshot_pack_id,
            }
        if str(pack_calibration.get("id") or "").strip() != order_pack_id:
            return {
                "ok": False,
                "error": "frozen_audience_pack_calibration_mismatch",
                "first_blocker": "frozen_audience_pack_calibration_mismatch",
            }
        if not require_pack or not _content(catalog.get("pack")):
            return {
                "ok": False,
                "error": "frozen_audience_pack_evidence_required",
                "first_blocker": "frozen_audience_pack_evidence_required",
            }
    result = {
        "ok": True,
        "truth_snapshot": truth,
        "portrait": portrait,
        "bridge_context": bridge_context,
        "facts": facts,
        "upstream_fact_hash": upstream_fact_hash,
        "evidence_catalog": catalog,
        "require_pack_evidence": require_pack,
        "lineage": {
            "sku_id": order.get("sku_id"),
            "audience_record_id": order.get("audience_record_id"),
            "audience_portrait_id": order_portrait_id,
            "audience_pack_id": facts_lineage.get("audience_pack_id"),
        },
    }
    if require_spec:
        spec = _content(_mapping(context.get("spec")).get("spec"))
        bridge = spec.get("pain_solution_bridge")
        spec_hash = str(spec.get("upstream_fact_hash") or "").strip()
        if not isinstance(bridge, Mapping) or not spec_hash:
            return {
                "ok": False,
                "error": "structured_pain_solution_bridge_required",
                "first_blocker": "structured_pain_solution_bridge_required",
            }
        if spec_hash != upstream_fact_hash:
            return {
                "ok": False,
                "error": "pain_solution_bridge_upstream_hash_mismatch",
                "first_blocker": "pain_solution_bridge_upstream_hash_mismatch",
                "expected_upstream_fact_hash": upstream_fact_hash,
                "actual_upstream_fact_hash": spec_hash,
            }
        single_validation = validate_pain_solution_bridge(
            bridge,
            evidence_catalog=catalog,
            require_pack_evidence=require_pack,
        )
        if not single_validation.get("ok"):
            return {
                "ok": False,
                "error": "pain_solution_bridge_invalid",
                "first_blocker": "pain_solution_bridge_invalid",
                "bridge_errors": list(single_validation.get("errors") or []),
                "missing_or_invalid": list(single_validation.get("missing_or_invalid") or []),
            }
        result["pain_solution_bridge"] = dict(bridge)
    return result


async def _transition_locked(conn, order: Mapping[str, Any], next_status: str) -> dict[str, Any] | None:
    current = str(order["status"])
    if current == next_status:
        return None
    checked = validate_transition(current_status=current, next_status=next_status)
    if not checked["ok"]:
        return checked
    await conn.execute(
        "UPDATE pipeline.production_orders SET status=$2 WHERE id=$1::uuid",
        order["id"],
        next_status,
    )
    order["status"] = next_status
    return None


async def _scripts_for_order(conn, production_order_id: str, *, lock: bool = False) -> list[dict[str, Any]]:
    suffix = " FOR UPDATE OF review, script" if lock else ""
    rows = await conn.fetch(
        f"""
        SELECT review.id::text AS review_id, review.candidate_slot, review.deterministic_gate,
               review.critic_gate, review.status AS review_status, review.selected,
               script.id::text AS script_id, script.script_md, script.status AS script_status,
               script.content_contract, script.created_at
        FROM pipeline.production_script_reviews review
        JOIN pipeline.scripts script ON script.id=review.script_id
        WHERE review.production_order_id=$1::uuid
        ORDER BY review.candidate_slot ASC{suffix}
        """,
        production_order_id,
    )
    return [
        _public_row(
            row,
            json_fields=("deterministic_gate", "critic_gate", "content_contract"),
        )
        for row in rows
    ]


async def _persist_execution_content_match(
    conn,
    *,
    production_order_id: str,
    context: Mapping[str, Any],
    source: Mapping[str, Any],
    candidate: Mapping[str, Any],
    stage: str,
    audio_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist visible P0 alignment evidence idempotently inside one transaction."""

    report = build_execution_content_match_report(
        stage=stage,
        truth_snapshot=_content(_mapping(context.get("truth")).get("snapshot")),
        candidate=candidate,
        prompt_source=_content(source.get("prompt_source")),
        reference_manifest=_content(source.get("reference_manifest")),
        audio_plan=audio_plan,
    )
    source_id = str(source.get("id") or "").strip()
    if not source_id:
        raise ValueError("prompt_source_not_found")
    inserted = await conn.fetchrow(
        """
        INSERT INTO pipeline.production_content_match_reports(
            production_order_id,prompt_source_id,stage,input_hash,report
        ) VALUES($1::uuid,$2::uuid,$3,$4,$5::jsonb)
        ON CONFLICT (production_order_id,prompt_source_id,stage,input_hash) DO NOTHING
        RETURNING id::text AS id,report,created_at
        """,
        production_order_id,
        source_id,
        stage,
        report["input_hash"],
        _json(report),
    )
    if inserted:
        return {"id": inserted["id"], "report": _content(inserted["report"]), "reused": False}
    existing = await conn.fetchrow(
        """
        SELECT id::text AS id,report,created_at
        FROM pipeline.production_content_match_reports
        WHERE production_order_id=$1::uuid AND prompt_source_id=$2::uuid
          AND stage=$3 AND input_hash=$4
        """,
        production_order_id,
        source_id,
        stage,
        report["input_hash"],
    )
    if not existing:
        raise RuntimeError("execution_content_match_persist_failed")
    return {"id": existing["id"], "report": _content(existing["report"]), "reused": True}


async def _persist_execution_vector_match(
    conn,
    *,
    production_order_id: str,
    content_spec_id: str,
    script_id: str,
    prompt_source_id: str | None,
    stage: str,
    candidate_slot: int | None,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Store a real semantic pre-match without pretending it is an experiment arm."""

    embedding = _mapping(report.get("embedding"))
    execution_hash = str(report.get("execution_source_hash") or "").strip()
    audience_hash = str(report.get("audience_source_hash") or "").strip()
    provider = str(embedding.get("provider") or "").strip()
    model = str(embedding.get("model") or "").strip()
    matcher_version = str(embedding.get("matcher_version") or P0_VECTOR_MATCHER_VERSION).strip()
    report_status = str(report.get("status") or "").strip()
    audience_source_kind = str(report.get("audience_source_kind") or "").strip()
    execution_source_kind = str(report.get("execution_source_kind") or "").strip()
    if not all((execution_hash, audience_hash, provider, model, matcher_version, report_status,
                audience_source_kind, execution_source_kind)):
        raise ValueError("execution_vector_match_report_invalid")

    inserted = await conn.fetchrow(
        """
        INSERT INTO pipeline.production_vector_match_reports(
            production_order_id,content_spec_id,script_id,prompt_source_id,stage,candidate_slot,
            execution_source_kind,execution_source_hash,audience_source_kind,audience_source_hash,
            embedding_provider,embedding_model,matcher_version,report_status,report
        ) VALUES(
            $1::uuid,$2::uuid,$3::uuid,$4::uuid,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb
        )
        ON CONFLICT (
            production_order_id,script_id,stage,execution_source_hash,audience_source_hash,
            embedding_provider,embedding_model,matcher_version
        ) DO NOTHING
        RETURNING id::text AS id,report,created_at
        """,
        production_order_id,
        content_spec_id,
        script_id,
        prompt_source_id,
        stage,
        candidate_slot,
        execution_source_kind,
        execution_hash,
        audience_source_kind,
        audience_hash,
        provider,
        model,
        matcher_version,
        report_status,
        _json(report),
    )
    if inserted:
        return {"id": inserted["id"], "report": _content(inserted["report"]), "reused": False}
    existing = await conn.fetchrow(
        """
        SELECT id::text AS id,report,created_at
        FROM pipeline.production_vector_match_reports
        WHERE production_order_id=$1::uuid AND script_id=$2::uuid AND stage=$3
          AND execution_source_hash=$4 AND audience_source_hash=$5
          AND embedding_provider=$6 AND embedding_model=$7 AND matcher_version=$8
        ORDER BY created_at DESC LIMIT 1
        """,
        production_order_id,
        script_id,
        stage,
        execution_hash,
        audience_hash,
        provider,
        model,
        matcher_version,
    )
    if not existing:
        raise RuntimeError("execution_vector_match_persist_failed")
    return {"id": existing["id"], "report": _content(existing["report"]), "reused": True}


def _candidate_from_review(row: Mapping[str, Any]) -> dict[str, Any]:
    contract = _content(row.get("content_contract"))
    candidate = contract.get("p0_candidate")
    return dict(candidate) if isinstance(candidate, Mapping) else {}


def _p0_bridge_evidence_values(bridge: Mapping[str, Any]) -> list[str]:
    values = bridge.get("product_evidence")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return []
    return [
        str(item.get("value") or "").strip()
        for item in values
        if isinstance(item, Mapping) and str(item.get("value") or "").strip()
    ]


def _p0_triangle_inputs(
    *,
    truth_snapshot: Mapping[str, Any],
    spec: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Prepare explicit frozen inputs for the canonical content triangle audit."""

    truth = _mapping(truth_snapshot)
    bridge = _mapping(spec.get("pain_solution_bridge"))
    portrait = _mapping(truth.get("audience_portrait"))
    evidence = _p0_bridge_evidence_values(bridge)
    product_text = "\n".join(
        part
        for part in (
            str(bridge.get("product_action") or "").strip(),
            *evidence,
            str(bridge.get("visible_result") or "").strip(),
        )
        if part
    )
    audience_text = "\n".join(
        part
        for part in (
            str(bridge.get("audience_segment") or "").strip(),
            str(bridge.get("trigger_scene") or "").strip(),
            str(bridge.get("pain_point") or "").strip(),
            str(bridge.get("pain_consequence") or "").strip(),
            str(portrait.get("portrait_md") or "").strip(),
        )
        if part
    )
    beats = candidate.get("beat_plan")
    beat_items = beats if isinstance(beats, Sequence) and not isinstance(beats, (str, bytes, bytearray)) else []
    visual_parts: list[str] = []
    sound_parts: list[str] = []
    for beat in beat_items:
        if not isinstance(beat, Mapping):
            continue
        visual_parts.extend(
            str(beat.get(field) or "").strip() for field in ("visual", "action")
        )
        sound_parts.append(str(beat.get("sound") or "").strip())
    text_parts = [
        str(candidate.get(field) or "").strip()
        for field in ("opening_hook_3s", "body", "spoken_copy")
    ]
    return {
        "product_text": product_text,
        "audience_text": audience_text,
        "content_tracks": {
            "text": "\n".join(part for part in text_parts if part),
            "visual": "\n".join(part for part in visual_parts if part),
            "music": "\n".join(part for part in sound_parts if part),
        },
    }


def _unavailable_formal_content_gate(*, reason: str) -> dict[str, Any]:
    """Represent unavailable review evidence as a non-passing formal gate."""

    return {
        "pass": False,
        "failed_checks": [reason],
        "gate_version": "planting_v1",
        "status": "unavailable",
    }


def _stamp_frozen_candidate_fields(
    raw_candidates: Sequence[object],
    *,
    spec: Mapping[str, Any],
    content_spec_hash: str,
    truth_snapshot_hash: str,
) -> list[dict[str, Any]] | None:
    """Apply non-creative P0 invariants after the writer returns JSON.

    The writer owns the hook, body, spoken copy and selected factual claims.
    It must not be allowed to paraphrase or drift the frozen product-action
    field, duration, or lineage hashes.  The deterministic gate below still
    verifies that the canonical product action is literally rendered in the
    creative body and spoken copy, so this cannot mask a changed story.
    """

    actions = spec.get("product_actions")
    if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)):
        return None
    canonical_action = str(actions[0] if len(actions) == 1 else "").strip()
    if not canonical_action:
        return None
    try:
        canonical_duration = float(spec["duration_seconds"])
    except (KeyError, TypeError, ValueError):
        return None

    stamped: list[dict[str, Any]] = []
    for raw in raw_candidates:
        if not isinstance(raw, Mapping):
            return None
        candidate = dict(raw)
        candidate.update(
            {
                "product_action": canonical_action,
                "duration_seconds": canonical_duration,
                "content_spec_hash": content_spec_hash,
                "truth_snapshot_hash": truth_snapshot_hash,
            }
        )
        stamped.append(candidate)
    return stamped


async def save_script_candidates(
    *,
    production_order_id: str,
    candidates: Sequence[Mapping[str, Any]],
    writer_trace: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze exactly two P0 candidates before independent review.

    The only allowed difference is ``opening_hook_3s``.  This gives later
    review and paid generation a stable comparison instead of a drifting pair.
    """

    paired = validate_candidate_pair(candidates)
    if not paired["ok"]:
        return paired
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            context = await _load_context(conn, production_order_id, lock=True)
            missing = _require_context(context)
            if missing:
                return missing
            assert context is not None
            order = context["order"]
            if _is_p0_strong_lineage_order(order):
                frozen = _frozen_strong_lineage_planting_context(context, require_spec=True)
                if not frozen.get("ok"):
                    return frozen
            if order["status"] not in {"spec_ready", "awaiting_script_selection"}:
                return {"ok": False, "error": "production_order_wrong_state", "status": order["status"]}
            existing = await _scripts_for_order(conn, production_order_id, lock=True)
            if existing:
                existing_hashes = [
                    content_hash(_candidate_from_review(row)) for row in existing
                ]
                if existing_hashes == paired["candidate_hashes"]:
                    return {
                        "ok": True,
                        "reused": True,
                        "script_reviews": [
                            {"script_id": row["script_id"], "candidate_slot": row["candidate_slot"]}
                            for row in existing
                        ],
                    }
                return {"ok": False, "error": "script_candidates_immutable"}

            truth = _content(context["truth"]["snapshot"])
            spec = _content(context["spec"]["spec"])
            gates = [
                deterministic_script_gate(
                    candidate,
                    spec=spec,
                    truth_snapshot=truth,
                    content_spec_hash=context["spec"]["spec_hash"],
                    truth_snapshot_hash=context["truth"]["snapshot_hash"],
                )
                for candidate in candidates
            ]
            failed = [gate for gate in gates if gate["status"] != "passed"]
            if failed:
                return {"ok": False, "error": "script_deterministic_gate_failed", "gates": gates}

            review_rows: list[dict[str, Any]] = []
            for slot, (candidate, gate) in enumerate(zip(candidates, gates), start=1):
                script_contract = {
                    "version": P0_CONTRACT_VERSION,
                    "production_order_id": production_order_id,
                    "p0_candidate": dict(candidate),
                    "p0_candidate_hash": gate["candidate_hash"],
                    "writer_trace": dict(writer_trace or {}),
                }
                script = await conn.fetchrow(
                    """
                    INSERT INTO pipeline.scripts(
                        audience_record_id, sku_id, script_md, hooks, scenes,
                        target_purpose, model_provider, model, prompt_hash,
                        status, version, portrait_id, intent, notes, kind, content_contract
                    ) VALUES(
                        $1::uuid,$2,$3,$4::jsonb,$5::jsonb,
                        'planting',$6,$7,$8,
                        'draft',$9,$10::uuid,'planting',$11,'video_planting',$12::jsonb
                    ) RETURNING id::text AS id
                    """,
                    order["audience_record_id"],
                    order["sku_id"],
                    _candidate_script_markdown(candidate, slot),
                    _json([candidate["opening_hook_3s"]]),
                    _json([
                        {
                            "scene_no": 1,
                            "beat_no": beat_no,
                            "start_seconds": beat["start_seconds"],
                            "end_seconds": beat["end_seconds"],
                            "duration_seconds": round(
                                float(beat["end_seconds"]) - float(beat["start_seconds"]), 3
                            ),
                            "description": beat["visual"],
                            "action": beat["action"],
                            "spoken_copy": beat["spoken_copy"],
                            "sound": beat["sound"],
                            "product_action": candidate["product_action"],
                        }
                        for beat_no, beat in enumerate(candidate["beat_plan"], start=1)
                    ]),
                    str((writer_trace or {}).get("provider") or "p0_input"),
                    str((writer_trace or {}).get("model") or "p0_input"),
                    gate["candidate_hash"],
                    slot,
                    order.get("audience_portrait_id"),
                    "P0 candidate; immutable after review creation",
                    _json(script_contract),
                )
                review = await conn.fetchrow(
                    """
                    INSERT INTO pipeline.production_script_reviews(
                        production_order_id,content_spec_id,script_id,candidate_slot,
                        deterministic_gate,critic_gate,status
                    ) VALUES($1::uuid,$2::uuid,$3::uuid,$4,$5::jsonb,$6::jsonb,'pending_review')
                    RETURNING id::text AS id
                    """,
                    production_order_id,
                    context["spec"]["id"],
                    script["id"],
                    slot,
                    _json(gate),
                    _json({"status": "pending"}),
                )
                review_rows.append({"review_id": review["id"], "script_id": script["id"], "candidate_slot": slot})
            transition = await _transition_locked(conn, order, "awaiting_script_selection")
            if transition:
                return transition
            return {"ok": True, "reused": False, "script_reviews": review_rows}


async def generate_planting_bridge_candidates(
    *, production_order_id: str
) -> dict[str, Any]:
    """Generate review-only P0 bridges against one frozen order snapshot.

    The canonical planting generator owns prompt construction, model choice and
    bridge schema validation.  This wrapper only pins that generator to the
    production order's frozen lineage and rejects a result when mutable
    upstream facts have changed since the order was created.
    """

    pool = get_pool()
    async with pool.acquire() as conn:
        context = await _load_context(conn, production_order_id)
    missing = _require_context(context, require_spec=False)
    if missing:
        return missing
    assert context is not None
    order = _mapping(context.get("order"))
    if order.get("status") != "truth_ready":
        return {
            "ok": False,
            "error": "production_order_wrong_state",
            "status": order.get("status"),
            "first_blocker": "bridge_review_requires_truth_ready",
            "next_action": {
                "action": "create_or_open_a_new_v4_order",
                "requires_explicit_user_choice": True,
            },
        }
    frozen = _frozen_strong_lineage_planting_context(context, require_spec=False)
    if not frozen.get("ok"):
        return frozen

    # The canonical implementation deliberately lives behind its own audited
    # public MCP tool.  Calling its implementation here avoids a parallel P0
    # schema while this wrapper supplies the P0 order/freeze semantics.
    from app.mcp.tools.planting import _generate_planting_pain_solution_bridge_impl

    generated = await _generate_planting_pain_solution_bridge_impl(
        str(order["sku_id"]),
        str(order["audience_record_id"]),
        str(order["audience_portrait_id"]),
        str(order["audience_pack_id"]),
    )
    if not generated.get("ok"):
        result = dict(generated)
        result.setdefault("first_blocker", str(result.get("error") or "bridge_generation_failed"))
        return result
    canonical_result = _content(generated.get("result"))
    generated_hash = str(canonical_result.get("upstream_fact_hash") or "").strip()
    expected_hash = str(frozen["upstream_fact_hash"])
    if generated_hash != expected_hash:
        return {
            "ok": False,
            "error": "pain_solution_bridge_upstream_hash_mismatch",
            "first_blocker": "pain_solution_bridge_upstream_hash_mismatch",
            "expected_upstream_fact_hash": expected_hash,
            "actual_upstream_fact_hash": generated_hash or None,
            "trace": generated.get("trace"),
        }
    bridges = canonical_result.get("bridges")
    pair_validation = validate_bridge_pair(
        bridges,
        evidence_catalog=_mapping(frozen.get("evidence_catalog")),
        require_pack_evidence=bool(frozen.get("require_pack_evidence")),
    )
    if not pair_validation.get("ok"):
        return {
            "ok": False,
            "error": "pain_solution_bridge_invalid",
            "first_blocker": "pain_solution_bridge_invalid",
            "missing_or_invalid": list(pair_validation.get("missing_or_invalid") or []),
            "errors": list(pair_validation.get("errors") or []),
            "trace": generated.get("trace"),
        }

    response = {
        "ok": True,
        "production_order_id": production_order_id,
        "state": "BRIDGE_REVIEW",
        "lineage": dict(_mapping(frozen.get("lineage"))),
        # Keep the canonical payload for callers that already know the
        # planting bridge contract, and add P0 aliases for the dedicated page.
        "result": {
            "bridges": list(bridges),
            "upstream_fact_hash": expected_hash,
        },
        "bridge_review": {
            "bridges": list(bridges),
            "upstream_fact_hash": expected_hash,
        },
        "bridges": list(bridges),
        "upstream_fact_hash": expected_hash,
        "first_blocker": None,
        "next_action": {
            "action": "select_bridge_and_build_content_spec",
            "requires_explicit_user_choice": True,
        },
        "trace": generated.get("trace"),
    }
    return response


async def generate_script_candidates(
    *, production_order_id: str, extra_context: str | None = None
) -> dict[str, Any]:
    """Generate the two P0 candidate scripts, then freeze them through the same gate."""

    pool = get_pool()
    async with pool.acquire() as conn:
        context = await _load_context(conn, production_order_id)
    missing = _require_context(context)
    if missing:
        return missing
    assert context is not None
    if _is_p0_strong_lineage_order(_mapping(context.get("order"))):
        frozen = _frozen_strong_lineage_planting_context(context, require_spec=True)
        if not frozen.get("ok"):
            return frozen
    if context["order"]["status"] not in {"spec_ready", "awaiting_script_selection"}:
        return {"ok": False, "error": "production_order_wrong_state", "status": context["order"]["status"]}
    config = get_model_for_tool(P0_WRITER_TOOL)
    system_prompt = prompts.render("p0_video_writer.system")
    user_prompt = prompts.render(
        "p0_video_writer.user",
        truth_snapshot_json=canonical_json(_content(context["truth"]["snapshot"])),
        content_spec_json=canonical_json(_content(context["spec"]["spec"])),
        content_spec_hash=context["spec"]["spec_hash"],
        truth_snapshot_hash=context["truth"]["snapshot_hash"],
        extra_context=(extra_context or "无").strip() or "无",
    )
    client = AIHubClient(timeout=120.0)
    try:
        response = await client.chat(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            provider=str(config["provider"]),
            model=str(config["model"]),
            temperature=float(config.get("temperature", 0.3)),
            max_tokens=int(config.get("max_tokens", 4000)),
        )
    except Exception as exc:
        return {"ok": False, "error": "script_writer_unavailable", "detail": str(exc)[:300]}
    parsed = _extract_json_object(response)
    raw_candidates = parsed.get("candidates") if parsed else None
    if not isinstance(raw_candidates, list):
        return {"ok": False, "error": "script_writer_output_invalid"}
    spec = _content(context["spec"]["spec"])
    candidates = _stamp_frozen_candidate_fields(
        raw_candidates,
        spec=spec,
        content_spec_hash=context["spec"]["spec_hash"],
        truth_snapshot_hash=context["truth"]["snapshot_hash"],
    )
    if candidates is None:
        return {"ok": False, "error": "script_writer_output_invalid"}
    writer_trace = build_trace(
        provider=str(response.get("provider") or config["provider"]),
        model=str(response.get("model") or config["model"]),
        prompt=f"{system_prompt}\n\n{user_prompt}",
        params={"production_order_id": production_order_id, "extra_context": extra_context or ""},
        cost_estimate="LLM script-writing call; see hub usage",
    )
    return await save_script_candidates(
        production_order_id=production_order_id,
        candidates=candidates,
        writer_trace=writer_trace,
    )


async def review_script_candidates(*, production_order_id: str) -> dict[str, Any]:
    """Run independent critic checks after deterministic truth checks pass."""

    pool = get_pool()
    async with pool.acquire() as conn:
        context = await _load_context(conn, production_order_id)
        if _require_context(context):
            return _require_context(context) or {}
        reviews = await _scripts_for_order(conn, production_order_id)
    assert context is not None
    if _is_p0_strong_lineage_order(_mapping(context.get("order"))):
        frozen = _frozen_strong_lineage_planting_context(context, require_spec=True)
        if not frozen.get("ok"):
            return frozen
    if len(reviews) != 2:
        return {"ok": False, "error": "script_candidates_not_ready"}
    config = get_model_for_tool(P0_CRITIC_TOOL)
    system_prompt = prompts.render("p0_video_critic.system")
    outcome: list[dict[str, Any]] = []
    for review in reviews:
        candidate = _candidate_from_review(review)
        deterministic = deterministic_script_gate(
            candidate,
            spec=_content(context["spec"]["spec"]),
            truth_snapshot=_content(context["truth"]["snapshot"]),
            content_spec_hash=context["spec"]["spec_hash"],
            truth_snapshot_hash=context["truth"]["snapshot_hash"],
        )
        if deterministic["status"] != "passed":
            critic = {
                "status": "skipped",
                "reason_codes": ["deterministic_gate_failed"],
                "formal_content_gate": _unavailable_formal_content_gate(
                    reason="deterministic_gate_failed"
                ),
            }
            reviewed_status = "failed"
        else:
            user_prompt = prompts.render(
                "p0_video_critic.user",
                truth_snapshot_json=canonical_json(_content(context["truth"]["snapshot"])),
                content_spec_json=canonical_json(_content(context["spec"]["spec"])),
                candidate_json=canonical_json(candidate),
            )
            reviewer_run_id = str(uuid.uuid4())
            try:
                response = await AIHubClient(timeout=120.0).chat(
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                    provider=str(config["provider"]),
                    model=str(config["model"]),
                    temperature=float(config.get("temperature", 0.1)),
                    max_tokens=int(config.get("max_tokens", 2500)),
                )
                parsed = _extract_json_object(response)
                decision = str((parsed or {}).get("decision") or "").strip().lower()
                reasons = (parsed or {}).get("reason_codes")
                evidence = (parsed or {}).get("evidence")
                metrics = (parsed or {}).get("metrics")
                if (
                    decision not in {"passed", "failed"}
                    or not isinstance(reasons, list)
                    or not isinstance(evidence, list)
                    or not isinstance(metrics, Mapping)
                ):
                    raise ValueError("critic_json_schema_invalid")
                triangle_inputs = _p0_triangle_inputs(
                    truth_snapshot=_content(context["truth"]["snapshot"]),
                    spec=_content(context["spec"]["spec"]),
                    candidate=candidate,
                )
                triangle = await audit_content_triangle(
                    product_text=str(triangle_inputs["product_text"]),
                    audience_text=str(triangle_inputs["audience_text"]),
                    content_tracks=_mapping(triangle_inputs["content_tracks"]),
                )
                if triangle.get("ok") is not True:
                    formal_gate = _unavailable_formal_content_gate(
                        reason="content_triangle_unavailable"
                    )
                    formal_gate["triangle_error"] = triangle.get("error")
                else:
                    formal_gate = evaluate_planting_content_gate(metrics, triangle)
                critic = {
                    "status": decision,
                    "reason_codes": [str(item) for item in reasons],
                    "evidence": [str(item) for item in evidence],
                    "metrics": dict(metrics),
                    "triangle": triangle,
                    "formal_content_gate": formal_gate,
                    "reviewer_run_id": reviewer_run_id,
                    "provider": response.get("provider") or config["provider"],
                    "model": response.get("model") or config["model"],
                    "response_hash": content_hash(parsed),
                }
                if decision == "passed" and formal_gate.get("pass") is True:
                    reviewed_status = "passed"
                elif decision == "failed":
                    reviewed_status = "failed"
                elif formal_gate.get("status") == "unavailable":
                    reviewed_status = "pending_review"
                else:
                    reviewed_status = "failed"
                if (
                    decision == "passed"
                    and formal_gate.get("pass") is not True
                    and "planting_content_gate_failed" not in critic["reason_codes"]
                ):
                    critic["reason_codes"].append("planting_content_gate_failed")
            except Exception as exc:
                critic = {
                    "status": "unavailable",
                    "reason_codes": ["independent_critic_unavailable"],
                    "detail": str(exc)[:300],
                    "reviewer_run_id": reviewer_run_id,
                    "formal_content_gate": _unavailable_formal_content_gate(
                        reason="independent_critic_unavailable"
                    ),
                }
                reviewed_status = "pending_review"
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE pipeline.production_script_reviews
                SET deterministic_gate=$2::jsonb, critic_gate=$3::jsonb, status=$4
                WHERE id=$1::uuid
                """,
                review["review_id"],
                _json(deterministic),
                _json(critic),
                reviewed_status,
            )
        outcome.append({"script_id": review["script_id"], "candidate_slot": review["candidate_slot"], "status": reviewed_status, "critic": critic})
    vector_pre_match = await assess_candidate_execution_vector_match(
        production_order_id=production_order_id,
    )
    return {
        "ok": all(item["status"] in {"passed", "failed"} for item in outcome),
        "error": None if all(item["status"] in {"passed", "failed"} for item in outcome) else "independent_critic_pending",
        "reviews": outcome,
        "vector_pre_match": vector_pre_match,
    }


async def assess_candidate_execution_vector_match(*, production_order_id: str) -> dict[str, Any]:
    """Score every review-passed candidate from its real executable prompt preview.

    The embedding call is deliberately outside a database transaction.  A
    provider outage becomes an honest ``unscored`` record rather than a fake
    zero or a blocked human script review.
    """

    pool = get_pool()
    async with pool.acquire() as conn:
        context = await _load_context(conn, production_order_id)
        missing = _require_context(context)
        if missing:
            return missing
        assert context is not None
        if context["order"]["status"] not in {"awaiting_script_selection", "prompt_ready", "awaiting_generation_approval"}:
            return {
                "ok": False,
                "error": "production_order_wrong_state",
                "status": context["order"]["status"],
            }
        reviews = await _scripts_for_order(conn, production_order_id)

    frozen_v3: dict[str, Any] | None = None
    if _is_p0_strong_lineage_order(_mapping(context.get("order"))):
        frozen_v3 = _frozen_strong_lineage_planting_context(context, require_spec=True)
        if not frozen_v3.get("ok"):
            return frozen_v3

    prepared: list[dict[str, Any]] = []
    for review in reviews:
        if review["review_status"] != "passed":
            continue
        candidate = _candidate_from_review(review)
        preview = candidate_prompt_preview(
            candidate=candidate,
            spec=_content(context["spec"]["spec"]),
            truth_snapshot=_content(context["truth"]["snapshot"]),
        )
        if not preview.get("ok"):
            return {
                "ok": False,
                "error": str(preview.get("error") or "candidate_prompt_preview_invalid"),
                "script_id": review["script_id"],
                "detail": preview.get("detail"),
            }
        assessed = await assess_execution_vector_match(
            execution=preview,
            truth_snapshot=_content(context["truth"]["snapshot"]),
            require_frozen_portrait=frozen_v3 is not None,
            pain_solution_bridge=(
                _mapping(frozen_v3.get("pain_solution_bridge"))
                if frozen_v3 is not None
                else None
            ),
            duration_seconds=_content(context["spec"]["spec"]).get("duration_seconds"),
        )
        report = _mapping(assessed.get("report"))
        if not assessed.get("ok") or not report:
            return {
                "ok": False,
                "error": str(assessed.get("error") or "execution_vector_match_failed"),
                "script_id": review["script_id"],
            }
        prepared.append(
            {
                "script_id": review["script_id"],
                "candidate_slot": int(review["candidate_slot"]),
                "report": report,
            }
        )

    persisted: list[dict[str, Any]] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await _load_context(conn, production_order_id, lock=True)
            missing = _require_context(current)
            if missing:
                return missing
            assert current is not None
            for item in prepared:
                saved = await _persist_execution_vector_match(
                    conn,
                    production_order_id=production_order_id,
                    content_spec_id=current["spec"]["id"],
                    script_id=item["script_id"],
                    prompt_source_id=None,
                    stage="candidate",
                    candidate_slot=item["candidate_slot"],
                    report=item["report"],
                )
                persisted.append(
                    {
                        "script_id": item["script_id"],
                        "candidate_slot": item["candidate_slot"],
                        "vector_match_report_id": saved["id"],
                        "reused": saved["reused"],
                        "status": saved["report"].get("status"),
                        "overall_score": saved["report"].get("overall_score"),
                        "report": saved["report"],
                    }
                )

    scored = [item for item in persisted if isinstance(item.get("overall_score"), (int, float))]
    ranking = [
        item["script_id"]
        for item in sorted(scored, key=lambda item: float(item["overall_score"]), reverse=True)
    ]
    return {
        "ok": True,
        "reports": persisted,
        "ranking": ranking,
        "disclaimer": "投前向量分仅供排序和人工诊断；系统不会自动选择脚本或判定 winner。",
    }


async def assess_frozen_execution_vector_match(*, production_order_id: str) -> dict[str, Any]:
    """Score the selected script's immutable PromptSource before paid approval."""

    pool = get_pool()
    async with pool.acquire() as conn:
        context = await _load_context(conn, production_order_id)
        missing = _require_context(context)
        if missing:
            return missing
        assert context is not None
        frozen_v3: dict[str, Any] | None = None
        if _is_p0_strong_lineage_order(_mapping(context.get("order"))):
            frozen_v3 = _frozen_strong_lineage_planting_context(context, require_spec=True)
            if not frozen_v3.get("ok"):
                return frozen_v3
        if context["order"]["status"] not in {"prompt_ready", "awaiting_generation_approval"}:
            return {
                "ok": False,
                "error": "production_order_wrong_state",
                "status": context["order"]["status"],
            }
        source = await conn.fetchrow(
            """
            SELECT id::text AS id,script_id::text AS script_id,prompt_source
            FROM pipeline.production_prompt_sources
            WHERE production_order_id=$1::uuid
            ORDER BY created_at DESC LIMIT 1
            """,
            production_order_id,
        )
        selected = await conn.fetchrow(
            """
            SELECT candidate_slot
            FROM pipeline.production_script_reviews
            WHERE production_order_id=$1::uuid AND selected=true
            """,
            production_order_id,
        )
    if not source or not selected:
        return {"ok": False, "error": "execution_vector_match_inputs_missing"}
    execution = frozen_prompt_execution_source(_content(source["prompt_source"]))
    if not execution.get("ok"):
        return {"ok": False, "error": str(execution.get("error") or "frozen_prompt_source_invalid")}
    assessed = await assess_execution_vector_match(
        execution=execution,
        truth_snapshot=_content(context["truth"]["snapshot"]),
        require_frozen_portrait=frozen_v3 is not None,
        pain_solution_bridge=(
            _mapping(frozen_v3.get("pain_solution_bridge"))
            if frozen_v3 is not None
            else None
        ),
        duration_seconds=_content(context["spec"]["spec"]).get("duration_seconds"),
    )
    report = _mapping(assessed.get("report"))
    if not assessed.get("ok") or not report:
        return {"ok": False, "error": str(assessed.get("error") or "execution_vector_match_failed")}

    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await _load_context(conn, production_order_id, lock=True)
            missing = _require_context(current)
            if missing:
                return missing
            assert current is not None
            saved = await _persist_execution_vector_match(
                conn,
                production_order_id=production_order_id,
                content_spec_id=current["spec"]["id"],
                script_id=source["script_id"],
                prompt_source_id=source["id"],
                stage="planned",
                candidate_slot=None,
                report=report,
            )
    return {
        "ok": True,
        "vector_match_report_id": saved["id"],
        "reused": saved["reused"],
        "status": saved["report"].get("status"),
        "report": saved["report"],
    }


async def select_script(*, production_order_id: str, script_id: str) -> dict[str, Any]:
    """Apply the explicit script-selection gate before executable prompt creation."""

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            context = await _load_context(conn, production_order_id, lock=True)
            missing = _require_context(context)
            if missing:
                return missing
            assert context is not None
            order = context["order"]
            frozen_v3: dict[str, Any] | None = None
            if _is_p0_strong_lineage_order(order):
                frozen_v3 = _frozen_strong_lineage_planting_context(context, require_spec=True)
                if not frozen_v3.get("ok"):
                    return frozen_v3
            if order["status"] not in {"awaiting_script_selection", "prompt_ready", "awaiting_generation_approval"}:
                return {"ok": False, "error": "production_order_wrong_state", "status": order["status"]}
            rows = await _scripts_for_order(conn, production_order_id, lock=True)
            selected = next((row for row in rows if row["selected"]), None)
            if selected:
                if selected["script_id"] == script_id:
                    return {"ok": True, "reused": True, "script_id": script_id}
                return {"ok": False, "error": "script_selection_immutable", "selected_script_id": selected["script_id"]}
            target = next((row for row in rows if row["script_id"] == script_id), None)
            if not target:
                return {"ok": False, "error": "script_not_in_production_order"}
            if target["review_status"] != "passed":
                return {"ok": False, "error": "script_review_not_passed", "status": target["review_status"]}
            vector_pre_match = await conn.fetchrow(
                """
                SELECT id::text AS id,report_status,audience_source_kind,report
                FROM pipeline.production_vector_match_reports
                WHERE production_order_id=$1::uuid AND script_id=$2::uuid AND stage='candidate'
                ORDER BY created_at DESC LIMIT 1
                """,
                production_order_id,
                script_id,
            )
            if not vector_pre_match:
                return {"ok": False, "error": "execution_vector_pre_match_required"}
            if frozen_v3 is not None and (
                vector_pre_match["report_status"] != "scored"
                or vector_pre_match["audience_source_kind"] != "portrait"
            ):
                return {
                    "ok": False,
                    "error": "execution_vector_pre_match_v4_required",
                    "first_blocker": "execution_vector_pre_match_v4_required",
                    "vector_pre_match_status": vector_pre_match["report_status"],
                    "audience_source_kind": vector_pre_match["audience_source_kind"],
                }
            await conn.execute(
                "UPDATE pipeline.production_script_reviews SET selected=true WHERE id=$1::uuid",
                target["review_id"],
            )
            await conn.execute("UPDATE pipeline.scripts SET status='adopted' WHERE id=$1::uuid", script_id)
            return {
                "ok": True,
                "reused": False,
                "script_id": script_id,
                "vector_pre_match_report_id": vector_pre_match["id"],
                "vector_pre_match_status": vector_pre_match["report_status"],
            }


async def _reference_manifest_from_truth(context: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = _content(context["truth"]["snapshot"])
    references = snapshot.get("product_reference_manifest")
    assets = references.get("assets") if isinstance(references, Mapping) else []
    if not isinstance(assets, list) or not assets:
        raise ReferenceManifestError("product_ref_invalid_or_mismatch", "frozen product references missing")
    items: list[dict[str, str]] = []
    for asset in assets:
        if not isinstance(asset, Mapping):
            raise ReferenceManifestError("product_ref_invalid_or_mismatch", "frozen product reference invalid")
        asset_id = str(asset.get("id") or "").strip()
        file_url = str(asset.get("file_url") or "").strip()
        if not asset_id or not file_url:
            raise ReferenceManifestError("product_ref_invalid_or_mismatch", "frozen product reference incomplete")
        path = resolve_reference_path(file_url)
        items.append({"id": asset_id, "type": "product", "sha256": sha256_reference(path), "file_url": file_url})
    return {"sku_id": context["order"]["sku_id"], "items": items}


async def prepare_prompt_source(*, production_order_id: str) -> dict[str, Any]:
    """Compile and freeze the executable Seedance prompt after selection."""

    config = get_model_for_tool(P0_GENERATION_TOOL)
    provider = str(config.get("provider") or "")
    model = str(config.get("model") or "")
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            context = await _load_context(conn, production_order_id, lock=True)
            missing = _require_context(context)
            if missing:
                return missing
            assert context is not None
            order = context["order"]
            if _is_p0_strong_lineage_order(order):
                frozen = _frozen_strong_lineage_planting_context(context, require_spec=True)
                if not frozen.get("ok"):
                    return frozen
            if order["status"] not in {"awaiting_script_selection", "prompt_ready", "awaiting_generation_approval"}:
                return {"ok": False, "error": "production_order_wrong_state", "status": order["status"]}
            selected_rows = [row for row in await _scripts_for_order(conn, production_order_id, lock=True) if row["selected"]]
            if len(selected_rows) != 1:
                return {"ok": False, "error": "script_selection_required"}
            selected = selected_rows[0]
            candidate = _candidate_from_review(selected)
            source = build_p0_prompt_source(
                candidate=candidate,
                spec=_content(context["spec"]["spec"]),
                truth_snapshot=_content(context["truth"]["snapshot"]),
            )
            compiled = compile_final_prompt_segment(
                source,
                duration_seconds=int(float(candidate["duration_seconds"])),
                intent="planting",
            )
            if not compiled.get("ok"):
                return {"ok": False, "error": "prompt_compile_failed", "detail": compiled}
            try:
                reference_manifest = await _reference_manifest_from_truth(context)
            except (OSError, ReferenceManifestError) as exc:
                return {"ok": False, "error": "product_ref_invalid_or_mismatch", "detail": str(exc)}
            envelope = {
                "version": P0_CONTRACT_VERSION,
                "prompt_source": source,
                "compiled": compiled,
                "candidate_hash": content_hash(candidate),
                "content_spec_hash": context["spec"]["spec_hash"],
                "truth_snapshot_hash": context["truth"]["snapshot_hash"],
            }
            source_hash = content_hash(envelope)
            existing = await conn.fetchrow(
                """
                SELECT id::text AS id,prompt_source_hash FROM pipeline.production_prompt_sources
                WHERE production_order_id=$1::uuid AND script_id=$2::uuid FOR UPDATE
                """,
                production_order_id,
                selected["script_id"],
            )
            if existing:
                if existing["prompt_source_hash"] != source_hash:
                    return {"ok": False, "error": "prompt_source_immutable"}
                prompt_source_id = existing["id"]
                reused = True
            else:
                inserted = await conn.fetchrow(
                    """
                    INSERT INTO pipeline.production_prompt_sources(
                        production_order_id,content_spec_id,script_id,prompt_source,prompt_source_hash,
                        requested_provider,requested_model,adapter_version,reference_manifest
                    ) VALUES($1::uuid,$2::uuid,$3::uuid,$4::jsonb,$5,$6,$7,$8,$9::jsonb)
                    RETURNING id::text AS id
                    """,
                    production_order_id,
                    context["spec"]["id"],
                    selected["script_id"],
                    _json(envelope),
                    source_hash,
                    provider,
                    model,
                    P0_PROMPT_ADAPTER_VERSION,
                    _json(reference_manifest),
                )
                prompt_source_id = inserted["id"]
                reused = False
            transition = await _transition_locked(conn, order, "prompt_ready")
            if transition:
                return transition
            return {
                "ok": True,
                "reused": reused,
                "prompt_source_id": prompt_source_id,
                "prompt_source_hash": source_hash,
                "requested_provider": provider,
                "requested_model": model,
                "final_prompt": compiled["final_prompt"],
                "reference_manifest": reference_manifest,
            }


async def assess_execution_content_match(*, production_order_id: str) -> dict[str, Any]:
    """Expose the frozen execution inputs against the adopted audience.

    This is intentionally a visible proxy, not a hidden approval score.  The
    paid-generation approval cannot be requested until this evidence exists.
    """

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            context = await _load_context(conn, production_order_id, lock=True)
            missing = _require_context(context)
            if missing:
                return missing
            assert context is not None
            order = context["order"]
            frozen_v3: dict[str, Any] | None = None
            if _is_p0_strong_lineage_order(order):
                frozen_v3 = _frozen_strong_lineage_planting_context(context, require_spec=True)
                if not frozen_v3.get("ok"):
                    return frozen_v3
            if order["status"] not in {"prompt_ready", "awaiting_generation_approval"}:
                return {"ok": False, "error": "production_order_wrong_state", "status": order["status"]}
            source = await conn.fetchrow(
                """
                SELECT id::text AS id,prompt_source,reference_manifest
                FROM pipeline.production_prompt_sources
                WHERE production_order_id=$1::uuid
                ORDER BY created_at DESC LIMIT 1 FOR UPDATE
                """,
                production_order_id,
            )
            selected = await conn.fetchrow(
                """
                SELECT review.script_id::text AS script_id,script.content_contract
                FROM pipeline.production_script_reviews review
                JOIN pipeline.scripts script ON script.id=review.script_id
                WHERE review.production_order_id=$1::uuid AND review.selected=true
                """,
                production_order_id,
            )
            if not source or not selected:
                return {"ok": False, "error": "execution_content_match_inputs_missing"}
            candidate = _candidate_from_review(dict(selected))
            if not candidate:
                return {"ok": False, "error": "selected_script_contract_missing"}
            match = await _persist_execution_content_match(
                conn,
                production_order_id=production_order_id,
                context=context,
                source=dict(source),
                candidate=candidate,
                stage="planned",
                audio_plan={
                    "mode": "planned_native_audio",
                    "native_audio_requested": True,
                    "bgm": {"mode": "not_supplied"},
                },
            )
            return {
                "ok": True,
                "reused": match["reused"],
                "content_match_report_id": match["id"],
                "report": match["report"],
            }


async def request_generation_approval(*, production_order_id: str) -> dict[str, Any]:
    """Expose the exact paid payload, then wait for the human-gated tool call."""

    # This deliberately runs before the transaction: embedding may retry or
    # fail, and an unavailable provider must become a persisted ``unscored``
    # pre-match rather than hold a row lock or fabricate a number.
    vector_match = await assess_frozen_execution_vector_match(
        production_order_id=production_order_id,
    )
    if not vector_match.get("ok"):
        return vector_match

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            context = await _load_context(conn, production_order_id, lock=True)
            missing = _require_context(context)
            if missing:
                return missing
            assert context is not None
            order = context["order"]
            frozen_v3: dict[str, Any] | None = None
            if _is_p0_strong_lineage_order(order):
                frozen_v3 = _frozen_strong_lineage_planting_context(context, require_spec=True)
                if not frozen_v3.get("ok"):
                    return frozen_v3
            if order["status"] not in {"prompt_ready", "awaiting_generation_approval"}:
                return {"ok": False, "error": "production_order_wrong_state", "status": order["status"]}
            source = await conn.fetchrow(
                """
                SELECT id::text AS id,prompt_source,prompt_source_hash,reference_manifest,
                       requested_provider,requested_model
                FROM pipeline.production_prompt_sources
                WHERE production_order_id=$1::uuid
                ORDER BY created_at DESC LIMIT 1 FOR UPDATE
                """,
                production_order_id,
            )
            if not source:
                return {"ok": False, "error": "prompt_source_not_found"}
            planned_vector_match = await conn.fetchrow(
                """
                SELECT id::text AS id,report_status,audience_source_kind,report
                FROM pipeline.production_vector_match_reports
                WHERE production_order_id=$1::uuid AND prompt_source_id=$2::uuid
                  AND stage='planned'
                ORDER BY created_at DESC LIMIT 1
                """,
                production_order_id,
                source["id"],
            )
            if not planned_vector_match:
                return {"ok": False, "error": "execution_vector_match_required"}
            if frozen_v3 is not None:
                planned_report = _content(planned_vector_match["report"])
                formal_gate = _content(planned_report.get("formal_pre_video_vector_gate"))
                if (
                    planned_vector_match["report_status"] != "scored"
                    or planned_vector_match["audience_source_kind"] != "portrait"
                ):
                    return {
                        "ok": False,
                        "error": "execution_vector_match_v4_required",
                        "first_blocker": "execution_vector_match_v4_required",
                        "vector_match_status": planned_vector_match["report_status"],
                        "audience_source_kind": planned_vector_match["audience_source_kind"],
                    }
                if formal_gate.get("pass") is not True:
                    return {
                        "ok": False,
                        "error": "formal_pre_video_vector_gate_failed",
                        "first_blocker": "formal_pre_video_vector_gate_failed",
                        "formal_pre_video_vector_gate": formal_gate,
                    }
            envelope = _content(source["prompt_source"])
            compiled = _content(envelope.get("compiled"))
            approval = build_generation_approval_payload(
                production_order_id=production_order_id,
                prompt_source_hash=source["prompt_source_hash"],
                prompt_source=_content(envelope.get("prompt_source")),
                reference_manifest=_content(source["reference_manifest"]),
                requested_provider=source["requested_provider"],
                requested_model=source["requested_model"],
                duration_seconds=_content(context["spec"]["spec"]).get("duration_seconds"),
                final_prompt=str(compiled.get("final_prompt") or ""),
            )
            if not approval["ok"]:
                return approval
            transition = await _transition_locked(conn, order, "awaiting_generation_approval")
            if transition:
                return transition
            return {
                "ok": True,
                "prompt_source_id": source["id"],
                "planned_vector_match_report_id": planned_vector_match["id"],
                "planned_vector_match_status": planned_vector_match["report_status"],
                "vector_match": vector_match,
                **approval,
            }


async def _generation_input_snapshot(conn, production_order_id: str, *, lock: bool = False) -> dict[str, Any] | None:
    context = await _load_context(conn, production_order_id, lock=lock)
    if not context or _require_context(context):
        return None
    suffix = " FOR UPDATE" if lock else ""
    source = await conn.fetchrow(
        f"""
        SELECT id::text AS id,script_id::text,prompt_source,prompt_source_hash,
               reference_manifest,requested_provider,requested_model,adapter_version
        FROM pipeline.production_prompt_sources
        WHERE production_order_id=$1::uuid
        ORDER BY created_at DESC LIMIT 1{suffix}
        """,
        production_order_id,
    )
    if not source:
        return None
    selected = await conn.fetchrow(
        """
        SELECT review.script_id::text AS script_id,script.content_contract
        FROM pipeline.production_script_reviews review
        JOIN pipeline.scripts script ON script.id=review.script_id
        WHERE review.production_order_id=$1::uuid AND review.selected=true
        """,
        production_order_id,
    )
    if not selected or selected["script_id"] != source["script_id"]:
        return None
    return {"context": context, "source": dict(source), "selected": dict(selected)}


def _approval_for_inputs(inputs: Mapping[str, Any]) -> dict[str, Any]:
    context = inputs["context"]
    source = inputs["source"]
    envelope = _content(source["prompt_source"])
    compiled = _content(envelope.get("compiled"))
    return build_generation_approval_payload(
        production_order_id=context["order"]["id"],
        prompt_source_hash=source["prompt_source_hash"],
        prompt_source=_content(envelope.get("prompt_source")),
        reference_manifest=_content(source["reference_manifest"]),
        requested_provider=source["requested_provider"],
        requested_model=source["requested_model"],
        duration_seconds=_content(context["spec"]["spec"]).get("duration_seconds"),
        final_prompt=str(compiled.get("final_prompt") or ""),
    )


async def _mark_attempt_failed(
    *,
    production_order_id: str,
    attempt_id: str,
    category: str,
    detail: str,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            context = await _load_context(conn, production_order_id, lock=True)
            if not context:
                return
            await conn.execute(
                """
                UPDATE pipeline.production_generation_attempts
                SET status='failed',error_category=$2,completed_at=NOW()
                WHERE id=$1::uuid AND status IN ('created','running','recoverable')
                """,
                attempt_id,
                f"{category}:{detail[:500]}",
            )
            if context["order"]["status"] == "generating":
                await _transition_locked(conn, context["order"], "awaiting_generation_approval")


async def start_generation_attempt(*, production_order_id: str, approval_hash: str) -> dict[str, Any]:
    """Start exactly one Seedance request after the Human Gate has approved it.

    This function deliberately only starts the provider task.  Polling/recovery
    is separate, so a long remote render never holds a database transaction or
    accidentally creates another paid request after a client reconnect.
    """

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            inputs = await _generation_input_snapshot(conn, production_order_id, lock=True)
            if not inputs:
                return {"ok": False, "error": "generation_inputs_not_ready"}
            context = inputs["context"]
            order = context["order"]
            if order["status"] != "awaiting_generation_approval":
                return {"ok": False, "error": "production_order_wrong_state", "status": order["status"]}
            approval = _approval_for_inputs(inputs)
            if not approval.get("ok") or approval.get("approval_hash") != approval_hash:
                return {"ok": False, "error": "generation_approval_hash_mismatch"}
            active = await conn.fetchrow(
                """
                SELECT id::text AS id,status,remote_task_id
                FROM pipeline.production_generation_attempts
                WHERE production_order_id=$1::uuid AND approval_hash=$2
                  AND status IN ('created','running','recoverable')
                FOR UPDATE
                """,
                production_order_id,
                approval_hash,
            )
            if active:
                return {
                    "ok": True,
                    "reused": True,
                    "attempt_id": active["id"],
                    "status": active["status"],
                    "remote_task_id": active["remote_task_id"],
                }
            next_no = await conn.fetchval(
                "SELECT COALESCE(MAX(attempt_no),0)+1 FROM pipeline.production_generation_attempts WHERE production_order_id=$1::uuid",
                production_order_id,
            )
            attempt = await conn.fetchrow(
                """
                INSERT INTO pipeline.production_generation_attempts(
                    production_order_id,prompt_source_id,attempt_no,approval_hash,
                    requested_provider,requested_model,status
                ) VALUES($1::uuid,$2::uuid,$3,$4,$5,$6,'created')
                RETURNING id::text AS id,attempt_no
                """,
                production_order_id,
                inputs["source"]["id"],
                next_no,
                approval_hash,
                inputs["source"]["requested_provider"],
                inputs["source"]["requested_model"],
            )
            transition = await _transition_locked(conn, order, "generating")
            if transition:
                return transition
            attempt_id = attempt["id"]

    try:
        snapshot = _content(inputs["context"]["truth"]["snapshot"])
        refs = snapshot.get("product_reference_manifest", {}).get("assets", [])
        if not isinstance(refs, list):
            raise ReferenceManifestError("product_ref_invalid_or_mismatch", "frozen product references invalid")
        prepared_refs, sent_manifest = prepare_video_reference_images(None, refs)
        assert_reference_manifest_matches(_content(inputs["source"]["reference_manifest"]), sent_manifest)
        envelope = _content(inputs["source"]["prompt_source"])
        compiled = _content(envelope.get("compiled"))
        duration = int(float(_content(inputs["context"]["spec"]["spec"])["duration_seconds"]))
        response = await AIHubClient(timeout=120.0).generate_video_v2(
            str(compiled["final_prompt"]),
            duration_sec=duration,
            prepared_reference_images=prepared_refs,
            aspect="9:16",
            provider=inputs["source"]["requested_provider"],
            model=inputs["source"]["requested_model"],
            extra={"generate_audio": True, "watermark": False},
        )
        started = _mapping(response.get("data") if isinstance(response, Mapping) else {}) or _mapping(response)
        actual_provider = str(started.get("provider") or "").strip()
        actual_model = str(started.get("model") or "").strip()
        remote_task_id = str(started.get("task_id") or "").strip()
        if (
            actual_provider != inputs["source"]["requested_provider"]
            or actual_model != inputs["source"]["requested_model"]
            or not remote_task_id
        ):
            raise RuntimeError("provider_or_model_route_unverified")
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE pipeline.production_generation_attempts
                SET status='running',actual_provider=$2,actual_model=$3,remote_task_id=$4
                WHERE id=$1::uuid AND status='created'
                """,
                attempt_id,
                actual_provider,
                actual_model,
                remote_task_id,
            )
        return {
            "ok": True,
            "reused": False,
            "attempt_id": attempt_id,
            "attempt_no": attempt["attempt_no"],
            "status": "running",
            "remote_task_id": remote_task_id,
            "actual_provider": actual_provider,
            "actual_model": actual_model,
            "next_step": "p0_recover_video_generation",
        }
    except HubError as exc:
        await _mark_attempt_failed(
            production_order_id=production_order_id,
            attempt_id=attempt_id,
            category=exc.classify(),
            detail=exc.detail,
        )
        return {"ok": False, "error": "seedance_generation_failed", "category": exc.classify()}
    except Exception as exc:
        await _mark_attempt_failed(
            production_order_id=production_order_id,
            attempt_id=attempt_id,
            category="generation_start_failed",
            detail=str(exc),
        )
        return {"ok": False, "error": "seedance_generation_failed", "detail": str(exc)[:300]}


async def recover_generation_attempt(
    *, production_order_id: str, attempt_id: str, max_wait_seconds: int = 0
) -> dict[str, Any]:
    """Poll a previously created remote task and persist a successful raw asset."""

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT attempt.id::text AS id,attempt.status,attempt.remote_task_id,
                   attempt.requested_provider,attempt.requested_model,attempt.actual_provider,
                   attempt.actual_model,attempt.prompt_source_id::text,
                   source.script_id::text,order_row.sku_id,order_row.audience_record_id::text,
                   order_row.status AS order_status
            FROM pipeline.production_generation_attempts attempt
            JOIN pipeline.production_prompt_sources source ON source.id=attempt.prompt_source_id
            JOIN pipeline.production_orders order_row ON order_row.id=attempt.production_order_id
            WHERE attempt.id=$1::uuid AND attempt.production_order_id=$2::uuid
            """,
            attempt_id,
            production_order_id,
        )
    if not row:
        return {"ok": False, "error": "generation_attempt_not_found"}
    attempt = dict(row)
    if attempt["status"] == "succeeded":
        return {"ok": True, "reused": True, "attempt_id": attempt_id, "status": "succeeded"}
    if attempt["status"] not in {"running", "recoverable"} or not attempt["remote_task_id"]:
        return {"ok": False, "error": "generation_attempt_not_recoverable", "status": attempt["status"]}
    try:
        waited = await AIHubClient(timeout=120.0).wait_for_video(
            attempt["remote_task_id"],
            max_seconds=max(0, int(max_wait_seconds)),
            poll=5.0,
        )
    except Exception as exc:
        return {"ok": False, "error": "generation_status_unavailable", "detail": str(exc)[:300]}
    data = _mapping(waited.get("data") if isinstance(waited, Mapping) else {}) or _mapping(waited)
    status = str(data.get("status") or "").lower()
    if status in {"processing", "running", "queued", "pending", "timeout", ""}:
        return {"ok": True, "attempt_id": attempt_id, "status": "running", "remote_task_id": attempt["remote_task_id"]}
    if status in {"failed", "error"}:
        await _mark_attempt_failed(
            production_order_id=production_order_id,
            attempt_id=attempt_id,
            category="provider_task_failed",
            detail=str(data.get("error") or status),
        )
        return {"ok": False, "error": "seedance_generation_failed", "detail": str(data.get("error") or status)[:300]}
    if status not in {"succeeded", "completed"}:
        return {"ok": False, "error": "generation_status_invalid", "status": status}
    video_url = str(data.get("video_url") or "").strip()
    if not video_url:
        await _mark_attempt_failed(
            production_order_id=production_order_id,
            attempt_id=attempt_id,
            category="provider_output_missing",
            detail="video_url missing",
        )
        return {"ok": False, "error": "generation_output_missing"}
    try:
        asset_id = await save_storyboard_asset(
            sku_id=attempt["sku_id"],
            asset_type="video",
            script_id=attempt["script_id"],
            audience_record_id=attempt["audience_record_id"],
            file_url=video_url,
            prompt="P0 raw Seedance render; immutable prompt source recorded in production_prompt_sources",
            duration_seconds=float(data.get("duration") or 0) or None,
            external_video_id=attempt["remote_task_id"],
            notes=f"p0/raw; production_order={production_order_id}; attempt={attempt_id}",
            persist_to_disk=True,
        )
    except Exception as exc:
        asset_id = None
        logger.exception("P0 raw asset persistence failed: %s", exc)
    if not asset_id:
        await _mark_attempt_failed(
            production_order_id=production_order_id,
            attempt_id=attempt_id,
            category="asset_persist_failed",
            detail="raw asset could not be recorded",
        )
        return {"ok": False, "error": "raw_asset_persist_failed"}
    async with pool.acquire() as conn:
        async with conn.transaction():
            context = await _load_context(conn, production_order_id, lock=True)
            if not context:
                return {"ok": False, "error": "production_order_not_found"}
            if context["order"]["status"] != "generating":
                return {"ok": False, "error": "production_order_wrong_state", "status": context["order"]["status"]}
            await conn.execute(
                """
                UPDATE pipeline.production_generation_attempts
                SET status='succeeded',raw_asset_id=$2::uuid,
                    duration_ms=$3,completed_at=NOW()
                WHERE id=$1::uuid AND status IN ('running','recoverable')
                """,
                attempt_id,
                asset_id,
                int(float(data.get("duration") or 0) * 1000) or None,
            )
            transition = await _transition_locked(conn, context["order"], "raw_qa")
            if transition:
                return transition
    return {"ok": True, "attempt_id": attempt_id, "status": "raw_qa", "raw_asset_id": asset_id}


def _run_process(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, text=True, capture_output=True, encoding="utf-8", errors="replace")


def _ffprobe(path: Path) -> dict[str, Any]:
    completed = _run_process(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffprobe_failed")
    parsed = json.loads(completed.stdout)
    if not isinstance(parsed, Mapping):
        raise RuntimeError("ffprobe_output_invalid")
    return dict(parsed)


def _black_freeze_scan(path: Path) -> dict[str, Any]:
    completed = _run_process(
        [
            "ffmpeg", "-hide_banner", "-v", "info", "-i", str(path), "-an",
            "-vf", "blackdetect=d=0.8:pix_th=0.10,freezedetect=n=0.003:d=2.0",
            "-f", "null", "-",
        ]
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip()[-500:] or "ffmpeg_scan_failed")
    output = completed.stderr
    return {
        "black_detected": "black_start:" in output,
        "freeze_detected": "freeze_start:" in output,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _insert_qa_report(
    *, production_order_id: str, stage: str, asset_id: str, report: Mapping[str, Any], passed: bool | None
) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO pipeline.production_qa_reports(production_order_id,stage,asset_id,report,passed)
        VALUES($1::uuid,$2,$3::uuid,$4::jsonb,$5)
        """,
        production_order_id,
        stage,
        asset_id,
        _json(dict(report)),
        passed,
    )


async def run_raw_qa(*, production_order_id: str, attempt_id: str) -> dict[str, Any]:
    """Fail closed on raw media technical or independent semantic QA."""

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT attempt.id::text AS attempt_id,attempt.raw_asset_id::text,
                   asset.file_url,source.prompt_source,truth.snapshot,spec.spec AS content_spec
            FROM pipeline.production_generation_attempts attempt
            JOIN pipeline.assets asset ON asset.id=attempt.raw_asset_id
            JOIN pipeline.production_prompt_sources source ON source.id=attempt.prompt_source_id
            JOIN pipeline.order_truth_snapshots truth ON truth.production_order_id=attempt.production_order_id
            JOIN pipeline.production_content_specs spec ON spec.id=source.content_spec_id
            WHERE attempt.id=$1::uuid AND attempt.production_order_id=$2::uuid
            """,
            attempt_id,
            production_order_id,
        )
    if not row:
        return {"ok": False, "error": "raw_asset_not_found"}
    data = dict(row)
    try:
        path = resolve_reference_path(str(data["file_url"] or ""))
    except FileNotFoundError:
        report = {"stage": "raw", "status": "failed", "reason_codes": ["raw_asset_not_persisted"]}
        await _insert_qa_report(production_order_id=production_order_id, stage="raw", asset_id=data["raw_asset_id"], report=report, passed=False)
        await _move_after_raw_qa(production_order_id, passed=False)
        return {"ok": False, "error": "raw_asset_not_persisted", "report": report}
    try:
        probe = _ffprobe(path)
        technical = validate_media_probe(
            probe,
            require_audio=False,
            expected_duration_seconds=_content(data["content_spec"]).get("duration_seconds"),
        )
        scan = _black_freeze_scan(path)
        technical["file_sha256"] = _sha256_file(path)
        if scan["black_detected"]:
            technical.setdefault("failed_checks", []).append("black_frame_detected")
        if scan["freeze_detected"]:
            technical.setdefault("failed_checks", []).append("freeze_detected")
        technical["ok"] = not technical.get("failed_checks")
    except FileNotFoundError as exc:
        report = {"stage": "raw", "status": "pending", "reason_codes": ["ffmpeg_unavailable"], "detail": str(exc)}
        await _insert_qa_report(production_order_id=production_order_id, stage="raw", asset_id=data["raw_asset_id"], report=report, passed=None)
        return {"ok": False, "error": "ffmpeg_unavailable", "report": report}
    except Exception as exc:
        report = {"stage": "raw", "status": "pending", "reason_codes": ["technical_qa_unavailable"], "detail": str(exc)[:500]}
        await _insert_qa_report(production_order_id=production_order_id, stage="raw", asset_id=data["raw_asset_id"], report=report, passed=None)
        return {"ok": False, "error": "technical_qa_unavailable", "report": report}
    if not technical["ok"]:
        report = {"stage": "raw", "status": "failed", "technical": technical}
        await _insert_qa_report(production_order_id=production_order_id, stage="raw", asset_id=data["raw_asset_id"], report=report, passed=False)
        await _move_after_raw_qa(production_order_id, passed=False)
        return {"ok": False, "error": "raw_technical_qa_failed", "report": report}
    semantic = await _run_raw_semantic_qa(
        path=path,
        prompt_source=_content(data["prompt_source"]),
        truth_snapshot=_content(data["snapshot"]),
        content_spec=_content(data["content_spec"]),
    )
    product_reference = await _run_product_reference_qa(
        path=path,
        truth_snapshot=_content(data["snapshot"]),
        content_spec=_content(data["content_spec"]),
    )
    if semantic.get("status") == "unavailable" or product_reference.get("status") == "unavailable":
        report = {
            "stage": "raw",
            "status": "pending",
            "technical": technical,
            "semantic": semantic,
            "product_reference": product_reference,
        }
        await _insert_qa_report(production_order_id=production_order_id, stage="raw", asset_id=data["raw_asset_id"], report=report, passed=None)
        return {"ok": False, "error": "raw_semantic_qa_unavailable", "report": report}
    passed = semantic.get("status") == "passed" and product_reference.get("status") == "passed"
    report = {
        "stage": "raw",
        "status": "passed" if passed else "failed",
        "technical": technical,
        "semantic": semantic,
        "product_reference": product_reference,
    }
    await _insert_qa_report(production_order_id=production_order_id, stage="raw", asset_id=data["raw_asset_id"], report=report, passed=passed)
    await _move_after_raw_qa(production_order_id, passed=passed)
    return {"ok": passed, "error": None if passed else "raw_semantic_qa_failed", "report": report}


async def _move_after_raw_qa(production_order_id: str, *, passed: bool) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            context = await _load_context(conn, production_order_id, lock=True)
            if not context:
                return
            target = "raw_passed" if passed else "raw_rejected"
            current = context["order"]["status"]
            if current == target:
                return
            if current in {"raw_qa", "raw_rejected", "raw_passed"}:
                await _transition_locked(conn, context["order"], target)


async def _run_raw_semantic_qa(
    *, path: Path, prompt_source: Mapping[str, Any], truth_snapshot: Mapping[str, Any], content_spec: Mapping[str, Any]
) -> dict[str, Any]:
    """Independent visual judge; unavailable is pending, never a silent pass."""

    try:
        from app.services.gemini_video_client import GeminiVideoClient

        config = get_model_for_tool(P0_QA_TOOL)
        envelope = _content(prompt_source)
        compiled = _content(envelope.get("compiled"))
        system_prompt = prompts.render("p0_video_qa.system")
        user_prompt = prompts.render(
            "p0_video_qa.user",
            truth_snapshot_json=canonical_json(truth_snapshot),
            content_spec_json=canonical_json(content_spec),
            final_prompt=str(compiled.get("final_prompt") or ""),
        )
        result, usage = await GeminiVideoClient(str(config["model"])).analyze_video(
            str(path),
            system_prompt,
            user_prompt,
            temperature=float(config.get("temperature", 0.2)),
            max_tokens=int(config.get("max_tokens", 2500)),
            response_schema=RAW_SEMANTIC_QA_RESPONSE_SCHEMA,
        )
        decision = str(result.get("decision") or "").strip().lower() if isinstance(result, Mapping) else ""
        reasons = result.get("reason_codes") if isinstance(result, Mapping) else None
        evidence = result.get("evidence") if isinstance(result, Mapping) else None
        if decision not in {"passed", "failed"} or not isinstance(reasons, list) or not isinstance(evidence, list):
            raise ValueError("semantic_qa_json_schema_invalid")
        return {
            "status": decision,
            "reason_codes": [str(item) for item in reasons],
            "evidence": [str(item) for item in evidence],
            "provider": config.get("provider", "gemini"),
            "model": config["model"],
            "usage": usage,
            "response_hash": content_hash(result),
        }
    except Exception as exc:
        return {"status": "unavailable", "reason_codes": ["semantic_qa_unavailable"], "detail": str(exc)[:500]}


def _data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if not mime or not mime.startswith("image/"):
        raise ValueError("qa_image_not_supported")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


_PRODUCT_REFERENCE_FRAME_FRACTIONS = (0.30, 0.42, 0.54, 0.66)
_PRODUCT_REFERENCE_NONIDENTIFIABLE_REASON_CODES = frozenset(
    {
        "product_not_visible",
        "product_label_unclear",
        "product_not_identifiable",
        "product_occluded",
        "product_blurred",
    }
)


def _product_reference_frame_timestamps(content_spec: Mapping[str, Any] | None) -> list[float]:
    """Return stable P0 evidence-frame times from the frozen ContentSpec."""

    try:
        duration = float(_mapping(content_spec or {}).get("duration_seconds") or 12.0)
    except (TypeError, ValueError):
        duration = 12.0
    if duration <= 0:
        duration = 12.0
    return [round(duration * fraction, 3) for fraction in _PRODUCT_REFERENCE_FRAME_FRACTIONS]


def _unique_reason_codes(frame_checks: Sequence[Mapping[str, Any]]) -> list[str]:
    codes: list[str] = []
    for check in frame_checks:
        raw = check.get("reason_codes")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            continue
        for value in raw:
            code = str(value)
            if code and code not in codes:
                codes.append(code)
    return codes


def _is_nonidentifiable_product_reference_failure(check: Mapping[str, Any]) -> bool:
    """Whether a failed frame is safe to ignore after another frame matches.

    A frame can be unusable because the product is absent, covered, or too
    blurred to identify.  That is not evidence of a wrong product.  Every
    other failed classification is blocking: in particular,
    ``packaging_different`` and ``label_text_different`` must never be
    cancelled out by a matching frame elsewhere in the same raw video.
    """

    if check.get("status") != "failed":
        return False
    codes = _unique_reason_codes([check])
    return bool(codes) and set(codes).issubset(_PRODUCT_REFERENCE_NONIDENTIFIABLE_REASON_CODES)


async def _run_single_product_reference_frame_qa(
    *, path: Path, truth_snapshot: Mapping[str, Any], timestamp_seconds: float
) -> dict[str, Any]:
    """Compare deterministic raw-video frames against a frozen product reference.

    Video semantics and still-image identity are judged separately: the former
    checks the action over time, while this gate prevents a recognizable but
    wrong bottle/package from passing merely because its product name appears
    in the prompt.
    """

    frame_path = path.parent / f".p0-product-qa-{uuid.uuid4().hex}.jpg"
    try:
        references = truth_snapshot.get("product_reference_manifest")
        assets = references.get("assets") if isinstance(references, Mapping) else []
        first = assets[0] if isinstance(assets, list) and assets else None
        if not isinstance(first, Mapping):
            raise ValueError("product_reference_missing")
        reference_path = resolve_reference_path(str(first.get("file_url") or ""))
        extracted = _run_process(
            [
                "ffmpeg", "-y", "-ss", f"{timestamp_seconds:.3f}", "-i", str(path),
                "-frames:v", "1", "-q:v", "2", str(frame_path),
            ]
        )
        if extracted.returncode != 0 or not frame_path.is_file() or frame_path.stat().st_size == 0:
            return {
                "status": "unavailable",
                "timestamp_seconds": timestamp_seconds,
                "reason_codes": ["qa_frame_extract_failed"],
                "detail": (extracted.stderr or "qa_frame_extract_failed")[-500:],
            }
        config = get_model_for_tool(P0_QA_TOOL)
        system_prompt = prompts.render("p0_product_reference_qa.system")
        user_prompt = prompts.render(
            "p0_product_reference_qa.user",
            product_name=str(_mapping(truth_snapshot.get("sku")).get("name") or "产品"),
            reference_asset_id=str(first.get("id") or ""),
            frame_timestamp_seconds=f"{timestamp_seconds:.3f}",
        )
        response = await AIHubClient(timeout=120.0).chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": _data_url(reference_path)}},
                        {"type": "image_url", "image_url": {"url": _data_url(frame_path)}},
                    ],
                },
            ],
            provider=str(config["provider"]),
            model=str(config["model"]),
            temperature=float(config.get("temperature", 0.2)),
            max_tokens=int(config.get("max_tokens", 2500)),
        )
        result = _extract_json_object(response)
        decision = str((result or {}).get("decision") or "").strip().lower()
        reasons = (result or {}).get("reason_codes")
        evidence = (result or {}).get("evidence")
        if decision not in {"passed", "failed"} or not isinstance(reasons, list) or not isinstance(evidence, list):
            raise ValueError("product_reference_qa_json_schema_invalid")
        return {
            "status": decision,
            "timestamp_seconds": timestamp_seconds,
            "reason_codes": [str(item) for item in reasons],
            "evidence": [str(item) for item in evidence],
            "reference_asset_id": first.get("id"),
            "reference_sha256": sha256_reference(reference_path),
            "provider": response.get("provider") or config["provider"],
            "model": response.get("model") or config["model"],
            "response_hash": content_hash(result),
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "timestamp_seconds": timestamp_seconds,
            "reason_codes": ["product_reference_qa_unavailable"],
            "detail": str(exc)[:500],
        }
    finally:
        try:
            frame_path.unlink(missing_ok=True)
        except OSError:
            pass


async def _run_product_reference_qa(
    *, path: Path, truth_snapshot: Mapping[str, Any], content_spec: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Pass only if a frame clearly matches and no frame clearly contradicts it.

    A blurred or hand-covered still is neither a pass nor proof of a mismatch.
    It may be ignored only after another frame is a clear match.  Each sampled
    time point is nevertheless recorded.  The gate remains fail closed: a
    clear, explicit per-frame pass is required to move forward, while any
    identifiable packaging or label mismatch blocks the entire raw video.
    """

    frame_checks: list[dict[str, Any]] = []
    for frame_index, timestamp_seconds in enumerate(
        _product_reference_frame_timestamps(content_spec), start=1
    ):
        result = dict(
            await _run_single_product_reference_frame_qa(
                path=path,
                truth_snapshot=truth_snapshot,
                timestamp_seconds=timestamp_seconds,
            )
        )
        result["frame_index"] = frame_index
        frame_checks.append(result)

    passing = next((check for check in frame_checks if check.get("status") == "passed"), None)
    shared = {
        "frame_checks": frame_checks,
        "reference_asset_id": next(
            (check.get("reference_asset_id") for check in frame_checks if check.get("reference_asset_id")),
            None,
        ),
        "reference_sha256": next(
            (check.get("reference_sha256") for check in frame_checks if check.get("reference_sha256")),
            None,
        ),
    }
    blocking = [
        check
        for check in frame_checks
        if check.get("status") == "failed"
        and not _is_nonidentifiable_product_reference_failure(check)
    ]
    if blocking:
        return {
            "status": "failed",
            "reason_codes": _unique_reason_codes(blocking),
            "evidence": [
                f"{check['timestamp_seconds']}s: {item}"
                for check in blocking
                for item in check.get("evidence", [])
                if isinstance(item, str)
            ],
            "blocking_frame_indices": [int(check["frame_index"]) for check in blocking],
            "blocking_frame_timestamps_seconds": [
                check["timestamp_seconds"] for check in blocking
            ],
            **shared,
        }

    unavailable = [check for check in frame_checks if check.get("status") == "unavailable"]
    if unavailable:
        return {
            "status": "unavailable",
            "reason_codes": _unique_reason_codes(unavailable) or ["product_reference_qa_unavailable"],
            "evidence": [],
            **shared,
        }

    if passing:
        return {
            "status": "passed",
            "reason_codes": list(passing.get("reason_codes") or []),
            "evidence": list(passing.get("evidence") or []),
            "matched_frame_index": passing["frame_index"],
            "matched_frame_timestamp_seconds": passing["timestamp_seconds"],
            "provider": passing.get("provider"),
            "model": passing.get("model"),
            "response_hash": passing.get("response_hash"),
            **shared,
        }

    return {
        "status": "failed",
        "reason_codes": _unique_reason_codes(frame_checks) or ["product_reference_no_clear_match"],
        "evidence": [
            f"{check['timestamp_seconds']}s: {item}"
            for check in frame_checks
            for item in check.get("evidence", [])
            if isinstance(item, str)
        ],
        **shared,
    }


def _subtitle_filter_path(path: Path) -> str:
    """Escape the tiny subset ffmpeg's subtitle filter interprets on Linux."""

    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _audio_stream_info(probe: Mapping[str, Any]) -> dict[str, Any]:
    streams = probe.get("streams")
    if not isinstance(streams, Sequence):
        return {"has_audio": False, "duration_seconds": 0.0}
    audio = next(
        (item for item in streams if isinstance(item, Mapping) and item.get("codec_type") == "audio"),
        None,
    )
    try:
        duration = float(_mapping(probe.get("format")).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {"has_audio": isinstance(audio, Mapping), "duration_seconds": duration}


async def compose_final_video(
    *,
    production_order_id: str,
    attempt_id: str,
    voiceover_audio_ref: str | None = None,
    bgm_audio_ref: str | None = None,
    bgm_authorization_note: str | None = None,
    allow_no_bgm: bool = False,
    no_bgm_scope_note: str | None = None,
) -> dict[str, Any]:
    """Burn the frozen subtitle timeline and record every audio-stage input.

    Native Seedance audio is preferred.  If it is absent, the caller must give
    a readable, owner-supplied audio source; this code never manufactures a
    silent track merely so final QA can observe an audio stream.  BGM is either
    an explicitly authorized source or an explicit no-BGM scope confirmation.
    """

    pool = get_pool()
    async with pool.acquire() as conn:
        context = await _load_context(conn, production_order_id)
        if _require_context(context):
            return _require_context(context) or {}
        assert context is not None
        if context["order"]["status"] not in {"raw_passed", "final_qa"}:
            return {"ok": False, "error": "production_order_wrong_state", "status": context["order"]["status"]}
        row = await conn.fetchrow(
            """
            SELECT attempt.id::text AS attempt_id,attempt.raw_asset_id::text,
                   asset.file_url,review.script_id::text,script.content_contract
            FROM pipeline.production_generation_attempts attempt
            JOIN pipeline.assets asset ON asset.id=attempt.raw_asset_id
            JOIN pipeline.production_script_reviews review ON review.production_order_id=attempt.production_order_id
                 AND review.selected=true
            JOIN pipeline.scripts script ON script.id=review.script_id
            WHERE attempt.id=$1::uuid AND attempt.production_order_id=$2::uuid AND attempt.status='succeeded'
            """,
            attempt_id,
            production_order_id,
        )
    if not row:
        return {"ok": False, "error": "raw_generation_attempt_not_ready"}
    generation = dict(row)
    candidate = _candidate_from_review(generation)
    spec = _content(context["spec"]["spec"])
    duration = float(spec["duration_seconds"])
    subtitle = build_subtitle_timeline(
        spoken_copy=str(candidate.get("spoken_copy") or ""),
        duration_seconds=duration,
        beat_plan=candidate.get("beat_plan"),
    )
    if not subtitle["ok"]:
        return subtitle
    try:
        raw_path = resolve_reference_path(str(generation["file_url"] or ""))
        raw_probe = _ffprobe(raw_path)
    except FileNotFoundError:
        return {"ok": False, "error": "raw_asset_not_persisted"}
    except Exception as exc:
        return {"ok": False, "error": "ffmpeg_unavailable", "detail": str(exc)[:300]}
    native_audio = _audio_stream_info(raw_probe)
    audio_mode = "native" if native_audio["has_audio"] else "owner_supplied"
    supplied_audio_path: Path | None = None
    supplied_audio_hash: str | None = None
    if not native_audio["has_audio"]:
        if not voiceover_audio_ref:
            return {
                "ok": False,
                "error": "audio_source_required",
                "note": "Seedance raw video has no audio; provide a verified owner-supplied voiceover source.",
            }
        try:
            supplied_audio_path = resolve_reference_path(voiceover_audio_ref)
            supplied_probe = _ffprobe(supplied_audio_path)
            supplied_audio = _audio_stream_info(supplied_probe)
        except Exception as exc:
            return {"ok": False, "error": "owner_audio_invalid", "detail": str(exc)[:300]}
        if not supplied_audio["has_audio"] or supplied_audio["duration_seconds"] < duration * 0.8:
            return {"ok": False, "error": "owner_audio_invalid", "detail": "audio stream missing or too short"}
        supplied_audio_hash = _sha256_file(supplied_audio_path)
    bgm_audio_path: Path | None = None
    bgm_audio_hash: str | None = None
    authorization_note = str(bgm_authorization_note or "").strip()
    scope_note = str(no_bgm_scope_note or "").strip()
    if bgm_audio_ref:
        if not authorization_note:
            return {
                "ok": False,
                "error": "bgm_authorization_required",
                "note": "Provide an authorization basis for the BGM source before it can enter the final timeline.",
            }
        try:
            bgm_audio_path = resolve_reference_path(bgm_audio_ref)
            bgm_probe = _ffprobe(bgm_audio_path)
            bgm_info = _audio_stream_info(bgm_probe)
        except Exception as exc:
            return {"ok": False, "error": "authorized_bgm_invalid", "detail": str(exc)[:300]}
        if not bgm_info["has_audio"] or bgm_info["duration_seconds"] <= 0:
            return {"ok": False, "error": "authorized_bgm_invalid", "detail": "audio stream missing"}
        bgm_audio_hash = _sha256_file(bgm_audio_path)
        bgm_manifest: dict[str, Any] = {
            "mode": "authorized",
            "source_sha256": bgm_audio_hash,
            "authorization_note": authorization_note[:500],
            "authorization_note_hash": content_hash(authorization_note),
        }
    else:
        if not allow_no_bgm or not scope_note:
            return {
                "ok": False,
                "error": "authorized_bgm_or_scope_confirmation_required",
                "note": "Provide an authorized BGM source, or explicitly confirm this VO+subtitle/no-BGM scope.",
            }
        bgm_manifest = {
            "mode": "none_scope_confirmed",
            "scope_note": scope_note[:500],
            "scope_note_hash": content_hash(scope_note),
        }
    raw_hash = _sha256_file(raw_path)
    timeline_spec = {
        "contract_version": P0_CONTRACT_VERSION,
        "raw_asset_id": generation["raw_asset_id"],
        "raw_sha256": raw_hash,
        "duration_seconds": duration,
        "subtitles": subtitle["entries"],
        "spoken_copy": candidate["spoken_copy"],
        "audio": {
            "mode": audio_mode,
            "source_sha256": supplied_audio_hash if supplied_audio_hash else raw_hash,
            "native_requested": True,
            "bgm": bgm_manifest,
        },
    }
    timeline_hash = content_hash(timeline_spec)
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                """
                SELECT id::text AS id,status,final_asset_id::text
                FROM pipeline.production_timelines WHERE timeline_hash=$1 FOR UPDATE
                """,
                timeline_hash,
            )
            if existing and existing["status"] == "succeeded" and existing["final_asset_id"]:
                return {"ok": True, "reused": True, "timeline_id": existing["id"], "final_asset_id": existing["final_asset_id"]}
            if existing:
                timeline_id = existing["id"]
                await conn.execute(
                    "UPDATE pipeline.production_timelines SET status='composing',compose_log='{}'::jsonb WHERE id=$1::uuid",
                    timeline_id,
                )
            else:
                created = await conn.fetchrow(
                    """
                    INSERT INTO pipeline.production_timelines(
                        production_order_id,generation_attempt_id,timeline_spec,timeline_hash,status
                    ) VALUES($1::uuid,$2::uuid,$3::jsonb,$4,'composing') RETURNING id::text AS id
                    """,
                    production_order_id,
                    attempt_id,
                    _json(timeline_spec),
                    timeline_hash,
                )
                timeline_id = created["id"]

    safe_sku = _safe_sku_dir(context["order"]["sku_id"])
    output_dir = ASSETS_ROOT / safe_sku
    output_dir.mkdir(parents=True, exist_ok=True)
    nonce = uuid.uuid4().hex
    srt_path = output_dir / f"p0-{production_order_id}-{nonce}.srt"
    output_path = output_dir / f"p0-{production_order_id}-{nonce}.mp4"
    try:
        srt_path.write_text(subtitle["srt"], encoding="utf-8")
        subtitle_filter = f"subtitles=filename='{_subtitle_filter_path(srt_path)}'"
        if native_audio["has_audio"] and bgm_audio_path is None:
            command = [
                "ffmpeg", "-y", "-i", str(raw_path), "-vf", subtitle_filter,
                "-map", "0:v:0", "-map", "0:a:0", "-c:v", "libx264", "-c:a", "aac",
                "-movflags", "+faststart", "-t", str(duration), str(output_path),
            ]
        elif native_audio["has_audio"]:
            command = [
                "ffmpeg", "-y", "-i", str(raw_path), "-stream_loop", "-1", "-i", str(bgm_audio_path),
                "-filter_complex",
                f"[0:v]{subtitle_filter}[v];[0:a]volume=1.0[voice];[1:a]volume=0.16[bed];[voice][bed]amix=inputs=2:duration=first:dropout_transition=2[a]",
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-c:a", "aac",
                "-movflags", "+faststart", "-t", str(duration), str(output_path),
            ]
        elif bgm_audio_path is None:
            assert supplied_audio_path is not None
            command = [
                "ffmpeg", "-y", "-i", str(raw_path), "-i", str(supplied_audio_path),
                "-filter_complex", f"[0:v]{subtitle_filter}[v];[1:a]apad=pad_dur={duration}[a]",
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-c:a", "aac",
                "-movflags", "+faststart", "-t", str(duration), str(output_path),
            ]
        else:
            assert supplied_audio_path is not None
            command = [
                "ffmpeg", "-y", "-i", str(raw_path), "-i", str(supplied_audio_path),
                "-stream_loop", "-1", "-i", str(bgm_audio_path),
                "-filter_complex",
                f"[0:v]{subtitle_filter}[v];[1:a]apad=pad_dur={duration},volume=1.0[voice];[2:a]volume=0.16[bed];[voice][bed]amix=inputs=2:duration=first:dropout_transition=2[a]",
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-c:a", "aac",
                "-movflags", "+faststart", "-t", str(duration), str(output_path),
            ]
        completed = _run_process(command)
        if completed.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError(completed.stderr[-800:] or "ffmpeg_compose_failed")
        compose_log = {
            "status": "succeeded",
            "stages": {
                "voice": {
                    "status": "succeeded",
                    "mode": audio_mode,
                    "source_sha256": timeline_spec["audio"]["source_sha256"],
                },
                "bgm": {"status": "succeeded", **bgm_manifest},
                "subtitles": {"status": "succeeded", "timeline_hash": subtitle["timeline_hash"]},
                "ffmpeg": {"status": "succeeded", "output_sha256": _sha256_file(output_path)},
            },
        }
    except FileNotFoundError as exc:
        compose_log = {
            "status": "partial",
            "error": "ffmpeg_unavailable",
            "retryable_stage": "ffmpeg",
            "stages": {"bgm": {"status": "succeeded", **bgm_manifest}, "ffmpeg": {"status": "failed", "detail": str(exc)}},
        }
        await pool.execute(
            "UPDATE pipeline.production_timelines SET status='failed',compose_log=$2::jsonb WHERE id=$1::uuid",
            timeline_id,
            _json(compose_log),
        )
        return {"ok": False, "error": "ffmpeg_unavailable", "status": "partial", "retryable_stage": "ffmpeg"}
    except Exception as exc:
        compose_log = {
            "status": "partial",
            "error": "ffmpeg_compose_failed",
            "retryable_stage": "ffmpeg",
            "stages": {"bgm": {"status": "succeeded", **bgm_manifest}, "ffmpeg": {"status": "failed", "detail": str(exc)[:800]}},
        }
        await pool.execute(
            "UPDATE pipeline.production_timelines SET status='failed',compose_log=$2::jsonb WHERE id=$1::uuid",
            timeline_id,
            _json(compose_log),
        )
        return {
            "ok": False,
            "error": "ffmpeg_compose_failed",
            "detail": str(exc)[:300],
            "status": "partial",
            "retryable_stage": "ffmpeg",
        }
    finally:
        try:
            srt_path.unlink(missing_ok=True)
        except OSError:
            pass
    final_url = f"{PUBLIC_URL_PREFIX}/{safe_sku}/{output_path.name}"
    final_asset_id = await save_storyboard_asset(
        sku_id=context["order"]["sku_id"],
        asset_type="video",
        script_id=generation["script_id"],
        audience_record_id=context["order"]["audience_record_id"],
        file_url=final_url,
        prompt="P0 final composition; subtitle and audio source are frozen in production_timeline",
        duration_seconds=duration,
        notes=f"p0/final; production_order={production_order_id}; raw_attempt={attempt_id}",
        persist_to_disk=False,
    )
    if not final_asset_id:
        await pool.execute(
            "UPDATE pipeline.production_timelines SET status='failed',compose_log=$2::jsonb WHERE id=$1::uuid",
            timeline_id,
            _json({"status": "failed", "error": "final_asset_record_failed", **compose_log}),
        )
        return {"ok": False, "error": "final_asset_record_failed"}
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await _load_context(conn, production_order_id, lock=True)
            if not locked:
                return {"ok": False, "error": "production_order_not_found"}
            source = await conn.fetchrow(
                """
                SELECT id::text AS id,prompt_source,reference_manifest
                FROM pipeline.production_prompt_sources
                WHERE production_order_id=$1::uuid
                ORDER BY created_at DESC LIMIT 1 FOR UPDATE
                """,
                production_order_id,
            )
            if not source:
                return {"ok": False, "error": "prompt_source_not_found"}
            try:
                match = await _persist_execution_content_match(
                    conn,
                    production_order_id=production_order_id,
                    context=locked,
                    source=dict(source),
                    candidate=candidate,
                    stage="final",
                    audio_plan=_content(timeline_spec["audio"]),
                )
            except Exception as exc:
                await conn.execute(
                    "UPDATE pipeline.production_timelines SET status='failed',compose_log=$2::jsonb WHERE id=$1::uuid",
                    timeline_id,
                    _json({"status": "partial", "error": "content_match_persist_failed", "detail": str(exc)[:500], **compose_log}),
                )
                return {"ok": False, "error": "content_match_persist_failed", "status": "partial"}
            await conn.execute(
                """
                UPDATE pipeline.production_timelines
                SET status='succeeded',final_asset_id=$2::uuid,compose_log=$3::jsonb
                WHERE id=$1::uuid
                """,
                timeline_id,
                final_asset_id,
                _json(compose_log),
            )
            if locked and locked["order"]["status"] == "raw_passed":
                await _transition_locked(conn, locked["order"], "final_qa")
    return {
        "ok": True,
        "reused": False,
        "timeline_id": timeline_id,
        "final_asset_id": final_asset_id,
        "content_match_report_id": match["id"],
        "status": "final_qa",
    }


async def run_final_qa(*, production_order_id: str) -> dict[str, Any]:
    """Verify final media, audio, subtitle timing and frozen-manifest consistency."""

    pool = get_pool()
    async with pool.acquire() as conn:
        context = await _load_context(conn, production_order_id)
        if _require_context(context):
            return _require_context(context) or {}
        assert context is not None
        if context["order"]["status"] != "final_qa":
            return {"ok": False, "error": "production_order_wrong_state", "status": context["order"]["status"]}
        row = await conn.fetchrow(
            """
            SELECT timeline.id::text AS timeline_id,timeline.timeline_spec,timeline.timeline_hash,
                   timeline.final_asset_id::text,asset.file_url,
                   review.script_id::text,script.content_contract
            FROM pipeline.production_timelines timeline
            JOIN pipeline.assets asset ON asset.id=timeline.final_asset_id
            JOIN pipeline.production_script_reviews review ON review.production_order_id=timeline.production_order_id AND review.selected=true
            JOIN pipeline.scripts script ON script.id=review.script_id
            WHERE timeline.production_order_id=$1::uuid AND timeline.status='succeeded'
            ORDER BY timeline.created_at DESC LIMIT 1
            """,
            production_order_id,
        )
        raw_qa_passed = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM pipeline.production_qa_reports
                WHERE production_order_id=$1::uuid AND stage='raw' AND passed=true
            )
            """,
            production_order_id,
        )
    if not row:
        return {"ok": False, "error": "final_timeline_not_found"}
    final = dict(row)
    try:
        final_path = resolve_reference_path(str(final["file_url"] or ""))
        probe = _ffprobe(final_path)
        technical = validate_media_probe(
            probe,
            require_audio=True,
            expected_duration_seconds=_content(context["spec"]["spec"]).get("duration_seconds"),
        )
        technical["file_sha256"] = _sha256_file(final_path)
    except FileNotFoundError:
        technical = {"ok": False, "failed_checks": ["final_asset_not_persisted"]}
    except Exception as exc:
        report = {"stage": "final", "status": "pending", "reason_codes": ["technical_qa_unavailable"], "detail": str(exc)[:500]}
        await _insert_qa_report(production_order_id=production_order_id, stage="final", asset_id=final["final_asset_id"], report=report, passed=None)
        return {"ok": False, "error": "technical_qa_unavailable", "report": report}
    timeline_spec = _content(final["timeline_spec"])
    candidate = _candidate_from_review(final)
    subtitles = validate_subtitle_timeline(
        timeline_spec.get("subtitles"),
        duration_seconds=_content(context["spec"]["spec"]).get("duration_seconds"),
        spoken_copy=str(candidate.get("spoken_copy") or ""),
        beat_plan=candidate.get("beat_plan"),
    )
    audio_manifest = _content(timeline_spec.get("audio"))
    bgm_manifest = _content(audio_manifest.get("bgm"))
    bgm_mode = str(bgm_manifest.get("mode") or "")
    bgm_manifest_valid = (
        (bgm_mode == "authorized" and bool(bgm_manifest.get("source_sha256")) and bool(bgm_manifest.get("authorization_note")))
        or (bgm_mode == "none_scope_confirmed" and bool(bgm_manifest.get("scope_note")))
    )
    manifest_match = (
        timeline_spec.get("contract_version") == P0_CONTRACT_VERSION
        and bool(timeline_spec.get("raw_asset_id"))
        and bool(timeline_spec.get("raw_sha256"))
        and bool(audio_manifest.get("source_sha256"))
        and bgm_manifest_valid
    )
    passed = bool(raw_qa_passed) and bool(technical.get("ok")) and bool(subtitles.get("ok")) and manifest_match
    report = {
        "stage": "final",
        "status": "passed" if passed else "failed",
        "technical": technical,
        "subtitles": subtitles,
        "raw_qa_passed": bool(raw_qa_passed),
        "manifest_match": manifest_match,
        "audio_manifest": {
            "mode": audio_manifest.get("mode"),
            "bgm_mode": bgm_mode,
            "bgm_manifest_valid": bgm_manifest_valid,
        },
        "timeline_hash": final["timeline_hash"],
    }
    await _insert_qa_report(production_order_id=production_order_id, stage="final", asset_id=final["final_asset_id"], report=report, passed=passed)
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await _load_context(conn, production_order_id, lock=True)
            if locked and locked["order"]["status"] == "final_qa":
                await _transition_locked(conn, locked["order"], "ready_to_release" if passed else "final_rejected")
    return {"ok": passed, "error": None if passed else "final_qa_failed", "report": report}


async def release_package(*, production_order_id: str) -> dict[str, Any]:
    """Create the immutable release manifest after the third, explicit human gate."""

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            context = await _load_context(conn, production_order_id, lock=True)
            missing = _require_context(context)
            if missing:
                return missing
            assert context is not None
            if context["order"]["status"] == "released":
                existing = await conn.fetchrow(
                    "SELECT id::text AS id,manifest_hash,final_asset_id::text FROM pipeline.release_packages WHERE production_order_id=$1::uuid",
                    production_order_id,
                )
                return {"ok": True, "reused": True, "release": dict(existing) if existing else None}
            if context["order"]["status"] != "ready_to_release":
                return {"ok": False, "error": "production_order_wrong_state", "status": context["order"]["status"]}
            final_qa = await conn.fetchrow(
                """
                SELECT asset_id::text,report FROM pipeline.production_qa_reports
                WHERE production_order_id=$1::uuid AND stage='final' AND passed=true
                ORDER BY created_at DESC LIMIT 1 FOR UPDATE
                """,
                production_order_id,
            )
            timeline = await conn.fetchrow(
                """
                SELECT id::text AS id,timeline_spec,timeline_hash,final_asset_id::text,compose_log
                FROM pipeline.production_timelines
                WHERE production_order_id=$1::uuid AND status='succeeded'
                ORDER BY created_at DESC LIMIT 1 FOR UPDATE
                """,
                production_order_id,
            )
            attempt = await conn.fetchrow(
                """
                SELECT id::text AS id,attempt_no,approval_hash,requested_provider,requested_model,
                       actual_provider,actual_model,remote_task_id,raw_asset_id::text
                FROM pipeline.production_generation_attempts
                WHERE production_order_id=$1::uuid AND status='succeeded'
                ORDER BY attempt_no DESC LIMIT 1
                """,
                production_order_id,
            )
            source = await conn.fetchrow(
                """
                SELECT id::text AS id,prompt_source,prompt_source_hash,reference_manifest,
                       requested_provider,requested_model,adapter_version
                FROM pipeline.production_prompt_sources WHERE production_order_id=$1::uuid
                ORDER BY created_at DESC LIMIT 1
                """,
                production_order_id,
            )
            selected = await conn.fetchrow(
                """
                SELECT review.script_id::text AS id,script.content_contract,script.script_md
                FROM pipeline.production_script_reviews review
                JOIN pipeline.scripts script ON script.id=review.script_id
                WHERE review.production_order_id=$1::uuid AND review.selected=true
                """,
                production_order_id,
            )
            content_match = await conn.fetchrow(
                """
                SELECT id::text AS id,input_hash,report,created_at
                FROM pipeline.production_content_match_reports
                WHERE production_order_id=$1::uuid AND prompt_source_id=$2::uuid
                  AND stage='final'
                ORDER BY created_at DESC LIMIT 1
                """,
                production_order_id,
                source["id"] if source else None,
            ) if source else None
            if not final_qa or not timeline or not attempt or not source or not selected or not content_match:
                return {"ok": False, "error": "release_lineage_incomplete"}
            if final_qa["asset_id"] != timeline["final_asset_id"]:
                return {"ok": False, "error": "release_final_asset_mismatch"}
            manifest = {
                "contract_version": P0_CONTRACT_VERSION,
                "production_order": context["order"],
                "truth_snapshot": context["truth"],
                "content_spec": context["spec"],
                "selected_script": dict(selected),
                "prompt_source": dict(source),
                "generation_attempt": dict(attempt),
                "timeline": dict(timeline),
                "final_qa": dict(final_qa),
                "execution_content_match": dict(content_match),
            }
            manifest_hash = content_hash(manifest)
            released = await conn.fetchrow(
                """
                INSERT INTO pipeline.release_packages(production_order_id,final_asset_id,manifest,manifest_hash)
                VALUES($1::uuid,$2::uuid,$3::jsonb,$4)
                ON CONFLICT (production_order_id) DO NOTHING
                RETURNING id::text AS id,manifest_hash,final_asset_id::text,released_at
                """,
                production_order_id,
                timeline["final_asset_id"],
                _json(manifest),
                manifest_hash,
            )
            if not released:
                existing = await conn.fetchrow(
                    "SELECT id::text AS id,manifest_hash,final_asset_id::text,released_at FROM pipeline.release_packages WHERE production_order_id=$1::uuid",
                    production_order_id,
                )
                return {"ok": True, "reused": True, "release": dict(existing) if existing else None}
            await conn.execute("UPDATE pipeline.assets SET status='adopted' WHERE id=$1::uuid", timeline["final_asset_id"])
            transition = await _transition_locked(conn, context["order"], "released")
            if transition:
                return transition
            return {"ok": True, "reused": False, "release": dict(released), "manifest_hash": manifest_hash}


async def cancel_production_order(*, production_order_id: str) -> dict[str, Any]:
    """Cancel without deleting source, attempts or audit history."""

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            context = await _load_context(conn, production_order_id, lock=True)
            if not context:
                return {"ok": False, "error": "production_order_not_found"}
            if context["order"]["status"] == "cancelled":
                return {"ok": True, "reused": True, "status": "cancelled"}
            transition = await _transition_locked(conn, context["order"], "cancelled")
            if transition:
                return transition
            return {"ok": True, "reused": False, "status": "cancelled"}


async def get_full_production_order(production_order_id: str) -> dict[str, Any]:
    """Read the complete P0 lineage and its concrete next action."""

    pool = get_pool()
    async with pool.acquire() as conn:
        context = await _load_context(conn, production_order_id)
        if not context:
            return {"ok": False, "error": "production_order_not_found"}
        reviews = await _scripts_for_order(conn, production_order_id)
        sources = await conn.fetch(
            """
            SELECT id::text AS id,script_id::text,prompt_source_hash,requested_provider,requested_model,
                   adapter_version,reference_manifest,created_at
            FROM pipeline.production_prompt_sources WHERE production_order_id=$1::uuid ORDER BY created_at
            """,
            production_order_id,
        )
        attempts = await conn.fetch(
            """
            SELECT id::text AS id,prompt_source_id::text,attempt_no,approval_hash,requested_provider,
                   requested_model,actual_provider,actual_model,remote_task_id,status,error_category,
                   raw_asset_id::text,duration_ms,cost_cents,created_at,completed_at
            FROM pipeline.production_generation_attempts WHERE production_order_id=$1::uuid ORDER BY attempt_no
            """,
            production_order_id,
        )
        timelines = await conn.fetch(
            """
            SELECT id::text AS id,generation_attempt_id::text,timeline_hash,final_asset_id::text,
                   timeline_spec,compose_log,status,created_at
            FROM pipeline.production_timelines WHERE production_order_id=$1::uuid ORDER BY created_at
            """,
            production_order_id,
        )
        content_match_reports = await conn.fetch(
            """
            SELECT id::text AS id,prompt_source_id::text,stage,input_hash,report,created_at
            FROM pipeline.production_content_match_reports
            WHERE production_order_id=$1::uuid
            ORDER BY created_at
            """,
            production_order_id,
        )
        vector_match_reports = await conn.fetch(
            """
            SELECT id::text AS id,content_spec_id::text,script_id::text,prompt_source_id::text,
                   stage,candidate_slot,execution_source_kind,execution_source_hash,
                   audience_source_kind,audience_source_hash,embedding_provider,embedding_model,
                   matcher_version,report_status,report,created_at
            FROM pipeline.production_vector_match_reports
            WHERE production_order_id=$1::uuid
            ORDER BY created_at
            """,
            production_order_id,
        )
        qa_reports = await conn.fetch(
            """
            SELECT id::text AS id,stage,asset_id::text,report,passed,created_at
            FROM pipeline.production_qa_reports WHERE production_order_id=$1::uuid ORDER BY created_at
            """,
            production_order_id,
        )
        release = await conn.fetchrow(
            """
            SELECT id::text AS id,final_asset_id::text,manifest_hash,released_at
            FROM pipeline.release_packages WHERE production_order_id=$1::uuid
            """,
            production_order_id,
        )
    status = context["order"]["status"]
    next_actions = {
        "truth_ready": "p0_save_video_content_spec",
        "spec_ready": "p0_generate_video_script_candidates or p0_save_video_script_candidates",
        "awaiting_script_selection": "p0_review_video_script_candidates (includes vector pre-match), then p0_select_video_script",
        "prompt_ready": "p0_assess_video_execution_vector_match, then p0_request_video_generation_approval",
        "awaiting_generation_approval": "p0_start_video_generation (Human Gate)",
        "generating": "p0_recover_video_generation",
        "raw_qa": "p0_run_raw_video_qa",
        "raw_passed": "p0_compose_video_final",
        "final_qa": "p0_run_final_video_qa",
        "ready_to_release": "p0_release_video_package (Human Gate)",
    }
    if status == "truth_ready" and str(_mapping(context["order"]).get("contract_version") or "") == P0_CONTRACT_VERSION:
        next_actions["truth_ready"] = "p0_generate_planting_bridge_candidates"
    order_contract_version = str(_mapping(context["order"]).get("contract_version") or "")
    if order_contract_version != P0_CONTRACT_VERSION:
        next_action = "create_a_new_v4_order (legacy order is read-only audit history)"
    else:
        next_action = next_actions.get(status)
    return {
        "ok": True,
        "order": _public_row(context["order"], json_fields=("baseline_manifest",)),
        "truth_snapshot": _public_row(context["truth"], json_fields=("snapshot",)) if context["truth"] else None,
        "content_spec": _public_row(context["spec"], json_fields=("spec",)) if context["spec"] else None,
        "script_reviews": reviews,
        "prompt_sources": [_public_row(row, json_fields=("reference_manifest",)) for row in sources],
        "generation_attempts": [dict(row) for row in attempts],
        "timelines": [_public_row(row, json_fields=("timeline_spec", "compose_log")) for row in timelines],
        "content_match_reports": [_public_row(row, json_fields=("report",)) for row in content_match_reports],
        "vector_match_reports": [_public_row(row, json_fields=("report",)) for row in vector_match_reports],
        "qa_reports": [_public_row(row, json_fields=("report",)) for row in qa_reports],
        "release": dict(release) if release else None,
        "next_action": next_action,
    }


__all__ = [
    "assess_candidate_execution_vector_match",
    "assess_execution_content_match",
    "assess_frozen_execution_vector_match",
    "cancel_production_order",
    "compose_final_video",
    "generate_planting_bridge_candidates",
    "generate_script_candidates",
    "get_full_production_order",
    "prepare_prompt_source",
    "recover_generation_attempt",
    "release_package",
    "request_generation_approval",
    "review_script_candidates",
    "run_final_qa",
    "run_raw_qa",
    "save_script_candidates",
    "select_script",
    "start_generation_attempt",
]
