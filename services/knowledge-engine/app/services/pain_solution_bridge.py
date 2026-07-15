"""Pure helpers for validating and parsing planting pain-solution bridges.

This module deliberately has no database or provider dependencies.  It defines
the deterministic boundary between upstream facts and the two bridge variants
used by the planting workflow.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence, Set
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.database import get_pool
from app.services import pipeline_lineage


_TEXT_FIELDS = (
    "audience_segment",
    "trigger_scene",
    "pain_point",
    "pain_consequence",
    "product_action",
    "visible_result",
    "belief_shift",
    "relevance_module",
    "justification_module",
)
_EVIDENCE_FIELDS = (
    "portrait_evidence",
    "pack_calibration_evidence",
    "product_evidence",
)
_REQUIRED_FIELDS = frozenset((*_TEXT_FIELDS, *_EVIDENCE_FIELDS))
_EVIDENCE_ENTRY_KEYS = {
    "portrait_evidence": frozenset({"source", "field", "value"}),
    "pack_calibration_evidence": frozenset({"field", "value"}),
    "product_evidence": frozenset({"source", "field", "value"}),
}
_SKU_CATALOG_FIELDS = (
    "id",
    "name",
    "category",
    "price_min",
    "price_max",
    "specifications",
    "owner_selling_points",
    "owner_notes",
    "platform_status",
)
_RECORD_CATALOG_FIELDS = (
    "id",
    "audience_run_id",
    "matrix_run_id",
    "sku_id",
    "ordinal",
    "name",
    "kb_doc",
    "kb_section",
    "kb_chunk_text",
    "match_reasons",
    "layer_tags",
    "raw_md_segment",
    "status",
    "selected_for_pack",
)
_LEGACY_CATALOG_FIELDS = {
    "sku": frozenset(_SKU_CATALOG_FIELDS),
    "matrix": frozenset({"matrix_md"}),
    "record": frozenset(_RECORD_CATALOG_FIELDS),
    "portrait": frozenset({"portrait_md"}),
    "pack": frozenset({"pack_md", "dmp_tags"}),
}
_VARIABLE_PAIR_FIELDS = frozenset(
    ("trigger_scene", "pain_point", "pain_consequence")
)
_FIXED_PAIR_FIELDS = (
    "audience_segment",
    "portrait_evidence",
    "pack_calibration_evidence",
    "product_action",
    "visible_result",
    "product_evidence",
    "belief_shift",
    "relevance_module",
    "justification_module",
)
_MISSING_LITERALS = frozenset(
    {
        "-",
        "--",
        "missing",
        "n/a",
        "na",
        "nil",
        "none",
        "null",
        "tbd",
        "unknown",
        "不详",
        "待定",
        "待补",
        "待补充",
        "暂无",
        "未知",
        "未提供",
        "无",
        "缺失",
    }
)
_ATTRIBUTE_ONLY_SEGMENT_RE = re.compile(
    r"(?:年龄[:：]?)?\d{1,2}(?:-|–|—|~|～|至|到)\d{1,2}岁?(?:女性|男性)?"
    r"|(?:一|二|三|四|五|新一|新二)线城市(?:女性|男性|人群|用户)?"
    r"|(?:女性|男性|宝妈|白领|学生|银发人群)"
    r"|(?:高|中|低)消费力"
)
_ATTRIBUTE_LIST_SEPARATOR_RE = re.compile(r"[,，、;/；|]+")
_FENCED_JSON_RE = re.compile(
    r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL
)


def _canonicalize(value: Any, *, path: str = "facts") -> Any:
    """Convert supported values into a deterministic JSON-compatible tree."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError(f"unsupported non-finite float at {path}")
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"mapping keys must be strings at {path}")
            normalized[key] = _canonicalize(item, path=f"{path}.{key}")
        return normalized
    if isinstance(value, Set) and not isinstance(value, (str, bytes, bytearray)):
        items = [_canonicalize(item, path=f"{path}[]") for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [
            _canonicalize(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise TypeError(f"unsupported object at {path}: {type(value).__name__}")


def canonical_upstream_fact_hash(facts: Any) -> str:
    """Return a canonical SHA-256 digest for supported upstream fact values."""

    payload = json.dumps(
        _canonicalize(facts),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_uuid(value: Any) -> str | None:
    try:
        return str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError):
        return None


def _normalize_json_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return value
    return parsed if isinstance(parsed, (dict, list)) else value


def _stable_json(value: Any) -> str:
    return json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _stable_field_text(value: Any) -> str:
    return value if isinstance(value, str) else _stable_json(value)


def _stable_field_catalog(
    values: Mapping[str, Any],
    fields: Sequence[str],
) -> dict[str, str]:
    return {field: _stable_field_text(values.get(field)) for field in fields}


def _lineage_failure(
    reason: str,
    *,
    passed_checks: list[str],
    lineage: Mapping[str, Any],
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "upstream_lineage_incomplete",
        "reason": reason,
        "passed_checks": list(passed_checks),
        "lineage": dict(lineage),
        "detail": dict(detail or {}),
    }


def _stable_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {field: record.get(field) for field in _RECORD_CATALOG_FIELDS}


async def load_planting_bridge_context(
    sku_id: str,
    audience_record_id: str,
    portrait_id: str,
    audience_pack_id: str | None = None,
) -> dict[str, Any]:
    """Load one explicit, adopted lineage for planting bridge generation.

    The caller must supply record and portrait IDs (and optionally a pack ID).
    This function never selects a latest or implicit upstream artifact.
    """

    passed_checks: list[str] = []
    lineage: dict[str, Any] = {"sku_id": sku_id}

    pool = get_pool()
    sku_row = await pool.fetchrow(
        "SELECT id,name,category,price_min,price_max,specifications,"
        "owner_selling_points,owner_notes,platform_status "
        "FROM mvp_sku WHERE id=$1",
        sku_id,
    )
    if not sku_row:
        return _lineage_failure(
            "sku_not_found",
            passed_checks=passed_checks,
            lineage=lineage,
            detail={"sku_id": sku_id},
        )
    passed_checks.append("sku_exists")

    canonical_record_id = _canonical_uuid(audience_record_id)
    if canonical_record_id is None:
        return _lineage_failure(
            "invalid_audience_record_id",
            passed_checks=passed_checks,
            lineage=lineage,
            detail={"audience_record_id": audience_record_id},
        )
    lineage["audience_record_id"] = canonical_record_id
    passed_checks.append("audience_record_id_valid")

    record = await pipeline_lineage.get_audience_record(canonical_record_id)
    if record is None:
        return _lineage_failure(
            "record_not_found",
            passed_checks=passed_checks,
            lineage=lineage,
            detail={"audience_record_id": canonical_record_id},
        )
    passed_checks.append("audience_record_exists")
    if record.get("sku_id") != sku_id:
        return _lineage_failure(
            "record_sku_mismatch",
            passed_checks=passed_checks,
            lineage=lineage,
            detail={"expected_sku_id": sku_id, "actual_sku_id": record.get("sku_id")},
        )
    passed_checks.append("audience_record_sku_matches")
    if not (
        record.get("status") == "adopted"
        or record.get("selected_for_pack") is True
    ):
        return _lineage_failure(
            "record_not_eligible",
            passed_checks=passed_checks,
            lineage=lineage,
            detail={
                "status": record.get("status"),
                "selected_for_pack": record.get("selected_for_pack"),
            },
        )
    passed_checks.append("audience_record_eligible")

    canonical_matrix_id = _canonical_uuid(record.get("matrix_run_id"))
    canonical_run_id = _canonical_uuid(record.get("audience_run_id"))
    lineage["matrix_run_id"] = canonical_matrix_id or record.get("matrix_run_id")
    lineage["audience_run_id"] = canonical_run_id or record.get("audience_run_id")
    if canonical_matrix_id is None:
        return _lineage_failure(
            "matrix_not_found",
            passed_checks=passed_checks,
            lineage=lineage,
            detail={"matrix_run_id": record.get("matrix_run_id")},
        )

    matrix = await pipeline_lineage.get_matrix_run(canonical_matrix_id)
    if matrix is None:
        return _lineage_failure(
            "matrix_not_found",
            passed_checks=passed_checks,
            lineage=lineage,
            detail={"matrix_run_id": canonical_matrix_id},
        )
    passed_checks.append("matrix_exists")
    if matrix.get("status") != "adopted":
        return _lineage_failure(
            "matrix_not_adopted",
            passed_checks=passed_checks,
            lineage=lineage,
            detail={"status": matrix.get("status")},
        )
    passed_checks.append("matrix_adopted")
    if (
        _canonical_uuid(matrix.get("id")) != canonical_matrix_id
        or matrix.get("sku_id") != sku_id
    ):
        return _lineage_failure(
            "matrix_lineage_mismatch",
            passed_checks=passed_checks,
            lineage=lineage,
            detail={
                "expected": {"id": canonical_matrix_id, "sku_id": sku_id},
                "actual": {"id": matrix.get("id"), "sku_id": matrix.get("sku_id")},
            },
        )
    passed_checks.append("matrix_lineage_matches")

    canonical_portrait_id = _canonical_uuid(portrait_id)
    if canonical_portrait_id is None:
        return _lineage_failure(
            "invalid_portrait_id",
            passed_checks=passed_checks,
            lineage=lineage,
            detail={"portrait_id": portrait_id},
        )
    lineage["portrait_id"] = canonical_portrait_id
    passed_checks.append("portrait_id_valid")

    portrait = await pipeline_lineage.get_audience_portrait(canonical_portrait_id)
    if portrait is None:
        return _lineage_failure(
            "portrait_not_found",
            passed_checks=passed_checks,
            lineage=lineage,
            detail={"portrait_id": canonical_portrait_id},
        )
    passed_checks.append("portrait_exists")
    if portrait.get("status") != "adopted":
        return _lineage_failure(
            "portrait_not_adopted",
            passed_checks=passed_checks,
            lineage=lineage,
            detail={"status": portrait.get("status")},
        )
    passed_checks.append("portrait_adopted")

    expected_lineage = {
        "sku_id": sku_id,
        "audience_record_id": canonical_record_id,
        "audience_run_id": canonical_run_id,
        "matrix_run_id": canonical_matrix_id,
    }
    actual_portrait_lineage = {
        "sku_id": portrait.get("sku_id"),
        "audience_record_id": _canonical_uuid(portrait.get("audience_record_id")),
        "audience_run_id": _canonical_uuid(portrait.get("audience_run_id")),
        "matrix_run_id": _canonical_uuid(portrait.get("matrix_run_id")),
    }
    if actual_portrait_lineage != expected_lineage:
        return _lineage_failure(
            "portrait_lineage_mismatch",
            passed_checks=passed_checks,
            lineage=lineage,
            detail={"expected": expected_lineage, "actual": actual_portrait_lineage},
        )
    passed_checks.append("portrait_lineage_matches")

    pack: Mapping[str, Any] | None = None
    canonical_pack_id: str | None = None
    if audience_pack_id is not None:
        canonical_pack_id = _canonical_uuid(audience_pack_id)
        if canonical_pack_id is None:
            return _lineage_failure(
                "invalid_audience_pack_id",
                passed_checks=passed_checks,
                lineage=lineage,
                detail={"audience_pack_id": audience_pack_id},
            )
        lineage["audience_pack_id"] = canonical_pack_id
        passed_checks.append("audience_pack_id_valid")
        pack = await pipeline_lineage.get_audience_pack(canonical_pack_id)
        if pack is None:
            return _lineage_failure(
                "pack_not_found",
                passed_checks=passed_checks,
                lineage=lineage,
                detail={"audience_pack_id": canonical_pack_id},
            )
        passed_checks.append("pack_exists")
        if pack.get("status") != "adopted":
            return _lineage_failure(
                "pack_not_adopted",
                passed_checks=passed_checks,
                lineage=lineage,
                detail={"status": pack.get("status")},
            )
        passed_checks.append("pack_adopted")
        actual_pack_lineage = {
            "sku_id": pack.get("sku_id"),
            "audience_record_id": _canonical_uuid(pack.get("audience_record_id")),
            "audience_run_id": _canonical_uuid(pack.get("audience_run_id")),
            "matrix_run_id": _canonical_uuid(pack.get("matrix_run_id")),
        }
        if actual_pack_lineage != expected_lineage:
            return _lineage_failure(
                "pack_lineage_mismatch",
                passed_checks=passed_checks,
                lineage=lineage,
                detail={"expected": expected_lineage, "actual": actual_pack_lineage},
            )
        passed_checks.append("pack_lineage_matches")

    sku_source = dict(sku_row)
    sku_facts = {
        "id": sku_source.get("id"),
        "name": sku_source.get("name"),
        "category": sku_source.get("category"),
        "price_min": sku_source.get("price_min"),
        "price_max": sku_source.get("price_max"),
        "specifications": _normalize_json_text(sku_source.get("specifications")),
        "owner_selling_points": _normalize_json_text(
            sku_source.get("owner_selling_points")
        ),
        "owner_notes": sku_source.get("owner_notes"),
        "platform_status": sku_source.get("platform_status"),
    }
    record_evidence = _stable_record(record)
    pack_calibration = (
        {
            "id": canonical_pack_id,
            "pack_md": pack.get("pack_md"),
            "dmp_tags": pack.get("dmp_tags"),
        }
        if pack is not None
        else None
    )
    facts = {
        "lineage": {
            "sku_id": sku_id,
            "matrix_run_id": canonical_matrix_id,
            "audience_run_id": canonical_run_id,
            "audience_record_id": canonical_record_id,
            "portrait_id": canonical_portrait_id,
            "audience_pack_id": canonical_pack_id,
        },
        "sku_facts": sku_facts,
        "matrix_evidence": {
            "id": canonical_matrix_id,
            "matrix_md": matrix.get("matrix_md"),
        },
        "portrait_record_evidence": {
            "record": record_evidence,
            "portrait": {
                "id": canonical_portrait_id,
                "portrait_md": portrait.get("portrait_md"),
            },
        },
        "pack_calibration": pack_calibration,
        "eligible_evidence_catalog": {
            "sku": _stable_field_catalog(sku_facts, _SKU_CATALOG_FIELDS),
            "matrix": {"matrix_md": matrix.get("matrix_md") or ""},
            "record": _stable_field_catalog(
                record_evidence,
                _RECORD_CATALOG_FIELDS,
            ),
            "portrait": {"portrait_md": portrait.get("portrait_md") or ""},
        },
        "pack_calibration_catalog": (
            {
                "pack_md": pack.get("pack_md") or "",
                "dmp_tags": _stable_field_text(pack.get("dmp_tags")),
            }
            if pack is not None
            else {}
        ),
    }
    return {
        "ok": True,
        "facts": facts,
        "upstream_fact_hash": canonical_upstream_fact_hash(facts),
    }


def _is_meaningful_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return bool(stripped) and stripped.casefold() not in _MISSING_LITERALS


def _normalized_slogan(value: str) -> str:
    return "".join(
        character.casefold()
        for character in unicodedata.normalize("NFKC", value)
        if not character.isspace()
        and not unicodedata.category(character).startswith("P")
    )


def _is_attribute_only_pain_point(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    segments = [
        segment
        for segment in _ATTRIBUTE_LIST_SEPARATOR_RE.split(compact)
        if segment
    ]
    return bool(segments) and all(
        _ATTRIBUTE_ONLY_SEGMENT_RE.fullmatch(segment) for segment in segments
    )


def _normalized_meaningful_value(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", value)
        if unicodedata.category(character)[0] in {"L", "N"}
    )


def _catalog_has_content(
    evidence_catalog: Mapping[str, Any],
    source: str,
) -> bool:
    source_catalog = evidence_catalog.get(source)
    if isinstance(source_catalog, str):
        return bool(source_catalog.strip())
    if isinstance(source_catalog, Mapping):
        return any(
            isinstance(value, str) and bool(value.strip())
            for value in source_catalog.values()
        )
    return False


def _catalog_field_text(
    evidence_catalog: Mapping[str, Any],
    source: str,
    field: str,
) -> tuple[str | None, bool]:
    """Return exact field text and whether the claimed field is exposed."""

    source_catalog = evidence_catalog.get(source)
    if isinstance(source_catalog, Mapping):
        if field not in source_catalog:
            return None, False
        value = source_catalog.get(field)
        return (value if isinstance(value, str) else None), True
    if isinstance(source_catalog, str):
        if field not in _LEGACY_CATALOG_FIELDS.get(source, frozenset()):
            return None, False
        return source_catalog, True
    return None, False


def _allowed_source_label(allowed_sources: frozenset[str]) -> str:
    if allowed_sources == {"portrait", "record"}:
        return "portrait|record"
    if allowed_sources == {"sku", "matrix"}:
        return "sku|matrix"
    return "|".join(sorted(allowed_sources))


def _validate_evidence_list(
    bridge: Mapping[str, Any],
    field: str,
    *,
    allowed_sources: frozenset[str] | None,
    catalog_source: str | None,
    evidence_catalog: Mapping[str, Any] | None,
    require_nonempty: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    missing_or_invalid: list[str] = []
    entries = bridge.get(field)
    if not isinstance(entries, list):
        return [f"{field} must be a list"], [field]
    if not entries:
        if require_nonempty:
            return [f"{field} must be a non-empty list"], [field]
        return [], []

    has_allowed_source = False
    expected_keys = _EVIDENCE_ENTRY_KEYS[field]
    for index, entry in enumerate(entries):
        prefix = f"{field}[{index}]"
        if not isinstance(entry, Mapping):
            errors.append(f"{prefix} must be an object")
            missing_or_invalid.append(prefix)
            continue

        entry_keys = set(entry)
        for key in sorted(expected_keys - entry_keys):
            errors.append(f"{prefix} missing required key: {key}")
            missing_or_invalid.append(f"{prefix}.{key}")
        for key in sorted(entry_keys - expected_keys):
            errors.append(f"{prefix} has unexpected key: {key}")
            missing_or_invalid.append(f"{prefix}.{key}")

        source: str | None = catalog_source
        if allowed_sources is not None:
            raw_source = entry.get("source")
            if not isinstance(raw_source, str) or raw_source not in allowed_sources:
                allowed = _allowed_source_label(allowed_sources)
                errors.append(f"{prefix}.source must be one of {allowed}")
                missing_or_invalid.append(f"{prefix}.source")
                source = None
            else:
                has_allowed_source = True
                source = raw_source

        for key in ("field", "value"):
            if not _is_meaningful_text(entry.get(key)):
                errors.append(f"{prefix}.{key} must be non-empty evidence text")
                missing_or_invalid.append(f"{prefix}.{key}")

        evidence_field = entry.get("field")
        evidence_value = entry.get("value")
        meaningful_value = _normalized_meaningful_value(evidence_value)
        if _is_meaningful_text(evidence_value) and len(meaningful_value) < 2:
            errors.append(
                f"{prefix}.value must contain at least 2 meaningful characters"
            )
            missing_or_invalid.append(f"{prefix}.value")

        if (
            evidence_catalog is not None
            and source is not None
            and _is_meaningful_text(evidence_field)
            and _is_meaningful_text(evidence_value)
        ):
            field_text, field_exists = _catalog_field_text(
                evidence_catalog,
                source,
                evidence_field,
            )
            if not field_exists:
                errors.append(
                    f"{prefix}.field is not present in evidence_catalog[{source!r}]"
                )
                missing_or_invalid.append(f"{prefix}.field")
            elif field_text is None or evidence_value not in field_text:
                errors.append(
                    f"{prefix}.value is not present in exact field "
                    f"evidence_catalog[{source!r}][{evidence_field!r}]"
                )
                missing_or_invalid.append(f"{prefix}.value")

    if allowed_sources is not None and not has_allowed_source:
        allowed = _allowed_source_label(allowed_sources)
        errors.append(f"{field} must contain evidence from {allowed}")
        missing_or_invalid.append(field)
    return errors, missing_or_invalid


def _dedupe(items: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _bridge_validation_result(
    bridge: Any,
    errors: list[str],
    missing_or_invalid: list[str],
) -> dict[str, Any]:
    if errors:
        return {
            "ok": False,
            "error": "pain_solution_bridge_invalid",
            "missing_or_invalid": _dedupe(missing_or_invalid),
            "errors": errors,
        }
    return {
        "ok": True,
        "bridge": bridge,
        "missing_or_invalid": [],
        "errors": [],
    }


def validate_pain_solution_bridge(
    bridge: Any,
    evidence_catalog: Mapping[str, Any] | None = None,
    *,
    require_pack_evidence: bool | None = None,
) -> dict[str, Any]:
    """Validate one pain-solution bridge and return deterministic errors."""

    if not isinstance(bridge, Mapping):
        return _bridge_validation_result(
            bridge,
            ["bridge must be an object"],
            ["bridge"],
        )
    if evidence_catalog is not None and not isinstance(evidence_catalog, Mapping):
        return _bridge_validation_result(
            bridge,
            ["evidence_catalog must be an object when provided"],
            ["evidence_catalog"],
        )
    if require_pack_evidence is not None and not isinstance(require_pack_evidence, bool):
        return _bridge_validation_result(
            bridge,
            ["require_pack_evidence must be a bool when provided"],
            ["require_pack_evidence"],
        )

    if require_pack_evidence is None:
        require_pack_evidence = bool(
            evidence_catalog is not None
            and _catalog_has_content(evidence_catalog, "pack")
        )

    errors: list[str] = []
    missing_or_invalid: list[str] = []
    bridge_keys = set(bridge)
    for field in sorted(_REQUIRED_FIELDS - bridge_keys):
        errors.append(f"missing required bridge field: {field}")
        missing_or_invalid.append(field)
    for field in sorted(bridge_keys - _REQUIRED_FIELDS):
        errors.append(f"unexpected bridge field: {field}")
        missing_or_invalid.append(field)

    for field in _TEXT_FIELDS:
        if not _is_meaningful_text(bridge.get(field)):
            errors.append(f"{field} must be non-empty text")
            missing_or_invalid.append(field)

    relevance_module = bridge.get("relevance_module")
    if _is_meaningful_text(relevance_module) and relevance_module not in {"M1", "M2"}:
        errors.append("relevance_module must be M1 or M2")
        missing_or_invalid.append("relevance_module")

    justification_module = bridge.get("justification_module")
    if _is_meaningful_text(justification_module) and justification_module not in {
        f"M{number}" for number in range(3, 10)
    }:
        errors.append("justification_module must be one of M3..M9")
        missing_or_invalid.append("justification_module")

    evidence_errors, evidence_invalid = _validate_evidence_list(
        bridge,
        "portrait_evidence",
        allowed_sources=frozenset({"portrait", "record"}),
        catalog_source=None,
        evidence_catalog=evidence_catalog,
        require_nonempty=True,
    )
    errors.extend(evidence_errors)
    missing_or_invalid.extend(evidence_invalid)

    evidence_errors, evidence_invalid = _validate_evidence_list(
        bridge,
        "pack_calibration_evidence",
        allowed_sources=None,
        catalog_source="pack",
        evidence_catalog=evidence_catalog,
        require_nonempty=require_pack_evidence,
    )
    errors.extend(evidence_errors)
    missing_or_invalid.extend(evidence_invalid)

    evidence_errors, evidence_invalid = _validate_evidence_list(
        bridge,
        "product_evidence",
        allowed_sources=frozenset({"sku", "matrix"}),
        catalog_source=None,
        evidence_catalog=evidence_catalog,
        require_nonempty=True,
    )
    errors.extend(evidence_errors)
    missing_or_invalid.extend(evidence_invalid)

    pain_point = bridge.get("pain_point")
    if _is_meaningful_text(pain_point) and _is_attribute_only_pain_point(pain_point):
        errors.append("pain_point must describe a pain, not only an attribute label/list")
        missing_or_invalid.append("pain_point")

    product_action = bridge.get("product_action")
    visible_result = bridge.get("visible_result")
    if _is_meaningful_text(product_action) and _is_meaningful_text(visible_result):
        if _normalized_slogan(product_action) == _normalized_slogan(visible_result):
            errors.append(
                "product_action and visible_result must not be the same slogan"
            )
            missing_or_invalid.extend(("product_action", "visible_result"))

    return _bridge_validation_result(bridge, errors, missing_or_invalid)


def validate_bridge_pair(
    bridges: Any,
    evidence_catalog: Mapping[str, Any] | None = None,
    *,
    require_pack_evidence: bool | None = None,
) -> dict[str, Any]:
    """Validate the two-bridge contract and fixed/variable field discipline."""

    if (
        not isinstance(bridges, Sequence)
        or isinstance(bridges, (str, bytes, bytearray))
        or len(bridges) != 2
    ):
        return {
            "ok": False,
            "error": "pain_solution_bridge_invalid",
            "missing_or_invalid": ["bridges"],
            "errors": ["bridges must contain exactly 2 items"],
        }

    errors: list[str] = []
    missing_or_invalid: list[str] = []
    for index, bridge in enumerate(bridges):
        result = validate_pain_solution_bridge(
            bridge,
            evidence_catalog,
            require_pack_evidence=require_pack_evidence,
        )
        for field in result["missing_or_invalid"]:
            if field == "bridge":
                missing_or_invalid.append(f"bridges[{index}]")
            else:
                missing_or_invalid.append(f"bridges[{index}].{field}")
        for error in result["errors"]:
            if error == "bridge must be an object":
                errors.append(f"bridges[{index}] must be an object")
            else:
                errors.append(f"bridges[{index}].{error}")

    first, second = bridges
    if isinstance(first, Mapping) and isinstance(second, Mapping):
        for field in _FIXED_PAIR_FIELDS:
            if first.get(field) != second.get(field):
                errors.append(f"{field} must be identical across both bridges")
                missing_or_invalid.extend(("cross_candidate_drift", field))

        first_path = tuple(first.get(field) for field in _VARIABLE_PAIR_FIELDS)
        second_path = tuple(second.get(field) for field in _VARIABLE_PAIR_FIELDS)
        if first_path == second_path:
            errors.append(
                "trigger_scene/pain_point/pain_consequence tuples must differ"
            )
            missing_or_invalid.extend(sorted(_VARIABLE_PAIR_FIELDS))

    if errors:
        return {
            "ok": False,
            "error": "pain_solution_bridge_invalid",
            "missing_or_invalid": _dedupe(missing_or_invalid),
            "errors": errors,
        }
    return {
        "ok": True,
        "bridges": bridges,
        "missing_or_invalid": [],
        "errors": [],
    }


def _member(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    try:
        return getattr(value, name)
    except (AttributeError, TypeError):
        return None


def _first(value: Any) -> Any:
    if (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and value
    ):
        return value[0]
    return None


def _parts_text(parts: Any) -> str | None:
    if not isinstance(parts, Sequence) or isinstance(parts, (str, bytes, bytearray)):
        return None
    texts: list[str] = []
    for part in parts:
        text = _member(part, "text")
        if isinstance(text, str):
            texts.append(text)
    combined = "".join(texts)
    return combined if combined.strip() else None


def _content_text(content: Any) -> str | None:
    if isinstance(content, str) and content.strip():
        return content
    parts = _member(content, "parts")
    text = _parts_text(parts)
    if text is not None:
        return text
    return _parts_text(content)


def extract_response_text(response: Any) -> str:
    """Extract text from common AIHub, OpenAI, and Gemini response shapes."""

    if isinstance(response, str) and response.strip():
        return response

    for name in ("content", "text"):
        text = _content_text(_member(response, name))
        if text is not None:
            return text

    choice = _first(_member(response, "choices"))
    if choice is not None:
        message = _member(choice, "message")
        text = _content_text(_member(message, "content"))
        if text is not None:
            return text

    candidate = _first(_member(response, "candidates"))
    if candidate is not None:
        text = _content_text(_member(candidate, "content"))
        if text is not None:
            return text

    raise ValueError("response does not contain extractable text")


def parse_bridge_payload(text: str) -> list[dict[str, Any]]:
    """Parse a plain or Markdown-fenced bridge JSON payload."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("bridge payload must contain valid JSON text")

    stripped = text.strip()
    fenced = _FENCED_JSON_RE.search(stripped)
    candidate = fenced.group(1).strip() if fenced else stripped
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("bridge payload must contain valid JSON") from exc

    if isinstance(payload, list):
        bridges = payload
    elif isinstance(payload, Mapping):
        if "bridges" not in payload:
            raise ValueError("bridge payload object must contain 'bridges'")
        bridges = payload["bridges"]
    else:
        raise ValueError("bridge payload root must be a list or an object with 'bridges'")

    if not isinstance(bridges, list):
        raise ValueError("bridge payload 'bridges' must be a list")
    if not all(isinstance(bridge, dict) for bridge in bridges):
        raise ValueError("bridge payload list items must be objects")
    return bridges


__all__ = [
    "canonical_upstream_fact_hash",
    "extract_response_text",
    "load_planting_bridge_context",
    "parse_bridge_payload",
    "validate_bridge_pair",
    "validate_pain_solution_bridge",
]
