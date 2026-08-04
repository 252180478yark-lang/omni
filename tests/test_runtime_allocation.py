from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "omni_runtime_allocation_tests", ROOT / "scripts" / "runtime_allocation.py"
)
assert SPEC is not None and SPEC.loader is not None
allocation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = allocation
SPEC.loader.exec_module(allocation)


def _run(repo: Path, *args: str) -> str:
    result = subprocess.run(args, cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-q", "-b", "main")
    _run(repo, "git", "config", "user.email", "test@example.com")
    _run(repo, "git", "config", "user.name", "Test")
    (repo / "config").mkdir()
    manifest = {
        "schema_version": 1,
        "canonical_runtime": {
            "runtime_id": "omni-main",
            "compose_project": "omni",
            "database": "omni_vibe_db",
        },
        "services": {
            "postgres": {"published_ports": [5432]},
            "redis": {"published_ports": [6379]},
            "frontend": {"published_ports": [3000]},
            "knowledge-engine": {"published_ports": [8002]},
        },
    }
    (repo / "config" / "runtime-manifest.yaml").write_text(json.dumps(manifest), encoding="utf-8")
    (repo / "services" / "example").mkdir(parents=True)
    (repo / "services" / "example" / "app.py").write_text("value = 1\n", encoding="utf-8")
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-qm", "base")
    return repo


def test_default_store_is_shared_by_git_common_dir(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    linked = tmp_path / "linked"
    _run(repo, "git", "worktree", "add", "-q", "-b", "feature", str(linked))
    assert allocation.default_state_dir(repo) == allocation.default_state_dir(linked)
    assert allocation.default_state_dir(repo).parent == repo / ".git"


def test_nonoverlapping_allocations_are_isolated_and_conflicts_fail(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    state_dir = tmp_path / "state"
    first = allocation.acquire(
        repo,
        change_id="change-a",
        owner="agent-a",
        path_globs=["services/a/**"],
        state_dir=state_dir,
    )
    second = allocation.acquire(
        repo,
        change_id="change-b",
        owner="agent-b",
        path_globs=["services/b/**"],
        state_dir=state_dir,
    )
    a, b = first["allocation"], second["allocation"]
    assert a["compose_project"] != b["compose_project"]
    assert a["database"] != b["database"]
    assert set(a["ports"].values()).isdisjoint(b["ports"].values())
    assert set(a["volumes"]).isdisjoint(b["volumes"])
    assert a["redis_namespace"] != b["redis_namespace"]
    assert a["cron_owner"] is b["cron_owner"] is False
    assert first["environment"]["OMNI_APPROVAL_WORKER_ENABLED"] == "true"
    assert first["environment"]["OMNI_APPROVAL_WORKER_ROLE"] == "owner"
    assert first["environment"]["OMNI_RESTART_POLICY"] == "no"
    assert (
        first["environment"]["OMNI_IDENTITY_JWT_SECRET_FILE"] != first["environment"]["OMNI_APPROVAL_HMAC_SECRET_FILE"]
    )
    assert first["environment"]["OMNI_COMPATIBILITY_TOKEN_FILE"] not in {
        first["environment"]["OMNI_APPROVAL_HMAC_SECRET_FILE"],
        first["environment"]["OMNI_IDENTITY_JWT_SECRET_FILE"],
    }

    with pytest.raises(allocation.AllocationConflict) as caught:
        allocation.acquire(
            repo,
            change_id="change-c",
            owner="agent-c",
            path_globs=["services/a/app.py"],
            state_dir=state_dir,
        )
    assert any(item["kind"] == "path" and item["owner"] == "agent-a" for item in caught.value.conflicts)


def test_real_manifest_allocates_every_host_dev_service_port() -> None:
    manifest = json.loads((ROOT / "config" / "runtime-manifest.yaml").read_text(encoding="utf-8"))
    canonical_ports = allocation._canonical_ports(manifest)
    host_services = {
        "identity-service",
        "ai-provider-hub",
        "knowledge-engine",
        "news-aggregator",
        "video-analysis",
        "livestream-analysis",
        "ad-review-service",
        "scout-agent",
        "frontend",
        "postgres",
        "redis",
    }
    assert host_services <= set(canonical_ports)
    projected = allocation.allocation_environment(
        {
            "compose_project": "omni-fixture",
            "runtime_id": "runtime-fixture",
            "allocation_id": "allocation-" + "a" * 32,
            "database": "omni_verify_fixture",
            "database_schema": "wt_fixture",
            "redis_namespace": "fixture",
            "cron_owner": False,
            "approval_worker_owner": True,
            "build_sha": "b" * 40,
            "source_fingerprint": "c" * 64,
            "canonical": False,
            "worktree_id": "worktree-" + "d" * 16,
            "risk_level": "R2",
            "ports": canonical_ports,
            "volumes": ["postgres-data", "redis-data", "knowledge-data"],
        }
    )
    for service in host_services:
        assert allocation.PORT_ENV[service] in projected
    assert projected["OMNI_BUILD_COMMIT"] == "b" * 40
    assert projected["OMNI_BUILD_SOURCE_FINGERPRINT"] == "c" * 64


def test_read_only_allocation_does_not_own_scheduler_or_approval_worker(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    result = allocation.acquire(
        repo,
        change_id="read-only",
        owner="reader",
        path_globs=["services/example/**"],
        mode="read",
        state_dir=tmp_path / "state",
    )
    assert result["allocation"]["cron_owner"] is False
    assert result["allocation"]["approval_worker_owner"] is False
    assert result["environment"]["OMNI_SCHEDULER_ENABLED"] == "false"
    assert result["environment"]["OMNI_APPROVAL_WORKER_ENABLED"] == "false"


def test_expired_record_is_retained_but_does_not_block_reacquire(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    state_dir = tmp_path / "state"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = allocation.acquire(
        repo,
        change_id="old",
        owner="agent-old",
        path_globs=["services/shared/**"],
        ttl_seconds=60,
        state_dir=state_dir,
        now=start,
    )
    second = allocation.acquire(
        repo,
        change_id="new",
        owner="agent-new",
        path_globs=["services/shared/**"],
        ttl_seconds=60,
        state_dir=state_dir,
        now=start + timedelta(seconds=61),
    )
    state = allocation.list_state(repo, state_dir=state_dir, now=start + timedelta(seconds=61))
    old = next(item for item in state["allocations"] if item["allocation_id"] == first["allocation"]["allocation_id"])
    assert old["state"] == "stale"
    assert second["allocation"]["state"] == "active"
    assert len(state["allocations"]) == 2


def test_hook_path_conflict_read_api_is_read_only_and_reports_stale(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    missing_dir = tmp_path / "missing"
    before = allocation.resolve_path_conflict(
        repo, "services/a/app.py", "change-a", read_only=False, state_dir=missing_dir
    )
    assert before == {
        "known": False,
        "conflict": False,
        "owner": None,
        "change_id": None,
        "expires_at": None,
        "stale": False,
    }
    assert not missing_dir.exists()

    state_dir = tmp_path / "state"
    start = datetime.now(timezone.utc)
    allocation.acquire(
        repo,
        change_id="change-a",
        owner="agent-a",
        path_globs=["services/a/**"],
        ttl_seconds=60,
        state_dir=state_dir,
        now=start,
    )
    same = allocation.resolve_path_conflict(repo, "services/a/app.py", "change-a", read_only=False, state_dir=state_dir)
    other_read = allocation.resolve_path_conflict(
        repo, "services/a/app.py", "change-b", read_only=True, state_dir=state_dir
    )
    other_write = allocation.resolve_path_conflict(
        repo, "services/a/app.py", "change-b", read_only=False, state_dir=state_dir
    )
    assert same["conflict"] is False
    assert other_read["conflict"] is False
    assert other_write["conflict"] is True
    assert other_write["owner"] == "agent-a"

    state = json.loads((state_dir / "allocations.json").read_text(encoding="utf-8"))
    state["leases"][0]["expires_at"] = allocation.isoformat(start - timedelta(seconds=1))
    (state_dir / "allocations.json").write_text(json.dumps(state), encoding="utf-8")
    stale = allocation.resolve_path_conflict(
        repo, "services/a/app.py", "change-b", read_only=False, state_dir=state_dir
    )
    assert stale["stale"] is True
    assert stale["conflict"] is False


def test_source_fingerprint_tracks_content_not_mtime_or_secret_files(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    source = repo / "services" / "example" / "app.py"
    initial = allocation.source_tree_fingerprint(repo)
    stat = source.stat()
    os.utime(source, (stat.st_atime + 5, stat.st_mtime + 5))
    assert allocation.source_tree_fingerprint(repo) == initial
    source.write_text("value = 2\n", encoding="utf-8")
    changed = allocation.source_tree_fingerprint(repo)
    assert changed != initial
    (repo / ".env").write_text("API_KEY=live_abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")
    assert allocation.source_tree_fingerprint(repo) == changed


def test_lock_file_stays_one_byte_and_release_requires_owner_cas(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    state_dir = tmp_path / "state"
    result = allocation.acquire(
        repo,
        change_id="change-a",
        owner="agent-a",
        path_globs=["services/a/**"],
        state_dir=state_dir,
    )
    for _ in range(5):
        allocation.list_state(repo, state_dir=state_dir)
        allocation.acquire(
            repo,
            change_id="change-a",
            owner="agent-a",
            path_globs=["services/a/**"],
            state_dir=state_dir,
        )
    assert (state_dir / "allocations.lock").stat().st_size == 1
    allocation_id = result["allocation"]["allocation_id"]
    with pytest.raises(allocation.AllocationError):
        allocation.release(repo, allocation_id, owner="other", expected_revision=1, state_dir=state_dir)
    with pytest.raises(allocation.CompareAndSwapConflict):
        allocation.release(
            repo,
            allocation_id,
            owner="agent-a",
            expected_revision=2,
            state_dir=state_dir,
        )
    released = allocation.release(repo, allocation_id, owner="agent-a", expected_revision=1, state_dir=state_dir)
    assert released["state"] == "released"


def test_approval_hmac_secret_is_external_private_reused_and_never_returned(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    secret_path = tmp_path / "external-secrets" / "approval-hmac.key"
    first = allocation.ensure_approval_hmac_secret(repo, path=secret_path)
    first_bytes = first.read_bytes()
    second = allocation.ensure_approval_hmac_secret(repo, path=secret_path)

    assert first == second == secret_path.resolve()
    assert len(first_bytes) >= 32
    assert second.read_bytes() == first_bytes
    if os.name != "nt":
        assert second.stat().st_mode & 0o077 == 0
    serialized_path = str(second)
    assert first_bytes.hex() not in serialized_path

    inside = repo / ".runtime" / "approval-hmac.key"
    with pytest.raises(allocation.AllocationError, match="outside"):
        allocation.ensure_approval_hmac_secret(repo, path=inside)


def test_identity_jwt_secret_is_independent_external_private_and_reused(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    directory = tmp_path / "external-secrets"
    approval_path = directory / "approval-hmac.key"
    identity_path = directory / "identity-jwt.key"
    allocation.ensure_approval_hmac_secret(repo, path=approval_path)
    first = allocation.ensure_identity_jwt_secret(repo, path=identity_path)
    first_bytes = first.read_bytes()
    second = allocation.ensure_identity_jwt_secret(repo, path=identity_path)

    assert first == second == identity_path.resolve()
    assert len(first_bytes) >= 32
    assert first_bytes.isascii()
    assert second.read_bytes() == first_bytes
    assert approval_path.read_bytes() != first_bytes
    if os.name != "nt":
        assert second.stat().st_mode & 0o077 == 0

    inside = repo / ".runtime" / "identity-jwt.key"
    with pytest.raises(allocation.AllocationError, match="outside"):
        allocation.ensure_identity_jwt_secret(repo, path=inside)


def test_compatibility_token_is_independent_external_private_and_reused(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    directory = tmp_path / "external-secrets"
    approval_path = directory / "approval-hmac.key"
    identity_path = directory / "identity-jwt.key"
    compatibility_path = directory / "compatibility-token.key"
    allocation.ensure_approval_hmac_secret(repo, path=approval_path)
    allocation.ensure_identity_jwt_secret(repo, path=identity_path)
    first = allocation.ensure_compatibility_token(repo, path=compatibility_path)
    first_bytes = first.read_bytes()
    second = allocation.ensure_compatibility_token(repo, path=compatibility_path)

    assert first == second == compatibility_path.resolve()
    assert len(first_bytes) >= 32
    assert first_bytes.isascii()
    assert second.read_bytes() == first_bytes
    assert first_bytes not in {approval_path.read_bytes(), identity_path.read_bytes()}
    if os.name != "nt":
        assert second.stat().st_mode & 0o077 == 0

    inside = repo / ".runtime" / "compatibility-token.key"
    with pytest.raises(allocation.AllocationError, match="outside"):
        allocation.ensure_compatibility_token(repo, path=inside)
