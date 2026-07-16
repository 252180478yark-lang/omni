"""Fail-closed reference-image manifests for formal AI video generation."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID


PRODUCT_REF_ERROR = "product_ref_invalid_or_mismatch"
MANIFEST_ERROR = "reference_manifest_mismatch"


class ReferenceManifestError(ValueError):
    """Stable, caller-visible reference admission error."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail or code
        super().__init__(f"{code}: {self.detail}")


def _canonical_arm_id(value: Any) -> str:
    """Canonicalize valid UUID spellings while preserving legacy opaque IDs."""

    raw = str(value or "").strip()
    if not raw:
        return raw
    try:
        return str(UUID(raw))
    except (AttributeError, ValueError):
        return raw


def resolve_reference_path(value: str | Path) -> Path:
    """Resolve a real local file, including omni's public static URL form."""

    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise FileNotFoundError("empty reference path")
    raw = str(value).strip()

    # A real filesystem path wins. This also canonicalizes aliases/symlinks so
    # registration can reject the same physical file under another SKU.
    try:
        direct = Path(raw).expanduser()
        if direct.is_file():
            resolved = direct.resolve(strict=True)
            with resolved.open("rb") as stream:
                stream.read(1)
            return resolved
    except (OSError, RuntimeError, ValueError):
        pass

    from app.services.asset_storage import get_disk_path_for_public_url

    mapped = get_disk_path_for_public_url(raw)
    if mapped is None:
        raise FileNotFoundError(raw)
    try:
        resolved = mapped.expanduser().resolve(strict=True)
        if not resolved.is_file():
            raise FileNotFoundError(raw)
        with resolved.open("rb") as stream:
            stream.read(1)
        return resolved
    except (OSError, RuntimeError, ValueError) as exc:
        raise FileNotFoundError(raw) from exc


def sha256_reference(path: str | Path) -> str:
    """Hash bytes from the resolved local file, never the URL/path string."""

    resolved = resolve_reference_path(path)
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_file_ref(asset: Mapping[str, Any]) -> str:
    value = asset.get("file_url") or asset.get("file_ref") or asset.get("path")
    if not isinstance(value, str) or not value.strip():
        raise FileNotFoundError("asset has no local file reference")
    return value.strip()


def _manifest_item(asset: Mapping[str, Any], reference_type: str) -> dict[str, str]:
    asset_id = asset.get("id")
    if not isinstance(asset_id, str) or not asset_id.strip():
        raise ValueError("asset id missing")
    file_ref = _asset_file_ref(asset)
    path = resolve_reference_path(file_ref)
    return {
        "id": asset_id.strip(),
        "type": reference_type,
        "sha256": sha256_reference(path),
        "file_ref": file_ref,
        "resolved_path": str(path),
    }


def build_reference_manifest(
    sku_id: str,
    arm_id: str,
    face_assets: Sequence[Mapping[str, Any]],
    product_assets: Sequence[Mapping[str, Any]],
    provider: str,
    model: str,
) -> dict[str, Any]:
    """Build the ordered expected manifest for one formal video request.

    Face assets from another arm are deliberately excluded. Product assets are
    stricter: any wrong SKU/type/status/ownership or unreadable file rejects the
    complete request.
    """

    canonical_arm_id = _canonical_arm_id(arm_id)
    if not canonical_arm_id:
        raise ReferenceManifestError(MANIFEST_ERROR, "experiment arm id missing")
    items: list[dict[str, str]] = []
    for asset in face_assets:
        if not isinstance(asset, Mapping):
            continue
        if _canonical_arm_id(asset.get("experiment_arm_id")) != canonical_arm_id:
            continue
        if asset.get("asset_type") != "character_sheet" or asset.get("sku_id") != sku_id:
            raise ReferenceManifestError(MANIFEST_ERROR, "invalid character asset ownership")
        try:
            items.append(_manifest_item(asset, "face"))
        except (OSError, ValueError) as exc:
            raise ReferenceManifestError(MANIFEST_ERROR, str(exc)) from exc

    for asset in product_assets:
        valid = (
            isinstance(asset, Mapping)
            and asset.get("asset_type") == "product_reference"
            and asset.get("sku_id") == sku_id
            and asset.get("status") == "adopted"
            and asset.get("script_id") is None
            and asset.get("experiment_arm_id") is None
            and asset.get("generation_set_id") is None
        )
        if not valid:
            raise ReferenceManifestError(PRODUCT_REF_ERROR, "invalid product asset ownership")
        try:
            items.append(_manifest_item(asset, "product"))
        except (OSError, ValueError) as exc:
            raise ReferenceManifestError(PRODUCT_REF_ERROR, str(exc)) from exc

    return {
        "sku_id": sku_id,
        "experiment_arm_id": canonical_arm_id,
        "provider": provider,
        "model": model,
        "items": items,
    }


def reference_manifest_pairs(manifest: Mapping[str, Any]) -> list[tuple[str, str]]:
    raw_items = manifest.get("items")
    if not isinstance(raw_items, list):
        raise ReferenceManifestError(MANIFEST_ERROR, "manifest items missing")
    pairs: list[tuple[str, str]] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            raise ReferenceManifestError(MANIFEST_ERROR, "manifest item invalid")
        asset_id = item.get("id")
        sha256 = item.get("sha256")
        if not isinstance(asset_id, str) or not isinstance(sha256, str):
            raise ReferenceManifestError(MANIFEST_ERROR, "manifest pair invalid")
        pairs.append((asset_id, sha256))
    return pairs


def assert_reference_manifest_matches(
    expected: Mapping[str, Any], sent: Mapping[str, Any]
) -> None:
    """Require the exact ordered ``(asset id, final-byte sha256)`` sequence."""

    if reference_manifest_pairs(expected) != reference_manifest_pairs(sent):
        raise ReferenceManifestError(MANIFEST_ERROR, "expected and sent references differ")


__all__ = [
    "MANIFEST_ERROR",
    "PRODUCT_REF_ERROR",
    "ReferenceManifestError",
    "assert_reference_manifest_matches",
    "build_reference_manifest",
    "reference_manifest_pairs",
    "resolve_reference_path",
    "sha256_reference",
]
