from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import triangle_match as tm


def test_weighted_track_score_normalizes_available_tracks():
    score = tm.weighted_track_score({"visual": 0.8, "text": 0.7})
    expected = (0.8 * 0.45 + 0.7 * 0.40) / (0.45 + 0.40)
    assert round(score, 4) == round(expected, 4)


def test_triangle_gate_requires_content_edges():
    gate = tm.triangle_gate(
        {
            "product_audience": 0.80,
            "product_content": 0.69,
            "audience_content": 0.75,
        }
    )
    assert gate["overall_100"] >= 70
    assert gate["pass"] is False
    assert any("product_content" in w for w in gate["warnings"])


def test_triangle_gate_exposes_canonical_scales_aliases_and_boundary():
    gate = tm.triangle_gate(
        {
            "product_audience": 0.70,
            "product_content": 0.70,
            "audience_content": 0.70,
        }
    )

    assert gate["pass"] is True
    assert gate["overall_score"] == 0.70
    assert gate["overall_score_100"] == 70.0
    assert gate["edges"] == {
        "product_audience": 0.70,
        "product_content": 0.70,
        "audience_content": 0.70,
    }
    assert gate["edges_100"] == {
        "product_audience": 70.0,
        "product_content": 70.0,
        "audience_content": 70.0,
    }
    assert gate["overall"] == gate["overall_score"]
    assert gate["overall_100"] == gate["overall_score_100"]
    assert gate["min_edge"] == 0.70
    assert gate["overall_threshold_100"] == 70.0
    assert gate["edge_thresholds_100"] == {
        "product_audience": 65.0,
        "product_content": 70.0,
        "audience_content": 70.0,
    }
    assert gate["failed_checks"] == []


def test_triangle_gate_uses_profile_and_explicit_edge_thresholds():
    profile = SimpleNamespace(vector_threshold_100=72, version="profile-v1")
    gate = tm.triangle_gate(
        {
            "product_audience": 0.72,
            "product_content": 0.72,
            "audience_content": 0.72,
        },
        profile=profile,
        edge_thresholds_100={"product_audience": 75},
    )

    assert gate["overall_threshold_100"] == 72.0
    assert gate["edge_thresholds_100"] == {
        "product_audience": 75.0,
        "product_content": 72.0,
        "audience_content": 72.0,
    }
    # Product-audience is advisory: it warns but does not block a content gate.
    assert gate["pass"] is True
    assert gate["failed_checks"] == []
    assert any("product_audience" in warning for warning in gate["warnings"])


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -0.01, 1.01])
def test_triangle_gate_rejects_invalid_edge_scores_fail_closed(bad):
    gate = tm.triangle_gate(
        {
            "product_audience": 1.0,
            "product_content": bad,
            "audience_content": 1.0,
        }
    )

    assert gate["pass"] is False
    assert "invalid_edge:product_content" in gate["failed_checks"]
    assert gate["edges"]["product_content"] == 0.0


def test_triangle_gate_rejects_missing_edge_fail_closed():
    gate = tm.triangle_gate(
        {
            "product_audience": 1.0,
            "audience_content": 1.0,
        }
    )

    assert gate["pass"] is False
    assert "invalid_edge:product_content" in gate["failed_checks"]


@pytest.mark.asyncio
async def test_audit_content_triangle_is_pure_and_embeds_once(monkeypatch):
    calls = []

    async def fake_embed(texts, model=None, provider=None):
        calls.append((list(texts), model, provider))
        return [[1.0, 0.0] for _ in texts]

    def forbidden_pool():
        raise AssertionError("pure audit must not load DB state")

    monkeypatch.setattr(tm, "embed_texts", fake_embed)
    monkeypatch.setattr(tm, "get_pool", forbidden_pool)

    result = await tm.audit_content_triangle(
        product_text="verified product facts",
        audience_text="selected audience facts",
        content_tracks={"visual": "visible use", "text": "specific relief"},
        profile=SimpleNamespace(vector_threshold_100=70),
        has_audio=False,
    )

    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0][0] == [
        "verified product facts",
        "selected audience facts",
        "visible use",
        "specific relief",
    ]
    assert result["gate"]["overall_score_100"] == 100.0
    assert result["edge_scores"] == result["gate"]["edges"]
    assert any("audio" in item.lower() for item in result["recommendations"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        (
            {
                "product_text": "",
                "audience_text": "audience",
                "content_tracks": {"text": "x"},
            },
            "empty_product_text",
        ),
        (
            {
                "product_text": "product",
                "audience_text": "",
                "content_tracks": {"text": "x"},
            },
            "empty_audience_text",
        ),
        (
            {
                "product_text": "product",
                "audience_text": "audience",
                "content_tracks": {},
            },
            "empty_content_tracks",
        ),
    ],
)
async def test_audit_content_triangle_missing_inputs_have_stable_errors(kwargs, error):
    assert await tm.audit_content_triangle(**kwargs) == {"ok": False, "error": error}


@pytest.mark.asyncio
async def test_audit_script_triangle_wraps_db_loading_and_preserves_keys(monkeypatch):
    script = {
        "sku_id": "SKU-X",
        "portrait_id": "portrait-X",
        "matrix_run_id": "matrix-X",
        "script_md": "script",
        "kind": "video_planting",
        "scenes": [],
    }

    class Pool:
        async def fetchrow(self, _query, *_args):
            return {
                "id": "SKU-X",
                "name": "neutral product",
                "price_min": 10,
                "owner_selling_points": [],
                "specifications": "standard",
            }

    async def fake_core(**kwargs):
        assert kwargs["product_text"]
        assert kwargs["audience_text"] == "audience facts"
        assert kwargs["content_tracks"] == {"text": "content facts"}
        return {
            "ok": True,
            "edge_scores": {
                "product_audience": 1.0,
                "product_content": 1.0,
                "audience_content": 1.0,
            },
            "edge_scores_100": {
                "product_audience": 100.0,
                "product_content": 100.0,
                "audience_content": 100.0,
            },
            "product_track_scores": {"text": 1.0},
            "product_track_scores_100": {"text": 100.0},
            "audience_track_scores": {"text": 1.0},
            "audience_track_scores_100": {"text": 100.0},
            "gate": {"pass": True, "overall_score": 1.0, "overall_score_100": 100.0},
            "recommendations": [],
            "source_chars": {
                "product": 10,
                "audience": 10,
                "content_tracks": {"text": 10},
            },
            "content_tracks": ["text"],
            "disclaimer": "proxy",
        }

    async def fake_matrix(_sku_id, _matrix_id):
        return "matrix-X", "matrix facts"

    async def fake_portrait_id(_script, _explicit):
        return "portrait-X"

    monkeypatch.setattr(tm, "get_creative_pack", lambda _id: _async_value(script))
    monkeypatch.setattr(tm, "get_pool", Pool)
    monkeypatch.setattr(tm, "_latest_matrix_md", fake_matrix)
    monkeypatch.setattr(tm, "_latest_portrait_id", fake_portrait_id)
    monkeypatch.setattr(
        tm,
        "get_audience_portrait",
        lambda _id: _async_value({"portrait_md": "portrait"}),
    )
    monkeypatch.setattr(tm, "extract_audience_text", lambda _md: "audience facts")
    monkeypatch.setattr(
        tm, "extract_content_tracks", lambda *_args: {"text": "content facts"}
    )
    monkeypatch.setattr(tm, "audit_content_triangle", fake_core)

    result = await tm.audit_script_triangle(script_id="script-X")

    assert result["ok"] is True
    assert result["script_id"] == "script-X"
    assert result["sku_id"] == "SKU-X"
    assert result["portrait_id"] == "portrait-X"
    assert result["matrix_run_id"] == "matrix-X"
    assert result["edge_scores_100"]["product_content"] == 100.0


async def _async_value(value):
    return value


def test_build_product_text_includes_sku_matrix_and_ref_desc():
    text = tm.build_product_text(
        {
            "id": "SKU-X",
            "name": "和田宽有机酱油",
            "specifications": "500ml*2 + 200ml*2",
            "price_min": 76,
            "owner_selling_points": [{"text": "有机"}, {"text": "零添加"}],
        },
        matrix_md="大小瓶组合，厨房做菜和餐桌蘸食两个场景。",
        product_ref_desc="白底图，玻璃瓶，绿色有机标签。",
    )
    assert "SKU-X" in text
    assert "有机" in text
    assert "大小瓶组合" in text
    assert "白底图" in text
