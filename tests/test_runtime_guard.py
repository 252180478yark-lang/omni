from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_module("omni_runtime_guard", ROOT / "scripts" / "runtime_guard.py")


def _manifest() -> dict:
    return guard.load_manifest(ROOT / "config" / "runtime-manifest.yaml")


def _raw_container(
    name: str,
    *,
    service: str,
    worktree: str,
    runtime_id: str = "omni-main",
    source_commit: str = "a" * 40,
    source_fingerprint: str = "b" * 64,
    baked_source_commit: str | None = None,
    baked_source_fingerprint: str | None = None,
    port: int | None = None,
    database_url: str = "postgresql+asyncpg://omni_user:top-secret@omni-postgres:5432/omni_vibe_db",
    volume: str | None = "omni_knowledge_data",
    scheduler_role: str = "disabled",
) -> dict:
    labels = {
        "com.docker.compose.project": "omni",
        "com.docker.compose.service": service,
        "io.omni.runtime_id": runtime_id,
        "org.opencontainers.image.revision": source_commit,
        "io.omni.source_fingerprint": source_fingerprint,
        "io.omni.worktree_id": guard.opaque_worktree_id(worktree),
        "io.omni.scheduler_role": scheduler_role,
        "io.omni.build.source_commit": baked_source_commit or source_commit,
        "io.omni.build.source_fingerprint": baked_source_fingerprint or source_fingerprint,
    }
    mounts = [
        {
            "Type": "bind",
            "Source": worktree,
            "Destination": "/workspace",
            "RW": False,
            "Name": "",
        }
    ]
    if volume:
        mounts.append(
            {
                "Type": "volume",
                "Source": f"/volumes/{volume}",
                "Destination": "/app/data",
                "RW": True,
                "Name": volume,
            }
        )
    ports = {}
    if port is not None:
        ports[f"{port}/tcp"] = [{"HostIp": "127.0.0.1", "HostPort": str(port)}]
    env = [f"DATABASE_URL={database_url}"] if database_url else []
    return {
        "Id": (name.replace("-", "") + "0" * 64)[:64],
        "Name": f"/{name}",
        "Config": {"Image": f"image/{service}", "Labels": labels, "Env": env},
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
        "Mounts": mounts,
        "NetworkSettings": {"Ports": ports},
    }


def _expected(manifest: dict, worktree: str = "e:/agent/omni") -> dict:
    return {
        "commit": "a" * 40,
        "worktree": guard.opaque_worktree_id(worktree),
        "primary_worktree": guard.opaque_worktree_id(worktree),
        "fingerprints": {service: "b" * 64 for service in manifest["services"]},
    }


def _codes(issues: list) -> set[str]:
    return {issue.code for issue in issues}


def test_manifest_is_json_compatible_yaml_without_host_absolute_paths() -> None:
    path = ROOT / "config" / "runtime-manifest.yaml"
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["schema_version"] == 1
    assert guard.find_host_absolute_values(parsed) == []


def test_connection_identity_is_credential_free_and_stable() -> None:
    first = guard.connection_identity(
        "postgresql+asyncpg://omni_user:first-password@db:5432/omni_vibe_db"
    )
    second = guard.connection_identity(
        "postgresql://another:second-password@db:5432/omni_vibe_db"
    )
    assert first == second
    assert "password" not in first
    assert "omni_user" not in first
    assert first.startswith("db:")


def test_cross_worktree_database_volume_and_scheduler_are_blocked() -> None:
    manifest = _manifest()
    main = guard.container_from_inspect(
        _raw_container(
            "ke-main",
            service="knowledge-engine",
            worktree="E:/agent/omni",
            port=8002,
            scheduler_role="owner",
        ),
        manifest,
    )
    feature = guard.container_from_inspect(
        _raw_container(
            "ke-feature",
            service="knowledge-engine",
            worktree="E:/agent/work/feature-a",
            runtime_id="feature-a",
            port=8003,
            scheduler_role="owner",
        ),
        manifest,
    )
    issues = guard.analyze_runtime(
        [main, feature],
        manifest,
        _expected(manifest),
        runtime_id="omni-main",
        check_unknown_listeners=False,
    )
    assert {
        "cross_worktree_writable_database",
        "cross_worktree_writable_volume",
        "cross_worktree_scheduler",
    } <= _codes(issues)


def test_same_worktree_resource_reuse_is_not_cross_worktree_conflict() -> None:
    manifest = _manifest()
    first = guard.container_from_inspect(
        _raw_container("ke-a", service="knowledge-engine", worktree="E:/agent/omni"), manifest
    )
    second = guard.container_from_inspect(
        _raw_container("ke-b", service="knowledge-engine", worktree="E:/agent/omni"), manifest
    )
    issues = guard.analyze_runtime(
        [first, second],
        manifest,
        _expected(manifest),
        runtime_id="omni-main",
        check_unknown_listeners=False,
    )
    assert not any(issue.code.startswith("cross_worktree_") for issue in issues)


def test_wrong_port_owner_is_detected() -> None:
    manifest = _manifest()
    wrong = guard.container_from_inspect(
        _raw_container(
            "wrong-owner",
            service="knowledge-engine",
            worktree="E:/agent/omni",
            port=3000,
        ),
        manifest,
    )
    issues = guard.analyze_runtime(
        [wrong],
        manifest,
        _expected(manifest),
        runtime_id="omni-main",
        check_unknown_listeners=False,
    )
    assert "wrong_port_owner" in _codes(issues)


def test_missing_and_mismatched_build_identity_are_detected() -> None:
    manifest = _manifest()
    raw = _raw_container(
        "frontend",
        service="frontend",
        worktree="E:/agent/omni",
        port=3000,
        source_commit="c" * 40,
        source_fingerprint="d" * 64,
    )
    del raw["Config"]["Labels"]["io.omni.runtime_id"]
    del raw["Config"]["Labels"]["io.omni.worktree_id"]
    container = guard.container_from_inspect(raw, manifest)
    issues = guard.analyze_runtime(
        [container],
        manifest,
        _expected(manifest),
        runtime_id="omni-main",
        check_unknown_listeners=False,
    )
    codes = _codes(issues)
    assert "missing_runtime_identity" in codes
    assert "missing_worktree_identity" in codes

    raw["Config"]["Labels"]["io.omni.runtime_id"] = "omni-main"
    raw["Config"]["Labels"]["io.omni.worktree_id"] = guard.opaque_worktree_id("E:/agent/omni")
    mismatch = guard.container_from_inspect(raw, manifest)
    issues = guard.analyze_runtime(
        [mismatch],
        manifest,
        _expected(manifest),
        runtime_id="omni-main",
        check_unknown_listeners=False,
    )
    assert {"source_commit_mismatch", "source_fingerprint_mismatch"} <= _codes(issues)


def test_old_baked_image_with_new_runtime_expectation_is_stale() -> None:
    manifest = _manifest()
    raw = _raw_container(
        "ke-old-image",
        service="knowledge-engine",
        worktree="E:/agent/omni",
        source_commit="b" * 40,
        source_fingerprint="c" * 64,
        baked_source_commit="a" * 40,
        baked_source_fingerprint="d" * 64,
    )
    container = guard.container_from_inspect(raw, manifest)
    issues = guard.analyze_runtime(
        [container],
        manifest,
        {
            **_expected(manifest),
            "commit": "b" * 40,
            "checkout_fingerprint": "c" * 64,
        },
        runtime_id="omni-main",
        check_unknown_listeners=False,
    )
    assert {
        "baked_source_commit_mismatch",
        "baked_source_fingerprint_mismatch",
    } <= _codes(issues)


def test_safe_report_never_contains_connection_secrets() -> None:
    manifest = _manifest()
    secret = "do-not-print-this-password"
    raw = _raw_container(
        "ke-main",
        service="knowledge-engine",
        worktree="E:/agent/omni",
        database_url=f"postgresql://user:{secret}@db:5432/omni_vibe_db",
    )
    container = guard.container_from_inspect(raw, manifest)
    report = guard._report("audit", "omni-main", [container], [], _expected(manifest))
    serialized = json.dumps(report, ensure_ascii=False)
    assert secret not in serialized
    assert "postgresql://" not in serialized
    assert "E:/agent/omni" not in serialized
    assert "e:/agent/omni" not in serialized
    assert container.safe_dict()["worktree_ref"].startswith("worktree-")


def test_static_scan_reports_fixed_names_and_missing_identity_labels(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["compose_files"] = ["docker-compose.yml"]
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  frontend:\n    container_name: omni-frontend\n",
        encoding="utf-8",
    )
    issues = guard.scan_static(tmp_path, manifest)
    assert {"fixed_container_names", "compose_identity_labels_missing"} <= _codes(issues)


def test_required_service_gap_is_reported_only_for_verify_mode() -> None:
    manifest = _manifest()
    expected = _expected(manifest)
    audit_issues = guard.analyze_runtime(
        [],
        manifest,
        expected,
        runtime_id="omni-main",
        check_unknown_listeners=False,
        require_services=False,
    )
    verify_issues = guard.analyze_runtime(
        [],
        manifest,
        expected,
        runtime_id="omni-main",
        check_unknown_listeners=False,
        require_services=True,
    )
    assert "required_service_missing" not in _codes(audit_issues)
    assert "required_service_missing" in _codes(verify_issues)


def test_preflight_blocks_non_primary_long_lived_runtime(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["compose_files"] = []
    expected = _expected(manifest, worktree="E:/agent/omni/.worktrees/feature-a")
    expected["primary_worktree"] = guard.opaque_worktree_id("E:/agent/omni")
    issues = guard.preflight_policy_issues(tmp_path, manifest, expected)
    assert "non_primary_long_lived_runtime" in _codes(issues)


def test_allocation_evidence_preflight_rejects_missing_stale_and_wrong_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "allocations.json"
    allocation_id = "allocation-" + "a" * 32
    worktree_id = "worktree-" + "b" * 16
    with pytest.raises(guard.GuardFailure, match="missing"):
        guard.validate_allocation_evidence(
            path,
            allocation_id=allocation_id,
            runtime_id="runtime-a",
            worktree_id=worktree_id,
            source_commit="a" * 40,
            source_fingerprint="b" * 64,
        )
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    allocation = {
        "allocation_id": allocation_id,
        "lease_id": "lease-a",
        "repository_id": "repo-a",
        "change_id": "change-a",
        "owner": "agent-a",
        "runtime_id": "runtime-a",
        "worktree_id": worktree_id,
        "build_sha": "a" * 40,
        "source_fingerprint": "b" * 64,
        "compose_project": "omni-a",
        "ports": {"postgres": 15432},
        "volumes": ["omni-a-postgres"],
        "risk_level": "R2",
        "canonical": False,
        "cron_owner": False,
        "approval_worker_owner": True,
        "state": "active",
        "expires_at": expires,
    }
    state = {
        "schema_version": 1,
        "allocations": [allocation],
        "leases": [
            {
                "lease_id": "lease-a",
                "repository_id": "repo-a",
                "change_id": "change-a",
                "owner": "agent-a",
                "worktree_id": worktree_id,
                "risk_level": "R2",
                "mode": "write",
                "state": "active",
                "expires_at": expires,
            }
        ],
    }
    path.write_text(json.dumps(state), encoding="utf-8")
    verified = guard.validate_allocation_evidence(
        path,
        allocation_id=allocation_id,
        runtime_id="runtime-a",
        worktree_id=worktree_id,
        source_commit="a" * 40,
        source_fingerprint="b" * 64,
        compose_project="omni-a",
    )
    assert verified["allocation_id"] == allocation_id

    with pytest.raises(guard.GuardFailure, match="source_fingerprint"):
        guard.validate_allocation_evidence(
            path,
            allocation_id=allocation_id,
            runtime_id="runtime-a",
            worktree_id=worktree_id,
            source_commit="a" * 40,
            source_fingerprint="c" * 64,
        )
    allocation["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(guard.GuardFailure, match="not active"):
        guard.validate_allocation_evidence(
            path,
            allocation_id=allocation_id,
            runtime_id="runtime-a",
            worktree_id=worktree_id,
            source_commit="a" * 40,
            source_fingerprint="b" * 64,
        )


def test_allocation_preflight_rejects_old_migration_image_for_new_expected_source() -> None:
    verified = guard.validate_baked_identity(
        source_commit="a" * 40,
        source_fingerprint="b" * 64,
        baked_commit="a" * 40,
        baked_source_fingerprint="b" * 64,
    )
    assert verified["baked_source_commit"] == "a" * 40
    with pytest.raises(guard.GuardFailure, match="baked source commit"):
        guard.validate_baked_identity(
            source_commit="c" * 40,
            source_fingerprint="d" * 64,
            baked_commit="a" * 40,
            baked_source_fingerprint="b" * 64,
        )
    with pytest.raises(guard.GuardFailure, match="baked source fingerprint"):
        guard.validate_baked_identity(
            source_commit="a" * 40,
            source_fingerprint="d" * 64,
            baked_commit="a" * 40,
            baked_source_fingerprint="b" * 64,
        )
