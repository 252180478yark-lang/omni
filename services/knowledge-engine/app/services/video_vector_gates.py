"""Pure, fail-closed vector gates for formal AI-video generation."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from collections.abc import Callable, Mapping, Sequence, Set
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID


_PRE_FINGERPRINT_FIELDS = (
    "final_prompt_hashes",
    "dimension_manifest_hash",
    "upstream_fact_hash",
    "intent_profile_version",
    "embedding_model",
    "embedding_version",
)
_POST_FINGERPRINT_FIELDS = (
    "generation_set_id",
    "video_file_hash",
    "measured_duration_seconds",
    "final_prompt_hash",
    "upstream_fact_hash",
    "intent_profile_version",
    "judge_model",
    "judge_version",
)


class VectorGateValidationError(ValueError):
    """A deterministic, machine-readable fail-closed validation error."""

    def __init__(self, error: str, detail: str) -> None:
        super().__init__(f"{error}: {detail}")
        self.error = error
        self.detail = detail


def _canonicalize(value: Any, *, path: str = "$") -> Any:
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


def canonical_json(value: Any) -> str:
    """Serialize supported values into deterministic UTF-8 JSON text."""

    return json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    """Hash the canonical JSON representation with SHA-256."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_dimension_manifest(
    segments: object,
) -> list[dict[str, Any]]:
    """Return the ordered scene-to-lanes identity used by all formal gates."""

    if not isinstance(segments, Sequence) or isinstance(
        segments, (str, bytes, bytearray)
    ) or not segments:
        raise VectorGateValidationError(
            "scene_dimension_contract_invalid",
            "dimension manifest must be a non-empty ordered sequence",
        )
    result: list[dict[str, Any]] = []
    seen_ids: list[str | int] = []
    for index, raw in enumerate(segments):
        if not isinstance(raw, Mapping):
            raise VectorGateValidationError(
                "scene_dimension_contract_invalid",
                f"dimension manifest item {index} is not a mapping",
            )
        segment_id = _segment_identifier(
            raw.get("scene_no", raw.get("segment_id"))
        )
        if segment_id is None or segment_id in seen_ids:
            raise VectorGateValidationError(
                "scene_dimension_contract_invalid",
                f"dimension manifest item {index} has a missing or duplicate scene number",
            )
        applicable = raw.get("applicable_dimensions")
        if not isinstance(applicable, Sequence) or isinstance(
            applicable, (str, bytes, bytearray)
        ) or not applicable:
            raise VectorGateValidationError(
                "scene_dimension_contract_invalid",
                f"dimension manifest item {index} has no applicable_dimensions",
            )
        dimensions: list[str] = []
        for dimension in applicable:
            if not isinstance(dimension, str) or not dimension.strip():
                raise VectorGateValidationError(
                    "scene_dimension_contract_invalid",
                    f"dimension manifest item {index} has an invalid dimension",
                )
            normalized = dimension.strip()
            if normalized in dimensions:
                raise VectorGateValidationError(
                    "scene_dimension_contract_invalid",
                    f"dimension manifest item {index} has duplicate dimensions",
                )
            dimensions.append(normalized)
        seen_ids.append(segment_id)
        result.append(
            {
                "scene_no": segment_id,
                "applicable_dimensions": dimensions,
            }
        )
    return result


def build_dimension_manifest_hash(segments: object) -> str:
    """Hash the exact ordered scene/lane declarations for gate freshness."""

    return canonical_sha256(normalize_dimension_manifest(segments))


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash the bytes of an already-saved video without trusting its URL."""

    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_number_in_range(value: object, minimum: float, maximum: float) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError):
        return False
    return math.isfinite(numeric) and minimum <= numeric <= maximum


def _segment_identifier(value: object) -> str | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def aggregate_duration_weighted_scores(
    segments: Sequence[Mapping[str, Any]],
    *,
    expected_segment_ids: Sequence[str | int] | None = None,
    score_key: str = "overall_score_100",
) -> float:
    """Aggregate segment scores, rejecting incomplete or malformed groups."""

    if not isinstance(segments, Sequence) or isinstance(
        segments, (str, bytes, bytearray)
    ) or not segments:
        raise VectorGateValidationError(
            "generation_set_incomplete", "segments must be a non-empty sequence"
        )

    actual_ids: list[str | int] = []
    weighted_total = 0.0
    duration_total = 0.0
    for index, segment in enumerate(segments):
        if not isinstance(segment, Mapping):
            raise VectorGateValidationError(
                "generation_set_incomplete", f"segment {index} is not a mapping"
            )
        segment_id = _segment_identifier(segment.get("segment_id"))
        if segment_id is None:
            if expected_segment_ids is not None:
                raise VectorGateValidationError(
                    "generation_set_incomplete",
                    f"segment {index} has no segment_id for the expected manifest",
                )
            segment_id = index
        if segment_id in actual_ids:
            raise VectorGateValidationError(
                "generation_set_incomplete",
                f"segment {index} has a duplicate segment_id",
            )
        duration = segment.get("duration_seconds")
        if not _finite_number_in_range(duration, 0, float("inf")) or float(duration) <= 0:
            raise VectorGateValidationError(
                "generation_set_incomplete",
                f"segment {segment_id} has invalid duration_seconds",
            )
        score = segment.get(score_key)
        if not _finite_number_in_range(score, 0, 100):
            raise VectorGateValidationError(
                "generation_set_incomplete",
                f"segment {segment_id} has invalid {score_key}",
            )
        actual_ids.append(segment_id)
        weighted_total += float(duration) * float(score)
        duration_total += float(duration)

    if expected_segment_ids is not None:
        if not isinstance(expected_segment_ids, Sequence) or isinstance(
            expected_segment_ids, (str, bytes, bytearray)
        ):
            raise VectorGateValidationError(
                "generation_set_incomplete",
                "expected_segment_ids must be an ordered sequence",
            )
        expected_ids = [_segment_identifier(value) for value in expected_segment_ids]
        if (
            not expected_ids
            or any(value is None for value in expected_ids)
            or len(set(expected_ids)) != len(expected_ids)
            or actual_ids != expected_ids
        ):
            raise VectorGateValidationError(
                "generation_set_incomplete",
                "actual segments do not exactly match the ordered expected manifest",
            )

    if duration_total <= 0 or not math.isfinite(duration_total):
        raise VectorGateValidationError(
            "generation_set_incomplete", "total duration is invalid"
        )
    return round(weighted_total / duration_total, 4)


def _profile_value(profile: object, field: str) -> Any:
    if isinstance(profile, Mapping):
        return profile.get(field)
    return getattr(profile, field, None)


def _profile_contract(profile: object) -> tuple[str, float, tuple[str, ...]]:
    intent = _profile_value(profile, "intent")
    if not isinstance(intent, str) or not intent.strip():
        raise VectorGateValidationError(
            "vector_profile_invalid", "profile intent is missing"
        )
    threshold = _profile_value(profile, "vector_threshold_100")
    if not _finite_number_in_range(threshold, 0, 100):
        raise VectorGateValidationError(
            "vector_profile_invalid", "profile vector_threshold_100 is invalid"
        )
    raw_dimensions = _profile_value(profile, "key_vector_dimensions")
    if not isinstance(raw_dimensions, Sequence) or isinstance(
        raw_dimensions, (str, bytes, bytearray)
    ):
        raise VectorGateValidationError(
            "vector_profile_invalid", "profile key_vector_dimensions is invalid"
        )
    dimensions = tuple(raw_dimensions)
    if (
        not dimensions
        or any(not isinstance(item, str) or not item.strip() for item in dimensions)
        or len(set(dimensions)) != len(dimensions)
    ):
        raise VectorGateValidationError(
            "vector_profile_invalid", "profile key_vector_dimensions is invalid"
        )
    return intent.strip(), float(threshold), dimensions


def _gate_failure(
    *,
    stage: str,
    error: str,
    failed_checks: list[str],
    intent: str | None = None,
    threshold: float | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "pass": False,
        "error": error,
        "stage": stage,
        "intent": intent,
        "threshold_100": threshold,
        "overall_score_100": None,
        "key_vector_dimensions": [],
        "dimension_scores_100": {},
        "segment_results": [],
        "failed_checks": failed_checks,
        "planting_bridge_present": None,
    }


def _evaluate_vector_group_gate(
    profile: object,
    segments: Sequence[Mapping[str, Any]],
    *,
    stage: str,
    failure_error: str,
    expected_segment_ids: Sequence[str | int] | None = None,
) -> dict[str, Any]:
    try:
        intent, threshold, profile_dimensions = _profile_contract(profile)
    except VectorGateValidationError as exc:
        return _gate_failure(
            stage=stage,
            error=failure_error,
            failed_checks=[f"profile:{exc.detail}"],
        )

    try:
        overall_score = aggregate_duration_weighted_scores(
            segments,
            expected_segment_ids=expected_segment_ids,
        )
    except VectorGateValidationError as exc:
        return _gate_failure(
            stage=stage,
            error=exc.error,
            failed_checks=[exc.detail],
            intent=intent,
            threshold=threshold,
        )

    failed_checks: list[str] = []
    dimension_weighted_totals = {
        dimension: 0.0 for dimension in profile_dimensions
    }
    dimension_duration_totals = {
        dimension: 0.0 for dimension in profile_dimensions
    }
    segment_results: list[dict[str, Any]] = []
    planting_bridge_present = False if intent == "planting" else None

    for index, segment in enumerate(segments):
        segment_id = _segment_identifier(segment.get("segment_id"))
        if segment_id is None:
            segment_id = index
        duration = float(segment["duration_seconds"])
        segment_overall = float(segment["overall_score_100"])
        raw_applicable = segment.get("applicable_dimensions")
        raw_scores = segment.get("dimension_scores_100")
        applicable: tuple[str, ...] = ()
        applicable_valid = False
        scores: dict[str, float] = {}

        if not isinstance(raw_applicable, Sequence) or isinstance(
            raw_applicable, (str, bytes, bytearray)
        ):
            failed_checks.append(f"segment:{segment_id}:applicable_dimensions")
        else:
            applicable = tuple(raw_applicable)
            applicable_valid = not (
                not applicable
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in applicable
                )
                or len(set(applicable)) != len(applicable)
                or any(item not in profile_dimensions for item in applicable)
            )
            if not applicable_valid:
                failed_checks.append(
                    f"segment:{segment_id}:applicable_dimensions"
                )

        if not isinstance(raw_scores, Mapping):
            failed_checks.append(f"segment:{segment_id}:dimension_scores_100")
        else:
            score_keys = set(raw_scores)
            if not applicable_valid or score_keys != set(applicable):
                failed_checks.append(f"segment:{segment_id}:dimension_scores_100")
            for dimension in applicable if applicable_valid else ():
                score = raw_scores.get(dimension)
                if not _finite_number_in_range(score, 0, 100):
                    failed_checks.append(f"segment:{segment_id}:{dimension}:invalid")
                    continue
                numeric_score = float(score)
                scores[dimension] = numeric_score
                if dimension in dimension_weighted_totals:
                    dimension_weighted_totals[dimension] += numeric_score * duration
                    dimension_duration_totals[dimension] += duration
                if numeric_score < threshold:
                    failed_checks.append(f"segment:{segment_id}:{dimension}")

        if segment_overall < threshold:
            failed_checks.append(f"segment:{segment_id}:overall_score_100")

        if intent == "planting":
            carries_action = applicable_valid and "product_action" in applicable
            carries_relief = applicable_valid and bool(
                {"result_relief", "pain_relief"}.intersection(applicable)
            )
            if carries_action and carries_relief:
                planting_bridge_present = True

        segment_results.append(
            {
                "segment_id": segment_id,
                "duration_seconds": duration,
                "overall_score_100": segment_overall,
                "applicable_dimensions": list(applicable),
                "dimension_scores_100": scores,
                "pass": (
                    segment_overall >= threshold
                    and applicable_valid
                    and set(scores) == set(applicable)
                    and all(value >= threshold for value in scores.values())
                ),
            }
        )

    group_dimension_scores: dict[str, float] = {}
    for dimension in profile_dimensions:
        total_duration = dimension_duration_totals[dimension]
        if total_duration <= 0:
            failed_checks.append(f"group:missing_dimension:{dimension}")
            continue
        score = round(
            dimension_weighted_totals[dimension] / total_duration,
            4,
        )
        group_dimension_scores[dimension] = score
        if score < threshold:
            failed_checks.append(f"group:{dimension}")

    if overall_score < threshold:
        failed_checks.append("group:overall_score_100")
    if intent == "planting" and planting_bridge_present is not True:
        failed_checks.append("planting_product_action_and_relief_bridge")

    failed_checks = list(dict.fromkeys(failed_checks))
    passed = not failed_checks
    return {
        "ok": passed,
        "pass": passed,
        "error": None if passed else failure_error,
        "stage": stage,
        "intent": intent,
        "threshold_100": threshold,
        "overall_score_100": overall_score,
        "key_vector_dimensions": list(profile_dimensions),
        "dimension_scores_100": group_dimension_scores,
        "segment_results": segment_results,
        "failed_checks": failed_checks,
        "planting_bridge_present": planting_bridge_present,
    }


def evaluate_pre_video_vector_gate(
    profile: object,
    segments: Sequence[Mapping[str, Any]],
    *,
    expected_segment_ids: Sequence[str | int] | None = None,
) -> dict[str, Any]:
    """Evaluate final prompt scores against their declared profile dimensions."""

    return _evaluate_vector_group_gate(
        profile,
        segments,
        stage="pre_video",
        failure_error="pre_video_vector_gate_failed",
        expected_segment_ids=expected_segment_ids,
    )


def evaluate_post_video_vector_gate(
    profile: object,
    segments: Sequence[Mapping[str, Any]],
    *,
    expected_segment_ids: Sequence[str | int] | None = None,
) -> dict[str, Any]:
    """Evaluate actual video-signal scores for the selected generation set."""

    return _evaluate_vector_group_gate(
        profile,
        segments,
        stage="post_video",
        failure_error="post_video_vector_gate_failed",
        expected_segment_ids=expected_segment_ids,
    )


def evaluate_post_video_segment_gate(
    profile: object,
    segment: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate one saved segment only against the lanes declared for that scene.

    Profile-wide coverage and the planting action/result bridge are generation-set
    invariants.  Enforcing either here would make every split-lane scene fail even
    when the complete selected set satisfies the contract.
    """

    try:
        intent, threshold, profile_dimensions = _profile_contract(profile)
    except VectorGateValidationError as exc:
        return _gate_failure(
            stage="post_video",
            error="post_video_vector_gate_failed",
            failed_checks=[f"profile:{exc.detail}"],
        )
    if not isinstance(segment, Mapping):
        return _gate_failure(
            stage="post_video",
            error="post_video_vector_gate_failed",
            failed_checks=["segment:not_a_mapping"],
            intent=intent,
            threshold=threshold,
        )
    segment_id = _segment_identifier(segment.get("segment_id"))
    if segment_id is None:
        segment_id = 0
    duration = segment.get("duration_seconds")
    overall = segment.get("overall_score_100")
    raw_applicable = segment.get("applicable_dimensions")
    raw_scores = segment.get("dimension_scores_100")
    failed_checks: list[str] = []
    if (
        not _finite_number_in_range(duration, 0, float("inf"))
        or float(duration) <= 0
    ):
        failed_checks.append(f"segment:{segment_id}:duration_seconds")
    if not _finite_number_in_range(overall, 0, 100):
        failed_checks.append(f"segment:{segment_id}:overall_score_100")
    applicable: list[str] = []
    if not isinstance(raw_applicable, Sequence) or isinstance(
        raw_applicable, (str, bytes, bytearray)
    ):
        failed_checks.append(f"segment:{segment_id}:applicable_dimensions")
    else:
        applicable = list(raw_applicable)
        if (
            not applicable
            or any(
                not isinstance(dimension, str) or not dimension.strip()
                for dimension in applicable
            )
            or len(set(applicable)) != len(applicable)
            or any(dimension not in profile_dimensions for dimension in applicable)
        ):
            failed_checks.append(f"segment:{segment_id}:applicable_dimensions")
    scores: dict[str, float] = {}
    if not isinstance(raw_scores, Mapping) or (
        applicable and set(raw_scores) != set(applicable)
    ):
        failed_checks.append(f"segment:{segment_id}:dimension_scores_100")
    elif applicable:
        for dimension in applicable:
            score = raw_scores.get(dimension)
            if not _finite_number_in_range(score, 0, 100):
                failed_checks.append(f"segment:{segment_id}:{dimension}:invalid")
                continue
            numeric_score = float(score)
            scores[dimension] = numeric_score
            if numeric_score < threshold:
                failed_checks.append(f"segment:{segment_id}:{dimension}")
    if _finite_number_in_range(overall, 0, 100) and float(overall) < threshold:
        failed_checks.append(f"segment:{segment_id}:overall_score_100")
    failed_checks = list(dict.fromkeys(failed_checks))
    passed = not failed_checks
    planting_bridge_present = (
        {"product_action", "result_relief"}.issubset(applicable)
        if intent == "planting"
        else None
    )
    return {
        "ok": passed,
        "pass": passed,
        "error": None if passed else "post_video_vector_gate_failed",
        "stage": "post_video",
        "intent": intent,
        "threshold_100": threshold,
        "overall_score_100": (
            float(overall) if _finite_number_in_range(overall, 0, 100) else None
        ),
        "key_vector_dimensions": applicable,
        "dimension_scores_100": scores,
        "segment_results": [
            {
                "segment_id": segment_id,
                "duration_seconds": (
                    float(duration)
                    if _finite_number_in_range(duration, 0, float("inf"))
                    else None
                ),
                "overall_score_100": (
                    float(overall)
                    if _finite_number_in_range(overall, 0, 100)
                    else None
                ),
                "applicable_dimensions": applicable,
                "dimension_scores_100": scores,
                "pass": passed,
            }
        ],
        "failed_checks": failed_checks,
        "planting_bridge_present": planting_bridge_present,
    }


def score_100_to_arm_score(score_100: object) -> float:
    """Convert public 0-100 gate scores to the arm's explicit 0-1 scale."""

    if not _finite_number_in_range(score_100, 0, 100):
        raise VectorGateValidationError(
            "vector_score_invalid", "score_100 must be finite and within 0-100"
        )
    return round(float(score_100) / 100.0, 6)


def _pre_scoring_failure(profile: object, detail: str) -> dict[str, Any]:
    try:
        intent, threshold, _ = _profile_contract(profile)
    except VectorGateValidationError:
        intent, threshold = None, None
    return _gate_failure(
        stage="pre_video",
        error="pre_video_vector_gate_failed",
        failed_checks=[detail],
        intent=intent,
        threshold=threshold,
    )


async def score_pre_video_prompt_set(
    *,
    profile: object,
    compiled_segments: Sequence[Mapping[str, Any]],
    dimension_facts: Mapping[str, str],
    scorer: Callable[..., Any],
    expected_segment_ids: Sequence[str | int] | None = None,
) -> dict[str, Any]:
    """Score final prompts through an injected sync or async semantic scorer.

    The injected callable receives only explicit prompt text and fact lanes.  This
    keeps provider/network ownership outside the deterministic gate service.
    """

    if not callable(scorer):
        return _pre_scoring_failure(profile, "scorer:not_callable")
    if not isinstance(compiled_segments, Sequence) or isinstance(
        compiled_segments, (str, bytes, bytearray)
    ) or not compiled_segments:
        return _gate_failure(
            stage="pre_video",
            error="generation_set_incomplete",
            failed_checks=["segments must be a non-empty sequence"],
        )
    if expected_segment_ids is None:
        return _gate_failure(
            stage="pre_video",
            error="generation_set_incomplete",
            failed_checks=["expected_segment_ids is required for formal pre-scoring"],
        )
    if not isinstance(dimension_facts, Mapping):
        return _pre_scoring_failure(profile, "dimension_facts:not_mapping")

    actual_ids: list[str | int] = []
    for index, segment in enumerate(compiled_segments):
        if not isinstance(segment, Mapping):
            return _gate_failure(
                stage="pre_video",
                error="generation_set_incomplete",
                failed_checks=[f"segment {index} is not a mapping"],
            )
        segment_id = _segment_identifier(segment.get("segment_id"))
        duration = segment.get("duration_seconds")
        if segment_id is None or segment_id in actual_ids:
            return _gate_failure(
                stage="pre_video",
                error="generation_set_incomplete",
                failed_checks=[f"segment {index} has a missing or duplicate segment_id"],
            )
        if not _finite_number_in_range(duration, 0, float("inf")) or float(duration) <= 0:
            return _gate_failure(
                stage="pre_video",
                error="generation_set_incomplete",
                failed_checks=[f"segment {segment_id} has invalid duration_seconds"],
            )
        actual_ids.append(segment_id)
    if expected_segment_ids is not None:
        if not isinstance(expected_segment_ids, Sequence) or isinstance(
            expected_segment_ids, (str, bytes, bytearray)
        ):
            return _gate_failure(
                stage="pre_video",
                error="generation_set_incomplete",
                failed_checks=["expected_segment_ids must be an ordered sequence"],
            )
        expected_ids = [_segment_identifier(value) for value in expected_segment_ids]
        if (
            not expected_ids
            or any(value is None for value in expected_ids)
            or len(set(expected_ids)) != len(expected_ids)
            or actual_ids != expected_ids
        ):
            return _gate_failure(
                stage="pre_video",
                error="generation_set_incomplete",
                failed_checks=[
                    "actual segments do not exactly match the ordered expected manifest"
                ],
            )

    scored_segments: list[dict[str, Any]] = []
    for index, segment in enumerate(compiled_segments):
        if not isinstance(segment, Mapping):
            return _gate_failure(
                stage="pre_video",
                error="generation_set_incomplete",
                failed_checks=[f"segment {index} is not a mapping"],
            )
        segment_id = _segment_identifier(segment.get("segment_id"))
        if segment_id is None:
            return _gate_failure(
                stage="pre_video",
                error="generation_set_incomplete",
                failed_checks=[f"segment {index} has no segment_id"],
            )
        prompt_text = next(
            (
                value.strip()
                for key in ("prompt_text", "final_prompt", "prompt")
                if isinstance((value := segment.get(key)), str) and value.strip()
            ),
            None,
        )
        if prompt_text is None:
            return _pre_scoring_failure(
                profile, f"segment:{segment_id}:prompt_text"
            )
        applicable = segment.get("applicable_dimensions")
        if not isinstance(applicable, Sequence) or isinstance(
            applicable, (str, bytes, bytearray)
        ) or not applicable:
            return _pre_scoring_failure(
                profile, f"segment:{segment_id}:applicable_dimensions"
            )
        applicable_dimensions = list(applicable)
        try:
            _, _, profile_dimensions = _profile_contract(profile)
        except VectorGateValidationError:
            return _pre_scoring_failure(profile, "profile:invalid")
        if (
            any(
                not isinstance(dimension, str) or not dimension.strip()
                for dimension in applicable_dimensions
            )
            or len(set(applicable_dimensions)) != len(applicable_dimensions)
            or any(
                dimension not in profile_dimensions
                for dimension in applicable_dimensions
            )
        ):
            return _pre_scoring_failure(
                profile, f"segment:{segment_id}:applicable_dimensions"
            )
        facts: dict[str, str] = {}
        for dimension in applicable_dimensions:
            fact = dimension_facts.get(dimension)
            if not isinstance(fact, str) or not fact.strip():
                return _pre_scoring_failure(
                    profile, f"segment:{segment_id}:fact:{dimension}"
                )
            facts[dimension] = fact.strip()

        try:
            raw_result = scorer(
                content_text=prompt_text,
                dimension_facts=facts,
                segment_id=segment_id,
            )
            if inspect.isawaitable(raw_result):
                raw_result = await raw_result
        except Exception as exc:
            return _pre_scoring_failure(
                profile,
                f"segment:{segment_id}:scorer_failed:{type(exc).__name__}",
            )
        if not isinstance(raw_result, Mapping):
            return _pre_scoring_failure(
                profile, f"segment:{segment_id}:scorer_result"
            )
        nested_scores = raw_result.get("dimension_scores_100")
        score_values = nested_scores if isinstance(nested_scores, Mapping) else raw_result
        if set(score_values) != set(applicable_dimensions) or any(
            not _finite_number_in_range(score_values.get(dimension), 0, 100)
            for dimension in applicable_dimensions
        ):
            return _pre_scoring_failure(
                profile, f"segment:{segment_id}:dimension_scores_100"
            )
        dimension_scores = {
            dimension: float(score_values[dimension])
            for dimension in applicable_dimensions
        }
        supplied_overall = raw_result.get("overall_score_100")
        if supplied_overall is None:
            overall_score = sum(dimension_scores.values()) / len(dimension_scores)
        elif _finite_number_in_range(supplied_overall, 0, 100):
            overall_score = float(supplied_overall)
        else:
            return _pre_scoring_failure(
                profile, f"segment:{segment_id}:overall_score_100"
            )
        scored_segments.append(
            {
                "segment_id": segment_id,
                "duration_seconds": segment.get("duration_seconds"),
                "overall_score_100": round(overall_score, 4),
                "applicable_dimensions": applicable_dimensions,
                "dimension_scores_100": dimension_scores,
            }
        )

    return evaluate_pre_video_vector_gate(
        profile,
        scored_segments,
        expected_segment_ids=expected_segment_ids,
    )


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _duration_fingerprint_text(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("measured_duration_seconds must be a positive number")
    try:
        duration = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "measured_duration_seconds must be a positive number"
        ) from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("measured_duration_seconds must be a positive number")
    return f"{duration:.6f}"


def _required_prompt_hashes(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("final_prompt_hashes must be a non-empty ordered sequence")
    hashes = [
        _required_text(item, f"final_prompt_hashes[{index}]")
        for index, item in enumerate(value)
    ]
    if not hashes:
        raise ValueError("final_prompt_hashes must be a non-empty ordered sequence")
    return hashes


def _with_fingerprint_hash(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "fingerprint_hash": canonical_sha256(payload)}


def build_pre_gate_fingerprint(
    *,
    final_prompt_hashes: Sequence[str],
    upstream_fact_hash: str,
    intent_profile_version: str,
    embedding_model: str,
    embedding_version: str,
    dimension_manifest_hash: str,
) -> dict[str, Any]:
    """Bind one pre-video score to its ordered prompts and scoring inputs."""

    return _with_fingerprint_hash(
        {
            "final_prompt_hashes": _required_prompt_hashes(final_prompt_hashes),
            "dimension_manifest_hash": _required_text(
                dimension_manifest_hash, "dimension_manifest_hash"
            ),
            "upstream_fact_hash": _required_text(
                upstream_fact_hash, "upstream_fact_hash"
            ),
            "intent_profile_version": _required_text(
                intent_profile_version, "intent_profile_version"
            ),
            "embedding_model": _required_text(embedding_model, "embedding_model"),
            "embedding_version": _required_text(
                embedding_version, "embedding_version"
            ),
        }
    )


def build_post_gate_fingerprint(
    *,
    generation_set_id: str,
    video_file_hash: str,
    measured_duration_seconds: float | str,
    final_prompt_hash: str,
    upstream_fact_hash: str,
    intent_profile_version: str,
    judge_model: str,
    judge_version: str,
) -> dict[str, Any]:
    """Bind one post-video judgement to the selected asset's exact bytes."""

    values = {
        "generation_set_id": generation_set_id,
        "video_file_hash": video_file_hash,
        "measured_duration_seconds": _duration_fingerprint_text(
            measured_duration_seconds
        ),
        "final_prompt_hash": final_prompt_hash,
        "upstream_fact_hash": upstream_fact_hash,
        "intent_profile_version": intent_profile_version,
        "judge_model": judge_model,
        "judge_version": judge_version,
    }
    return _with_fingerprint_hash(
        {
            field: (
                values[field]
                if field == "measured_duration_seconds"
                else _required_text(values[field], field)
            )
            for field in _POST_FINGERPRINT_FIELDS
        }
    )


def _validate_freshness(
    stored: object,
    current: object,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    stored_mapping = stored if isinstance(stored, Mapping) else {}
    current_mapping = current if isinstance(current, Mapping) else {}
    changed = [
        field
        for field in fields
        if stored_mapping.get(field) != current_mapping.get(field)
    ]
    for label, value in (("stored", stored_mapping), ("current", current_mapping)):
        for field in fields:
            field_value = value.get(field)
            if field == "final_prompt_hashes":
                valid = (
                    isinstance(field_value, Sequence)
                    and not isinstance(field_value, (str, bytes, bytearray))
                    and bool(field_value)
                    and all(
                        isinstance(item, str) and bool(item.strip())
                        for item in field_value
                    )
                )
            else:
                valid = isinstance(field_value, str) and bool(field_value.strip())
            if not valid:
                changed.append(f"{label}:{field}")
        supplied_hash = value.get("fingerprint_hash")
        if not isinstance(supplied_hash, str) or not supplied_hash.strip():
            changed.append(f"{label}:fingerprint_hash")
    if not changed:
        for label, value in (("stored", stored_mapping), ("current", current_mapping)):
            supplied_hash = value.get("fingerprint_hash")
            if supplied_hash is not None:
                expected_hash = canonical_sha256(
                    {field: value.get(field) for field in fields}
                )
                if supplied_hash != expected_hash:
                    changed.append(f"{label}_fingerprint_hash")
    if changed:
        return {
            "ok": False,
            "pass": False,
            "error": "vector_gate_stale",
            "changed": changed,
        }
    return {"ok": True, "pass": True, "changed": []}


def validate_pre_gate_freshness(stored: object, current: object) -> dict[str, Any]:
    """Revalidate a pre-video score inside any caller-owned transaction."""

    return _validate_freshness(stored, current, _PRE_FINGERPRINT_FIELDS)


def validate_post_gate_freshness(stored: object, current: object) -> dict[str, Any]:
    """Revalidate selected-asset evidence inside any caller-owned transaction."""

    return _validate_freshness(stored, current, _POST_FINGERPRINT_FIELDS)


__all__ = [
    "VectorGateValidationError",
    "aggregate_duration_weighted_scores",
    "build_post_gate_fingerprint",
    "build_pre_gate_fingerprint",
    "build_dimension_manifest_hash",
    "canonical_json",
    "canonical_sha256",
    "evaluate_post_video_segment_gate",
    "evaluate_post_video_vector_gate",
    "evaluate_pre_video_vector_gate",
    "normalize_dimension_manifest",
    "score_100_to_arm_score",
    "score_pre_video_prompt_set",
    "sha256_file",
    "validate_post_gate_freshness",
    "validate_pre_gate_freshness",
]
