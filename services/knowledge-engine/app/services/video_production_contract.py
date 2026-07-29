"""Pure contracts for the P0 single-video production atom.

P0 deliberately owns a small, explicit contract instead of letting the
historical planting, ecommerce, and insert-video state machines leak into one
another.  Persistence and providers may change; these validation rules do not.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.services.video_prompt_source import (
    PromptSourceSchemaError,
    validate_prompt_source_schema,
)
from app.services.pain_solution_bridge import (
    canonical_upstream_fact_hash,
    constrain_p0_bridge_facts,
    validate_pain_solution_bridge,
)


# ``p0.v2`` and ``p0.v3`` production orders are immutable audit records.  New
# P0 writes use v4, which additionally freezes one explicit adopted audience
# pack.  Keep every prior version explicit instead of silently weakening the
# current order contract.
P0_V2_CONTRACT_VERSION = "2026-07-28.p0.v2"
P0_V3_CONTRACT_VERSION = "2026-07-29.p0.v3"
P0_CONTRACT_VERSION = "2026-07-29.p0.v4"
P0_SUPPORTED_CONTRACT_VERSIONS = frozenset(
    {P0_V2_CONTRACT_VERSION, P0_V3_CONTRACT_VERSION, P0_CONTRACT_VERSION}
)
P0_STRONG_LINEAGE_CONTRACT_VERSIONS = frozenset(
    {P0_V3_CONTRACT_VERSION, P0_CONTRACT_VERSION}
)
P0_PACK_REQUIRED_CONTRACT_VERSIONS = frozenset({P0_CONTRACT_VERSION})
P0_INTENT = "planting"
P0_MIN_DURATION_SECONDS = 12.0
P0_MAX_DURATION_SECONDS = 15.0
P0_HOOK_DURATION_SECONDS = 3.0
P0_MIN_BEAT_SECONDS = 2.5
P0_MAX_BEAT_SECONDS = 4.0
P0_MAX_SPOKEN_UNITS_PER_SECOND = 4.0

ORDER_STATUSES = frozenset(
    {
        "baseline_ready",
        "truth_ready",
        "spec_ready",
        "awaiting_script_selection",
        "prompt_ready",
        "awaiting_generation_approval",
        "generating",
        "raw_qa",
        "raw_passed",
        "final_qa",
        "ready_to_release",
        "released",
        "cancelled",
        "raw_rejected",
        "final_rejected",
    }
)

_ALLOWED_TRANSITIONS = {
    "baseline_ready": {"truth_ready", "cancelled"},
    "truth_ready": {"spec_ready", "cancelled"},
    "spec_ready": {"awaiting_script_selection", "cancelled"},
    "awaiting_script_selection": {"prompt_ready", "cancelled"},
    "prompt_ready": {"awaiting_generation_approval", "cancelled"},
    "awaiting_generation_approval": {"generating", "cancelled"},
    # A provider failure is recoverable without changing the approved prompt.
    # Returning to approval is intentional: a human still owns every paid
    # retry, while the failed attempt remains immutable audit history.
    "generating": {"raw_qa", "awaiting_generation_approval", "cancelled"},
    "raw_qa": {"raw_passed", "raw_rejected", "cancelled"},
    # A QA rule or provider recovery may re-evaluate the same immutable raw
    # asset.  This does not initiate a new paid generation; the new QA report
    # remains appended to the audit trail and must independently pass.
    "raw_rejected": {"awaiting_generation_approval", "raw_passed", "cancelled"},
    # A later raw-QA rerun can uncover a blocking issue in the same immutable
    # asset (for example a clearer frame revealing a wrong package).  It must
    # be able to revoke raw_passed without triggering a new paid generation.
    "raw_passed": {"raw_rejected", "final_qa", "cancelled"},
    "final_qa": {"ready_to_release", "final_rejected", "cancelled"},
    "final_rejected": {"raw_passed", "cancelled"},
    "ready_to_release": {"released", "cancelled"},
    "released": set(),
    "cancelled": set(),
}

_SPEC_REQUIRED_FIELDS = frozenset(
    {
        "target_audience_signal",
        "planting_function",
        "duration_seconds",
        "cast_count",
        "scene_count",
        "product_actions",
        "spoken_copy_goal",
        "pain_solution_bridge",
        "factual_whitelist",
        "forbidden_claims",
        "visual_constraints",
        "audio_constraints",
        "experiment_variable",
    }
)

_STRONG_LINEAGE_SPEC_REQUIRED_FIELDS = frozenset({"upstream_fact_hash"})

_STRONG_LINEAGE_TRUTH_CONTEXT_FIELDS = frozenset(
    {
        "facts",
        "eligible_evidence_catalog",
        "require_pack_evidence",
        "upstream_fact_hash",
    }
)

_CANDIDATE_REQUIRED_FIELDS = frozenset(
    {
        "opening_hook_3s",
        "body",
        "spoken_copy",
        "beat_plan",
        "product_action",
        "duration_seconds",
        "factual_claims",
        "content_spec_hash",
        "truth_snapshot_hash",
    }
)


def _canonicalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non_finite_number")
        return value
    if isinstance(value, (UUID, date, datetime)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("non_string_mapping_key")
            normalized[key] = _canonicalize(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonicalize(item) for item in value]
    raise ValueError(f"unsupported_value_type:{type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def p0_idempotency_key(
    *,
    sku_id: str,
    audience_record_id: str,
    audience_portrait_id: str | None = None,
    audience_pack_id: str | None = None,
    product_reference_asset_ids: Sequence[str],
    contract_version: str | None = None,
) -> str:
    """Return the stable key for the immutable P0 order inputs."""

    version = str(contract_version or P0_CONTRACT_VERSION).strip()
    if version not in P0_SUPPORTED_CONTRACT_VERSIONS:
        raise ValueError(f"unsupported_p0_contract_version:{version}")
    payload: dict[str, Any] = {
        "contract_version": version,
        "intent": P0_INTENT,
        "sku_id": str(sku_id).strip(),
        "audience_record_id": str(audience_record_id).strip(),
        "product_reference_asset_ids": [str(item).strip() for item in product_reference_asset_ids],
    }
    if version in P0_STRONG_LINEAGE_CONTRACT_VERSIONS:
        # v3+ requires this input at order creation.  Retaining an empty value
        # in the pure helper keeps deterministic diagnostics possible, while
        # the persistence service refuses a new current order without a
        # portrait.
        payload["audience_portrait_id"] = str(audience_portrait_id or "").strip()
    if version in P0_PACK_REQUIRED_CONTRACT_VERSIONS:
        payload["audience_pack_id"] = str(audience_pack_id or "").strip()
    return content_hash(payload)


def _resolve_contract_version(
    snapshot: object,
    contract_version: str | None,
) -> dict[str, Any]:
    declared = (
        str(snapshot.get("contract_version") or "").strip()
        if isinstance(snapshot, Mapping)
        else ""
    )
    requested = str(contract_version or "").strip()
    if declared and requested and declared != requested:
        return {
            "ok": False,
            "error": "truth_snapshot_contract_version_mismatch",
            "declared_contract_version": declared,
            "requested_contract_version": requested,
        }
    resolved = requested or declared or P0_CONTRACT_VERSION
    if resolved not in P0_SUPPORTED_CONTRACT_VERSIONS:
        return {
            "ok": False,
            "error": "truth_snapshot_contract_version_unsupported",
            "contract_version": resolved,
        }
    return {"ok": True, "contract_version": resolved}


def _bridge_evidence_catalog_from_facts(facts: Mapping[str, Any]) -> dict[str, Any] | None:
    """Mirror the canonical planting bridge tool's evidence-catalog shape."""

    raw_catalog = facts.get("eligible_evidence_catalog")
    if not isinstance(raw_catalog, Mapping):
        return None
    catalog = dict(raw_catalog)
    pack_catalog = facts.get("pack_calibration_catalog")
    if isinstance(pack_catalog, Mapping) and pack_catalog:
        catalog["pack"] = dict(pack_catalog)
    return catalog


def _validate_strong_lineage_truth_context(
    snapshot: Mapping[str, Any],
    *,
    sku: Mapping[str, Any],
    audience: Mapping[str, Any],
    portrait: Mapping[str, Any],
    require_pack: bool,
) -> tuple[list[str], list[str]]:
    """Validate the frozen canonical bridge context carried by a v3/v4 snapshot."""

    missing: list[str] = []
    invalid: list[str] = []
    context = snapshot.get("planting_bridge_context")
    if not isinstance(context, Mapping):
        return ["planting_bridge_context"], invalid

    for field in sorted(_STRONG_LINEAGE_TRUTH_CONTEXT_FIELDS):
        if field not in context:
            missing.append(f"planting_bridge_context.{field}")

    facts = context.get("facts")
    evidence_catalog = context.get("eligible_evidence_catalog")
    require_pack_evidence = context.get("require_pack_evidence")
    upstream_fact_hash = str(context.get("upstream_fact_hash") or "").strip()
    if not isinstance(facts, Mapping):
        missing.append("planting_bridge_context.facts")
        return missing, invalid
    if not isinstance(evidence_catalog, Mapping):
        missing.append("planting_bridge_context.eligible_evidence_catalog")
    if not isinstance(require_pack_evidence, bool):
        missing.append("planting_bridge_context.require_pack_evidence")
    if not re.fullmatch(r"[a-f0-9]{64}", upstream_fact_hash):
        missing.append("planting_bridge_context.upstream_fact_hash")

    lineage = facts.get("lineage")
    if not isinstance(lineage, Mapping):
        missing.append("planting_bridge_context.facts.lineage")
    else:
        expected_lineage = {
            "sku_id": str(sku.get("id") or ""),
            "audience_record_id": str(audience.get("id") or ""),
            "portrait_id": str(portrait.get("id") or ""),
        }
        for field, expected in expected_lineage.items():
            if str(lineage.get(field) or "") != expected:
                invalid.append(f"planting_bridge_context.facts.lineage.{field}")

    portrait_evidence = facts.get("portrait_record_evidence")
    frozen_portrait = (
        portrait_evidence.get("portrait")
        if isinstance(portrait_evidence, Mapping)
        else None
    )
    if not isinstance(frozen_portrait, Mapping):
        missing.append("planting_bridge_context.facts.portrait_record_evidence.portrait")
    else:
        if str(frozen_portrait.get("id") or "") != str(portrait.get("id") or ""):
            invalid.append("planting_bridge_context.facts.portrait_record_evidence.portrait.id")
        if str(frozen_portrait.get("portrait_md") or "") != str(portrait.get("portrait_md") or ""):
            invalid.append("planting_bridge_context.facts.portrait_record_evidence.portrait.portrait_md")

    facts_catalog = _bridge_evidence_catalog_from_facts(facts)
    if facts_catalog is None:
        missing.append("planting_bridge_context.facts.eligible_evidence_catalog")
    elif isinstance(evidence_catalog, Mapping):
        if canonical_json(facts_catalog) != canonical_json(evidence_catalog):
            invalid.append("planting_bridge_context.eligible_evidence_catalog")

    if isinstance(require_pack_evidence, bool):
        if require_pack_evidence != bool(facts.get("pack_calibration")):
            invalid.append("planting_bridge_context.require_pack_evidence")

    if require_pack:
        lineage_pack_id = (
            str(lineage.get("audience_pack_id") or "").strip()
            if isinstance(lineage, Mapping)
            else ""
        )
        if not lineage_pack_id:
            missing.append("planting_bridge_context.facts.lineage.audience_pack_id")
        pack_calibration = facts.get("pack_calibration")
        if not isinstance(pack_calibration, Mapping):
            missing.append("planting_bridge_context.facts.pack_calibration")
        else:
            if str(pack_calibration.get("id") or "").strip() != lineage_pack_id:
                invalid.append("planting_bridge_context.facts.pack_calibration.id")
        pack_catalog = facts.get("pack_calibration_catalog")
        if not isinstance(pack_catalog, Mapping) or not any(
            isinstance(value, str) and value.strip() for value in pack_catalog.values()
        ):
            missing.append("planting_bridge_context.facts.pack_calibration_catalog")
        if require_pack_evidence is not True:
            missing.append("planting_bridge_context.require_pack_evidence=true")
        if not isinstance(evidence_catalog, Mapping) or not isinstance(
            evidence_catalog.get("pack"), Mapping
        ):
            missing.append("planting_bridge_context.eligible_evidence_catalog.pack")

    if re.fullmatch(r"[a-f0-9]{64}", upstream_fact_hash):
        try:
            expected_hash = canonical_upstream_fact_hash(facts)
        except (TypeError, ValueError):
            invalid.append("planting_bridge_context.facts")
        else:
            if expected_hash != upstream_fact_hash:
                invalid.append("planting_bridge_context.upstream_fact_hash")
    return missing, invalid


def validate_truth_snapshot(
    snapshot: object,
    *,
    contract_version: str | None = None,
) -> dict[str, Any]:
    """Validate and normalize the immutable source-of-truth payload."""

    if not isinstance(snapshot, Mapping):
        return {"ok": False, "error": "truth_snapshot_invalid", "missing": ["snapshot"]}
    version = _resolve_contract_version(snapshot, contract_version)
    if not version["ok"]:
        return version
    resolved_contract_version = version["contract_version"]
    required = ("sku", "audience_record", "product_reference_manifest", "facts")
    missing = [field for field in required if not snapshot.get(field)]
    sku = snapshot.get("sku")
    audience = snapshot.get("audience_record")
    references = snapshot.get("product_reference_manifest")
    facts = snapshot.get("facts")
    if not isinstance(sku, Mapping) or not str(sku.get("id") or "").strip():
        missing.append("sku.id")
    if not isinstance(audience, Mapping) or not str(audience.get("id") or "").strip():
        missing.append("audience_record.id")
    if not isinstance(references, Mapping):
        missing.append("product_reference_manifest")
    else:
        assets = references.get("assets")
        if not isinstance(assets, list) or not assets:
            missing.append("product_reference_manifest.assets")
    if not isinstance(facts, Mapping):
        missing.append("facts")
    else:
        whitelist = facts.get("whitelist")
        if not isinstance(whitelist, list) or not whitelist:
            missing.append("facts.whitelist")
    portrait = snapshot.get("audience_portrait")
    if resolved_contract_version in P0_STRONG_LINEAGE_CONTRACT_VERSIONS:
        if not isinstance(portrait, Mapping):
            missing.append("audience_portrait")
        else:
            if not str(portrait.get("id") or "").strip():
                missing.append("audience_portrait.id")
            if str(portrait.get("status") or "") != "adopted":
                missing.append("audience_portrait.status=adopted")
            if not str(portrait.get("portrait_md") or "").strip():
                missing.append("audience_portrait.portrait_md")
            if isinstance(sku, Mapping) and str(portrait.get("sku_id") or "") != str(sku.get("id") or ""):
                missing.append("audience_portrait.sku_id")
            if isinstance(audience, Mapping) and str(portrait.get("audience_record_id") or "") != str(audience.get("id") or ""):
                missing.append("audience_portrait.audience_record_id")
            context_missing, context_invalid = _validate_strong_lineage_truth_context(
                snapshot,
                sku=sku if isinstance(sku, Mapping) else {},
                audience=audience if isinstance(audience, Mapping) else {},
                portrait=portrait,
                require_pack=resolved_contract_version in P0_PACK_REQUIRED_CONTRACT_VERSIONS,
            )
            missing.extend(context_missing)
            if context_invalid:
                return {
                    "ok": False,
                    "error": "truth_snapshot_invalid",
                    "invalid": sorted(set(context_invalid)),
                    "contract_version": resolved_contract_version,
                }
    if missing:
        return {
            "ok": False,
            "error": "truth_snapshot_incomplete",
            "missing": sorted(set(missing)),
            "contract_version": resolved_contract_version,
        }
    normalized = _canonicalize(snapshot)
    return {
        "ok": True,
        "snapshot": normalized,
        "snapshot_hash": content_hash(normalized),
        "contract_version": resolved_contract_version,
    }


def validate_content_spec(
    spec: object,
    *,
    truth_snapshot_hash: str,
    truth_snapshot: Mapping[str, Any] | None = None,
    contract_version: str | None = None,
) -> dict[str, Any]:
    """Enforce the intentionally narrow P0 production contract."""

    if not isinstance(spec, Mapping):
        return {"ok": False, "error": "content_spec_invalid", "missing": ["spec"]}
    version = _resolve_contract_version(truth_snapshot or {}, contract_version)
    if not version["ok"]:
        return version
    resolved_contract_version = version["contract_version"]
    required_fields = _SPEC_REQUIRED_FIELDS
    if resolved_contract_version in P0_STRONG_LINEAGE_CONTRACT_VERSIONS:
        required_fields = required_fields | _STRONG_LINEAGE_SPEC_REQUIRED_FIELDS
    missing = sorted(field for field in required_fields if field not in spec)
    if str(spec.get("intent") or P0_INTENT) != P0_INTENT:
        missing.append("intent=planting")
    try:
        duration = float(spec.get("duration_seconds"))
    except (TypeError, ValueError):
        duration = -1
    if not P0_MIN_DURATION_SECONDS <= duration <= P0_MAX_DURATION_SECONDS:
        missing.append("duration_seconds_12_to_15")
    if spec.get("cast_count") != 1:
        missing.append("cast_count=1")
    if spec.get("scene_count") != 1:
        missing.append("scene_count=1")
    actions = spec.get("product_actions")
    if not isinstance(actions, list) or len(actions) != 1 or not str(actions[0]).strip():
        missing.append("one_product_action")
    if str(spec.get("experiment_variable") or "").strip() != "opening_hook_3s":
        missing.append("experiment_variable=opening_hook_3s")
    if not str(truth_snapshot_hash or "").strip():
        missing.append("truth_snapshot_hash")
    if missing:
        return {
            "ok": False,
            "error": "content_spec_incomplete",
            "missing": sorted(set(missing)),
        }

    if resolved_contract_version in P0_STRONG_LINEAGE_CONTRACT_VERSIONS:
        if truth_snapshot is None:
            return {
                "ok": False,
                "error": "content_spec_truth_context_missing",
                "missing": ["truth_snapshot"],
            }
        truth = validate_truth_snapshot(
            truth_snapshot,
            contract_version=resolved_contract_version,
        )
        if not truth["ok"]:
            return {
                "ok": False,
                "error": "content_spec_truth_snapshot_invalid",
                "truth_error": truth,
            }
        if truth["snapshot_hash"] != truth_snapshot_hash:
            return {
                "ok": False,
                "error": "content_spec_truth_snapshot_hash_mismatch",
                "expected_truth_snapshot_hash": truth["snapshot_hash"],
                "actual_truth_snapshot_hash": truth_snapshot_hash,
            }

        context = truth["snapshot"]["planting_bridge_context"]
        bridge = spec.get("pain_solution_bridge")
        snapshot_facts = truth["snapshot"].get("facts")
        factual_whitelist = (
            _string_list(snapshot_facts.get("whitelist"))
            if isinstance(snapshot_facts, Mapping)
            and resolved_contract_version == P0_CONTRACT_VERSION
            else None
        )
        bridge_catalog = context["eligible_evidence_catalog"]
        if factual_whitelist is not None:
            try:
                constrained_facts = constrain_p0_bridge_facts(
                    context["facts"],
                    factual_whitelist,
                )
            except (TypeError, ValueError) as exc:
                return {
                    "ok": False,
                    "error": "content_spec_pain_solution_bridge_invalid",
                    "missing_or_invalid": ["bridge_evidence_context"],
                    "bridge_errors": [f"p0_claim_evidence_invalid: {exc}"],
                }
            bridge_catalog = constrained_facts["eligible_evidence_catalog"]
            if "pack" in context["eligible_evidence_catalog"]:
                bridge_catalog = {
                    **bridge_catalog,
                    "pack": context["eligible_evidence_catalog"]["pack"],
                }
        bridge_validation = validate_pain_solution_bridge(
            bridge,
            bridge_catalog,
            require_pack_evidence=context["require_pack_evidence"],
            require_claim_grounding=resolved_contract_version == P0_CONTRACT_VERSION,
            allowed_product_evidence=factual_whitelist,
        )
        if not bridge_validation["ok"]:
            return {
                "ok": False,
                "error": "content_spec_pain_solution_bridge_invalid",
                "missing_or_invalid": bridge_validation["missing_or_invalid"],
                "bridge_errors": bridge_validation["errors"],
            }
        expected_upstream_fact_hash = context["upstream_fact_hash"]
        actual_upstream_fact_hash = str(spec.get("upstream_fact_hash") or "").strip()
        if actual_upstream_fact_hash != expected_upstream_fact_hash:
            return {
                "ok": False,
                "error": "content_spec_upstream_fact_hash_mismatch",
                "expected_upstream_fact_hash": expected_upstream_fact_hash,
                "actual_upstream_fact_hash": actual_upstream_fact_hash,
            }
        if _normalized_text(actions[0]) != _normalized_text(bridge["product_action"]):
            return {
                "ok": False,
                "error": "content_spec_product_action_bridge_mismatch",
                "product_action": str(actions[0]).strip(),
                "bridge_product_action": str(bridge["product_action"]).strip(),
            }
    normalized = _canonicalize({**dict(spec), "intent": P0_INTENT})
    return {
        "ok": True,
        "spec": normalized,
        "spec_hash": content_hash(normalized),
        "truth_snapshot_hash": truth_snapshot_hash,
        "contract_version": resolved_contract_version,
    }


def validate_candidate_pair(candidates: object) -> dict[str, Any]:
    """Require exactly two scripts that differ only in the first three seconds."""

    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        return {"ok": False, "error": "script_candidates_invalid"}
    if len(candidates) != 2 or not all(isinstance(item, Mapping) for item in candidates):
        return {"ok": False, "error": "script_candidates_must_be_two"}
    left, right = (dict(candidates[0]), dict(candidates[1]))
    missing = sorted(
        field
        for candidate in (left, right)
        for field in _CANDIDATE_REQUIRED_FIELDS
        if field not in candidate or candidate[field] in (None, "", [])
    )
    if missing:
        return {"ok": False, "error": "script_candidate_incomplete", "missing": sorted(set(missing))}
    changed = sorted(
        field
        for field in _CANDIDATE_REQUIRED_FIELDS - {"opening_hook_3s"}
        if canonical_json(left[field]) != canonical_json(right[field])
    )
    if str(left["opening_hook_3s"]).strip() == str(right["opening_hook_3s"]).strip():
        changed.append("opening_hook_3s_not_varied")
    if changed:
        return {
            "ok": False,
            "error": "script_candidate_cross_drift",
            "changed": sorted(set(changed)),
        }
    return {
        "ok": True,
        "candidate_hashes": [content_hash(left), content_hash(right)],
        "swept_variable": "opening_hook_3s",
    }


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


_P0_BEAT_FIELDS = frozenset(
    {
        "start_seconds",
        "end_seconds",
        "visual",
        "action",
        "spoken_copy",
        "sound",
    }
)
_SPEECH_UNIT_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9]+")


def _format_seconds(value: float) -> str:
    """Render deterministic timeline timestamps without needless decimal noise."""

    rounded = round(float(value), 3)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.3f}".rstrip("0").rstrip(".")


def _speech_units(value: object) -> int:
    """Count Chinese characters and Latin/number tokens for a conservative VO budget."""

    return len(_SPEECH_UNIT_RE.findall(str(value or "")))


def _normalized_spoken(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def p0_beat_windows(duration_seconds: object) -> list[dict[str, float]]:
    """Return the fixed short-beat cadence for one P0 raw video.

    P0 still makes one 12–15 second provider request.  The request is the
    complete raw video, not a static shot: 12–14 seconds use four beats and
    a 15-second video uses five, so no beat can exceed four seconds.
    """

    try:
        duration = float(duration_seconds)
    except (TypeError, ValueError):
        return []
    if not P0_MIN_DURATION_SECONDS <= duration <= P0_MAX_DURATION_SECONDS:
        return []
    beat_count = 5 if duration >= P0_MAX_DURATION_SECONDS else 4
    remaining_duration = duration - P0_HOOK_DURATION_SECONDS
    remaining_beats = beat_count - 1
    beat_duration = remaining_duration / remaining_beats
    if not P0_MIN_BEAT_SECONDS <= beat_duration <= P0_MAX_BEAT_SECONDS:
        return []

    windows: list[dict[str, float]] = []
    start = 0.0
    for index in range(beat_count):
        end = P0_HOOK_DURATION_SECONDS if index == 0 else (
            duration if index == beat_count - 1 else P0_HOOK_DURATION_SECONDS + beat_duration * index
        )
        windows.append(
            {
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
            }
        )
        start = end
    return windows


def validate_p0_beat_plan(
    beat_plan: object,
    *,
    duration_seconds: object,
    spoken_copy: object,
    expected_product_action: str | None = None,
) -> dict[str, Any]:
    """Validate the internal cut cadence of a single P0 raw-video request.

    This is deliberately not P0.2 multi-call segmentation.  It is the
    executable shot/voice cadence within the one 12–15 second P0 raw video.
    """

    windows = p0_beat_windows(duration_seconds)
    if not windows:
        return {"ok": False, "error": "beat_plan_duration_invalid"}
    if not isinstance(beat_plan, Sequence) or isinstance(beat_plan, (str, bytes, bytearray)):
        return {"ok": False, "error": "beat_plan_invalid"}
    if len(beat_plan) != len(windows):
        return {
            "ok": False,
            "error": "beat_plan_count_invalid",
            "expected": len(windows),
            "actual": len(beat_plan),
        }

    normalized_beats: list[dict[str, Any]] = []
    rendered_spoken: list[str] = []
    for index, (raw_beat, window) in enumerate(zip(beat_plan, windows), start=1):
        if not isinstance(raw_beat, Mapping):
            return {"ok": False, "error": "beat_plan_entry_invalid", "beat_no": index}
        actual_fields = set(raw_beat)
        if actual_fields != _P0_BEAT_FIELDS:
            return {
                "ok": False,
                "error": "beat_plan_entry_schema_invalid",
                "beat_no": index,
                "missing": sorted(_P0_BEAT_FIELDS - actual_fields),
                "extra": sorted(actual_fields - _P0_BEAT_FIELDS),
            }
        try:
            start = float(raw_beat["start_seconds"])
            end = float(raw_beat["end_seconds"])
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "error": "beat_plan_timing_invalid", "beat_no": index}
        if (
            abs(start - window["start_seconds"]) > 0.02
            or abs(end - window["end_seconds"]) > 0.02
            or end <= start
            or end - start > P0_MAX_BEAT_SECONDS + 0.02
        ):
            return {
                "ok": False,
                "error": "beat_plan_timing_invalid",
                "beat_no": index,
                "expected_start": window["start_seconds"],
                "expected_end": window["end_seconds"],
            }
        visual = raw_beat.get("visual")
        action = raw_beat.get("action")
        sound = raw_beat.get("sound")
        if not all(isinstance(value, str) and value.strip() for value in (visual, action, sound)):
            return {"ok": False, "error": "beat_plan_content_invalid", "beat_no": index}
        spoken = raw_beat.get("spoken_copy")
        if not isinstance(spoken, str):
            return {"ok": False, "error": "beat_plan_spoken_invalid", "beat_no": index}
        # The swept opening hook is visual/on-screen in P0.  Starting VO only
        # after the hook keeps the A/B variable isolated and preserves a real
        # first-three-second rhythm instead of racing a full sentence.
        if index == 1 and spoken.strip():
            return {"ok": False, "error": "beat_plan_hook_spoken_not_allowed", "beat_no": index}
        max_units = math.floor((end - start) * P0_MAX_SPOKEN_UNITS_PER_SECOND)
        spoken_units = _speech_units(spoken)
        if spoken_units > max_units:
            return {
                "ok": False,
                "error": "beat_plan_spoken_too_long",
                "beat_no": index,
                "spoken_units": spoken_units,
                "max_units": max_units,
            }
        normalized = {
            "start_seconds": round(start, 3),
            "end_seconds": round(end, 3),
            "visual": visual.strip(),
            "action": action.strip(),
            "spoken_copy": spoken.strip(),
            "sound": sound.strip(),
        }
        normalized_beats.append(normalized)
        rendered_spoken.append(normalized["spoken_copy"])

    if _normalized_spoken("".join(rendered_spoken)) != _normalized_spoken(spoken_copy):
        return {"ok": False, "error": "beat_plan_spoken_copy_mismatch"}
    if expected_product_action and _normalized_text(expected_product_action) not in _normalized_text(
        " ".join(beat["action"] for beat in normalized_beats)
    ):
        return {"ok": False, "error": "beat_plan_product_action_missing"}
    return {"ok": True, "beats": normalized_beats, "beat_count": len(normalized_beats)}


def _render_p0_beat_timeline(*, beats: Sequence[Mapping[str, Any]], opening_hook_3s: str) -> str:
    """Render the structured P0 beat plan into the strict shared prompt lane."""

    lines = [
        "同一条 12–15 秒 raw 视频必须按以下连续短节拍完成；同一厨房、同一人物，"
        "但每个节拍都要有可见的景别、动作或构图变化，任何一个静态镜头不得超过 4 秒。"
    ]
    for index, beat in enumerate(beats, start=1):
        visual = opening_hook_3s if index == 1 else str(beat["visual"])
        spoken = str(beat["spoken_copy"]).strip()
        voice_instruction = f"；口播：{spoken}" if spoken else "；只保留环境声和画面动作，不口播"
        lines.append(
            f"{_format_seconds(float(beat['start_seconds']))}-{_format_seconds(float(beat['end_seconds']))}秒："
            f"画面：{visual}；动作：{beat['action']}；声音：{beat['sound']}{voice_instruction}。"
        )
    return "\n".join(lines)


def validate_script_candidate(
    candidate: object,
    *,
    spec: Mapping[str, Any],
    truth_snapshot: Mapping[str, Any],
    content_spec_hash: str,
    truth_snapshot_hash: str,
) -> dict[str, Any]:
    """Validate one candidate against the frozen P0 truth and ContentSpec.

    This gate intentionally only checks deterministic things: exact lineage
    hashes, duration, the one allowed product action, facts, and forbidden
    wording.  Narrative quality stays with the independent critic rather than
    pretending a string rule can judge a video idea.
    """

    if not isinstance(candidate, Mapping):
        return {"ok": False, "error": "script_candidate_invalid"}
    normalized = _canonicalize(dict(candidate))
    missing = [
        field
        for field in _CANDIDATE_REQUIRED_FIELDS
        if field not in normalized or normalized[field] in (None, "", [])
    ]
    if missing:
        return {
            "ok": False,
            "error": "script_candidate_incomplete",
            "missing": sorted(set(missing)),
        }
    if normalized["content_spec_hash"] != content_spec_hash:
        return {"ok": False, "error": "script_content_spec_hash_mismatch"}
    if normalized["truth_snapshot_hash"] != truth_snapshot_hash:
        return {"ok": False, "error": "script_truth_snapshot_hash_mismatch"}

    try:
        duration = float(normalized["duration_seconds"])
        expected_duration = float(spec["duration_seconds"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "script_duration_invalid"}
    if duration != expected_duration:
        return {
            "ok": False,
            "error": "script_duration_mismatch",
            "expected": expected_duration,
            "actual": duration,
        }

    actions = _string_list(spec.get("product_actions"))
    expected_action = actions[0] if len(actions) == 1 else ""
    if not expected_action or _normalized_text(normalized["product_action"]) != _normalized_text(expected_action):
        return {
            "ok": False,
            "error": "script_product_action_mismatch",
            "expected": expected_action,
        }
    beat_gate = validate_p0_beat_plan(
        normalized["beat_plan"],
        duration_seconds=duration,
        spoken_copy=normalized["spoken_copy"],
        expected_product_action=expected_action,
    )
    if not beat_gate["ok"]:
        return {
            "ok": False,
            "error": "script_beat_plan_invalid",
            "reason": beat_gate["error"],
            **{key: value for key, value in beat_gate.items() if key not in {"ok", "error"}},
        }
    rendered = " ".join(
        str(normalized[field]).strip()
        for field in ("opening_hook_3s", "body", "spoken_copy")
    )
    if _normalized_text(expected_action) not in _normalized_text(rendered):
        return {"ok": False, "error": "script_product_action_not_rendered"}

    claims = _string_list(normalized["factual_claims"])
    spec_whitelist = {_normalized_text(item) for item in _string_list(spec.get("factual_whitelist"))}
    facts = truth_snapshot.get("facts") if isinstance(truth_snapshot.get("facts"), Mapping) else {}
    truth_whitelist = {_normalized_text(item) for item in _string_list(facts.get("whitelist"))}
    allowed = spec_whitelist & truth_whitelist
    invalid_claims = [claim for claim in claims if _normalized_text(claim) not in allowed]
    if invalid_claims:
        return {
            "ok": False,
            "error": "script_fact_violation",
            "invalid_claims": invalid_claims,
        }

    forbidden_hits = [
        item
        for item in _string_list(spec.get("forbidden_claims"))
        if _normalized_text(item) and _normalized_text(item) in _normalized_text(rendered)
    ]
    if forbidden_hits:
        return {
            "ok": False,
            "error": "script_forbidden_claim",
            "hits": forbidden_hits,
        }
    return {
        "ok": True,
        "candidate": normalized,
        "candidate_hash": content_hash(normalized),
    }


def deterministic_script_gate(
    candidate: object,
    *,
    spec: Mapping[str, Any],
    truth_snapshot: Mapping[str, Any],
    content_spec_hash: str,
    truth_snapshot_hash: str,
) -> dict[str, Any]:
    """Return a persisted, explainable pass/fail record for one candidate."""

    checked = validate_script_candidate(
        candidate,
        spec=spec,
        truth_snapshot=truth_snapshot,
        content_spec_hash=content_spec_hash,
        truth_snapshot_hash=truth_snapshot_hash,
    )
    if not checked["ok"]:
        detail = {key: value for key, value in checked.items() if key not in {"ok", "error"}}
        return {
            "status": "failed",
            "reason_codes": [checked["error"]],
            "detail": detail,
        }
    return {
        "status": "passed",
        "reason_codes": [],
        "candidate_hash": checked["candidate_hash"],
    }


def build_p0_prompt_source(
    *,
    candidate: Mapping[str, Any],
    spec: Mapping[str, Any],
    truth_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the shared executable-prompt schema from P0-only source facts.

    The text is intentionally descriptive enough for the shared Seedance
    compiler's duration budget, but it never adds product claims beyond the
    already validated candidate facts.
    """

    sku = truth_snapshot.get("sku") if isinstance(truth_snapshot.get("sku"), Mapping) else {}
    audience = (
        truth_snapshot.get("audience_record")
        if isinstance(truth_snapshot.get("audience_record"), Mapping)
        else {}
    )
    product_name = str(sku.get("name") or "产品").strip()
    audience_name = str(audience.get("name") or "目标人群").strip()
    action = str(candidate["product_action"]).strip()
    hook = str(candidate["opening_hook_3s"]).strip()
    body = str(candidate["body"]).strip()
    spoken = str(candidate["spoken_copy"]).strip()
    duration_value = float(spec["duration_seconds"])
    duration = int(duration_value)
    beat_gate = validate_p0_beat_plan(
        candidate.get("beat_plan"),
        duration_seconds=duration_value,
        spoken_copy=spoken,
        expected_product_action=action,
    )
    if not beat_gate["ok"]:
        raise ValueError(f"p0_beat_plan_invalid:{beat_gate['error']}")
    beats = beat_gate["beats"]
    result = "完成一顿热饭"
    visual_constraints = "；".join(_string_list(spec.get("visual_constraints")))
    audio_constraints = "；".join(_string_list(spec.get("audio_constraints")))
    references = truth_snapshot.get("product_reference_manifest")
    reference_assets = references.get("assets") if isinstance(references, Mapping) else []
    reference_ids = "、".join(
        str(item.get("id"))
        for item in reference_assets
        if isinstance(item, Mapping) and str(item.get("id") or "").strip()
    ) or "已冻结的产品参考图"
    character = f"一位属于{audience_name}的普通成年人"

    source = {
        "identity_product_anchor": (
            f"{character}，在真实、克制的家庭厨房里使用{product_name}。人物是日常做饭者，"
            "不使用明星脸或特定真实人物，不改变产品包装、瓶型、标签、颜色和文字。"
        ),
        "reference_instruction": (
            f"仅以冻结的产品参考图（{reference_ids}）作为产品外观依据。每次产品入镜都保持"
            f"{product_name}与参考图一致；不补写参考图之外的配料、认证、价格、销量或促销信息。"
        ),
        "product_solution_action": (
            f"核心动作只有一个：{action}。动作必须由人物完整执行，镜头给到产品、手部和菜肴的"
            "连续关系，不能把产品替换成泛化调味瓶，也不能跳剪成无法辨认的摆拍。"
        ),
        "timeline": (
            f"0-3秒：{hook}。3-{duration}秒：{body}，人物在自然做饭节奏中{action}，"
            f"随后端起或摆好成品，{result}；口播为“{spoken}”。"
        ),
        "scene_detail": (
            "竖屏9:16，单人、单场景、连续可理解的日常厨房叙事。开头先给人物正在面对的做饭时刻，"
            "随后以中近景展示手部、锅具和产品的空间关系，再回到人物与成品。镜头稳定、景别变化有因果，"
            "不出现第二人物、不换场、不做夸张表演，不用无法验证的特写文字替代真实产品。"
            f"画面约束：{visual_constraints or '自然家用厨房、产品清晰可辨'}。"
        ),
        "sound_detail": (
            f"保留自然厨房环境声，口播清楚、与画面同步，完整表达“{spoken}”。"
            f"音频约束：{audio_constraints or '不使用误导性旁白'}。如模型生成原生音频，优先保留；"
            "若原生音频缺失，后期只能接入经明确提供和校验的真实音频源，不能用静音冒充成片。"
        ),
        "decorative_detail": (
            "光线为自然暖白，材质真实，色彩克制，字幕留出安全区但不遮挡产品。剪辑只服务于看清"
            "人物为什么做、如何使用产品、做完后的结果；不叠加价格、优惠、销量、疗效、绝对化比较或"
            "与事实无关的视觉符号。"
        ),
        "negative": (
            "禁止产品变形、包装文字错乱、多人、多场景、产品凭空消失、与产品无关的夸张功效、"
            "价格促销、销量数字、伪造资质、快闪黑屏、长时间静帧、静音终片。"
        ),
        "required_anchors": {
            "character": character,
            "product": product_name,
            "action": action,
            "result": result,
        },
    }
    source["timeline"] = _render_p0_beat_timeline(beats=beats, opening_hook_3s=hook)
    source["scene_detail"] = (
        "竖屏 9:16、单人、同一厨房。"
        f"同场景不等于长镜头，必须按 timeline 的短节拍切换景别或动作，结尾{result}。"
        f"画面约束：{visual_constraints or '自然家用厨房、产品清晰可辨'}。"
    )
    source["sound_detail"] = (
        "保留厨房环境声；口播只按 timeline 中逐拍列出的短句进入，"
        f"不得把整段口播压成一条长句。音频约束：{audio_constraints or '口播清晰'}。"
    )
    source["negative"] = (
        "禁止产品变形、包装文字错乱、多人、多场景、价格促销、销量数字、伪造资质，"
        "以及任一静态镜头持续超过 4 秒。"
    )
    source["decorative_detail"] = "自然暖白光、真实材质、色彩克制；字幕留安全区且不遮挡产品。"
    return validate_prompt_source_schema(source)


def build_generation_approval_payload(
    *,
    production_order_id: str,
    prompt_source_hash: str,
    prompt_source: Mapping[str, Any],
    reference_manifest: Mapping[str, Any],
    requested_provider: str,
    requested_model: str,
    duration_seconds: object,
    final_prompt: str,
) -> dict[str, Any]:
    """Create the exact, replayable payload that a human approves for billing."""

    preview = validate_prompt_preview(
        prompt_source,
        duration_seconds=duration_seconds,
        requested_provider=requested_provider,
        requested_model=requested_model,
    )
    # The prompt source is normally stored separately from the reference
    # manifest.  Callers may pass it in the manifest for lightweight pure
    # validation, but the approval hash itself always binds the final prompt.
    if not str(production_order_id or "").strip() or not str(prompt_source_hash or "").strip():
        return {"ok": False, "error": "generation_approval_payload_invalid"}
    try:
        duration = float(duration_seconds)
    except (TypeError, ValueError):
        duration = -1
    if (
        not preview.get("ok")
        or
        requested_provider != "seedance"
        or not str(requested_model).strip()
        or not P0_MIN_DURATION_SECONDS <= duration <= P0_MAX_DURATION_SECONDS
        or not str(final_prompt).strip()
    ):
        return {"ok": False, "error": "generation_approval_payload_invalid"}
    payload = {
        "contract_version": P0_CONTRACT_VERSION,
        "production_order_id": str(production_order_id),
        "prompt_source_hash": str(prompt_source_hash),
        "reference_manifest": _canonicalize(reference_manifest),
        "requested_provider": requested_provider,
        "requested_model": requested_model.strip(),
        "duration_seconds": duration,
        "aspect_ratio": "9:16",
        "generate_audio": True,
        "watermark": False,
        "final_prompt": str(final_prompt).strip(),
    }
    return {
        "ok": True,
        "approval_payload": payload,
        "approval_hash": content_hash(payload),
        "prompt_preview_valid": bool(preview.get("ok")),
    }


def validate_media_probe(
    probe: object,
    *,
    require_audio: bool,
    expected_duration_seconds: object,
) -> dict[str, Any]:
    """Interpret an ``ffprobe`` JSON result without shelling out in tests."""

    if not isinstance(probe, Mapping):
        return {"ok": False, "error": "media_probe_invalid"}
    streams = probe.get("streams")
    format_data = probe.get("format")
    if not isinstance(streams, Sequence) or not isinstance(format_data, Mapping):
        return {"ok": False, "error": "media_probe_invalid"}
    video_stream = next(
        (item for item in streams if isinstance(item, Mapping) and item.get("codec_type") == "video"),
        None,
    )
    audio_stream = next(
        (item for item in streams if isinstance(item, Mapping) and item.get("codec_type") == "audio"),
        None,
    )
    failed: list[str] = []
    if not isinstance(video_stream, Mapping):
        failed.append("video_stream_missing")
        width = height = 0
    else:
        width = int(video_stream.get("width") or 0)
        height = int(video_stream.get("height") or 0)
        if width <= 0 or height <= 0:
            failed.append("video_dimensions_missing")
        elif abs((width / height) - (9 / 16)) > 0.02:
            failed.append("aspect_ratio_not_9_16")
    if require_audio and not isinstance(audio_stream, Mapping):
        failed.append("audio_stream_missing")
    try:
        duration = float(format_data.get("duration"))
        expected = float(expected_duration_seconds)
    except (TypeError, ValueError):
        duration = expected = -1
    if not P0_MIN_DURATION_SECONDS <= duration <= P0_MAX_DURATION_SECONDS:
        failed.append("duration_out_of_p0_range")
    elif expected > 0 and abs(duration - expected) > 0.75:
        failed.append("duration_mismatch")
    return {
        "ok": not failed,
        "failed_checks": failed,
        "video": {"width": width, "height": height},
        "has_audio": isinstance(audio_stream, Mapping),
        "duration_seconds": duration,
    }


def format_srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds_part, milliseconds = divmod(milliseconds, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds_part:02},{milliseconds:03}"


def build_subtitle_timeline(
    *, spoken_copy: str, duration_seconds: object, beat_plan: object
) -> dict[str, Any]:
    """Create exact-text subtitles that follow P0's short internal beats."""

    text = str(spoken_copy or "").strip()
    beat_gate = validate_p0_beat_plan(
        beat_plan,
        duration_seconds=duration_seconds,
        spoken_copy=text,
    )
    if not beat_gate["ok"]:
        return {"ok": False, "error": "subtitle_beat_plan_invalid", "reason": beat_gate["error"]}
    entries = [
        {
            "start": beat["start_seconds"],
            "end": beat["end_seconds"],
            "text": beat["spoken_copy"],
        }
        for beat in beat_gate["beats"]
        if beat["spoken_copy"]
    ]
    if not entries:
        return {"ok": False, "error": "subtitle_entries_missing"}
    srt = "\n".join(
        f"{index}\n{format_srt_timestamp(float(entry['start']))} --> {format_srt_timestamp(float(entry['end']))}\n{entry['text']}\n"
        for index, entry in enumerate(entries, start=1)
    )
    return {
        "ok": True,
        "entries": entries,
        "srt": srt,
        "timeline_hash": content_hash(
            {"duration_seconds": float(duration_seconds), "entries": entries}
        ),
    }


def validate_subtitle_timeline(
    entries: object,
    *,
    duration_seconds: object,
    spoken_copy: str,
    beat_plan: object,
) -> dict[str, Any]:
    beat_gate = validate_p0_beat_plan(
        beat_plan,
        duration_seconds=duration_seconds,
        spoken_copy=spoken_copy,
    )
    if not beat_gate["ok"]:
        return {"ok": False, "error": "subtitle_beat_plan_invalid", "reason": beat_gate["error"]}
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)) or not entries:
        return {"ok": False, "error": "subtitle_entries_missing"}
    expected_entries = [beat for beat in beat_gate["beats"] if beat["spoken_copy"]]
    if len(entries) != len(expected_entries):
        return {
            "ok": False,
            "error": "subtitle_beat_count_mismatch",
            "expected": len(expected_entries),
            "actual": len(entries),
        }
    extracted: list[str] = []
    for index, (entry, beat) in enumerate(zip(entries, expected_entries), start=1):
        if not isinstance(entry, Mapping):
            return {"ok": False, "error": "subtitle_entry_invalid", "beat_no": index}
        try:
            start = float(entry["start"])
            end = float(entry["end"])
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "error": "subtitle_timing_invalid", "beat_no": index}
        text = str(entry.get("text") or "").strip()
        if (
            abs(start - float(beat["start_seconds"])) > 0.02
            or abs(end - float(beat["end_seconds"])) > 0.02
            or text != str(beat["spoken_copy"])
        ):
            return {"ok": False, "error": "subtitle_beat_alignment_invalid", "beat_no": index}
        extracted.append(text)
    if _normalized_spoken("".join(extracted)) != _normalized_spoken(spoken_copy):
        return {"ok": False, "error": "subtitle_text_mismatch"}
    return {"ok": True, "beat_count": len(expected_entries)}


def validate_prompt_preview(
    source: object,
    *, duration_seconds: object,
    requested_provider: str,
    requested_model: str,
) -> dict[str, Any]:
    """Validate a provider-neutral prompt source before any paid API call."""

    try:
        normalized = validate_prompt_source_schema(source)
    except PromptSourceSchemaError as exc:
        return {"ok": False, "error": "prompt_source_invalid", "field": exc.field}
    try:
        duration = float(duration_seconds)
    except (TypeError, ValueError):
        duration = -1
    if not P0_MIN_DURATION_SECONDS <= duration <= P0_MAX_DURATION_SECONDS:
        return {"ok": False, "error": "prompt_duration_invalid"}
    if requested_provider != "seedance" or not str(requested_model).strip():
        return {"ok": False, "error": "p0_route_not_supported"}
    payload = {
        "schema_version": P0_CONTRACT_VERSION,
        "duration_seconds": duration,
        "prompt_source": normalized,
        "requested_provider": requested_provider,
        "requested_model": requested_model.strip(),
    }
    return {"ok": True, "preview": payload, "preview_hash": content_hash(payload)}


def can_transition(*, current_status: str, next_status: str) -> bool:
    return next_status in _ALLOWED_TRANSITIONS.get(current_status, set())


def validate_transition(*, current_status: str, next_status: str) -> dict[str, Any]:
    if current_status not in ORDER_STATUSES or next_status not in ORDER_STATUSES:
        return {"ok": False, "error": "production_order_status_invalid"}
    if not can_transition(current_status=current_status, next_status=next_status):
        return {
            "ok": False,
            "error": "production_order_transition_invalid",
            "current_status": current_status,
            "next_status": next_status,
        }
    return {"ok": True}


__all__ = [
    "ORDER_STATUSES",
    "P0_CONTRACT_VERSION",
    "P0_PACK_REQUIRED_CONTRACT_VERSIONS",
    "P0_HOOK_DURATION_SECONDS",
    "P0_INTENT",
    "P0_MAX_DURATION_SECONDS",
    "P0_MAX_BEAT_SECONDS",
    "P0_MAX_SPOKEN_UNITS_PER_SECOND",
    "P0_MIN_BEAT_SECONDS",
    "P0_MIN_DURATION_SECONDS",
    "P0_STRONG_LINEAGE_CONTRACT_VERSIONS",
    "P0_V2_CONTRACT_VERSION",
    "P0_V3_CONTRACT_VERSION",
    "build_generation_approval_payload",
    "build_p0_prompt_source",
    "build_subtitle_timeline",
    "can_transition",
    "canonical_json",
    "content_hash",
    "deterministic_script_gate",
    "format_srt_timestamp",
    "p0_beat_windows",
    "p0_idempotency_key",
    "validate_media_probe",
    "validate_candidate_pair",
    "validate_content_spec",
    "validate_prompt_preview",
    "validate_p0_beat_plan",
    "validate_script_candidate",
    "validate_subtitle_timeline",
    "validate_transition",
    "validate_truth_snapshot",
]
