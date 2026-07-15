from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

import pytest

from app.services import ai_hub_client


def _product(asset_id: str, path: Path, *, sku_id: str = "SKU-A") -> dict[str, Any]:
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


def _face(asset_id: str, path: Path, *, arm_id: str = "arm-a") -> dict[str, Any]:
    return {
        "id": asset_id,
        "sku_id": "SKU-A",
        "asset_type": "character_sheet",
        "file_url": str(path),
        "status": "draft",
        "script_id": "script-a",
        "experiment_arm_id": arm_id,
        "generation_set_id": None,
    }


def test_sha256_reference_hashes_file_bytes_and_changes_with_bytes(tmp_path: Path) -> None:
    from app.services.media_reference_manifest import sha256_reference

    path = tmp_path / "product.png"
    path.write_bytes(b"first-image-bytes")
    first = sha256_reference(path)

    path.write_bytes(b"second-image-bytes")
    second = sha256_reference(path)

    assert first == hashlib.sha256(b"first-image-bytes").hexdigest()
    assert second == hashlib.sha256(b"second-image-bytes").hexdigest()
    assert first != second


def test_manifest_preserves_order_and_exact_pair_compare_rejects_wrong_order(
    tmp_path: Path,
) -> None:
    from app.services.media_reference_manifest import (
        ReferenceManifestError,
        assert_reference_manifest_matches,
        build_reference_manifest,
    )

    face_path = tmp_path / "face.png"
    product_a_path = tmp_path / "product-a.png"
    product_b_path = tmp_path / "product-b.png"
    face_path.write_bytes(b"face")
    product_a_path.write_bytes(b"product-a")
    product_b_path.write_bytes(b"product-b")

    expected = build_reference_manifest(
        sku_id="SKU-A",
        arm_id="arm-a",
        face_assets=[_face("face-1", face_path)],
        product_assets=[
            _product("product-1", product_a_path),
            _product("product-2", product_b_path),
        ],
        provider="seedance",
        model="seedance-2-0",
    )
    assert [item["id"] for item in expected["items"]] == [
        "face-1",
        "product-1",
        "product-2",
    ]

    sent = {"items": list(reversed(expected["items"]))}
    with pytest.raises(ReferenceManifestError) as exc_info:
        assert_reference_manifest_matches(expected, sent)
    assert exc_info.value.code == "reference_manifest_mismatch"


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (lambda asset: asset.update(sku_id="SKU-B"), "product_ref_invalid_or_mismatch"),
        (lambda asset: asset.update(script_id="script-a"), "product_ref_invalid_or_mismatch"),
        (lambda asset: asset.update(experiment_arm_id="arm-a"), "product_ref_invalid_or_mismatch"),
        (lambda asset: asset.update(generation_set_id="set-a"), "product_ref_invalid_or_mismatch"),
    ],
)
def test_product_reference_must_belong_only_to_current_sku(
    tmp_path: Path,
    mutate: Any,
    expected_error: str,
) -> None:
    from app.services.media_reference_manifest import (
        ReferenceManifestError,
        build_reference_manifest,
    )

    path = tmp_path / "product.png"
    path.write_bytes(b"product")
    asset = _product("product-1", path)
    mutate(asset)

    with pytest.raises(ReferenceManifestError) as exc_info:
        build_reference_manifest(
            sku_id="SKU-A",
            arm_id="arm-a",
            face_assets=[],
            product_assets=[asset],
            provider="seedance",
            model="seedance-2-0",
        )
    assert exc_info.value.code == expected_error


def test_manifest_rejects_missing_product_file(tmp_path: Path) -> None:
    from app.services.media_reference_manifest import (
        ReferenceManifestError,
        build_reference_manifest,
    )

    with pytest.raises(ReferenceManifestError) as exc_info:
        build_reference_manifest(
            sku_id="SKU-A",
            arm_id="arm-a",
            face_assets=[],
            product_assets=[_product("product-1", tmp_path / "missing.png")],
            provider="seedance",
            model="seedance-2-0",
        )
    assert exc_info.value.code == "product_ref_invalid_or_mismatch"


def test_character_asset_from_other_arm_is_excluded(tmp_path: Path) -> None:
    from app.services.media_reference_manifest import build_reference_manifest

    accepted_path = tmp_path / "accepted.png"
    foreign_path = tmp_path / "foreign.png"
    accepted_path.write_bytes(b"accepted")
    foreign_path.write_bytes(b"foreign")

    manifest = build_reference_manifest(
        sku_id="SKU-A",
        arm_id="arm-a",
        face_assets=[
            _face("foreign", foreign_path, arm_id="arm-b"),
            _face("accepted", accepted_path, arm_id="arm-a"),
        ],
        product_assets=[],
        provider="seedance",
        model="seedance-2-0",
    )

    assert [item["id"] for item in manifest["items"]] == ["accepted"]


@pytest.mark.parametrize(
    "value",
    [
        "https://example.test/ref.png",
        "data:image/png,not-base64",
        "data:;base64,Zm9v",
        "data:image/png;base64,not-valid-***",
    ],
)
def test_decode_data_url_bytes_is_strict(value: str) -> None:
    with pytest.raises(ValueError, match="invalid_reference_data_url"):
        ai_hub_client.decode_data_url_bytes(value)


def test_prepare_video_reference_images_hashes_final_serialized_bytes(
    tmp_path: Path,
) -> None:
    face_path = tmp_path / "face.png"
    product_path = tmp_path / "product.png"
    face_path.write_bytes(b"face-final-bytes")
    product_path.write_bytes(b"product-final-bytes")

    prepared, sent = ai_hub_client.prepare_video_reference_images(
        [_face("face-1", face_path)],
        [_product("product-1", product_path)],
    )

    assert [item["type"] for item in prepared] == ["face", "product"]
    assert [item["id"] for item in sent["items"]] == ["face-1", "product-1"]
    assert ai_hub_client.decode_data_url_bytes(prepared[0]["url"]) == b"face-final-bytes"
    assert ai_hub_client.decode_data_url_bytes(prepared[1]["url"]) == b"product-final-bytes"
    assert sent["items"][0]["sha256"] == hashlib.sha256(b"face-final-bytes").hexdigest()
    assert sent["items"][1]["sha256"] == hashlib.sha256(b"product-final-bytes").hexdigest()


@pytest.mark.asyncio
async def test_generate_video_v2_sends_prepared_bytes_without_relocalizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    raw_face = b"serialized-face"
    raw_product = b"serialized-product"
    prepared = [
        {
            "url": "data:image/png;base64," + base64.b64encode(raw_face).decode("ascii"),
            "type": "face",
            "weight": 1.0,
        },
        {
            "url": "data:image/webp;base64," + base64.b64encode(raw_product).decode("ascii"),
            "type": "product",
            "weight": 1.0,
        },
    ]
    sent_manifest = {
        "items": [
            {"id": "face-1", "sha256": hashlib.sha256(raw_face).hexdigest()},
            {"id": "product-1", "sha256": hashlib.sha256(raw_product).hexdigest()},
        ]
    }

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, Any]:
            return {"task_id": "task-1"}

    class FakeAsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, *, json: dict[str, Any]) -> FakeResponse:
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(ai_hub_client.httpx, "AsyncClient", FakeAsyncClient)

    client = ai_hub_client.AIHubClient(base_url="http://hub.test")
    result = await client.generate_video_v2(
        prompt="prompt",
        prepared_reference_images=prepared,
    )

    assert result == {"task_id": "task-1"}
    assert captured["json"]["reference_images"] == prepared
    body_hashes = [
        hashlib.sha256(ai_hub_client.decode_data_url_bytes(item["url"])).hexdigest()
        for item in captured["json"]["reference_images"]
    ]
    assert body_hashes == [item["sha256"] for item in sent_manifest["items"]]


@pytest.mark.asyncio
async def test_prepared_reference_images_cannot_be_overridden_by_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    prepared = [
        {
            "url": "data:image/png;base64," + base64.b64encode(b"bound").decode("ascii"),
            "type": "product",
            "weight": 1.0,
        }
    ]

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, Any]:
            return {"task_id": "task-1"}

    class FakeAsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, *, json: dict[str, Any]) -> FakeResponse:
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(ai_hub_client.httpx, "AsyncClient", FakeAsyncClient)

    await ai_hub_client.AIHubClient(base_url="http://hub.test").generate_video_v2(
        prompt="prompt",
        prepared_reference_images=prepared,
        extra={"reference_images": [{"url": "https://evil.test/override.png"}]},
    )

    assert captured["json"]["reference_images"] == prepared
