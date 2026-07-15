from __future__ import annotations

from typing import Any

import pytest

import app.mcp.server  # noqa: F401  # Load tool registry before importing media.
import app.mcp.tools.media as media
from app.services import pipeline_lineage
from app.services.video_prompt_compiler import compile_final_prompt_segment


def _formal_prompt_source_3s() -> dict[str, Any]:
    return {
        "identity_product_anchor": (
            "主角小林保持同一张脸和米色针织衫。"
            "和田宽寿喜烧汁保持方瓶、红盖和米白标签一致。"
        ),
        "reference_instruction": "角色参考图锁定小林，产品参考图锁定寿喜烧汁包装。",
        "product_solution_action": "小林把寿喜烧汁倒入锅中，一次完成晚饭调味。",
        "timeline": (
            "0-1秒小林拿起寿喜烧汁；"
            "1-2秒把汁连续倒入锅中；"
            "2-3秒热饭完成并端上桌。"
        ),
        "scene_detail": (
            "晚归厨房有通勤包、灶台蒸汽和自然暖光，竖屏近景保持生活感。" * 2
        ),
        "sound_detail": "瓶盖轻响、锅中咕嘟声和瓷碗落桌声清楚连续。",
        "decorative_detail": "轻微手持感，真实皮肤和厨房使用痕迹可见。",
        "negative": "禁止换脸、包装变形、手部畸形、乱码、动作跳变。",
        "required_anchors": {
            "character": "主角小林",
            "product": "和田宽寿喜烧汁",
            "action": "倒入锅中",
            "result": "热饭完成并端上桌",
        },
    }


def _script(*, contract: object = None) -> dict[str, Any]:
    script: dict[str, Any] = {
        "id": "script-contract-test",
        "kind": "video_planting",
        "intent": "planting",
        "sku_id": "SKU-TEST",
        "scenes": [
            {
                "scene_no": 1,
                "time_range": "0-3s",
                "duration_s": 3,
                "whole_prompt": True,
                "video_prompt": "未经编译的原始提示词。",
                "prompt_source": _formal_prompt_source_3s(),
                "product_appearance": True,
            }
        ],
    }
    if contract is not None:
        script["content_contract"] = contract
    return script


def _install_pipeline_fakes(
    monkeypatch: pytest.MonkeyPatch,
    script: dict[str, Any],
) -> list[dict[str, Any]]:
    asset_reads: list[dict[str, Any]] = []

    async def fake_get_creative_pack(script_id: str) -> dict[str, Any]:
        return script

    async def fake_list_assets(**kwargs: Any) -> list[dict[str, Any]]:
        asset_reads.append(kwargs)
        return []

    async def fake_character_sheets(script_id: str) -> list[dict[str, Any]]:
        return []

    async def fake_lineage_context(script_row: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def fake_save_asset(**kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        pipeline_lineage, "get_creative_pack", fake_get_creative_pack
    )
    monkeypatch.setattr(pipeline_lineage, "list_assets", fake_list_assets)
    monkeypatch.setattr(
        pipeline_lineage,
        "list_character_sheets_for_script",
        fake_character_sheets,
    )
    monkeypatch.setattr(
        pipeline_lineage, "gather_lineage_context", fake_lineage_context
    )
    monkeypatch.setattr(
        pipeline_lineage, "save_storyboard_asset", fake_save_asset
    )
    return asset_reads


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "contract",
    [
        None,
        {},
        {"version": "2026-07-16.v2", "intent": "planting"},
        {"version": "legacy"},
        "2026-07-15.v1",
    ],
    ids=[
        "missing",
        "empty-getter-contract",
        "future",
        "legacy-inside-content-contract",
        "non-mapping",
    ],
)
async def test_step7_rejects_missing_or_unknown_content_contracts(
    monkeypatch: pytest.MonkeyPatch,
    contract: object,
) -> None:
    script = _script(contract=contract)
    asset_reads = _install_pipeline_fakes(monkeypatch, script)

    result = await media.generate_video_segments.__wrapped__(
        script_id=script["id"],
        product_refs=["https://example.test/product.png"],
        dry_run=True,
    )

    assert result["ok"] is False
    assert result["error"] == "unsupported_video_content_contract"
    assert asset_reads == []


@pytest.mark.asyncio
async def test_step7_explicit_legacy_mode_accepts_real_getter_empty_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script(contract={})
    _install_pipeline_fakes(monkeypatch, script)

    result = await media.generate_video_segments.__wrapped__(
        script_id=script["id"],
        product_refs=["https://example.test/product.png"],
        dry_run=True,
        legacy_mode=True,
    )

    assert result["ok"] is True
    row = result["result"]["results"][0]
    assert row["duration_s"] == 4
    assert row["duration_clamped"] is True


@pytest.mark.asyncio
async def test_step7_legacy_mode_cannot_override_future_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script(
        contract={"version": "2026-07-16.v2", "intent": "planting"}
    )
    asset_reads = _install_pipeline_fakes(monkeypatch, script)

    result = await media.generate_video_segments.__wrapped__(
        script_id=script["id"],
        product_refs=["https://example.test/product.png"],
        dry_run=True,
        legacy_mode=True,
    )

    assert result["ok"] is False
    assert result["error"] == "unsupported_video_content_contract"
    assert asset_reads == []


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, False], ids=["dry", "provider"])
async def test_formal_nonwhole_scene_without_prompt_source_fails_before_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
) -> None:
    script = _script(
        contract={"version": "2026-07-15.v1", "intent": "planting"}
    )
    scene = script["scenes"][0]
    scene["whole_prompt"] = False
    scene.pop("prompt_source")
    asset_reads = _install_pipeline_fakes(monkeypatch, script)
    provider_calls: list[dict[str, Any]] = []

    class FakeClient:
        async def generate_video_v2(self, **kwargs: Any) -> dict[str, Any]:
            provider_calls.append(kwargs)
            return {"video_url": "https://example.test/should-not-run.mp4"}

    async def no_cap(kind: str) -> None:
        return None

    monkeypatch.setattr(media, "AIHubClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(media, "_check_daily_media_cap", no_cap)
    monkeypatch.setattr(
        media,
        "get_model_for_tool",
        lambda tool_name: {"provider": "seedance", "model": "seedance-2-0"},
    )

    result = await media.generate_video_segments.__wrapped__(
        script_id=script["id"],
        product_refs=["https://example.test/product.png"],
        dry_run=dry_run,
    )

    assert result["ok"] is False
    assert result["error"] == "prompt_detail_insufficient"
    assert result["failed_checks"] == ["prompt_source"]
    assert result["scene_no"] == 1
    assert asset_reads == []
    assert provider_calls == []


@pytest.mark.asyncio
async def test_formal_compiler_prompt_is_exact_provider_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _formal_prompt_source_3s()
    expected = compile_final_prompt_segment(
        source,
        duration_seconds=3,
        intent="planting",
    )
    assert expected["ok"] is True
    script = _script(
        contract={"version": "2026-07-15.v1", "intent": "planting"}
    )
    _install_pipeline_fakes(monkeypatch, script)
    provider_calls: list[dict[str, Any]] = []

    class FakeClient:
        async def generate_video_v2(self, **kwargs: Any) -> dict[str, Any]:
            provider_calls.append(kwargs)
            return {"video_url": "https://example.test/video.mp4"}

    async def no_cap(kind: str) -> None:
        return None

    async def passing_vector_gate(**kwargs: Any) -> dict[str, Any]:
        return {"passed": True, "score_100": 100.0, "stage": kwargs["stage"]}

    async def no_post_description(video_url: str) -> dict[str, Any]:
        return {"ok": False, "error": "disabled_in_test"}

    monkeypatch.setattr(media, "AIHubClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(media, "_check_daily_media_cap", no_cap)
    monkeypatch.setattr(
        media,
        "get_model_for_tool",
        lambda tool_name: {"provider": "seedance", "model": "seedance-2-0"},
    )
    # These symbols belong to the uncommitted vector-gate work. `raising=False`
    # keeps this regression runnable against clean HEAD as well as this worktree.
    monkeypatch.setattr(
        media, "_score_vector_gate", passing_vector_gate, raising=False
    )
    monkeypatch.setattr(
        media,
        "_describe_video_for_vector_gate",
        no_post_description,
        raising=False,
    )

    result = await media.generate_video_segments.__wrapped__(
        script_id=script["id"],
        product_refs=["https://example.test/product.png"],
        character_anchor="MUST_NOT_PREPEND_CHARACTER_ANCHOR",
        extra_prompt_suffix="MUST_NOT_APPEND_EXTRA_SUFFIX",
    )

    assert result["ok"] is True
    assert len(provider_calls) == 1
    assert provider_calls[0]["prompt"] == expected["final_prompt"]
    assert provider_calls[0]["product_refs"] == [
        "https://example.test/product.png"
    ]
    assert "MUST_NOT_PREPEND_CHARACTER_ANCHOR" not in provider_calls[0]["prompt"]
    assert "MUST_NOT_APPEND_EXTRA_SUFFIX" not in provider_calls[0]["prompt"]
