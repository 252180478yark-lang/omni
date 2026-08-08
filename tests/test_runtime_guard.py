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
    health_status: str = "healthy",
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
        "State": {"Status": "running", "Health": {"Status": health_status}},
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


def test_verify_uses_exact_profile_services_and_rejects_leftovers() -> None:
    manifest = _manifest()
    expected = _expected(manifest)
    content_services = manifest["runtime_profiles"]["profiles"]["content"]["long_lived_services"]
    containers = [
        guard.container_from_inspect(
            _raw_container(
                f"fixture-{service}",
                service=service,
                worktree="E:/agent/omni",
                database_url="",
                volume=None,
            ),
            manifest,
        )
        for service in content_services
    ]
    content_issues = guard.analyze_runtime(
        containers,
        manifest,
        expected,
        runtime_id="omni-main",
        runtime_profile="content",
        check_unknown_listeners=False,
        require_services=True,
    )
    assert "required_service_missing" not in _codes(content_issues)
    assert "unexpected_profile_service" not in _codes(content_issues)

    core_issues = guard.analyze_runtime(
        containers,
        manifest,
        expected,
        runtime_id="omni-main",
        runtime_profile="core",
        check_unknown_listeners=False,
        require_services=True,
    )
    unexpected = [issue for issue in core_issues if issue.code == "unexpected_profile_service"]
    assert {issue.containers[0].split("#", 1)[0] for issue in unexpected} == {
        "fixture-video-analysis",
        "fixture-livestream-analysis",
        "fixture-scout-agent",
    }

    unknown = guard.container_from_inspect(
        _raw_container(
            "fixture-unknown",
            service="unmanaged-sidecar",
            worktree="E:/agent/omni",
            database_url="",
            volume=None,
        ),
        manifest,
    )
    unknown_issues = guard.analyze_runtime(
        [*containers, unknown],
        manifest,
        expected,
        runtime_id="omni-main",
        runtime_profile="content",
        check_unknown_listeners=False,
        require_services=True,
    )
    assert any(
        issue.code == "unexpected_profile_service" and "fixture-unknown" in issue.containers[0]
        for issue in unknown_issues
    )


def test_other_runtime_service_cannot_satisfy_selected_profile() -> None:
    manifest = _manifest()
    foreign_frontend = guard.container_from_inspect(
        _raw_container(
            "foreign-frontend",
            service="frontend",
            worktree="E:/agent/omni",
            runtime_id="other-runtime",
            database_url="",
            volume=None,
        ),
        manifest,
    )
    issues = guard.analyze_runtime(
        [foreign_frontend],
        manifest,
        _expected(manifest),
        runtime_id="omni-main",
        runtime_profile="core",
        check_unknown_listeners=False,
        require_services=True,
    )
    assert any(
        issue.code == "required_service_missing" and "frontend" in issue.message
        for issue in issues
    )


def test_health_checks_only_selected_profile_services() -> None:
    manifest = _manifest()
    manifest["services"]["video-analysis"]["health"] = {"kind": "docker"}
    video = guard.container_from_inspect(
        _raw_container(
            "video-unhealthy",
            service="video-analysis",
            worktree="E:/agent/omni",
            database_url="",
            volume=None,
            health_status="unhealthy",
        ),
        manifest,
    )
    assert "service_unhealthy" not in _codes(
        guard._health_issues(
            [video], manifest, 0.01, runtime_id="omni-main", runtime_profile="core"
        )
    )
    assert "service_unhealthy" in _codes(
        guard._health_issues(
            [video], manifest, 0.01, runtime_id="omni-main", runtime_profile="content"
        )
    )


@pytest.mark.parametrize(
    ("service", "runtime_profile", "port"),
    (("scout-agent", "content", 28009), ("ad-review-service", "full", 28008)),
)
def test_profile_http_health_uses_the_runtime_container_port(
    monkeypatch, service: str, runtime_profile: str, port: int
) -> None:
    manifest = _manifest()
    container = guard.container_from_inspect(
        _raw_container(
            f"healthy-{service}",
            service=service,
            worktree="E:/agent/omni",
            port=port,
            database_url="",
            volume=None,
        ),
        manifest,
    )
    opened: list[str] = []

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _Opener:
        def open(self, url: str, timeout: float):
            opened.append(url)
            return _Response()

    monkeypatch.setattr(guard, "build_opener", lambda *_args, **_kwargs: _Opener())
    issues = guard._health_issues(
        [container],
        manifest,
        0.01,
        runtime_id="omni-main",
        runtime_profile=runtime_profile,
    )
    assert "service_unhealthy" not in _codes(issues)
    assert opened == [f"http://127.0.0.1:{port}/health"]

    opened.clear()
    guard._health_issues(
        [container], manifest, 0.01, runtime_id="omni-main", runtime_profile="core"
    )
    assert opened == []


def test_manifest_rejects_inconsistent_profile_membership() -> None:
    manifest = _manifest()
    manifest["services"]["scout-agent"]["runtime_profiles"] = ["full"]
    with pytest.raises(guard.GuardFailure, match="inconsistent profile membership"):
        guard.runtime_profile_spec(manifest, "content")


def test_preflight_blocks_non_primary_long_lived_runtime(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["compose_files"] = []
    expected = _expected(manifest, worktree="E:/agent/omni/.worktrees/feature-a")
    expected["primary_worktree"] = guard.opaque_worktree_id("E:/agent/omni")
    issues = guard.preflight_policy_issues(tmp_path, manifest, expected)
    assert "non_primary_long_lived_runtime" in _codes(issues)


def test_preflight_reports_allocation_profile_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    manifest["compose_files"] = []
    expected = _expected(manifest)

    class _AllocationModule:
        @staticmethod
        def list_state(_repo_root: Path, *, state_dir: Path | None = None) -> dict:
            del state_dir
            return {
                "allocations": [
                    {
                        "allocation_id": "allocation-test",
                        "state": "active",
                        "worktree_id": expected["worktree"],
                        "runtime_id": "omni-main",
                        "runtime_profile": "core",
                        "canonical": True,
                        "database": manifest["canonical_runtime"]["database"],
                        "cron_owner": True,
                    }
                ]
            }

        @staticmethod
        def worktree_id(_repo_root: Path) -> str:
            return expected["worktree"]

    monkeypatch.setattr(guard, "_load_allocation_module", lambda _repo_root: _AllocationModule)
    issues = guard.preflight_policy_issues(
        tmp_path,
        manifest,
        expected,
        allocation_id="allocation-test",
        runtime_id="omni-main",
        runtime_profile="content",
    )

    mismatch = next(issue for issue in issues if issue.code == "allocation_profile_mismatch")
    assert mismatch.severity == "error"
    assert mismatch.message == "RuntimeAllocation runtime profile does not match preflight"


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
        "runtime_profile": "core",
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
        runtime_profile="core",
    )
    assert verified["allocation_id"] == allocation_id

    with pytest.raises(guard.GuardFailure, match="runtime_profile"):
        guard.validate_allocation_evidence(
            path,
            allocation_id=allocation_id,
            runtime_id="runtime-a",
            worktree_id=worktree_id,
            source_commit="a" * 40,
            source_fingerprint="b" * 64,
            runtime_profile="full",
        )

    del allocation["runtime_profile"]
    path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(guard.GuardFailure, match="release/reacquire"):
        guard.validate_allocation_evidence(
            path,
            allocation_id=allocation_id,
            runtime_id="runtime-a",
            worktree_id=worktree_id,
            source_commit="a" * 40,
            source_fingerprint="b" * 64,
        )
    allocation["runtime_profile"] = "core"
    path.write_text(json.dumps(state), encoding="utf-8")

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
