"""Product-audience-content semantic triangle audit.

The score is a pre-launch vector proxy.  It checks whether generated content
still connects explicit product facts with the selected audience; it never
replaces post-launch outcome metrics.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any

import numpy as np

from app.config import settings
from app.database import get_pool
from app.services.embedding_client import embed_texts
from app.services.match_vectors import extract_audience_text, extract_content_tracks
from app.services.pipeline_lineage import get_audience_portrait, get_creative_pack

TRACK_WEIGHTS = {"visual": 0.45, "text": 0.40, "music": 0.15}
EDGE_WEIGHTS = {
    "product_audience": 0.25,
    "product_content": 0.35,
    "audience_content": 0.40,
}
_EDGE_NAMES = tuple(EDGE_WEIGHTS)
_CONTENT_HARD_EDGES = ("product_content", "audience_content")


def _emb_model() -> str:
    return getattr(settings, "embedding_model", "gemini-embedding-2-preview")


def _emb_provider() -> str | None:
    return getattr(settings, "embedding_provider", "gemini")


def _clean(text: str | None, limit: int = 6000) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text[:limit].strip()


def _as_list(v: Any) -> list[Any]:
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def weighted_track_score(
    track_scores: dict[str, float], weights: dict[str, float] | None = None
) -> float:
    """Average available track scores with normalized weights."""
    weights = weights or TRACK_WEIGHTS
    available = {k: v for k, v in track_scores.items() if k in weights}
    if not available:
        return 0.0
    total_w = sum(weights[k] for k in available)
    if total_w <= 0:
        return 0.0
    return sum(available[k] * weights[k] for k in available) / total_w


def score_band(score: float) -> str:
    if score >= 0.75:
        return "strong"
    if score >= 0.70:
        return "pass"
    if score >= 0.65:
        return "watch"
    return "weak"


def _profile_value(profile: object | None, key: str, default: Any = None) -> Any:
    if isinstance(profile, Mapping):
        return profile.get(key, default)
    return getattr(profile, key, default) if profile is not None else default


def _finite_in_range(value: object, minimum: float, maximum: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and minimum <= float(value) <= maximum
    )


def _append_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def triangle_gate(
    edge_scores: Mapping[str, float],
    profile: object | None = None,
    overall_threshold_100: float | None = None,
    edge_thresholds_100: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Evaluate a semantic triangle on the canonical 0-1 input scale.

    Invalid scores and thresholds are converted to safe defaults but recorded
    as failed checks, so malformed input can never pass the gate.
    """
    failed_checks: list[str] = []
    warnings: list[str] = []

    threshold_value = (
        overall_threshold_100
        if overall_threshold_100 is not None
        else _profile_value(profile, "vector_threshold_100", 70)
    )
    if not _finite_in_range(threshold_value, 0, 100):
        threshold_value = 70.0
        failed_checks.append("invalid_threshold:overall")
    overall_threshold = float(threshold_value)

    override_thresholds = (
        edge_thresholds_100 if isinstance(edge_thresholds_100, Mapping) else {}
    )
    default_edge_thresholds = {
        "product_audience": 65.0,
        "product_content": overall_threshold,
        "audience_content": overall_threshold,
    }
    resolved_edge_thresholds: dict[str, float] = {}
    for edge in _EDGE_NAMES:
        raw_threshold = override_thresholds.get(edge, default_edge_thresholds[edge])
        if not _finite_in_range(raw_threshold, 0, 100):
            raw_threshold = default_edge_thresholds[edge]
            failed_checks.append(f"invalid_threshold:{edge}")
        resolved_edge_thresholds[edge] = float(raw_threshold)

    provided_scores = edge_scores if isinstance(edge_scores, Mapping) else {}
    edges: dict[str, float] = {}
    for edge in _EDGE_NAMES:
        raw_score = provided_scores.get(edge)
        if not _finite_in_range(raw_score, 0, 1):
            edges[edge] = 0.0
            failed_checks.append(f"invalid_edge:{edge}")
            warnings.append(f"{edge} is invalid or missing")
        else:
            edges[edge] = float(raw_score)

    product_audience = edges["product_audience"]
    product_content = edges["product_content"]
    audience_content = edges["audience_content"]
    overall = (
        product_audience * EDGE_WEIGHTS["product_audience"]
        + product_content * EDGE_WEIGHTS["product_content"]
        + audience_content * EDGE_WEIGHTS["audience_content"]
    )
    if product_audience * 100 < resolved_edge_thresholds["product_audience"]:
        warnings.append(
            "product_audience is below its advisory threshold; review audience-product fit"
        )
    for edge in _CONTENT_HARD_EDGES:
        if edges[edge] * 100 < resolved_edge_thresholds[edge]:
            _append_once(failed_checks, edge)
            warnings.append(f"{edge} is below its content threshold")
    if overall * 100 < overall_threshold:
        _append_once(failed_checks, "overall")
        warnings.append("triangle overall is below its content threshold")

    rounded_edges = {key: round(value, 4) for key, value in edges.items()}
    rounded_edges_100 = {key: round(value * 100, 1) for key, value in edges.items()}
    rounded_overall = round(overall, 4)
    rounded_overall_100 = round(overall * 100, 1)
    edge_thresholds = {
        key: round(value / 100, 4) for key, value in resolved_edge_thresholds.items()
    }
    return {
        "overall_score": rounded_overall,
        "overall_score_100": rounded_overall_100,
        "edges": rounded_edges,
        "edges_100": rounded_edges_100,
        "overall_threshold": round(overall_threshold / 100, 4),
        "overall_threshold_100": round(overall_threshold, 4),
        "edge_thresholds": edge_thresholds,
        "edge_thresholds_100": {
            key: round(value, 4) for key, value in resolved_edge_thresholds.items()
        },
        # Compatibility aliases for pre-contract callers.
        "overall": rounded_overall,
        "overall_100": rounded_overall_100,
        "min_edge": round(min(edges.values()), 4),
        "band": score_band(overall),
        "pass": not failed_checks,
        "failed_checks": failed_checks,
        "warnings": warnings,
        "weights": dict(EDGE_WEIGHTS),
    }


def build_product_text(
    sku_row: dict[str, Any] | None,
    matrix_md: str | None = None,
    product_ref_desc: str | None = None,
) -> str:
    """Build the product vector source from SKU facts, matrix, and ref image notes."""
    sku_row = sku_row or {}
    owner_points = []
    for item in _as_list(sku_row.get("owner_selling_points")):
        if isinstance(item, dict) and item.get("text"):
            owner_points.append(str(item["text"]))
        elif isinstance(item, str):
            owner_points.append(item)
    parts = [
        f"SKU: {sku_row.get('id') or ''}",
        f"name: {sku_row.get('name') or ''}",
        f"specifications: {sku_row.get('specifications') or ''}",
        f"price_min: {sku_row.get('price_min') or ''}",
        f"owner_selling_points: {'; '.join(owner_points)}",
    ]
    if product_ref_desc:
        parts.append(f"product_reference_image: {product_ref_desc}")
    if matrix_md:
        parts.append("selling_point_matrix_excerpt: " + _clean(matrix_md, 3500))
    return _clean("\n".join(parts), 6000)


def _recommend(
    edge_scores: dict[str, float],
    product_track_scores: dict[str, float],
    audience_track_scores: dict[str, float],
    has_audio: bool | None = None,
    gate: dict[str, Any] | None = None,
) -> list[str]:
    recs: list[str] = []
    thresholds = (gate or {}).get("edge_thresholds") or {
        "product_audience": 0.65,
        "product_content": 0.70,
        "audience_content": 0.70,
    }
    if edge_scores.get("product_content", 0) < thresholds["product_content"]:
        recs.append(
            "Raise product-content match with a clearer verified use action and visible result."
        )
    if edge_scores.get("audience_content", 0) < thresholds["audience_content"]:
        recs.append(
            "Raise audience-content match with more specific selected-audience context and language."
        )
    if edge_scores.get("product_audience", 0) < thresholds["product_audience"]:
        recs.append(
            "Review product-audience fit or use a more explicit scene-to-product bridge."
        )
    track_threshold = float((gate or {}).get("overall_threshold", 0.70))
    low_product_tracks = [
        key for key, value in product_track_scores.items() if value < track_threshold
    ]
    if low_product_tracks:
        recs.append(f"Product weak tracks: {', '.join(low_product_tracks)}.")
    low_audience_tracks = [
        key for key, value in audience_track_scores.items() if value < track_threshold
    ]
    if low_audience_tracks:
        recs.append(f"Audience weak tracks: {', '.join(low_audience_tracks)}.")
    if has_audio is False:
        recs.append(
            "Video has no audio stream: treat as silent visual draft and add BGM/SFX/voiceover before launch."
        )
    return recs


async def audit_content_triangle(
    *,
    product_text: str,
    audience_text: str,
    content_tracks: Mapping[str, str],
    profile: object | None = None,
    has_audio: bool | None = None,
) -> dict[str, Any]:
    """Audit already-loaded facts without looking up DB or latest lineage state."""
    clean_product = _clean(product_text)
    if not clean_product:
        return {"ok": False, "error": "empty_product_text"}
    clean_audience = _clean(audience_text)
    if not clean_audience:
        return {"ok": False, "error": "empty_audience_text"}
    clean_tracks = {
        str(key): _clean(value)
        for key, value in (content_tracks or {}).items()
        if isinstance(key, str) and isinstance(value, str) and _clean(value)
    }
    if not clean_tracks:
        return {"ok": False, "error": "empty_content_tracks"}

    keys = ["product", "audience", *[f"content:{key}" for key in clean_tracks]]
    texts = [clean_product, clean_audience, *clean_tracks.values()]
    vecs = await embed_texts(texts, model=_emb_model(), provider=_emb_provider())
    if len(vecs) != len(texts):
        return {"ok": False, "error": "embedding_result_invalid"}
    vectors = {key: np.array(value, dtype=np.float32) for key, value in zip(keys, vecs)}

    product_audience = _cosine(vectors["product"], vectors["audience"])
    product_track_scores = {
        key.removeprefix("content:"): _cosine(vectors["product"], vectors[key])
        for key in vectors
        if key.startswith("content:")
    }
    audience_track_scores = {
        key.removeprefix("content:"): _cosine(vectors["audience"], vectors[key])
        for key in vectors
        if key.startswith("content:")
    }
    edge_scores = {
        "product_audience": product_audience,
        "product_content": weighted_track_score(product_track_scores),
        "audience_content": weighted_track_score(audience_track_scores),
    }
    gate = triangle_gate(edge_scores, profile=profile)
    rounded_edges = {key: round(value, 4) for key, value in edge_scores.items()}
    rounded_product_tracks = {
        key: round(value, 4) for key, value in product_track_scores.items()
    }
    rounded_audience_tracks = {
        key: round(value, 4) for key, value in audience_track_scores.items()
    }
    return {
        "ok": True,
        "edge_scores": rounded_edges,
        "edge_scores_100": {
            key: round(value * 100, 1) for key, value in edge_scores.items()
        },
        "product_track_scores": rounded_product_tracks,
        "product_track_scores_100": {
            key: round(value * 100, 1) for key, value in product_track_scores.items()
        },
        "audience_track_scores": rounded_audience_tracks,
        "audience_track_scores_100": {
            key: round(value * 100, 1) for key, value in audience_track_scores.items()
        },
        "overall_score": gate["overall_score"],
        "overall_score_100": gate["overall_score_100"],
        "edges": gate["edges"],
        "edges_100": gate["edges_100"],
        "gate": gate,
        "recommendations": _recommend(
            edge_scores,
            product_track_scores,
            audience_track_scores,
            has_audio,
            gate,
        ),
        "source_chars": {
            "product": len(clean_product),
            "audience": len(clean_audience),
            "content_tracks": {key: len(value) for key, value in clean_tracks.items()},
        },
        "content_tracks": list(clean_tracks),
        "disclaimer": (
            "Triangle vector score is a cold-start semantic proxy; "
            "post-launch north-star metrics decide the winner."
        ),
    }


async def _latest_matrix_md(
    sku_id: str, matrix_run_id: str | None = None
) -> tuple[str | None, str | None]:
    pool = get_pool()
    if matrix_run_id:
        row = await pool.fetchrow(
            "SELECT id::text AS id, matrix_md FROM pipeline.matrix_runs WHERE id=$1::uuid",
            matrix_run_id,
        )
        if row:
            return row["id"], row["matrix_md"]
    row = await pool.fetchrow(
        """
        SELECT id::text AS id, matrix_md
        FROM pipeline.matrix_runs
        WHERE sku_id=$1 AND status='adopted'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        sku_id,
    )
    if row:
        return row["id"], row["matrix_md"]
    return None, None


async def _latest_portrait_id(
    script: dict[str, Any], explicit_portrait_id: str | None = None
) -> str | None:
    if explicit_portrait_id:
        return explicit_portrait_id
    if script.get("portrait_id"):
        return script["portrait_id"]
    pool = get_pool()
    if script.get("audience_record_id"):
        row = await pool.fetchrow(
            """
            SELECT id::text AS id
            FROM pipeline.audience_portraits
            WHERE audience_record_id=$1::uuid
            ORDER BY created_at DESC
            LIMIT 1
            """,
            script["audience_record_id"],
        )
        if row:
            return row["id"]
    row = await pool.fetchrow(
        """
        SELECT id::text AS id
        FROM pipeline.audience_portraits
        WHERE sku_id=$1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        script.get("sku_id"),
    )
    return row["id"] if row else None


async def audit_script_triangle(
    *,
    script_id: str,
    portrait_id: str | None = None,
    matrix_run_id: str | None = None,
    product_ref_desc: str | None = None,
    has_audio: bool | None = None,
    profile: object | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper that loads one script's explicit audit inputs."""
    script = await get_creative_pack(script_id)
    if not script:
        return {"ok": False, "error": "script_not_found"}

    pool = get_pool()
    sku_id = script.get("sku_id")
    sku_row = await pool.fetchrow(
        "SELECT id, name, price_min, owner_selling_points, specifications FROM mvp_sku WHERE id=$1",
        sku_id,
    )
    actual_matrix_id, matrix_md = await _latest_matrix_md(
        sku_id, matrix_run_id or script.get("matrix_run_id")
    )
    actual_portrait_id = await _latest_portrait_id(script, portrait_id)
    if not actual_portrait_id:
        return {"ok": False, "error": "portrait_not_found"}
    portrait = await get_audience_portrait(actual_portrait_id)
    if not portrait:
        return {"ok": False, "error": "portrait_not_found"}

    product_text = build_product_text(
        dict(sku_row) if sku_row else None, matrix_md, product_ref_desc
    )
    audience_text = extract_audience_text(portrait.get("portrait_md") or "")
    content_tracks = extract_content_tracks(
        script.get("script_md") or "",
        script.get("kind") or "",
        script.get("scenes") or [],
    )
    audit = await audit_content_triangle(
        product_text=product_text,
        audience_text=audience_text,
        content_tracks=content_tracks,
        profile=profile,
        has_audio=has_audio,
    )
    if not audit.get("ok"):
        return audit
    return {
        **audit,
        "script_id": script_id,
        "sku_id": sku_id,
        "portrait_id": actual_portrait_id,
        "matrix_run_id": actual_matrix_id,
    }
