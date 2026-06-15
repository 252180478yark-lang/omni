"""REST endpoint tests for the post-campaign ad_metrics loop (roadmap E1/E2).

Covers the three dedicated endpoints added to mcp_exec.py:
- POST /api/v1/mcp/exec/record_ad_metrics            (E1 录入表单后端)
- POST /api/v1/mcp/exec/pipeline_list_asset_performance  (E2 带货榜数据源)
- POST /api/v1/mcp/exec/pipeline_get_asset_lineage   (E2 榜单下钻)

These validate endpoint plumbing (request model → tool kwargs → response passthrough)
by mocking the underlying tools; the tools themselves are exercised elsewhere.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

BASE = "/api/v1/mcp/exec"


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


# ═══ record_ad_metrics (E1) ═══

def test_record_ad_metrics_forwards_and_passthrough(client):
    fake = {
        "ok": True,
        "asset": {
            "asset_id": "a1",
            "sku_id": "SKU-1",
            "status": "published",
            "ad_metrics": {
                "gmv": 1200.0,
                "spend": 300.0,
                "_validation": {"suspect": {}, "ok_keys": ["gmv", "spend"]},
            },
            "last_metrics_at": "2026-06-15T00:00:00+00:00",
        },
    }
    with patch(
        "app.mcp.tools.pipeline.record_ad_metrics",
        new_callable=AsyncMock,
        return_value=fake,
    ) as m:
        resp = client.post(
            f"{BASE}/record_ad_metrics",
            json={
                "asset_id": "a1",
                "metrics": {"gmv": 1200, "spend": 300, "completion_rate": 42.5},
                "mark_published": True,
            },
        )
    assert resp.status_code == 200
    assert resp.json() == fake
    m.assert_awaited_once()
    kwargs = m.await_args.kwargs
    assert kwargs["asset_id"] == "a1"
    assert kwargs["metrics"] == {"gmv": 1200, "spend": 300, "completion_rate": 42.5}
    assert kwargs["mark_published"] is True


def test_record_ad_metrics_defaults(client):
    """metrics required; anchors default None; mark_published defaults True."""
    with patch(
        "app.mcp.tools.pipeline.record_ad_metrics",
        new_callable=AsyncMock,
        return_value={"ok": False, "error": "missing_anchor"},
    ) as m:
        resp = client.post(f"{BASE}/record_ad_metrics", json={"metrics": {}})
    assert resp.status_code == 200
    assert resp.json()["error"] == "missing_anchor"
    kwargs = m.await_args.kwargs
    assert kwargs["asset_id"] is None
    assert kwargs["external_video_id"] is None
    assert kwargs["external_creative_id"] is None
    assert kwargs["mark_published"] is True


def test_record_ad_metrics_requires_metrics(client):
    resp = client.post(f"{BASE}/record_ad_metrics", json={"asset_id": "a1"})
    assert resp.status_code == 422  # pydantic: metrics required


# ═══ pipeline_list_asset_performance (E2 leaderboard) ═══

def test_list_asset_performance_forwards(client):
    fake = {
        "ok": True,
        "count": 1,
        "assets": [
            {
                "asset_id": "a1",
                "sku_id": "SKU-1",
                "asset_type": "video",
                "ad_metrics": {"gmv": 1000, "spend": 250},
                "status": "published",
                "last_metrics_at": "2026-06-15T00:00:00+00:00",
            }
        ],
    }
    with patch(
        "app.mcp.tools.pipeline.pipeline_list_asset_performance",
        new_callable=AsyncMock,
        return_value=fake,
    ) as m:
        resp = client.post(
            f"{BASE}/pipeline_list_asset_performance",
            json={"sku_id": "SKU-1", "limit": 20},
        )
    assert resp.status_code == 200
    assert resp.json() == fake
    kwargs = m.await_args.kwargs
    assert kwargs["sku_id"] == "SKU-1"
    assert kwargs["limit"] == 20


def test_list_asset_performance_defaults(client):
    with patch(
        "app.mcp.tools.pipeline.pipeline_list_asset_performance",
        new_callable=AsyncMock,
        return_value={"ok": True, "count": 0, "assets": []},
    ) as m:
        resp = client.post(f"{BASE}/pipeline_list_asset_performance", json={})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0
    kwargs = m.await_args.kwargs
    assert kwargs["sku_id"] is None
    assert kwargs["limit"] == 50


# ═══ pipeline_get_asset_lineage (E2 drill-down) ═══

def test_get_asset_lineage_forwards(client):
    fake = {"ok": False, "error": "not_found", "asset_id": "nope"}
    with patch(
        "app.mcp.tools.pipeline.pipeline_get_asset_lineage",
        new_callable=AsyncMock,
        return_value=fake,
    ) as m:
        resp = client.post(f"{BASE}/pipeline_get_asset_lineage", json={"asset_id": "nope"})
    assert resp.status_code == 200
    assert resp.json() == fake
    assert m.await_args.kwargs["asset_id"] == "nope"


def test_get_asset_lineage_requires_asset_id(client):
    resp = client.post(f"{BASE}/pipeline_get_asset_lineage", json={})
    assert resp.status_code == 422  # pydantic: asset_id required
