from __future__ import annotations

import importlib
import sys
from typing import Any
import warnings

import pytest

try:
    from starlette.exceptions import StarletteDeprecationWarning
except ImportError:  # Starlette 1.0 removed the compatibility warning class.
    StarletteDeprecationWarning = DeprecationWarning

with warnings.catch_warnings():
    warnings.simplefilter("ignore", StarletteDeprecationWarning)
    import fastapi

import app.mcp.server  # noqa: F401  # Load tool registry before importing media.
import app.mcp.tools.media as media


class _NoopRouter:
    """Avoid the local FastAPI/Starlette constructor mismatch during unit import."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __getattr__(self, name: str):
        def route(*args: Any, **kwargs: Any):
            return lambda fn: fn

        return route


@pytest.mark.asyncio
async def test_rest_generate_video_segments_forwards_explicit_legacy_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fastapi, "APIRouter", _NoopRouter)
    sys.modules.pop("app.routers.mcp_exec", None)
    mcp_exec = importlib.import_module("app.routers.mcp_exec")
    calls: list[dict[str, Any]] = []

    async def fake_generate_video_segments(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        media, "generate_video_segments", fake_generate_video_segments
    )
    payload = mcp_exec.GenerateVideoSegmentsRequest(
        script_id="script-legacy-rest",
        legacy_mode=True,
        product_ref_asset_ids=["product-1"],
        experiment_arm_id="arm-1",
        allow_no_product=False,
    )

    result = await mcp_exec.exec_generate_video_segments(payload)

    assert result == {"ok": True}
    assert len(calls) == 1
    assert calls[0]["legacy_mode"] is True
    assert calls[0]["product_ref_asset_ids"] == ["product-1"]
    assert calls[0]["experiment_arm_id"] == "arm-1"
    assert calls[0]["allow_no_product"] is False


@pytest.mark.asyncio
async def test_rest_generate_character_sheets_forwards_experiment_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fastapi, "APIRouter", _NoopRouter)
    sys.modules.pop("app.routers.mcp_exec", None)
    mcp_exec = importlib.import_module("app.routers.mcp_exec")
    calls: list[dict[str, Any]] = []

    async def fake_generate_character_sheets(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        media, "generate_character_sheets", fake_generate_character_sheets
    )
    payload = mcp_exec.GenerateCharacterSheetsRequest(
        script_id="script-formal-rest",
        experiment_arm_id="arm-1",
    )

    result = await mcp_exec.exec_generate_character_sheets(payload)

    assert result == {"ok": True}
    assert calls[0]["experiment_arm_id"] == "arm-1"
