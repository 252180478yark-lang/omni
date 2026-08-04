import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "omni_w5_recovery_evidence_tests", ROOT / "scripts" / "w5_recovery_evidence.py"
)
assert SPEC is not None and SPEC.loader is not None
evidence = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = evidence
SPEC.loader.exec_module(evidence)


def _run(root: Path, *args: str) -> str:
    return subprocess.run(args, cwd=root, check=True, text=True, capture_output=True).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _run(root, "git", "init", "-q", "-b", "main")
    _run(root, "git", "config", "user.email", "test@example.com")
    _run(root, "git", "config", "user.name", "Test")
    (root / "tracked.py").write_text("value = 1\n", encoding="utf-8")
    _run(root, "git", "add", ".")
    _run(root, "git", "commit", "-qm", "base")
    (root / "tracked.py").write_text("value = 2\n", encoding="utf-8")
    return root


def _projection(*, retired: bool = True) -> dict:
    return {
        "source_paths": [
            {
                "path": "tracked.py",
                "scope_owners": ["2026-08-02-omni-unified-ai-workbench-w5"],
            }
        ],
        "source_residuals": [],
        "retired_source_change_ids": ["2026-08-01-system-convergence-s8-s10"] if retired else [],
    }


def _ready_dependencies(monkeypatch, source: Path) -> None:
    monkeypatch.setattr(evidence, "AUTHORITATIVE_W5_HISTORICAL_DELIVERY_IDS", ("required-owner",))
    monkeypatch.setattr(evidence, "ALLOWED_W5_RECOVERY_RESIDUAL_PATHS", ())
    monkeypatch.setattr(
        evidence.projection, "bounded_live_provenance", lambda _timeout: (lambda *_args: {"valid": True, "reasons": []})
    )
    monkeypatch.setattr(
        evidence,
        "_resolve_named_receipts",
        lambda *_args, **_kwargs: {"required-owner": {"valid": True}},
    )
    monkeypatch.setattr(
        evidence,
        "_source_ownership_projection",
        lambda *_args, **_kwargs: _projection(),
    )
    monkeypatch.setattr(
        evidence,
        "_source_runtime_lease_audit",
        lambda *_args: {"status": "passed", "active_count": 0, "records": []},
    )


def _lease(source: Path, *, lease_id: str = "lease-1", state: str = "active", **overrides) -> dict:
    record = {
        "lease_id": lease_id,
        "repository_id": "repo-1",
        "worktree_id": evidence.runtime.worktree_id(source),
        "change_id": evidence.W5_CHANGE_ID,
        "owner": "w5-owner",
        "path_globs": ["services/host-bridge/**"],
        "mode": "write",
        "risk_level": "R2",
        "created_at": "2026-08-04T00:00:00Z",
        "expires_at": "2099-08-04T00:00:00Z",
        "state": state,
        "revision": 1,
    }
    record.update(overrides)
    return record


def _allocation(source: Path, *, allocation_id: str = "allocation-1", lease_id: str = "lease-1", state: str = "active", **overrides) -> dict:
    record = {
        "allocation_id": allocation_id,
        "lease_id": lease_id,
        "repository_id": "repo-1",
        "worktree_id": evidence.runtime.worktree_id(source),
        "change_id": evidence.W5_CHANGE_ID,
        "owner": "w5-owner",
        "canonical": False,
        "runtime_id": "w5-runtime",
        "compose_project": "w5-project",
        "ports": {"api": 4010},
        "database": "w5-db",
        "database_schema": "w5_schema",
        "volumes": ["w5-volume"],
        "redis_namespace": "w5-redis",
        "cron_owner": False,
        "approval_worker_owner": False,
        "risk_level": "R2",
        "build_sha": "a" * 40,
        "source_fingerprint": "b" * 64,
        "created_at": "2026-08-04T00:00:00Z",
        "expires_at": "2099-08-04T00:00:00Z",
        "state": state,
        "revision": 1,
    }
    record.update(overrides)
    return record


def _audit_state(monkeypatch, source: Path, state: dict) -> dict:
    state_dir = source / ".audit-runtime"
    state_dir.mkdir()
    state_path = state_dir / "allocations.json"
    state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(evidence.runtime, "default_state_dir", lambda _root: state_dir)
    monkeypatch.setattr(evidence.runtime, "_read_state", lambda _path: state)
    return evidence._source_runtime_lease_audit(source, source)


def test_lease_audit_blocks_missing_worktree_id_on_active_lease(tmp_path: Path, monkeypatch) -> None:
    source = _repo(tmp_path)
    audit = _audit_state(
        monkeypatch,
        source,
        {"leases": [_lease(source, worktree_id="")], "allocations": [_allocation(source)]},
    )

    assert audit["status"] == "invalid"
    assert audit["active_count"] is None
    assert "lease_worktree_id_missing" in audit["validation_errors"]


def test_lease_audit_blocks_orphan_active_allocation_and_duplicate_lease_id(tmp_path: Path, monkeypatch) -> None:
    source = _repo(tmp_path)
    audit = _audit_state(
        monkeypatch,
        source,
        {
            "leases": [_lease(source), _lease(source, owner="other-owner")],
            "allocations": [_allocation(source, lease_id="orphan-lease")],
        },
    )

    assert audit["status"] == "invalid"
    assert "duplicate_lease_id" in audit["validation_errors"]
    assert "orphan_active_allocation" in audit["validation_errors"]


def test_lease_audit_blocks_malformed_allocation_and_ownership_mismatch(tmp_path: Path, monkeypatch) -> None:
    source = _repo(tmp_path)
    audit = _audit_state(
        monkeypatch,
        source,
        {
            "leases": [_lease(source)],
            "allocations": [_allocation(source, ports=[], owner="different-owner")],
        },
    )

    assert audit["status"] == "invalid"
    assert "allocation_ports_invalid" in audit["validation_errors"]
    assert "allocation_lease_ownership_mismatch" in audit["validation_errors"]


def test_lease_audit_blocks_orphan_released_lease(tmp_path: Path, monkeypatch) -> None:
    source = _repo(tmp_path)
    audit = _audit_state(
        monkeypatch,
        source,
        {"leases": [_lease(source, state="released")], "allocations": []},
    )

    assert audit["status"] == "invalid"
    assert "orphan_lease" in audit["validation_errors"]


def test_lease_audit_blocks_expired_lease_with_live_allocation(tmp_path: Path, monkeypatch) -> None:
    source = _repo(tmp_path)
    audit = _audit_state(
        monkeypatch,
        source,
        {
            "leases": [_lease(source, expires_at="2000-01-01T00:00:00Z")],
            "allocations": [_allocation(source, expires_at="2099-08-04T00:00:00Z")],
        },
    )

    assert audit["status"] == "invalid"
    assert "lease_allocation_effective_state_mismatch" in audit["validation_errors"]
    assert "lease_allocation_expiry_mismatch" in audit["validation_errors"]


def test_ready_evidence_persists_only_redacted_manifest(tmp_path: Path, monkeypatch) -> None:
    source = _repo(tmp_path)
    snapshot = evidence._status_snapshot(source)
    receipt = tmp_path / "receipt.json"
    receipt.write_text("{}", encoding="utf-8")
    _ready_dependencies(monkeypatch, source)

    result = evidence.build_recovery_evidence(
        source,
        source,
        receipt_paths=[receipt],
        expected_status_sha256=snapshot["status_sha256"],
        expected_runtime_source_fingerprint=snapshot["runtime_source_fingerprint"],
    )

    assert result["status"] == "recovery_ready"
    manifest = Path(result["manifest"]["path"])
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert saved["policy"]["source_mutated"] is False
    assert saved["policy"]["runtime_or_lease_mutated"] is False
    assert saved["policy"]["delivered_ids_injected"] is False
    assert "value = 2" not in manifest.read_text(encoding="utf-8")


def test_partial_receipt_set_blocks_but_preserves_stable_anchor(tmp_path: Path, monkeypatch) -> None:
    source = _repo(tmp_path)
    snapshot = evidence._status_snapshot(source)
    receipt = tmp_path / "receipt.json"
    receipt.write_text("{}", encoding="utf-8")
    _ready_dependencies(monkeypatch, source)
    monkeypatch.setattr(
        evidence, "AUTHORITATIVE_W5_HISTORICAL_DELIVERY_IDS", ("required-owner", "missing-owner")
    )

    result = evidence.build_recovery_evidence(
        source,
        source,
        receipt_paths=[receipt],
        expected_status_sha256=snapshot["status_sha256"],
        expected_runtime_source_fingerprint=snapshot["runtime_source_fingerprint"],
    )

    assert result["status"] == "blocked"
    assert result["status"] == "blocked"
    assert "required_receipt_not_verified" in result["failures"]
    assert "manifest" in result


def test_drift_and_unretired_source_fail_closed(tmp_path: Path, monkeypatch) -> None:
    source = _repo(tmp_path)
    before = evidence._status_snapshot(source)
    receipt = tmp_path / "receipt.json"
    receipt.write_text("{}", encoding="utf-8")
    _ready_dependencies(monkeypatch, source)
    monkeypatch.setattr(
        evidence,
        "_source_ownership_projection",
        lambda *_args, **_kwargs: _projection(retired=False),
    )
    (source / "tracked.py").write_text("value = 3\n", encoding="utf-8")

    result = evidence.build_recovery_evidence(
        source,
        source,
        receipt_paths=[receipt],
        expected_status_sha256=before["status_sha256"],
        expected_runtime_source_fingerprint=before["runtime_source_fingerprint"],
    )

    assert result["status"] == "blocked"
    assert "status_fingerprint_mismatch" in result["failures"]
    assert "runtime_source_fingerprint_mismatch" in result["failures"]
    assert "s8_s10_supersession_not_verified" in result["failures"]


def test_mid_run_source_drift_does_not_persist_an_anchor(tmp_path: Path, monkeypatch) -> None:
    source = _repo(tmp_path)
    snapshot = evidence._status_snapshot(source)
    receipt = tmp_path / "receipt.json"
    receipt.write_text("{}", encoding="utf-8")
    _ready_dependencies(monkeypatch, source)

    def mutate(_source: Path):
        (source / "tracked.py").write_text("value = 99\n", encoding="utf-8")
        return {
            "status": "passed",
            "raw_finding_count": 0,
            "allowlisted_fixture_finding_count": 0,
            "unexpected_finding_count": 0,
            "unexpected_findings": [],
            "allowlist": [],
            "redaction": "path_rule_fingerprint_only",
        }

    monkeypatch.setattr(evidence, "_secret_hygiene", mutate)
    result = evidence.build_recovery_evidence(
        source,
        source,
        receipt_paths=[receipt],
        expected_status_sha256=snapshot["status_sha256"],
        expected_runtime_source_fingerprint=snapshot["runtime_source_fingerprint"],
    )

    assert result["status"] == "blocked"
    assert "source_sample_drift" in result["failures"]
    assert not (source / ".git" / "omni-runtime" / "w5-recovery-evidence").exists()


def test_only_exact_fixture_path_rule_is_allowed(tmp_path: Path) -> None:
    source = _repo(tmp_path)
    fixture = source / "frontend" / "tests" / "agent-chat" / "unit" / "host-bridge-client.test.ts"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("const token = 'Bearer abcdefghijklmnopqrst';\n", encoding="utf-8")
    defaults = evidence.ownership.DEFAULT_SECRET_ALLOWLIST
    evidence.ownership.DEFAULT_SECRET_ALLOWLIST = ()
    try:
        raw = evidence.ownership.scan_secrets(source, scope="changed", _repository_root_resolved=True)
    finally:
        evidence.ownership.DEFAULT_SECRET_ALLOWLIST = defaults
    finding = raw["findings"][0]
    original = evidence.W5_FIXTURE_SECRET_ALLOWLIST
    evidence.W5_FIXTURE_SECRET_ALLOWLIST = ((finding["path"], finding["rule"], finding["fingerprint"]),)
    hygiene = evidence._secret_hygiene(source)
    try:
        assert hygiene["raw_finding_count"] == 1
        assert hygiene["allowlisted_fixture_finding_count"] == 1
        assert hygiene["unexpected_finding_count"] == 0

        (source / "service.py").write_text("const token = 'Bearer zyxwvutsrqponmlkjihg';\n", encoding="utf-8")
        blocked = evidence._secret_hygiene(source)
        assert blocked["unexpected_finding_count"] == 1
        assert blocked["status"] == "failed"
    finally:
        evidence.W5_FIXTURE_SECRET_ALLOWLIST = original


def test_named_receipt_resolution_never_uses_ambient_cache_or_bypasses_verifier(
    tmp_path: Path, monkeypatch
) -> None:
    source = _repo(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text("{}", encoding="utf-8")
    verifier = object()
    seen = []

    def verify(_root, _receipt, change_id, *, receipt_path=None, provenance_verifier=None):
        seen.append((change_id, receipt_path, provenance_verifier))
        return {"valid": True, "change_id": change_id}

    monkeypatch.setattr(evidence.projection, "verify_delivery_receipt", verify)
    resolved = evidence._resolve_named_receipts(
        source,
        [(receipt_path, {"change_id": "only-owner"})],
        ["only-owner", "ambient-owner"],
        verifier,
    )

    assert sorted(resolved) == ["only-owner"]
    assert seen == [("only-owner", receipt_path, verifier)]


def test_non_w5_unique_owner_is_still_a_recovery_residual(tmp_path: Path, monkeypatch) -> None:
    source = _repo(tmp_path)

    monkeypatch.setattr(evidence.ownership, "repository_root", lambda _path: source)
    monkeypatch.setattr(evidence.ownership, "trusted_retirements", lambda *_args: [])
    monkeypatch.setattr(evidence.ownership, "active_contract_scopes", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        evidence.ownership,
        "_status_entries",
        lambda _source: [("tracked.py", " M")],
    )
    monkeypatch.setattr(
        evidence.ownership,
        "owners_for_path",
        lambda *_args: ["2026-08-01-system-convergence-s7-s14"],
    )

    projection = evidence._source_ownership_projection(source, source, {})

    assert projection["source_residuals"] == [
        {
            "path": "tracked.py",
            "scope_owners": ["2026-08-01-system-convergence-s7-s14"],
            "expected_owner": evidence.W5_CHANGE_ID,
        }
    ]


def test_manifest_rejects_external_output_and_is_append_only(tmp_path: Path, monkeypatch) -> None:
    source = _repo(tmp_path)
    snapshot = evidence._status_snapshot(source)
    receipt = tmp_path / "receipt.json"
    receipt.write_text("{}", encoding="utf-8")
    _ready_dependencies(monkeypatch, source)

    with pytest.raises(evidence.RecoveryEvidenceError, match="git common-dir"):
        evidence.build_recovery_evidence(
            source, source, receipt_paths=[receipt],
            expected_status_sha256=snapshot["status_sha256"],
            expected_runtime_source_fingerprint=snapshot["runtime_source_fingerprint"],
            output_dir=tmp_path / "escape",
        )

    first = evidence.build_recovery_evidence(
        source, source, receipt_paths=[receipt],
        expected_status_sha256=snapshot["status_sha256"],
        expected_runtime_source_fingerprint=snapshot["runtime_source_fingerprint"],
    )
    second = evidence.build_recovery_evidence(
        source, source, receipt_paths=[receipt],
        expected_status_sha256=snapshot["status_sha256"],
        expected_runtime_source_fingerprint=snapshot["runtime_source_fingerprint"],
    )
    assert first["manifest"]["path"] != second["manifest"]["path"]
    assert first["run_id"] != second["run_id"]
    assert Path(first["manifest"]["path"]).parent == source / ".git" / "omni-runtime" / "w5-recovery-evidence"


def test_manifest_rejects_common_dir_symlink_escape(tmp_path: Path, monkeypatch) -> None:
    source = _repo(tmp_path)
    runtime_dir = source / ".git" / "omni-runtime"
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        runtime_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")

    with pytest.raises(evidence.RecoveryEvidenceError, match="reparse point"):
        evidence._manifest_directory(source)


def test_manifest_rejects_common_dir_junction_escape(tmp_path: Path) -> None:
    source = _repo(tmp_path)
    runtime_dir = source / ".git" / "omni-runtime"
    outside = tmp_path / "outside"
    outside.mkdir()
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(runtime_dir), str(outside)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("junction creation is unavailable on this host")

    with pytest.raises(evidence.RecoveryEvidenceError, match="reparse point"):
        evidence._manifest_directory(source)


def test_unknown_lease_state_and_unrelated_residual_both_block(tmp_path: Path, monkeypatch) -> None:
    source = _repo(tmp_path)
    snapshot = evidence._status_snapshot(source)
    receipt = tmp_path / "receipt.json"
    receipt.write_text("{}", encoding="utf-8")
    _ready_dependencies(monkeypatch, source)
    monkeypatch.setattr(
        evidence,
        "_source_ownership_projection",
        lambda *_args: {
            "source_paths": [{"path": "unrelated.py", "scope_owners": []}],
            "source_residuals": [{"path": "unrelated.py", "scope_owners": []}],
            "retired_source_change_ids": ["2026-08-01-system-convergence-s8-s10"],
        },
    )
    monkeypatch.setattr(
        evidence, "_source_runtime_lease_audit", lambda *_args: {"status": "missing", "active_count": None, "records": []}
    )

    result = evidence.build_recovery_evidence(
        source, source, receipt_paths=[receipt],
        expected_status_sha256=snapshot["status_sha256"],
        expected_runtime_source_fingerprint=snapshot["runtime_source_fingerprint"],
    )

    assert "source_runtime_lease_unknown_or_invalid" in result["failures"]
    assert "source_residual_paths_mismatch" in result["failures"]


def test_default_secret_allowlist_cannot_silently_excuse_recovery_fixture(tmp_path: Path, monkeypatch) -> None:
    source = _repo(tmp_path)
    fixture = source / "fixture.py"
    fixture.write_text("const token = 'Bearer abcdefghijklmnopqrst';\n", encoding="utf-8")
    monkeypatch.setattr(evidence, "W5_FIXTURE_SECRET_ALLOWLIST", ())
    monkeypatch.setattr(evidence.ownership, "DEFAULT_SECRET_ALLOWLIST", ("*:bearer_token",))

    hygiene = evidence._secret_hygiene(source)

    assert hygiene["default_allowlist_merged"] is False
    assert hygiene["unexpected_finding_count"] == 1
