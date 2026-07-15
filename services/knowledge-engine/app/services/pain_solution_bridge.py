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


def _catalog_text(evidence_catalog: Mapping[str, Any], source: str) -> str | None:
    value = evidence_catalog.get(source)
    if isinstance(value, str):
        return value
    return None


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
) -> list[str]:
    errors: list[str] = []
    entries = bridge.get(field)
    if not isinstance(entries, list) or not entries:
        return [f"{field} must be a non-empty list"]

    has_allowed_source = False
    for index, entry in enumerate(entries):
        prefix = f"{field}[{index}]"
        if not isinstance(entry, Mapping):
            errors.append(f"{prefix} must be an object")
            continue

        source: str | None = catalog_source
        if allowed_sources is not None:
            raw_source = entry.get("source")
            if not isinstance(raw_source, str) or raw_source not in allowed_sources:
                allowed = _allowed_source_label(allowed_sources)
                errors.append(f"{prefix}.source must be one of {allowed}")
                source = None
            else:
                has_allowed_source = True
                source = raw_source

        for key in ("field", "value"):
            if not _is_meaningful_text(entry.get(key)):
                errors.append(f"{prefix}.{key} must be non-empty evidence text")

        evidence_value = entry.get("value")
        if (
            evidence_catalog is not None
            and source is not None
            and _is_meaningful_text(evidence_value)
        ):
            source_text = _catalog_text(evidence_catalog, source)
            if source_text is None or evidence_value not in source_text:
                errors.append(
                    f"{prefix}.value is not present in evidence_catalog[{source!r}]"
                )

    if allowed_sources is not None and not has_allowed_source:
        allowed = _allowed_source_label(allowed_sources)
        errors.append(f"{field} must contain evidence from {allowed}")
    return errors


def validate_pain_solution_bridge(
    bridge: Any,
    evidence_catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one pain-solution bridge and return deterministic errors."""

    if not isinstance(bridge, Mapping):
        return {"ok": False, "errors": ["bridge must be an object"]}
    if evidence_catalog is not None and not isinstance(evidence_catalog, Mapping):
        return {
            "ok": False,
            "errors": ["evidence_catalog must be an object when provided"],
        }

    errors: list[str] = []
    for field in _TEXT_FIELDS:
        if not _is_meaningful_text(bridge.get(field)):
            errors.append(f"{field} must be non-empty text")

    relevance_module = bridge.get("relevance_module")
    if _is_meaningful_text(relevance_module) and relevance_module not in {"M1", "M2"}:
        errors.append("relevance_module must be M1 or M2")

    justification_module = bridge.get("justification_module")
    if _is_meaningful_text(justification_module) and justification_module not in {
        f"M{number}" for number in range(3, 10)
    }:
        errors.append("justification_module must be one of M3..M9")

    errors.extend(
        _validate_evidence_list(
            bridge,
            "portrait_evidence",
            allowed_sources=frozenset({"portrait", "record"}),
            catalog_source=None,
            evidence_catalog=evidence_catalog,
        )
    )
    errors.extend(
        _validate_evidence_list(
            bridge,
            "pack_calibration_evidence",
            allowed_sources=None,
            catalog_source="pack",
            evidence_catalog=evidence_catalog,
        )
    )
    errors.extend(
        _validate_evidence_list(
            bridge,
            "product_evidence",
            allowed_sources=frozenset({"sku", "matrix"}),
            catalog_source=None,
            evidence_catalog=evidence_catalog,
        )
    )

    pain_point = bridge.get("pain_point")
    if _is_meaningful_text(pain_point) and _is_attribute_only_pain_point(pain_point):
        errors.append("pain_point must describe a pain, not only an attribute label/list")

    product_action = bridge.get("product_action")
    visible_result = bridge.get("visible_result")
    if _is_meaningful_text(product_action) and _is_meaningful_text(visible_result):
        if _normalized_slogan(product_action) == _normalized_slogan(visible_result):
            errors.append(
                "product_action and visible_result must not be the same slogan"
            )

    return {"ok": not errors, "errors": errors}


def validate_bridge_pair(
    bridges: Any,
    evidence_catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the two-bridge contract and fixed/variable field discipline."""

    if (
        not isinstance(bridges, Sequence)
        or isinstance(bridges, (str, bytes, bytearray))
        or len(bridges) != 2
    ):
        return {"ok": False, "errors": ["bridges must contain exactly 2 items"]}

    errors: list[str] = []
    for index, bridge in enumerate(bridges):
        result = validate_pain_solution_bridge(bridge, evidence_catalog)
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

        extra_fixed_fields = sorted(
            (set(first) | set(second)) - _REQUIRED_FIELDS - _VARIABLE_PAIR_FIELDS
        )
        for field in extra_fixed_fields:
            if first.get(field) != second.get(field):
                errors.append(f"{field} must be identical across both bridges")

        first_path = tuple(first.get(field) for field in _VARIABLE_PAIR_FIELDS)
        second_path = tuple(second.get(field) for field in _VARIABLE_PAIR_FIELDS)
        if first_path == second_path:
            errors.append(
                "trigger_scene/pain_point/pain_consequence tuples must differ"
            )

    return {"ok": not errors, "errors": errors}


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
    "parse_bridge_payload",
    "validate_bridge_pair",
    "validate_pain_solution_bridge",
]
