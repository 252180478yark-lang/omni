from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

import app.mcp.server  # noqa: F401
from app.mcp.tools import media, planting
from app.services import ai_hub_client, pipeline_lineage, video_content_gate


def _video_kwargs(**kwargs: Any) -> dict[str, Any]:
    """Keep Task 7 tests runnable with or without the later Task 9 seam."""

    signature = inspect.signature(media.generate_video_segments.__wrapped__)
    if "post_vector_check" in signature.parameters:
        kwargs["post_vector_check"] = False
    return kwargs


def test_product_reference_registration_is_in_doctor_contract() -> None:
    from app.mcp.doctor import _wanted_tools

    assert "register_product_reference_asset" in _wanted_tools()


def _formal_script(*, roles: int = 1) -> dict[str, Any]:
    return {
        "id": "script-a",
        "sku_id": "SKU-A",
        "kind": "video_planting",
        "intent": "planting",
        "status": "adopted",
        "content_contract": {
            "version": "2026-07-15.v1",
            "intent": "planting",
            "content_gate": {"pass": True},
        },
        "character_sheets": [
            {
                "role_id": f"role-{idx}",
                "name": f"Role {idx}",
                "age": "30-39",
                "gender": "女",
                "appearance": "齐肩黑发，米色针织衫",
            }
            for idx in range(1, roles + 1)
        ],
        "scenes": [
            {
                "scene_no": 1,
                "time_range": "0-3s",
                "duration_s": 3,
                "whole_prompt": True,
                "product_appearance": True,
                "prompt_source": {
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
                },
            }
        ],
    }


def _product_asset(asset_id: str, path: Path, *, sku_id: str = "SKU-A") -> dict[str, Any]:
    return {
        "id": asset_id,
        "sku_id": sku_id,
        "asset_type": "product_reference",
        "file_url": str(path),
        "status": "adopted",
        "script_id": None,
        "experiment_arm_id": None,
        "generation_set_id": None,
    }


def _face_asset(asset_id: str, path: Path, *, arm_id: str = "arm-a") -> dict[str, Any]:
    return {
        "id": asset_id,
        "sku_id": "SKU-A",
        "asset_type": "character_sheet",
        "file_url": str(path),
        "status": "draft",
        "script_id": "script-a",
        "character_role": "role-1",
        "experiment_arm_id": arm_id,
        "generation_set_id": None,
    }


@pytest.mark.asyncio
async def test_register_product_reference_reuses_same_sku_and_rejects_other_sku(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "product.png"
    path.write_bytes(b"product")

    async def existing_other(file_ref: str) -> dict[str, Any]:
        return _product_asset("existing", path, sku_id="SKU-B")

    monkeypatch.setattr(pipeline_lineage, "get_product_reference_by_file", existing_other)
    result = await planting.register_product_reference_asset.__wrapped__("SKU-A", str(path))
    assert result["ok"] is False
    assert result["error"] == "product_ref_invalid_or_mismatch"

    async def existing_same(file_ref: str) -> dict[str, Any]:
        return _product_asset("existing", path, sku_id="SKU-A")

    monkeypatch.setattr(pipeline_lineage, "get_product_reference_by_file", existing_same)
    result = await planting.register_product_reference_asset.__wrapped__("SKU-A", str(path))
    assert result["ok"] is True
    assert result["result"]["asset_id"] == "existing"
    assert result["result"]["reused"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_owner",
    [
        {"status": "draft"},
        {"status": "published"},
        {"status": "discarded"},
        {"status": "archived"},
        {"script_id": "script-a"},
        {"experiment_arm_id": "arm-a"},
        {"generation_set_id": "set-a"},
    ],
)
async def test_register_product_reference_rejects_noncanonical_same_sku_reuse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    invalid_owner: dict[str, Any],
) -> None:
    path = tmp_path / "product.png"
    path.write_bytes(b"product")
    existing = _product_asset("existing", path, sku_id="SKU-A")
    existing.update(invalid_owner)

    async def existing_same_sku(file_ref: str) -> dict[str, Any]:
        return existing

    async def must_not_save(**kwargs: Any) -> str:
        raise AssertionError("invalid existing reference must not be replaced")

    monkeypatch.setattr(
        pipeline_lineage,
        "get_product_reference_by_file",
        existing_same_sku,
    )
    monkeypatch.setattr(
        pipeline_lineage,
        "save_product_reference_asset",
        must_not_save,
    )

    result = await planting.register_product_reference_asset.__wrapped__(
        "SKU-A", str(path)
    )

    assert result == {"ok": False, "error": "product_ref_invalid_or_mismatch"}


@pytest.mark.asyncio
async def test_register_product_reference_saves_canonical_readable_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "product.png"
    path.write_bytes(b"product")
    captured: dict[str, Any] = {}

    async def no_existing(file_ref: str) -> None:
        return None

    async def save(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "asset-new"

    monkeypatch.setattr(pipeline_lineage, "get_product_reference_by_file", no_existing)
    monkeypatch.setattr(pipeline_lineage, "save_product_reference_asset", save)

    result = await planting.register_product_reference_asset.__wrapped__("SKU-A", str(path))

    assert result["ok"] is True
    assert result["result"]["asset_id"] == "asset-new"
    assert captured == {"sku_id": "SKU-A", "file_ref": str(path.resolve())}


@pytest.mark.asyncio
async def test_register_product_reference_rejects_missing_file(tmp_path: Path) -> None:
    result = await planting.register_product_reference_asset.__wrapped__(
        "SKU-A", str(tmp_path / "missing.png")
    )

    assert result == {"ok": False, "error": "product_ref_invalid_or_mismatch"}


@pytest.mark.asyncio
async def test_character_sheets_arm_mismatch_stops_before_cap_provider_and_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def get_script(script_id: str) -> dict[str, Any]:
        return _formal_script()

    async def reject(script: dict[str, Any], arm_id: str) -> dict[str, Any]:
        calls.append("gate")
        return {"ok": False, "error": "experiment_arm_missing_or_mismatch"}

    async def cap(kind: str) -> None:
        calls.append("cap")
        return None

    async def save(**kwargs: Any) -> str:
        calls.append("save")
        return "asset"

    class FakeClient:
        async def generate_image_v2(self, **kwargs: Any) -> dict[str, Any]:
            calls.append("provider")
            return {"images": [{"url": "data:image/png;base64,eA=="}]}

    monkeypatch.setattr(pipeline_lineage, "get_creative_pack", get_script)
    monkeypatch.setattr(pipeline_lineage, "save_storyboard_asset", save)
    monkeypatch.setattr(video_content_gate, "assert_script_ready_for_media", reject)
    monkeypatch.setattr(media, "_check_daily_media_cap", cap)
    monkeypatch.setattr(media, "AIHubClient", lambda **kwargs: FakeClient())

    result = await media.generate_character_sheets.__wrapped__(
        "script-a", experiment_arm_id="arm-b"
    )

    assert result == {"ok": False, "error": "experiment_arm_missing_or_mismatch"}
    assert calls == ["gate"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content_contract",
    [
        {"version": "2026-07-16.v2"},
        {"unexpected": True},
        ["2026-07-15.v1"],
        "2026-07-15.v1",
    ],
)
async def test_character_sheets_reject_unknown_contract_before_any_side_effect(
    monkeypatch: pytest.MonkeyPatch,
    content_contract: Any,
) -> None:
    calls: list[str] = []
    script = _formal_script()
    script["content_contract"] = content_contract

    async def get_script(script_id: str) -> dict[str, Any]:
        return script

    async def gate(script_row: dict[str, Any], arm_id: str) -> dict[str, Any]:
        calls.append("gate")
        return {"ok": True}

    async def cap(kind: str) -> None:
        calls.append("cap")
        return None

    async def lineage(script_row: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def save(**kwargs: Any) -> str:
        calls.append("save")
        return "asset"

    class FakeClient:
        async def generate_image_v2(self, **kwargs: Any) -> dict[str, Any]:
            calls.append("provider")
            return {"images": [{"url": "data:image/png;base64,eA=="}]}

    monkeypatch.setattr(pipeline_lineage, "get_creative_pack", get_script)
    monkeypatch.setattr(pipeline_lineage, "gather_lineage_context", lineage)
    monkeypatch.setattr(pipeline_lineage, "save_storyboard_asset", save)
    monkeypatch.setattr(video_content_gate, "assert_script_ready_for_media", gate)
    monkeypatch.setattr(media, "_check_daily_media_cap", cap)
    monkeypatch.setattr(media, "AIHubClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(
        media,
        "get_model_for_tool",
        lambda name: {"provider": "openai", "model": "gpt-image-2"},
    )

    result = await media.generate_character_sheets.__wrapped__(
        "script-a", experiment_arm_id="arm-a"
    )

    assert result["ok"] is False
    assert result["error"] == "unsupported_video_content_contract"
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("content_contract", [None, {}])
async def test_character_sheets_empty_contract_remains_legacy(
    monkeypatch: pytest.MonkeyPatch,
    content_contract: Any,
) -> None:
    calls: list[str] = []
    script = _formal_script()
    script["content_contract"] = content_contract

    async def get_script(script_id: str) -> dict[str, Any]:
        return script

    async def gate(script_row: dict[str, Any], arm_id: str) -> dict[str, Any]:
        calls.append("gate")
        return {"ok": False}

    async def no_cap(kind: str) -> None:
        calls.append("cap")
        return None

    async def lineage(script_row: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def save(**kwargs: Any) -> str:
        calls.append("save")
        return "asset"

    class FakeClient:
        async def generate_image_v2(self, **kwargs: Any) -> dict[str, Any]:
            calls.append("provider")
            return {"images": [{"url": "data:image/png;base64,eA=="}]}

    monkeypatch.setattr(pipeline_lineage, "get_creative_pack", get_script)
    monkeypatch.setattr(pipeline_lineage, "gather_lineage_context", lineage)
    monkeypatch.setattr(pipeline_lineage, "save_storyboard_asset", save)
    monkeypatch.setattr(video_content_gate, "assert_script_ready_for_media", gate)
    monkeypatch.setattr(media, "_check_daily_media_cap", no_cap)
    monkeypatch.setattr(media, "AIHubClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(
        media,
        "get_model_for_tool",
        lambda name: {"provider": "openai", "model": "gpt-image-2"},
    )

    result = await media.generate_character_sheets.__wrapped__("script-a")

    assert result["ok"] is True
    assert calls == ["cap", "provider", "save"]


@pytest.mark.asyncio
@pytest.mark.parametrize("successes", [0, 1])
async def test_character_sheets_truthfully_report_all_fail_and_partial(
    monkeypatch: pytest.MonkeyPatch,
    successes: int,
) -> None:
    script = _formal_script(roles=2)
    provider_count = 0
    saved: list[dict[str, Any]] = []

    async def get_script(script_id: str) -> dict[str, Any]:
        return script

    async def admit(script: dict[str, Any], arm_id: str) -> dict[str, Any]:
        return {"ok": True, "experiment_arm_id": arm_id}

    async def no_cap(kind: str) -> None:
        return None

    async def no_lineage(script: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def save(**kwargs: Any) -> str:
        saved.append(kwargs)
        return f"asset-{len(saved)}"

    class FakeClient:
        async def generate_image_v2(self, **kwargs: Any) -> dict[str, Any]:
            nonlocal provider_count
            provider_count += 1
            if provider_count <= successes:
                return {"images": [{"url": "data:image/png;base64,eA=="}]}
            return {"images": []}

    monkeypatch.setattr(pipeline_lineage, "get_creative_pack", get_script)
    monkeypatch.setattr(pipeline_lineage, "gather_lineage_context", no_lineage)
    monkeypatch.setattr(pipeline_lineage, "save_storyboard_asset", save)
    monkeypatch.setattr(video_content_gate, "assert_script_ready_for_media", admit)
    monkeypatch.setattr(media, "_check_daily_media_cap", no_cap)
    monkeypatch.setattr(media, "AIHubClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(
        media,
        "get_model_for_tool",
        lambda name: {"provider": "openai", "model": "gpt-image-2"},
    )

    result = await media.generate_character_sheets.__wrapped__(
        "script-a", experiment_arm_id="arm-a"
    )

    assert result["ok"] is (successes > 0)
    assert result["partial"] is (successes == 1)
    assert len(result["successful_items"]) == successes
    assert len(result["failed_items"]) == 2 - successes
    assert len(result["retryable_role_ids"]) == 2 - successes
    assert all(item["experiment_arm_id"] == "arm-a" for item in saved)
    if successes == 0:
        assert result["error"] == "character_sheet_generation_failed"


async def _install_video_fakes(
    monkeypatch: pytest.MonkeyPatch,
    script: dict[str, Any],
    product_assets: list[dict[str, Any]],
    face_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    provider_calls: list[dict[str, Any]] = []

    async def get_script(script_id: str) -> dict[str, Any]:
        return script

    async def get_products(asset_ids: list[str]) -> list[dict[str, Any]]:
        return product_assets

    async def list_assets(**kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def list_faces(script_id: str, experiment_arm_id: str | None = None) -> list[dict[str, Any]]:
        return face_assets

    async def lineage(script: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def save(**kwargs: Any) -> None:
        return None

    async def admit(script: dict[str, Any], arm_id: str) -> dict[str, Any]:
        return {"ok": True, "experiment_arm_id": arm_id}

    async def no_cap(kind: str) -> None:
        return None

    async def pass_vector(**kwargs: Any) -> dict[str, Any]:
        return {"passed": True, "score_100": 100.0, "stage": kwargs["stage"]}

    class FakeClient:
        async def generate_video_v2(self, **kwargs: Any) -> dict[str, Any]:
            provider_calls.append(kwargs)
            return {"video_url": "https://example.test/video.mp4"}

    monkeypatch.setattr(pipeline_lineage, "get_creative_pack", get_script)
    monkeypatch.setattr(pipeline_lineage, "get_product_reference_assets", get_products)
    monkeypatch.setattr(pipeline_lineage, "list_assets", list_assets)
    monkeypatch.setattr(pipeline_lineage, "list_character_sheets_for_script", list_faces)
    monkeypatch.setattr(pipeline_lineage, "gather_lineage_context", lineage)
    monkeypatch.setattr(pipeline_lineage, "save_storyboard_asset", save)
    monkeypatch.setattr(video_content_gate, "assert_script_ready_for_media", admit)
    monkeypatch.setattr(media, "_check_daily_media_cap", no_cap)
    monkeypatch.setattr(media, "_score_vector_gate", pass_vector, raising=False)
    monkeypatch.setattr(media, "AIHubClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(
        media,
        "get_model_for_tool",
        lambda name: {"provider": "seedance", "model": "seedance-2-0"},
    )
    return provider_calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"product_refs": ["raw.png"]},
        {"allow_no_product": True},
    ],
)
async def test_formal_video_requires_registered_product_ids_before_compilation(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, Any],
) -> None:
    script = _formal_script()
    script["scenes"][0].pop("prompt_source")
    provider_calls = await _install_video_fakes(monkeypatch, script, [], [])

    result = await media.generate_video_segments.__wrapped__(
        "script-a", experiment_arm_id="arm-a", **kwargs
    )

    assert result["ok"] is False
    assert result["error"] == "missing_product_refs"
    assert provider_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_case", ["wrong_sku", "missing_file"])
async def test_formal_video_rejects_invalid_registered_product_before_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    bad_case: str,
) -> None:
    path = tmp_path / "product.png"
    if bad_case == "wrong_sku":
        path.write_bytes(b"product")
    asset = _product_asset(
        "product-1", path, sku_id="SKU-B" if bad_case == "wrong_sku" else "SKU-A"
    )
    provider_calls = await _install_video_fakes(
        monkeypatch, _formal_script(), [asset], []
    )

    result = await media.generate_video_segments.__wrapped__(
        "script-a",
        **_video_kwargs(
            experiment_arm_id="arm-a",
            product_ref_asset_ids=["product-1"],
        ),
    )

    assert result["ok"] is False
    assert result["error"] == "product_ref_invalid_or_mismatch"
    assert provider_calls == []


@pytest.mark.asyncio
async def test_formal_video_sends_current_sku_and_arm_bound_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    product_path = tmp_path / "product.png"
    face_path = tmp_path / "face.png"
    product_path.write_bytes(b"product")
    face_path.write_bytes(b"face")
    provider_calls = await _install_video_fakes(
        monkeypatch,
        _formal_script(),
        [_product_asset("product-1", product_path)],
        [_face_asset("face-1", face_path)],
    )

    result = await media.generate_video_segments.__wrapped__(
        "script-a",
        **_video_kwargs(
            experiment_arm_id="arm-a",
            product_ref_asset_ids=["product-1"],
        ),
    )

    assert result["ok"] is True
    assert len(provider_calls) == 1
    assert provider_calls[0]["face_refs"] is None
    assert provider_calls[0]["product_refs"] is None
    assert [item["type"] for item in provider_calls[0]["prepared_reference_images"]] == [
        "face",
        "product",
    ]


@pytest.mark.asyncio
async def test_formal_video_keeps_face_refs_for_equivalent_uuid_arm_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    canonical_arm = "550e8400-e29b-41d4-a716-446655440000"
    equivalent_input = "{550E8400-E29B-41D4-A716-446655440000}"
    product_path = tmp_path / "product.png"
    face_path = tmp_path / "face.png"
    product_path.write_bytes(b"product")
    face_path.write_bytes(b"face")
    provider_calls = await _install_video_fakes(
        monkeypatch,
        _formal_script(),
        [_product_asset("product-1", product_path)],
        [_face_asset("face-1", face_path, arm_id=canonical_arm)],
    )

    result = await media.generate_video_segments.__wrapped__(
        "script-a",
        **_video_kwargs(
            experiment_arm_id=equivalent_input,
            product_ref_asset_ids=["product-1"],
        ),
    )

    assert result["ok"] is True
    assert len(provider_calls) == 1
    assert [
        item["type"] for item in provider_calls[0]["prepared_reference_images"]
    ] == ["face", "product"]


@pytest.mark.asyncio
async def test_formal_video_manifest_mismatch_stops_before_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    product_path = tmp_path / "product.png"
    product_path.write_bytes(b"product")
    provider_calls = await _install_video_fakes(
        monkeypatch,
        _formal_script(),
        [_product_asset("product-1", product_path)],
        [],
    )

    def mismatched_prepare(
        face_refs: list[dict[str, Any]], product_refs: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return [], {"items": [{"id": "other", "sha256": "0" * 64}]}

    monkeypatch.setattr(
        ai_hub_client, "prepare_video_reference_images", mismatched_prepare
    )

    result = await media.generate_video_segments.__wrapped__(
        "script-a",
        **_video_kwargs(
            experiment_arm_id="arm-a",
            product_ref_asset_ids=["product-1"],
        ),
    )

    assert result["ok"] is False
    assert result["error"] == "reference_manifest_mismatch"
    assert provider_calls == []


@pytest.mark.asyncio
async def test_formal_video_force_t2v_cannot_clear_bound_references(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    product_path = tmp_path / "product.png"
    product_path.write_bytes(b"product")
    provider_calls = await _install_video_fakes(
        monkeypatch,
        _formal_script(),
        [_product_asset("product-1", product_path)],
        [],
    )

    result = await media.generate_video_segments.__wrapped__(
        "script-a",
        **_video_kwargs(
            experiment_arm_id="arm-a",
            product_ref_asset_ids=["product-1"],
            force_t2v=True,
        ),
    )

    assert result["ok"] is False
    assert result["error"] == "reference_manifest_mismatch"
    assert provider_calls == []


@pytest.mark.asyncio
async def test_formal_video_unsupported_model_cannot_clear_bound_references(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    product_path = tmp_path / "product.png"
    product_path.write_bytes(b"product")
    provider_calls = await _install_video_fakes(
        monkeypatch,
        _formal_script(),
        [_product_asset("product-1", product_path)],
        [],
    )

    result = await media.generate_video_segments.__wrapped__(
        "script-a",
        **_video_kwargs(
            experiment_arm_id="arm-a",
            product_ref_asset_ids=["product-1"],
            model_override="seedance-1-0",
        ),
    )

    assert result["ok"] is False
    assert result["error"] == "reference_manifest_mismatch"
    assert provider_calls == []
