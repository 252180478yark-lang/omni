from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "omni_implementation_status_tests", ROOT / "scripts" / "generate_implementation_status.py"
)
assert SPEC is not None and SPEC.loader is not None
status = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = status
SPEC.loader.exec_module(status)


def _run(repo: Path, *args: str) -> str:
    result = subprocess.run(args, cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _fixture_repo(tmp_path: Path) -> tuple[Path, str, str, dict]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-q", "-b", "main")
    _run(repo, "git", "config", "user.email", "test@example.com")
    _run(repo, "git", "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-qm", "base")
    base = _run(repo, "git", "rev-parse", "HEAD")

    change_id = "delivery-test"
    directory = repo / "docs" / "dev-changes" / change_id
    directory.mkdir(parents=True)
    impact = {
        "schema_version": 3,
        "change_id": change_id,
        "state": "GRAPH_DIFF_READY",
        "feature_refs": [{"feature_id": "foundation", "feature_ref": "prd:test:S0.5"}],
        "risk": {"level": "R1"},
    }
    completion = {"schema_version": 3, "change_id": change_id, "state": "GRAPH_DIFF_READY"}
    (directory / "impact.yaml").write_text(yaml.safe_dump(impact, sort_keys=False), encoding="utf-8")
    (directory / "completion.yaml").write_text(yaml.safe_dump(completion, sort_keys=False), encoding="utf-8")
    (repo / "feature.py").write_text("value = 1\n", encoding="utf-8")
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-qm", "candidate")
    subject = _run(repo, "git", "rev-parse", "HEAD")
    tree = _run(repo, "git", "rev-parse", f"{subject}^{{tree}}")
    impact_text = _run(repo, "git", "show", f"{subject}:docs/dev-changes/{change_id}/impact.yaml") + "\n"
    completion_text = _run(repo, "git", "show", f"{subject}:docs/dev-changes/{change_id}/completion.yaml") + "\n"
    paths = _run(repo, "git", "diff", "--name-only", f"{base}...{subject}").splitlines()
    changed_digest = hashlib.sha256(("\n".join(sorted(paths)) + "\n").encode()).hexdigest()
    receipt = {
        "schema_version": 2,
        "authority": "ci_attestation",
        "status": "COMPLETE",
        "subject_commit": subject,
        "head_sha": subject,
        "delivered_tree": tree,
        "repository": "fixture/repo",
        "target_ref": "refs/heads/main",
        "workflow_run_id": "12345",
        "attestation_artifact_name": f"delivery-attestation-{subject}",
        "evidence_artifact": {
            "name": f"delivery-evidence-{subject}",
            "digest": "sha256:" + "a" * 64,
        },
        "reachable": True,
        "required_checks": {"contract": "passed", "tests": "success"},
        "contracts": [
            {
                "change_id": change_id,
                "base_commit": base,
                "impact_sha256": hashlib.sha256(impact_text.encode()).hexdigest(),
                "completion_sha256": hashlib.sha256(completion_text.encode()).hexdigest(),
                "changed_paths_sha256": changed_digest,
            }
        ],
    }
    return repo, base, subject, receipt


def _trusted(_root: Path, receipt: dict, _path: Path | None) -> dict:
    return {
        "valid": True,
        "reasons": [],
        "repository": receipt.get("repository"),
        "target_ref": "refs/heads/main",
        "head_sha": receipt.get("subject_commit"),
        "workflow_run_id": receipt.get("workflow_run_id"),
        "attestation_artifact_name": receipt.get("attestation_artifact_name"),
        "evidence_artifact_name": (receipt.get("evidence_artifact") or {}).get("name"),
        "evidence_artifact_digest": (receipt.get("evidence_artifact") or {}).get("digest"),
        "checks_passed": True,
    }


S0_PASS = {
    "secret_scan": {"status": "passed", "finding_count": 0},
    "ownership": {"status": "passed", "counts": {}},
    "migration_baseline": {"status": "ready", "blockers": []},
}
HOOK_CONFIRMED = {
    "status": "confirmed",
    "user_confirmation": "confirmed",
    "confirmation_surface": "/hooks",
}


def test_historical_complete_contracts_remain_compatible_without_v3_receipts() -> None:
    assert status._contract_status("COMPLETE", None, schema_version=1) == "COMPLETE"
    assert status._contract_status("COMPLETE", None, schema_version=2) == "COMPLETE"
    assert status._contract_status("COMPLETE", None, schema_version=3) == "UNKNOWN"


def test_collect_s0_evidence_reuses_the_exact_provenance_verifier_for_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = object()
    seen: list[object] = []

    def inventory(_root: Path, **kwargs):
        seen.append(kwargs.get("provenance_verifier"))
        return {
            "secret_scan": {"status": "passed", "finding_count": 0},
            "counts": {},
        }

    monkeypatch.setattr(
        status,
        "_load_ownership_scanner",
        lambda _root: SimpleNamespace(inventory_workspace=inventory),
    )

    evidence = status.collect_s0_evidence(
        tmp_path,
        attestation_paths=[tmp_path / "receipt.json"],
        provenance_verifier=verifier,
        migration_baseline={"status": "ready"},
    )

    assert seen == [verifier]
    assert evidence["ownership"]["status"] == "passed"


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (False, "trusted_provenance_verifier_invalid"),
        (None, "trusted_provenance_verifier_invalid"),
        ([], "trusted_provenance_verifier_invalid"),
        ({"valid": False, "reasons": []}, "trusted_provenance_verifier_invalid"),
        ({"valid": False, "reasons": ["declared-false"]}, "trusted_provenance_verifier_invalid"),
        ({"valid": True, "reasons": None}, "trusted_provenance_verifier_invalid"),
        ({"valid": False, "reasons": 7}, "trusted_provenance_verifier_invalid"),
        ({"valid": False, "reasons": "not-a-list"}, "trusted_provenance_verifier_invalid"),
    ],
)
def test_malformed_provenance_results_are_fail_closed_without_crashing(
    tmp_path: Path, result: object, reason: str
) -> None:
    repo, _base, _subject, receipt = _fixture_repo(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    verified = status.verify_delivery_receipt(
        repo,
        receipt,
        "delivery-test",
        receipt_path=receipt_path,
        provenance_verifier=lambda *_args: result,
    )
    resolved = status.resolve_delivered_contracts(
        repo,
        [receipt_path],
        provenance_verifier=lambda *_args: result,
    )

    assert verified["valid"] is False
    assert reason in verified["reasons"]
    assert resolved == {}


@pytest.mark.parametrize("error", [RuntimeError("fixture"), TimeoutError("fixture")])
def test_provenance_exception_or_timeout_is_fail_closed_without_crashing(
    tmp_path: Path, error: Exception
) -> None:
    repo, _base, _subject, receipt = _fixture_repo(tmp_path)

    def broken(*_args):
        raise error

    verified = status.verify_delivery_receipt(
        repo,
        receipt,
        "delivery-test",
        provenance_verifier=broken,
    )

    assert verified["valid"] is False
    assert "trusted_provenance_verifier_failed" in verified["reasons"]


def test_resolver_verifies_one_receipt_provenance_once_for_multiple_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _base, _subject, receipt = _fixture_repo(tmp_path)
    receipt["contracts"] = [
        {"change_id": "delivery-one"},
        {"change_id": "delivery-two"},
    ]
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    provenance_calls = 0
    contract_calls: list[str] = []

    def provenance(*_args):
        nonlocal provenance_calls
        provenance_calls += 1
        return {"valid": True, "reasons": [], "checks_passed": True}

    def verify(_root, _receipt, change_id, **kwargs):
        contract_calls.append(change_id)
        assert kwargs["provenance_verifier"](_root, _receipt)["valid"] is True
        return {"valid": True, "change_id": change_id}

    monkeypatch.setattr(status, "verify_delivery_receipt", verify)

    resolved = status.resolve_delivered_contracts(
        repo,
        [receipt_path],
        provenance_verifier=provenance,
    )

    assert provenance_calls == 1
    assert contract_calls == ["delivery-one", "delivery-two"]
    assert set(resolved) == {"delivery-one", "delivery-two"}


def test_resolver_checks_independent_receipts_concurrently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _base, _subject, receipt = _fixture_repo(tmp_path)
    first = dict(receipt, contracts=[{"change_id": "delivery-one"}])
    second = dict(receipt, contracts=[{"change_id": "delivery-two"}])
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(json.dumps(first), encoding="utf-8")
    second_path.write_text(json.dumps(second), encoding="utf-8")
    barrier = threading.Barrier(2, timeout=2)
    observed_threads: set[int] = set()

    def provenance(*_args):
        observed_threads.add(threading.get_ident())
        barrier.wait()
        return {"valid": True, "reasons": [], "checks_passed": True}

    monkeypatch.setattr(
        status,
        "verify_delivery_receipt",
        lambda _root, _receipt, change_id, **_kwargs: {
            "valid": True,
            "change_id": change_id,
        },
    )

    resolved = status.resolve_delivered_contracts(
        repo,
        [first_path, second_path],
        provenance_verifier=provenance,
    )

    assert set(resolved) == {"delivery-one", "delivery-two"}
    assert len(observed_threads) == 2


@pytest.mark.parametrize("migration_status", ["ready", "passed", "verified"])
def test_s0_accepts_success_statuses_emitted_by_migration_preflight(
    migration_status: str,
) -> None:
    gate, reasons = status._s0_gate_status(
        {
            "secret_scan": {"status": "passed"},
            "ownership": {"status": "passed", "counts": {}},
            "migration_baseline": {"status": migration_status},
        }
    )

    assert gate == "COMPLETE"
    assert reasons == []


def test_valid_external_receipt_projects_complete_but_tamper_does_not(tmp_path: Path) -> None:
    repo, _base, _subject, receipt = _fixture_repo(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    verified = status.verify_delivery_receipt(
        repo, receipt, "delivery-test", receipt_path=receipt_path, provenance_verifier=_trusted
    )
    assert verified["valid"] is True
    projection = status.build_projection(
        repo,
        receipts=[(receipt_path, receipt)],
        provenance_verifier=_trusted,
        s0_evidence=S0_PASS,
        hook_trust=HOOK_CONFIRMED,
    )
    s05 = next(item for item in projection["slices"] if item["id"] == "S0.5")
    assert s05["status"] == "COMPLETE"
    assert str(repo) not in yaml.safe_dump(projection)

    tampered = json.loads(json.dumps(receipt))
    tampered["contracts"][0]["impact_sha256"] = "0" * 64
    rejected = status.verify_delivery_receipt(
        repo, tampered, "delivery-test", provenance_verifier=_trusted
    )
    assert rejected["valid"] is False
    assert "impact_sha256_mismatch" in rejected["reasons"]
    stale = status.build_projection(
        repo,
        receipts=[(None, tampered)],
        provenance_verifier=_trusted,
        s0_evidence=S0_PASS,
        hook_trust=HOOK_CONFIRMED,
    )
    stale_s05 = next(item for item in stale["slices"] if item["id"] == "S0.5")
    assert stale_s05["status"] == "VERIFIED_NOT_DELIVERED"


def test_v2_failed_signed_check_cannot_be_repaired_by_live_provenance(
    tmp_path: Path,
) -> None:
    repo, _base, _subject, receipt = _fixture_repo(tmp_path)
    receipt["required_checks"]["contract"] = "failed"

    result = status.verify_delivery_receipt(
        repo,
        receipt,
        "delivery-test",
        provenance_verifier=_trusted,
    )

    assert result["valid"] is False
    assert "required_checks_not_passed" in result["reasons"]


def test_v2_live_failed_check_cannot_be_repaired_by_signed_receipt(
    tmp_path: Path,
) -> None:
    repo, _base, _subject, receipt = _fixture_repo(tmp_path)

    def live_check_failed(*args):
        value = _trusted(*args)
        value["checks_passed"] = False
        return value

    result = status.verify_delivery_receipt(
        repo,
        receipt,
        "delivery-test",
        provenance_verifier=live_check_failed,
    )

    assert result["valid"] is False
    assert "required_checks_not_passed" in result["reasons"]


def test_v1_missing_signed_checks_can_use_verified_live_compatibility(
    tmp_path: Path,
) -> None:
    repo, _base, _subject, receipt = _fixture_repo(tmp_path)
    receipt["schema_version"] = 1
    receipt.pop("required_checks")

    result = status.verify_delivery_receipt(
        repo,
        receipt,
        "delivery-test",
        provenance_verifier=_trusted,
    )

    assert result["valid"] is True
    assert "required_checks_not_passed" not in result["reasons"]


def test_unreachable_subject_is_rejected(tmp_path: Path) -> None:
    repo, _base, subject, receipt = _fixture_repo(tmp_path)
    _run(repo, "git", "branch", "delivered-main", subject)
    _run(repo, "git", "checkout", "-qb", "feature")
    (repo / "unreachable.py").write_text("value = 2\n", encoding="utf-8")
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-qm", "unreachable")
    unreachable = _run(repo, "git", "rev-parse", "HEAD")
    receipt["subject_commit"] = unreachable
    receipt["head_sha"] = unreachable
    receipt["delivered_tree"] = _run(repo, "git", "rev-parse", f"{unreachable}^{{tree}}")
    receipt["contracts"][0].pop("impact_sha256")
    receipt["contracts"][0].pop("completion_sha256")
    receipt["contracts"][0].pop("changed_paths_sha256")

    result = status.verify_delivery_receipt(
        repo, receipt, "delivery-test", provenance_verifier=_trusted
    )

    assert result["valid"] is False
    assert "subject_not_reachable_from_target_ref" in result["reasons"]


def test_receipt_is_fail_closed_offline_and_rejects_minimal_v1_forgery(tmp_path: Path) -> None:
    repo, _base, subject, receipt = _fixture_repo(tmp_path)
    offline = status.verify_delivery_receipt(repo, receipt, "delivery-test")
    assert offline["valid"] is False
    assert "trusted_provenance_not_verified" in offline["reasons"]

    forged = {
        "schema_version": 1,
        "authority": "ci_attestation",
        "status": "COMPLETE",
        "delivered_commit": subject,
        "contracts": [{"change_id": "new-change"}],
    }
    rejected = status.verify_delivery_receipt(
        repo, forged, "new-change", provenance_verifier=_trusted
    )
    assert rejected["valid"] is False
    assert "delivered_tree_missing" in rejected["reasons"]
    assert "impact_sha256_missing" in rejected["reasons"]
    assert "completion_sha256_missing" in rejected["reasons"]
    assert "changed_paths_sha256_missing" in rejected["reasons"]
    assert "required_checks_not_passed" not in rejected["reasons"]  # trusted live checks may fill legacy v1
    assert any(reason.startswith("subject_contract_") for reason in rejected["reasons"])


def test_tree_repository_ref_and_replayed_provenance_tamper_are_rejected(tmp_path: Path) -> None:
    repo, _base, _subject, receipt = _fixture_repo(tmp_path)
    receipt["delivered_tree"] = "0" * 40
    receipt["repository"] = "wrong/repo"
    receipt["target_ref"] = "refs/heads/feature"

    def observed(_root: Path, _receipt: dict, _path: Path | None) -> dict:
        return {
            "valid": True,
            "reasons": [],
            "repository": "fixture/repo",
            "target_ref": "refs/heads/main",
            "head_sha": "f" * 40,
            "workflow_run_id": "99999",
            "attestation_artifact_name": "delivery-attestation-other",
            "evidence_artifact_name": "delivery-evidence-other",
            "evidence_artifact_digest": "sha256:" + "b" * 64,
            "checks_passed": True,
        }

    rejected = status.verify_delivery_receipt(
        repo, receipt, "delivery-test", provenance_verifier=observed
    )
    assert rejected["valid"] is False
    assert {
        "delivered_tree_mismatch",
        "target_ref_not_trusted_default",
        "repository_identity_mismatch",
        "provenance_head_sha_mismatch",
        "provenance_workflow_run_mismatch",
    } <= set(rejected["reasons"])


def test_manual_complete_source_value_is_never_trusted(tmp_path: Path) -> None:
    repo, _base, _subject, _receipt = _fixture_repo(tmp_path)
    projection = status.build_projection(
        repo,
        receipts=[],
        source_status={"current": {"status": "COMPLETE", "completion_claimed": True}},
        s0_evidence=S0_PASS,
        hook_trust=HOOK_CONFIRMED,
    )
    s05 = next(item for item in projection["slices"] if item["id"] == "S0.5")
    assert s05["status"] == "VERIFIED_NOT_DELIVERED"
    assert projection["generation"]["manual_completion_allowed"] is False


def test_repository_hook_delivery_does_not_infer_current_user_trust(tmp_path: Path) -> None:
    repo, _base, _subject, receipt = _fixture_repo(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    projection = status.build_projection(
        repo,
        receipts=[(receipt_path, receipt)],
        provenance_verifier=_trusted,
        s0_evidence=S0_PASS,
    )

    s05 = next(item for item in projection["slices"] if item["id"] == "S0.5")
    assert s05["status"] == "BLOCKED"
    assert s05["completion_claimed"] is False
    assert s05["remaining"] == [
        "current_user_hook_trust_confirmation_required:/hooks"
    ]
    assert projection["audit_snapshot"]["hook_trust"]["status"] == "review_required"
    assert projection["projection_policy"][
        "repository_hook_delivery_does_not_imply_user_trust"
    ] is True


def test_receipt_discovery_includes_nested_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "verified-receipts"
    nested = cache / "w0" / "receipt.json"
    nested.parent.mkdir(parents=True)
    nested.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(status, "_validated_cache_root", lambda _root: cache)

    discovered = status.discover_receipt_paths(tmp_path)

    assert discovered == (nested.resolve(),)


def test_receipt_discovery_fails_closed_on_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "verified-receipts"
    cache.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (cache / "escaped.json").symlink_to(outside)
    monkeypatch.setattr(status, "_validated_cache_root", lambda _root: cache)

    with pytest.raises(status.ProjectionInputError, match="linked receipt"):
        status.discover_receipt_paths(tmp_path)


def test_receipt_discovery_fails_closed_on_file_count_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "verified-receipts"
    cache.mkdir()
    for index in range(status.RECEIPT_CACHE_MAX_FILES + 1):
        (cache / f"{index:03d}.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(status, "_validated_cache_root", lambda _root: cache)

    with pytest.raises(status.ProjectionInputError, match="file count"):
        status.discover_receipt_paths(tmp_path)


def test_explicit_external_receipt_remains_compatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "verified-receipts"
    cache.mkdir()
    explicit = tmp_path / "external" / "receipt.json"
    explicit.parent.mkdir()
    explicit.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(status, "_validated_cache_root", lambda _root: cache)

    assert status.discover_receipt_paths(tmp_path, [explicit]) == (explicit.resolve(),)


def test_receipt_discovery_rejects_symlinked_cache_ancestor(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-q", "-b", "main")
    outside = tmp_path / "outside-cache"
    outside.mkdir()
    (repo / ".git" / "omni-delivery").symlink_to(outside, target_is_directory=True)

    with pytest.raises(status.ProjectionInputError, match="ancestry"):
        status.discover_receipt_paths(repo)


def test_secure_cached_read_rejects_ancestor_swap_after_discovery(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-q", "-b", "main")
    delivery_root = repo / ".git" / "omni-delivery"
    receipt = delivery_root / "verified-receipts" / "w0" / "receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"trusted": true}', encoding="utf-8")
    discovered = status.discover_receipt_paths(repo)
    assert discovered == (receipt.resolve(),)

    preserved = repo / ".git" / "omni-delivery-preserved"
    delivery_root.rename(preserved)
    outside = tmp_path / "outside"
    malicious = outside / "verified-receipts" / "w0" / "receipt.json"
    malicious.parent.mkdir(parents=True)
    malicious.write_text('{"trusted": false}', encoding="utf-8")
    delivery_root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(status.ProjectionInputError, match="ancestry"):
        status._read_cached_json(repo, discovered[0])


def test_legacy_gap_closure_has_versioned_s4_s6_compatibility_mapping() -> None:
    impact = {
        "change_id": "2026-08-01-system-convergence-s4-s6-gap-closure",
        "feature_refs": [{"feature_ref": "config/features/system-convergence-s4-s6.yaml@sha256:fixture"}],
    }

    assert status._contract_slices(impact) == ("S4", "S5", "S6")


def _artifact_zip(entries: list[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return output.getvalue()


@pytest.mark.parametrize(
    "entries, message",
    [
        (
            [
                ("../delivery-attestation.json", b"{}"),
            ],
            "unsafe archive member",
        ),
        (
            [
                ("a/delivery-attestation.json", b"{}"),
                ("b/delivery-attestation.json", b"{}"),
            ],
            "exactly one attestation",
        ),
    ],
)
def test_downloaded_delivery_artifact_rejects_unsafe_or_ambiguous_archives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entries: list[tuple[str, bytes]],
    message: str,
) -> None:
    archive = _artifact_zip(entries)
    monkeypatch.setattr(
        status.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, archive, b""),
    )

    with pytest.raises(status.ProjectionInputError, match=message):
        status._download_attestation_payload(tmp_path, "fixture/repo", {"id": 123})


def test_live_provenance_rejects_locally_forged_extra_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _base, subject, receipt = _fixture_repo(tmp_path)
    authoritative = json.loads(json.dumps(receipt))
    receipt["contracts"].append(
        {
            "change_id": "forged-extra",
            "base_commit": "0" * 40,
            "impact_sha256": "0" * 64,
            "completion_sha256": "0" * 64,
            "changed_paths_sha256": "0" * 64,
        }
    )
    monkeypatch.setattr(
        status, "repository_identity", lambda _root, **_kwargs: "fixture/repo"
    )

    def fake_run(command, *, cwd, check=False, timeout=10):
        del cwd, check, timeout
        if tuple(command[:3]) == ("gh", "run", "view"):
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "headSha": subject,
                        "headBranch": "main",
                        "event": "push",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ),
                "",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "artifacts": [
                        {
                            "id": 123,
                            "name": receipt["attestation_artifact_name"],
                            "expired": False,
                        },
                        {
                            "id": 124,
                            "name": receipt["evidence_artifact"]["name"],
                            "digest": receipt["evidence_artifact"]["digest"],
                            "expired": False,
                        },
                    ]
                }
            ),
            "",
        )

    monkeypatch.setattr(status, "_run", fake_run)
    monkeypatch.setattr(
        status,
        "_download_attestation_payload",
        lambda _root, _repository, _artifact, **_kwargs: authoritative,
    )

    result = status.live_github_provenance(repo, receipt)

    assert result["valid"] is False
    assert "local_receipt_differs_from_signed_artifact" in result["reasons"]


def test_default_provenance_is_offline_fail_closed_and_has_no_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline projection must not invoke a subprocess or network client")

    monkeypatch.setattr(status.subprocess, "run", forbidden)
    started = status.time.monotonic()
    result = status.offline_provenance(tmp_path, {"workflow_run_id": "1"})
    elapsed = status.time.monotonic() - started

    assert result["valid"] is False
    assert result["reasons"] == ["live_provenance_refresh_required"]
    assert elapsed < 0.1


def test_live_refresh_shares_one_wall_clock_deadline_across_all_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def bounded_fake(
        _root,
        _receipt,
        _path=None,
        *,
        deadline=None,
        authoritative_receipt=None,
    ):
        del authoritative_receipt
        nonlocal calls
        calls += 1
        assert deadline is not None
        remaining = max(0.0, deadline - status.time.monotonic())
        status.time.sleep(min(0.025, remaining))
        return {"valid": False, "reasons": ["fixture"], "checks_passed": False}

    monkeypatch.setattr(status, "live_github_provenance", bounded_fake)
    verifier = status.bounded_live_provenance(0.06)
    started = status.time.monotonic()
    results = [verifier(tmp_path, {"workflow_run_id": str(index)}) for index in range(12)]
    elapsed = status.time.monotonic() - started

    assert elapsed < 0.15
    assert calls <= 3
    assert any(
        "live_provenance_total_deadline_exhausted" in item["reasons"]
        for item in results
    )


def test_bounded_live_refresh_passes_only_matching_authoritative_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = "a" * 40
    receipt = {"subject_commit": subject, "workflow_run_id": "1"}
    captured: list[object] = []

    def fake_live(_root, _receipt, _path=None, *, deadline=None, authoritative_receipt=None):
        assert deadline is not None
        captured.append(authoritative_receipt)
        return {"valid": True, "reasons": [], "checks_passed": True}

    monkeypatch.setattr(status, "live_github_provenance", fake_live)
    authoritative = {subject: receipt}
    verifier = status.bounded_live_provenance(
        1,
        authoritative_receipts=authoritative,
    )

    assert verifier(tmp_path, receipt)["valid"] is True
    assert verifier(tmp_path, {"subject_commit": "b" * 40})["valid"] is True
    assert captured == [receipt, None]
