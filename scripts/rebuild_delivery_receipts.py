#!/usr/bin/env python3
"""Rebuild the verified delivery-receipt cache from a versioned manifest.

The cache is evidence, not authority. Every payload is downloaded from its exact
GitHub Actions artifact, checked against the manifest, verified against the
immutable repository contracts and live workflow provenance, then written
atomically below the Git common directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

import yaml

import generate_implementation_status as projection


DEFAULT_MANIFEST = Path(
    "docs/dev-changes/2026-08-02-omni-unified-ai-workbench-w0/"
    "path-ownership-fingerprint.yaml"
)
HEX_40 = re.compile(r"[0-9a-f]{40}")
HEX_64 = re.compile(r"[0-9a-f]{64}")


class ReceiptRecoveryError(ValueError):
    """The versioned recovery declaration or live evidence failed validation."""


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReceiptRecoveryError(f"{label} must be a mapping")
    return value


def _text(entry: Mapping[str, Any], key: str) -> str:
    value = str(entry.get(key) or "").strip()
    if not value:
        raise ReceiptRecoveryError(f"verified delivery is missing {key}")
    return value


def load_deliveries(manifest: Path) -> list[Mapping[str, Any]]:
    try:
        document = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ReceiptRecoveryError(f"cannot read recovery manifest: {exc}") from exc
    root = _mapping(document, "manifest")
    deliveries = root.get("verified_deliveries")
    if not isinstance(deliveries, list) or not deliveries:
        raise ReceiptRecoveryError("manifest verified_deliveries must be a non-empty list")
    if len(deliveries) > projection.RECEIPT_CACHE_MAX_FILES:
        raise ReceiptRecoveryError("manifest exceeds maximum receipt count")
    normalized = [_mapping(item, "verified delivery") for item in deliveries]
    for field in ("change_id", "artifact_id", "workflow_run_id", "cache_path"):
        values = [_text(item, field) for item in normalized]
        if len(values) != len(set(values)):
            raise ReceiptRecoveryError(f"manifest contains duplicate {field} values")
    return normalized


def _cache_nested(cache_path: object) -> PurePosixPath:
    raw = str(cache_path or "").strip()
    if not raw or "\\" in raw:
        raise ReceiptRecoveryError("cache_path must be a non-empty POSIX path")
    relative = PurePosixPath(raw)
    expected_prefix = PurePosixPath("omni-delivery/verified-receipts")
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".json":
        raise ReceiptRecoveryError(f"unsafe cache_path: {raw}")
    try:
        nested = relative.relative_to(expected_prefix)
    except ValueError as exc:
        raise ReceiptRecoveryError(f"cache_path is outside verified receipt cache: {raw}") from exc
    if not nested.parts:
        raise ReceiptRecoveryError(f"cache_path must name a JSON file: {raw}")
    if len(nested.parts) - 1 > projection.RECEIPT_CACHE_MAX_DEPTH:
        raise ReceiptRecoveryError(f"cache_path exceeds maximum depth: {raw}")

    return nested


def safe_cache_target(root: Path, cache_path: object) -> Path:
    nested = _cache_nested(cache_path)
    raw = str(cache_path)
    try:
        cache_root = projection._validated_cache_root(root)
    except projection.ProjectionInputError as exc:
        raise ReceiptRecoveryError(str(exc)) from exc
    target = cache_root.joinpath(*nested.parts)
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(cache_root)
    except ValueError as exc:
        raise ReceiptRecoveryError(f"cache_path resolves outside verified receipt cache: {raw}") from exc

    cursor = cache_root
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    for part in nested.parts:
        cursor = cursor / part
        if cursor.is_symlink() or is_junction(cursor):
            raise ReceiptRecoveryError(f"cache_path traverses a symbolic link: {raw}")
    return target


def _artifact_metadata(root: Path, repository: str, artifact_id: str) -> Mapping[str, Any]:
    result = projection._run(
        ("gh", "api", f"repos/{repository}/actions/artifacts/{artifact_id}"),
        cwd=root,
        timeout=15,
    )
    try:
        return _mapping(json.loads(result.stdout), "GitHub artifact metadata")
    except json.JSONDecodeError as exc:
        raise ReceiptRecoveryError("GitHub artifact metadata is not valid JSON") from exc


def _validate_declared_artifact(
    entry: Mapping[str, Any], metadata: Mapping[str, Any]
) -> None:
    artifact_id = _text(entry, "artifact_id")
    run_id = _text(entry, "workflow_run_id")
    artifact_name = _text(entry, "artifact_name")
    artifact_digest = _text(entry, "artifact_digest")
    subject = _text(entry, "subject_commit").lower()
    raw_sha256 = _text(entry, "raw_sha256").lower()
    if not artifact_id.isdigit() or not run_id.isdigit():
        raise ReceiptRecoveryError("artifact_id and workflow_run_id must be decimal identifiers")
    if HEX_40.fullmatch(subject) is None or HEX_64.fullmatch(raw_sha256) is None:
        raise ReceiptRecoveryError("subject_commit or raw_sha256 has an invalid format")
    if str(metadata.get("id") or "") != artifact_id:
        raise ReceiptRecoveryError(f"artifact id drift for {artifact_id}")
    if str(metadata.get("name") or "") != artifact_name:
        raise ReceiptRecoveryError(f"artifact name drift for {artifact_id}")
    if metadata.get("expired") is not False:
        raise ReceiptRecoveryError(f"artifact is expired or expiry is unknown: {artifact_id}")
    if str(metadata.get("digest") or "") != artifact_digest:
        raise ReceiptRecoveryError(f"artifact digest drift for {artifact_id}")
    workflow_run = _mapping(metadata.get("workflow_run"), "artifact workflow_run")
    if str(workflow_run.get("id") or "") != run_id:
        raise ReceiptRecoveryError(f"artifact workflow run drift for {artifact_id}")


def _open_cache_parent(root: Path, nested: PurePosixPath, *, create: bool) -> tuple[int, str]:
    required = {os.open, os.mkdir, os.link, os.unlink}
    if not required.issubset(os.supports_dir_fd) or not hasattr(os, "O_NOFOLLOW"):
        raise ReceiptRecoveryError("secure receipt-cache publication is unsupported on this platform")
    common = projection.git_common_dir(root).resolve()
    descriptor = os.open(common, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in ("omni-delivery", "verified-receipts", *nested.parts[:-1]):
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
            os.close(descriptor)
            descriptor = child
        return descriptor, nested.parts[-1]
    except BaseException:
        os.close(descriptor)
        raise


def _read_from_parent(parent_fd: int, leaf: str, expected: bytes) -> bool:
    try:
        descriptor = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ReceiptRecoveryError(f"cannot securely open existing receipt: {leaf}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > projection.RECEIPT_CACHE_MAX_FILE_BYTES:
            raise ReceiptRecoveryError(f"existing receipt target is not a bounded regular file: {leaf}")
        chunks: list[bytes] = []
        remaining = projection.RECEIPT_CACHE_MAX_FILE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        observed = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(observed) != metadata.st_size:
        raise ReceiptRecoveryError(f"existing receipt changed while being read: {leaf}")
    if observed != expected:
        raise ReceiptRecoveryError(f"existing receipt differs from verified artifact: {leaf}")
    return True


def _read_existing(root: Path, nested: PurePosixPath, expected: bytes) -> bool:
    try:
        parent_fd, leaf = _open_cache_parent(root, nested, create=False)
    except FileNotFoundError:
        return False
    try:
        return _read_from_parent(parent_fd, leaf, expected)
    finally:
        os.close(parent_fd)


def _publish_new(root: Path, nested: PurePosixPath, raw: bytes) -> tuple[bool, int | None]:
    """Publish without replacement and retain the parent handle for safe rollback."""

    parent_fd, leaf = _open_cache_parent(root, nested, create=True)
    if _read_from_parent(parent_fd, leaf, raw):
        os.close(parent_fd)
        return False, None
    temporary = f".{leaf}.{os.getpid()}.{secrets.token_hex(8)}"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=parent_fd,
    )
    retain_parent = False
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(
                temporary,
                leaf,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            if _read_from_parent(parent_fd, leaf, raw):
                return False, None
            raise
        retain_parent = True
        return True, parent_fd
    finally:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        finally:
            if not retain_parent:
                os.close(parent_fd)


def _rollback_created(created: list[tuple[int, str, str]]) -> None:
    failures: list[str] = []
    for parent_fd, leaf, expected_hash in reversed(created):
        try:
            descriptor = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                observed_hash = hashlib.sha256(stream.read(projection.RECEIPT_CACHE_MAX_FILE_BYTES + 1)).hexdigest()
            if observed_hash != expected_hash:
                failures.append(leaf)
                continue
            os.unlink(leaf, dir_fd=parent_fd)
        except OSError:
            failures.append(leaf)
        finally:
            os.close(parent_fd)
    if failures:
        raise ReceiptRecoveryError(
            "recovery rollback could not safely remove changed created paths: "
            + ", ".join(failures)
        )


def rebuild_receipts(root: Path, manifest: Path, *, dry_run: bool = False) -> dict[str, Any]:
    root = root.resolve()
    manifest = manifest.resolve()
    try:
        manifest_relative = manifest.relative_to(root)
    except ValueError as exc:
        raise ReceiptRecoveryError("recovery manifest must be inside the repository") from exc
    if manifest.is_symlink() or not manifest.is_file():
        raise ReceiptRecoveryError("recovery manifest must be a regular repository file")
    tracked = projection._run(
        ("git", "ls-files", "--error-unmatch", "--", manifest_relative.as_posix()),
        cwd=root,
        check=False,
    )
    if tracked.returncode != 0:
        raise ReceiptRecoveryError("recovery manifest must be tracked by Git")
    unchanged = projection._run(
        ("git", "diff", "--quiet", "HEAD", "--", manifest_relative.as_posix()),
        cwd=root,
        check=False,
    )
    if unchanged.returncode != 0:
        raise ReceiptRecoveryError("recovery manifest must match the committed Git version")
    repository = projection.repository_identity(root)
    if not repository:
        raise ReceiptRecoveryError("cannot resolve GitHub repository identity from origin")
    deliveries = load_deliveries(manifest)
    verifier = projection.bounded_live_provenance(60)
    validated: list[tuple[Mapping[str, Any], bytes, PurePosixPath, Path]] = []
    total_raw_bytes = 0

    for entry in deliveries:
        artifact_id = _text(entry, "artifact_id")
        metadata = _artifact_metadata(root, repository, artifact_id)
        _validate_declared_artifact(entry, metadata)
        raw = projection._download_attestation_bytes(root, repository, metadata)
        if len(raw) > projection.RECEIPT_CACHE_MAX_FILE_BYTES:
            raise ReceiptRecoveryError(f"attestation exceeds maximum file size: {artifact_id}")
        total_raw_bytes += len(raw)
        if total_raw_bytes > projection.RECEIPT_CACHE_MAX_TOTAL_BYTES:
            raise ReceiptRecoveryError("attestations exceed maximum total size")
        observed_hash = hashlib.sha256(raw).hexdigest()
        expected_hash = _text(entry, "raw_sha256").lower()
        if observed_hash != expected_hash:
            raise ReceiptRecoveryError(f"raw attestation hash drift for artifact {artifact_id}")
        try:
            receipt = _mapping(json.loads(raw.decode("utf-8")), "delivery attestation")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReceiptRecoveryError(f"invalid attestation JSON for artifact {artifact_id}") from exc
        change_id = _text(entry, "change_id")
        if str(receipt.get("subject_commit") or "").lower() != _text(entry, "subject_commit").lower():
            raise ReceiptRecoveryError(f"subject commit drift for artifact {artifact_id}")
        verified = projection.verify_delivery_receipt(
            root,
            receipt,
            change_id,
            provenance_verifier=verifier,
        )
        if verified.get("valid") is not True:
            reasons = ",".join(str(item) for item in verified.get("reasons", []))
            raise ReceiptRecoveryError(
                f"delivery receipt verification failed for {change_id}: {reasons or 'unknown'}"
            )
        nested = _cache_nested(entry.get("cache_path"))
        target = safe_cache_target(root, entry.get("cache_path"))
        _read_existing(root, nested, raw)
        validated.append((entry, raw, nested, target))

    restored: list[dict[str, str]] = []
    created: list[tuple[int, str, str]] = []
    try:
        for entry, raw, nested, target in validated:
            was_created, parent_fd = (
                (False, None) if dry_run else _publish_new(root, nested, raw)
            )
            if was_created:
                assert parent_fd is not None
                created.append((parent_fd, nested.parts[-1], hashlib.sha256(raw).hexdigest()))
            status = "verified" if dry_run else ("restored" if was_created else "existing")
            artifact_id = _text(entry, "artifact_id")
            change_id = _text(entry, "change_id")
            restored.append(
                {
                    "change_id": change_id,
                    "subject_commit": _text(entry, "subject_commit").lower(),
                    "artifact_id": artifact_id,
                    "cache_path": str(target.relative_to(projection.git_common_dir(root))),
                    "status": status,
                }
            )
    except BaseException as exc:
        try:
            _rollback_created(created)
        except ReceiptRecoveryError as rollback_exc:
            raise rollback_exc from exc
        raise
    for parent_fd, _leaf, _expected_hash in created:
        os.close(parent_fd)
    return {
        "schema_version": 1,
        "repository": repository,
        "manifest": manifest_relative.as_posix(),
        "dry_run": dry_run,
        "receipt_count": len(restored),
        "receipts": restored,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        root = projection.repository_root(Path.cwd())
        manifest = args.manifest if args.manifest.is_absolute() else root / args.manifest
        result = rebuild_receipts(root, manifest.resolve(), dry_run=args.dry_run)
    except (ReceiptRecoveryError, projection.ProjectionInputError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
