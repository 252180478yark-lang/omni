"""Real P0 execution-content ↔ audience vector pre-match.

The P0 production atom intentionally does not fabricate an experiment arm just
to get a score.  It still must run a semantic pre-match over the actual
executable inputs: PromptSource text/timeline, visual/action/source lanes and
the sound lane.  The score is a cold-start ordering aid only; it cannot select
a script, approve a paid request or declare a winner.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.config import settings
from app.services.embedding_client import embed_texts
from app.services.video_intent_profiles import get_video_intent_profile
from app.services.video_production_contract import build_p0_prompt_source, content_hash
from app.services.video_prompt_compiler import compile_final_prompt_segment
from app.services.video_vector_gates import score_pre_video_prompt_set


P0_VECTOR_MATCHER_VERSION = "p0.execution-vector-match.v2"
_TRACKS = ("text", "visual", "music")
_WEIGHTS = {"text": 0.40, "visual": 0.45, "music": 0.15}
_EXCERPT_LIMIT = 360


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object, limit: int = 6000) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:limit].strip()


def _items_text(value: object) -> str:
    if not isinstance(value, list):
        return ""
    return "\n".join(_text(item) for item in value if _text(item))


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    numerator = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(a) ** 2 for a in left))
    right_norm = math.sqrt(sum(float(b) ** 2 for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _weighted_score(scores: Mapping[str, float]) -> float:
    available = {track: score for track, score in scores.items() if track in _WEIGHTS}
    if not available:
        return 0.0
    total_weight = sum(_WEIGHTS[track] for track in available)
    return sum(_WEIGHTS[track] * score for track, score in available.items()) / total_weight


def _evidence(text: str) -> dict[str, Any]:
    return {
        "hash": content_hash(text),
        "chars": len(text),
        "excerpt": text[:_EXCERPT_LIMIT],
    }


def audience_source_from_truth(
    truth_snapshot: Mapping[str, Any], *, require_frozen_portrait: bool = False
) -> dict[str, Any]:
    """Use only the frozen order audience; never silently query a newer portrait.

    P0 v2 historically allowed a frozen audience-record fallback when an order
    had no portrait.  P0 v3+ makes the adopted portrait part of the formal
    planting evidence contract, so callers can opt into a hard requirement.
    The opt-in preserves read/audit compatibility for immutable v2 orders while
    making the strong-lineage execution gate fail closed rather than silently downgrading
    its audience source.
    """

    portrait = _mapping(truth_snapshot.get("audience_portrait"))
    portrait_text = _text(portrait.get("portrait_md"), 6000)
    if portrait_text:
        return {
            "ok": True,
            "kind": "portrait",
            "text": portrait_text,
            "hash": content_hash(portrait_text),
            "evidence": _evidence(portrait_text),
        }

    if require_frozen_portrait:
        return {
            "ok": False,
            "error": "frozen_audience_portrait_required",
            "kind": "portrait_required",
        }

    record = _mapping(truth_snapshot.get("audience_record"))
    reasons = record.get("match_reasons")
    if isinstance(reasons, list):
        reason_text = _items_text(reasons)
    else:
        reason_text = _text(reasons)
    fallback = _text(
        "\n".join(
            piece
            for piece in (
                f"audience: {_text(record.get('name'), 500)}",
                _text(record.get("raw_md_segment"), 5000),
                f"match_reasons: {reason_text}",
                f"layer_tags: {_items_text(record.get('layer_tags'))}",
            )
            if piece.strip()
        ),
        6000,
    )
    if not fallback:
        return {"ok": False, "error": "audience_source_missing"}
    return {
        "ok": True,
        "kind": "record_fallback",
        "text": fallback,
        "hash": content_hash(fallback),
        "evidence": _evidence(fallback),
    }


def _evidence_values(value: object) -> list[str]:
    """Read only the evidence values selected by the adopted bridge."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [
        _text(item.get("value"), 1200)
        for item in value
        if isinstance(item, Mapping) and _text(item.get("value"), 1200)
    ]


def formal_planting_dimension_facts(
    *, truth_snapshot: Mapping[str, Any], pain_solution_bridge: Mapping[str, Any]
) -> dict[str, str]:
    """Build the five-dimension gate inputs from frozen P0 v3/v4 facts.

    These are intentionally bridge-first: the scorer never gets a broad or
    latest SKU/portrait lookup that could make a disconnected script look
    better.  Every lane derives from the selected structured bridge plus the
    portrait frozen in the order snapshot.
    """

    truth = _mapping(truth_snapshot)
    bridge = _mapping(pain_solution_bridge)
    portrait = _mapping(truth.get("audience_portrait"))
    bridge_context = _mapping(truth.get("planting_bridge_context"))
    bridge_facts = _mapping(bridge_context.get("facts"))
    pack_calibration = _mapping(bridge_facts.get("pack_calibration"))
    portrait_text = _text(portrait.get("portrait_md"), 6000)
    product_evidence = _evidence_values(bridge.get("product_evidence"))
    pack_evidence = _evidence_values(bridge.get("pack_calibration_evidence"))
    frozen_pack_text = _text(pack_calibration.get("pack_md"), 3600)
    bridge_values = {
        field: _text(bridge.get(field), 1600)
        for field in (
            "audience_segment",
            "trigger_scene",
            "pain_point",
            "pain_consequence",
            "product_action",
            "visible_result",
            "belief_shift",
            "justification_module",
        )
    }
    return {
        "audience_scene": _text(
            "\n".join(
                part
                for part in (
                    bridge_values["audience_segment"],
                    bridge_values["trigger_scene"],
                    portrait_text,
                    frozen_pack_text,
                    *pack_evidence,
                )
                if part
            ),
            6000,
        ),
        "pain_conflict": _text(
            "\n".join(
                part
                for part in (
                    bridge_values["pain_point"],
                    bridge_values["pain_consequence"],
                )
                if part
            ),
            3600,
        ),
        "product_action": _text(
            "\n".join(
                part
                for part in (bridge_values["product_action"], *product_evidence)
                if part
            ),
            3600,
        ),
        "result_relief": _text(
            "\n".join(
                part
                for part in (
                    bridge_values["visible_result"],
                    bridge_values["belief_shift"],
                )
                if part
            ),
            3600,
        ),
        "justification_evidence": _text(
            "\n".join(
                part
                for part in (
                    bridge_values["justification_module"],
                    frozen_pack_text,
                    *pack_evidence,
                    *product_evidence,
                )
                if part
            ),
            3600,
        ),
    }


async def _score_formal_planting_pre_video_gate(
    *,
    execution: Mapping[str, Any],
    truth_snapshot: Mapping[str, Any],
    pain_solution_bridge: Mapping[str, Any],
    duration_seconds: object,
) -> dict[str, Any]:
    """Apply the shared five-dimension pre-video gate to one P0 raw prompt.

    P0 has one 12-second provider request rather than the longer multi-scene
    lifecycle, so it is represented as one explicit segment.  This preserves
    the formal profile and bridge discipline without inventing a generation
    set or a second video workflow.
    """

    try:
        duration = float(duration_seconds)
    except (TypeError, ValueError):
        duration = 0.0
    final_prompt = _text(execution.get("final_prompt"), 12000)
    dimension_facts = formal_planting_dimension_facts(
        truth_snapshot=truth_snapshot,
        pain_solution_bridge=pain_solution_bridge,
    )
    missing = [name for name, value in dimension_facts.items() if not value]
    if not final_prompt or duration <= 0 or missing:
        return {
            "ok": False,
            "pass": False,
            "error": "pre_video_vector_gate_failed",
            "stage": "pre_video",
            "failed_checks": [
                *( ["p0_final_prompt"] if not final_prompt else [] ),
                *( ["p0_duration_seconds"] if duration <= 0 else [] ),
                *[f"dimension_fact:{name}" for name in missing],
            ],
            "dimension_facts": dimension_facts,
        }

    provider = str(getattr(settings, "embedding_provider", "gemini") or "gemini")
    model = str(
        getattr(settings, "embedding_model", "gemini-embedding-2-preview")
        or "gemini-embedding-2-preview"
    )

    async def scorer(
        *, content_text: str, dimension_facts: Mapping[str, str], segment_id: object
    ) -> dict[str, Any]:
        del segment_id
        ordered_dimensions = list(dimension_facts)
        vectors = await embed_texts(
            [content_text, *[dimension_facts[name] for name in ordered_dimensions]],
            model=model,
            provider=provider,
        )
        if len(vectors) != len(ordered_dimensions) + 1 or not all(
            isinstance(vector, list) for vector in vectors
        ):
            raise ValueError("embedding_result_invalid")
        prompt_vector = [float(item) for item in vectors[0]]
        return {
            "dimension_scores_100": {
                name: round(
                    _cosine(prompt_vector, [float(item) for item in vector]) * 100,
                    1,
                )
                for name, vector in zip(ordered_dimensions, vectors[1:])
            }
        }

    try:
        profile = get_video_intent_profile("planting")
    except Exception as exc:
        return {
            "ok": False,
            "pass": False,
            "error": "pre_video_vector_gate_failed",
            "stage": "pre_video",
            "failed_checks": [f"profile:planting:{type(exc).__name__}"],
            "dimension_facts": dimension_facts,
        }
    result = await score_pre_video_prompt_set(
        profile=profile,
        compiled_segments=[
            {
                "segment_id": "p0_raw",
                "duration_seconds": duration,
                "final_prompt": final_prompt,
                "applicable_dimensions": list(profile.key_vector_dimensions),
            }
        ],
        dimension_facts=dimension_facts,
        scorer=scorer,
        expected_segment_ids=["p0_raw"],
    )
    result["dimension_facts"] = dimension_facts
    result["embedding"] = {
        "provider": provider,
        "model": model,
        "matcher_version": P0_VECTOR_MATCHER_VERSION,
    }
    return result


def execution_tracks_from_source(source: Mapping[str, Any]) -> dict[str, Any]:
    """Extract only executable PromptSource lanes, never meta algorithm text."""

    source = _mapping(source)
    tracks = {
        "text": _text(source.get("timeline")),
        "visual": _text(
            "\n".join(
                part
                for part in (
                    _text(source.get("reference_instruction")),
                    _text(source.get("product_solution_action")),
                    _text(source.get("scene_detail")),
                    _text(source.get("decorative_detail")),
                )
                if part
            )
        ),
        "music": _text(source.get("sound_detail")),
    }
    missing = [track for track in _TRACKS if not tracks[track]]
    return {
        "ok": not missing,
        "error": "match_source_incomplete" if missing else None,
        "missing_tracks": missing,
        "tracks": tracks,
    }


def candidate_prompt_preview(
    *,
    candidate: Mapping[str, Any],
    spec: Mapping[str, Any],
    truth_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile the exact candidate execution preview used for pre-selection ranking."""

    try:
        source = build_p0_prompt_source(
            candidate=candidate,
            spec=spec,
            truth_snapshot=truth_snapshot,
        )
        compiled = compile_final_prompt_segment(
            source,
            duration_seconds=int(float(candidate["duration_seconds"])),
            intent="planting",
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": "candidate_prompt_preview_invalid", "detail": str(exc)[:240]}
    if not compiled.get("ok"):
        return {"ok": False, "error": "candidate_prompt_preview_invalid", "detail": compiled}
    final_prompt = _text(compiled.get("final_prompt"), 12000)
    execution_hash = content_hash({"prompt_source": source, "final_prompt": final_prompt})
    return {
        "ok": True,
        "source": source,
        "final_prompt": final_prompt,
        "execution_source_kind": "candidate_prompt_preview",
        "execution_source_hash": execution_hash,
    }


def frozen_prompt_execution_source(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Read the stored immutable PromptSource instead of rebuilding it."""

    prompt_source = _mapping(envelope.get("prompt_source"))
    compiled = _mapping(envelope.get("compiled"))
    final_prompt = _text(compiled.get("final_prompt"), 12000)
    if not prompt_source or not final_prompt:
        return {"ok": False, "error": "frozen_prompt_source_invalid"}
    return {
        "ok": True,
        "source": prompt_source,
        "final_prompt": final_prompt,
        "execution_source_kind": "frozen_prompt_source",
        "execution_source_hash": content_hash({"prompt_source": prompt_source, "final_prompt": final_prompt}),
    }


def build_unscored_report(
    *,
    execution: Mapping[str, Any],
    audience: Mapping[str, Any],
    tracks: Mapping[str, Any] | None = None,
    error: str,
    detail: str | None = None,
    formal_pre_video_vector_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    parsed_tracks = _mapping(tracks).get("tracks") if tracks else {}
    parsed_tracks = _mapping(parsed_tracks)
    provider = str(getattr(settings, "embedding_provider", "gemini") or "gemini")
    model = str(getattr(settings, "embedding_model", "gemini-embedding-2-preview") or "gemini-embedding-2-preview")
    return {
        "schema_version": P0_VECTOR_MATCHER_VERSION,
        "status": "unscored",
        "error": error,
        "detail": detail or None,
        "execution_source_kind": execution.get("execution_source_kind"),
        "execution_source_hash": execution.get("execution_source_hash"),
        "final_prompt_hash": content_hash(str(execution.get("final_prompt") or "")),
        "audience_source_kind": audience.get("kind"),
        "audience_source_hash": audience.get("hash"),
        "audience_evidence": audience.get("evidence"),
        "embedding": {
            "provider": provider,
            "model": model,
            "dimensions": None,
            "matcher_version": P0_VECTOR_MATCHER_VERSION,
        },
        "execution_evidence": {
            key: _evidence(value)
            for key, value in parsed_tracks.items()
            if isinstance(value, str) and value
        },
        "missing_tracks": list(_mapping(tracks).get("missing_tracks") or []),
        "scores": {},
        "overall_score": None,
        "formal_pre_video_vector_gate": (
            dict(formal_pre_video_vector_gate)
            if isinstance(formal_pre_video_vector_gate, Mapping)
            else None
        ),
        "disclaimer": "投前向量分只是排序和人工诊断的冷启动代理，不自动选择脚本、不判 winner，也不代表购买概率。",
    }


async def assess_execution_vector_match(
    *,
    execution: Mapping[str, Any],
    truth_snapshot: Mapping[str, Any],
    require_frozen_portrait: bool = False,
    pain_solution_bridge: Mapping[str, Any] | None = None,
    duration_seconds: object | None = None,
) -> dict[str, Any]:
    """Embed frozen audience and executable lanes; never invent a score.

    When a structured planting bridge is supplied by P0 v3/v4, the shared
    five-dimension pre-video gate is evaluated over the same frozen prompt.
    Its result is additional gate evidence; it does not replace the explicit
    three-lane audience pre-match or any post-launch metric.
    """

    audience = audience_source_from_truth(
        truth_snapshot,
        require_frozen_portrait=require_frozen_portrait,
    )
    if not audience.get("ok"):
        if require_frozen_portrait:
            return {
                "ok": False,
                "error": str(audience.get("error") or "frozen_audience_portrait_required"),
                "audience_source_kind": audience.get("kind"),
            }
        return {
            "ok": True,
            "report": build_unscored_report(
                execution=execution,
                audience=audience,
                error=str(audience.get("error") or "audience_source_missing"),
            ),
        }
    tracks = execution_tracks_from_source(_mapping(execution.get("source")))
    if not tracks.get("ok"):
        return {
            "ok": True,
            "report": build_unscored_report(
                execution=execution,
                audience=audience,
                tracks=tracks,
                error=str(tracks.get("error") or "match_source_incomplete"),
            ),
        }

    track_values = _mapping(tracks.get("tracks"))
    values = [str(audience["text"]), *[str(track_values[track]) for track in _TRACKS]]
    provider = str(getattr(settings, "embedding_provider", "gemini") or "gemini")
    model = str(getattr(settings, "embedding_model", "gemini-embedding-2-preview") or "gemini-embedding-2-preview")
    try:
        vectors = await embed_texts(values, model=model, provider=provider)
    except Exception as exc:  # Embedding is advisory: persist an honest unscored attempt.
        return {
            "ok": True,
            "report": build_unscored_report(
                execution=execution,
                audience=audience,
                tracks=tracks,
                error="embedding_unavailable",
                detail=str(exc)[:300],
            ),
        }
    if len(vectors) != len(values) or not all(isinstance(vector, list) for vector in vectors):
        return {
            "ok": True,
            "report": build_unscored_report(
                execution=execution,
                audience=audience,
                tracks=tracks,
                error="embedding_result_invalid",
            ),
        }

    audience_vector = [float(item) for item in vectors[0]]
    scores = {
        track: round(_cosine(audience_vector, [float(item) for item in vector]), 4)
        for track, vector in zip(_TRACKS, vectors[1:])
    }
    overall = round(_weighted_score(scores), 4)
    formal_pre_video_vector_gate: dict[str, Any] | None = None
    if pain_solution_bridge is not None:
        formal_pre_video_vector_gate = await _score_formal_planting_pre_video_gate(
            execution=execution,
            truth_snapshot=truth_snapshot,
            pain_solution_bridge=pain_solution_bridge,
            duration_seconds=duration_seconds,
        )
    report = {
        "schema_version": P0_VECTOR_MATCHER_VERSION,
        "status": "scored",
        "execution_source_kind": execution["execution_source_kind"],
        "execution_source_hash": execution["execution_source_hash"],
        "final_prompt_hash": content_hash(str(execution.get("final_prompt") or "")),
        "audience_source_kind": audience["kind"],
        "audience_source_hash": audience["hash"],
        "embedding": {
            "provider": provider,
            "model": model,
            "dimensions": len(audience_vector),
            "matcher_version": P0_VECTOR_MATCHER_VERSION,
        },
        "scores": scores,
        "scores_100": {track: round(score * 100, 1) for track, score in scores.items()},
        "overall_score": overall,
        "overall_score_100": round(overall * 100, 1),
        "weights": dict(_WEIGHTS),
        "audience_evidence": audience["evidence"],
        "execution_evidence": {track: _evidence(str(track_values[track])) for track in _TRACKS},
        "missing_tracks": [],
        "formal_pre_video_vector_gate": formal_pre_video_vector_gate,
        "disclaimer": "投前向量分只是排序和人工诊断的冷启动代理，不自动选择脚本、不判 winner，也不代表购买概率。",
    }
    return {"ok": True, "report": report}


__all__ = [
    "P0_VECTOR_MATCHER_VERSION",
    "assess_execution_vector_match",
    "audience_source_from_truth",
    "candidate_prompt_preview",
    "execution_tracks_from_source",
    "formal_planting_dimension_facts",
    "frozen_prompt_execution_source",
]
