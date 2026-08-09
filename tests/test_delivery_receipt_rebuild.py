from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "omni_delivery_receipt_rebuild_tests", SCRIPTS / "rebuild_delivery_receipts.py"
)
assert SPEC is not None and SPEC.loader is not None
rebuild = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rebuild
SPEC.loader.exec_module(rebuild)


def _run(repo: Path, *args: str) -> str:
    result = subprocess.run(args, cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-q", "-b", "main")
    _run(repo, "git", "config", "user.email", "test@example.com")
    _run(repo, "git", "config", "user.name", "Test")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-qm", "fixture")
    return repo


def _manifest(repo: Path, raw: bytes) -> tuple[Path, dict]:
    subject = _run(repo, "git", "rev-parse", "HEAD")
    entry = {
        "change_id": "fixture-delivery",
        "subject_commit": subject,
        "workflow_run_id": "123",
        "artifact_id": "456",
        "artifact_name": f"delivery-attestation-{subject}",
        "artifact_digest": "sha256:" + "a" * 64,
        "cache_path": "omni-delivery/verified-receipts/w0/123-receipt.json",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
    }
    path = repo / "manifest.yaml"
    path.write_text(yaml.safe_dump({"verified_deliveries": [entry]}), encoding="utf-8")
    _run(repo, "git", "add", "manifest.yaml")
    _run(repo, "git", "commit", "-qm", "manifest")
    return path, entry


@pytest.mark.parametrize(
    "cache_path",
    [
        "../receipt.json",
        "/tmp/receipt.json",
        "omni-delivery/receipt.json",
        "omni-delivery/verified-receipts/../../receipt.json",
        "omni-delivery\\verified-receipts\\receipt.json",
        "omni-delivery/verified-receipts/not-json.txt",
    ],
)
def test_safe_cache_target_rejects_escape_and_non_json(tmp_path: Path, cache_path: str) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(rebuild.ReceiptRecoveryError):
        rebuild.safe_cache_target(repo, cache_path)


def test_safe_cache_target_rejects_symlinked_parent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    cache = rebuild.projection.receipt_cache_dir(repo)
    cache.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (cache / "w0").symlink_to(outside, target_is_directory=True)

    with pytest.raises(rebuild.ReceiptRecoveryError, match="outside|symbolic link"):
        rebuild.safe_cache_target(
            repo, "omni-delivery/verified-receipts/w0/receipt.json"
        )


def test_safe_cache_target_rejects_symlinked_cache_ancestor(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside-cache"
    outside.mkdir()
    (repo / ".git" / "omni-delivery").symlink_to(outside, target_is_directory=True)

    with pytest.raises(rebuild.ReceiptRecoveryError, match="ancestry"):
        rebuild.safe_cache_target(
            repo, "omni-delivery/verified-receipts/w0/receipt.json"
        )


def test_external_manifest_fails_before_any_network_or_cache_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    manifest = tmp_path / "external.yaml"
    manifest.write_text("verified_deliveries: []\n", encoding="utf-8")
    monkeypatch.setattr(
        rebuild.projection,
        "repository_identity",
        lambda _root: pytest.fail("network setup must not run for an external manifest"),
    )

    with pytest.raises(rebuild.ReceiptRecoveryError, match="inside the repository"):
        rebuild.rebuild_receipts(repo, manifest)

    assert not rebuild.projection.receipt_cache_dir(repo).exists()


def test_rebuild_validates_and_atomically_restores_manifest_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    subject = _run(repo, "git", "rev-parse", "HEAD")
    receipt = {"subject_commit": subject, "contracts": [{"change_id": "fixture-delivery"}]}
    raw = json.dumps(receipt, sort_keys=True).encode("utf-8")
    manifest, entry = _manifest(repo, raw)
    metadata = {
        "id": 456,
        "name": entry["artifact_name"],
        "digest": entry["artifact_digest"],
        "expired": False,
        "workflow_run": {"id": 123},
    }
    monkeypatch.setattr(rebuild.projection, "repository_identity", lambda _root: "fixture/repo")
    monkeypatch.setattr(rebuild, "_artifact_metadata", lambda *_args: metadata)
    monkeypatch.setattr(rebuild.projection, "_download_attestation_bytes", lambda *_args, **_kwargs: raw)
    monkeypatch.setattr(
        rebuild.projection,
        "verify_delivery_receipt",
        lambda *_args, **_kwargs: {"valid": True, "reasons": []},
    )

    result = rebuild.rebuild_receipts(repo, manifest)
    target = rebuild.safe_cache_target(repo, entry["cache_path"])

    assert result["receipt_count"] == 1
    assert result["receipts"][0]["status"] == "restored"
    assert target.read_bytes() == raw
    assert not list(target.parent.glob(f".{target.name}.*"))

    repeated = rebuild.rebuild_receipts(repo, manifest)
    assert repeated["receipts"][0]["status"] == "existing"


def test_rebuild_supplies_the_raw_hash_verified_payload_to_live_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    subject = _run(repo, "git", "rev-parse", "HEAD")
    receipt = {"subject_commit": subject, "contracts": [{"change_id": "fixture-delivery"}]}
    raw = json.dumps(receipt, sort_keys=True).encode("utf-8")
    manifest, entry = _manifest(repo, raw)
    metadata = {
        "id": 456,
        "name": entry["artifact_name"],
        "digest": entry["artifact_digest"],
        "expired": False,
        "workflow_run": {"id": 123},
    }
    captured: list[object] = []

    monkeypatch.setattr(rebuild.projection, "repository_identity", lambda _root: "fixture/repo")
    monkeypatch.setattr(rebuild, "_artifact_metadata", lambda *_args: metadata)
    monkeypatch.setattr(rebuild.projection, "_download_attestation_bytes", lambda *_args, **_kwargs: raw)

    def live(_root, _receipt, _path=None, *, deadline=None, authoritative_receipt=None):
        assert deadline is not None
        captured.append(authoritative_receipt)
        return {"valid": True, "reasons": [], "checks_passed": True}

    monkeypatch.setattr(rebuild.projection, "live_github_provenance", live)
    monkeypatch.setattr(
        rebuild.projection,
        "verify_delivery_receipt",
        lambda _root, current, _change_id, **kwargs: {
            "valid": kwargs["provenance_verifier"](_root, current)["valid"],
            "reasons": [],
        },
    )

    result = rebuild.rebuild_receipts(repo, manifest, dry_run=True)

    assert result["receipt_count"] == 1
    assert captured == [receipt]


def test_rebuild_never_overwrites_different_existing_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    subject = _run(repo, "git", "rev-parse", "HEAD")
    raw = json.dumps({"subject_commit": subject}).encode("utf-8")
    manifest, entry = _manifest(repo, raw)
    target = rebuild.safe_cache_target(repo, entry["cache_path"])
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing-user-evidence")
    metadata = {
        "id": 456,
        "name": entry["artifact_name"],
        "digest": entry["artifact_digest"],
        "expired": False,
        "workflow_run": {"id": 123},
    }
    monkeypatch.setattr(rebuild.projection, "repository_identity", lambda _root: "fixture/repo")
    monkeypatch.setattr(rebuild, "_artifact_metadata", lambda *_args: metadata)
    monkeypatch.setattr(rebuild.projection, "_download_attestation_bytes", lambda *_args, **_kwargs: raw)
    monkeypatch.setattr(
        rebuild.projection,
        "verify_delivery_receipt",
        lambda *_args, **_kwargs: {"valid": True, "reasons": []},
    )

    with pytest.raises(rebuild.ReceiptRecoveryError, match="differs"):
        rebuild.rebuild_receipts(repo, manifest)

    assert target.read_bytes() == b"existing-user-evidence"


def test_exclusive_publication_treats_identical_race_as_idempotent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    nested = rebuild._cache_nested(
        "omni-delivery/verified-receipts/w0/race.json"
    )
    raw = b'{"fixture":true}'

    first_created, first_parent = rebuild._publish_new(repo, nested, raw)
    second_created, second_parent = rebuild._publish_new(repo, nested, raw)

    assert first_created is True and first_parent is not None
    assert second_created is False and second_parent is None
    assert rebuild._read_existing(repo, nested, raw) is True
    first_parent and rebuild.os.close(first_parent)


def test_partial_publication_failure_rolls_back_only_created_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    subject = _run(repo, "git", "rev-parse", "HEAD")
    raw_by_id = {
        "456": json.dumps({"subject_commit": subject, "id": 1}).encode(),
        "457": json.dumps({"subject_commit": subject, "id": 2}).encode(),
    }
    manifest, first = _manifest(repo, raw_by_id["456"])
    second = dict(first)
    second.update(
        {
            "change_id": "fixture-delivery-two",
            "workflow_run_id": "124",
            "artifact_id": "457",
            "artifact_name": f"delivery-attestation-two-{subject}",
            "cache_path": "omni-delivery/verified-receipts/w0/124-receipt.json",
            "raw_sha256": hashlib.sha256(raw_by_id["457"]).hexdigest(),
        }
    )
    manifest.write_text(
        yaml.safe_dump({"verified_deliveries": [first, second]}), encoding="utf-8"
    )
    _run(repo, "git", "add", "manifest.yaml")
    _run(repo, "git", "commit", "-qm", "two receipts")
    monkeypatch.setattr(rebuild.projection, "repository_identity", lambda _root: "fixture/repo")
    monkeypatch.setattr(
        rebuild,
        "_artifact_metadata",
        lambda _root, _repository, artifact_id: {
            "id": int(artifact_id),
            "name": first["artifact_name"] if artifact_id == "456" else second["artifact_name"],
            "digest": first["artifact_digest"],
            "expired": False,
            "workflow_run": {"id": 123 if artifact_id == "456" else 124},
        },
    )
    monkeypatch.setattr(
        rebuild.projection,
        "_download_attestation_bytes",
        lambda _root, _repository, metadata, **_kwargs: raw_by_id[str(metadata["id"])],
    )
    monkeypatch.setattr(
        rebuild.projection,
        "verify_delivery_receipt",
        lambda *_args, **_kwargs: {"valid": True, "reasons": []},
    )
    original_publish = rebuild._publish_new
    calls = 0

    def fail_second(root: Path, nested, raw: bytes):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise rebuild.ReceiptRecoveryError("fixture publication race")
        return original_publish(root, nested, raw)

    monkeypatch.setattr(rebuild, "_publish_new", fail_second)

    with pytest.raises(rebuild.ReceiptRecoveryError, match="publication race"):
        rebuild.rebuild_receipts(repo, manifest)

    assert not rebuild.safe_cache_target(repo, first["cache_path"]).exists()
    assert not rebuild.safe_cache_target(repo, second["cache_path"]).exists()


def test_rebuild_dry_run_performs_validation_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    subject = _run(repo, "git", "rev-parse", "HEAD")
    raw = json.dumps({"subject_commit": subject}).encode("utf-8")
    manifest, entry = _manifest(repo, raw)
    metadata = {
        "id": 456,
        "name": entry["artifact_name"],
        "digest": entry["artifact_digest"],
        "expired": False,
        "workflow_run": {"id": 123},
    }
    monkeypatch.setattr(rebuild.projection, "repository_identity", lambda _root: "fixture/repo")
    monkeypatch.setattr(rebuild, "_artifact_metadata", lambda *_args: metadata)
    monkeypatch.setattr(rebuild.projection, "_download_attestation_bytes", lambda *_args, **_kwargs: raw)
    monkeypatch.setattr(
        rebuild.projection,
        "verify_delivery_receipt",
        lambda *_args, **_kwargs: {"valid": True, "reasons": []},
    )

    result = rebuild.rebuild_receipts(repo, manifest, dry_run=True)

    assert result["receipts"][0]["status"] == "verified"
    assert not rebuild.safe_cache_target(repo, entry["cache_path"]).exists()


def test_rebuild_fails_closed_before_write_on_hash_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    subject = _run(repo, "git", "rev-parse", "HEAD")
    raw = json.dumps({"subject_commit": subject}).encode("utf-8")
    manifest, entry = _manifest(repo, raw)
    metadata = {
        "id": 456,
        "name": entry["artifact_name"],
        "digest": entry["artifact_digest"],
        "expired": False,
        "workflow_run": {"id": 123},
    }
    monkeypatch.setattr(rebuild.projection, "repository_identity", lambda _root: "fixture/repo")
    monkeypatch.setattr(rebuild, "_artifact_metadata", lambda *_args: metadata)
    monkeypatch.setattr(
        rebuild.projection,
        "_download_attestation_bytes",
        lambda *_args, **_kwargs: b"tampered",
    )

    with pytest.raises(rebuild.ReceiptRecoveryError, match="hash drift"):
        rebuild.rebuild_receipts(repo, manifest)

    assert not rebuild.safe_cache_target(repo, entry["cache_path"]).exists()
