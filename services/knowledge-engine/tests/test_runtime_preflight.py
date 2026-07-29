from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.runtime_preflight import (
    RuntimePreflightError,
    validate_runtime_environment,
)


NOW = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)


def fixture() -> tuple[dict, dict[str, str]]:
    ports = {"knowledge-engine": 18002, "postgres": 15432}
    volumes = ["runtime-postgres", "runtime-redis", "runtime-knowledge"]
    allocation = {
        "allocation_id": "allocation-" + "a" * 32,
        "lease_id": "lease-" + "b" * 32,
        "repository_id": "repo-" + "c" * 16,
        "worktree_id": "worktree-" + "d" * 16,
        "change_id": "system-convergence",
        "owner": "agent-runtime",
        "canonical": False,
        "runtime_id": "system-convergence-deadbeef",
        "compose_project": "omni-system-convergence",
        "ports": ports,
        "database": "omni_verify_system_convergence",
        "database_schema": "wt_system_convergence",
        "volumes": volumes,
        "redis_namespace": "system-convergence",
        "cron_owner": False,
        "approval_worker_owner": True,
        "risk_level": "R3",
        "build_sha": "e" * 40,
        "source_fingerprint": "f" * 64,
        "created_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "state": "active",
        "revision": 1,
    }
    lease = {
        "lease_id": allocation["lease_id"],
        "repository_id": allocation["repository_id"],
        "worktree_id": allocation["worktree_id"],
        "change_id": allocation["change_id"],
        "owner": allocation["owner"],
        "path_globs": ["services/knowledge-engine/**"],
        "mode": "write",
        "risk_level": allocation["risk_level"],
        "created_at": NOW.isoformat(),
        "expires_at": allocation["expires_at"],
        "state": "active",
        "revision": 1,
    }
    state = {
        "schema_version": 1,
        "generation": 1,
        "allocations": [allocation],
        "leases": [lease],
    }
    env = {
        "OMNI_RUNTIME_ALLOCATION_FILE": "unused",
        "OMNI_ALLOCATION_ID": allocation["allocation_id"],
        "OMNI_RUNTIME_ID": allocation["runtime_id"],
        "OMNI_WORKTREE_ID": allocation["worktree_id"],
        "OMNI_SOURCE_COMMIT": allocation["build_sha"],
        "OMNI_SOURCE_FINGERPRINT": allocation["source_fingerprint"],
        "COMPOSE_PROJECT_NAME": allocation["compose_project"],
        "OMNI_ALLOCATED_PORTS_SHA256": hashlib.sha256(
            json.dumps(ports, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "OMNI_ALLOCATED_VOLUMES_SHA256": hashlib.sha256(
            json.dumps(sorted(volumes), separators=(",", ":")).encode()
        ).hexdigest(),
        "OMNI_BAKED_SOURCE_COMMIT": allocation["build_sha"],
        "OMNI_BAKED_SOURCE_FINGERPRINT": allocation["source_fingerprint"],
    }
    return state, env


def test_runtime_environment_binds_exact_active_allocation_and_lease(tmp_path: Path):
    state, env = fixture()
    path = tmp_path / "allocations.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    env["OMNI_RUNTIME_ALLOCATION_FILE"] = str(path)
    result = validate_runtime_environment(env, now=NOW)
    assert result["allocation_id"] == env["OMNI_ALLOCATION_ID"]
    assert result["cron_owner"] is False
    assert result["approval_worker_owner"] is True


@pytest.mark.parametrize(
    "mutation",
    ["expired", "owner-mismatch", "ports-mismatch", "source-mismatch"],
)
def test_runtime_preflight_fails_closed_on_stale_or_mismatched_evidence(
    tmp_path: Path, mutation: str
):
    state, env = fixture()
    if mutation == "expired":
        state["allocations"][0]["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    elif mutation == "owner-mismatch":
        state["leases"][0]["owner"] = "different-owner"
    elif mutation == "ports-mismatch":
        env["OMNI_ALLOCATED_PORTS_SHA256"] = "0" * 64
    else:
        env["OMNI_SOURCE_FINGERPRINT"] = "0" * 64
    path = tmp_path / "allocations.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    env["OMNI_RUNTIME_ALLOCATION_FILE"] = str(path)
    with pytest.raises(RuntimePreflightError):
        validate_runtime_environment(env, now=NOW)


def test_missing_runtime_environment_is_typed_and_path_free():
    with pytest.raises(RuntimePreflightError) as caught:
        validate_runtime_environment({})
    assert "OMNI_RUNTIME_ALLOCATION_FILE" in str(caught.value)
    assert "/" not in str(caught.value)


@pytest.mark.asyncio
async def test_lifespan_preflight_failure_precedes_db_and_filesystem(
    tmp_path: Path, monkeypatch
):
    from app import main

    upload = tmp_path / "must-not-exist"
    init_pool = AsyncMock()
    monkeypatch.setattr(main, "UPLOAD_DIR", str(upload))
    monkeypatch.setattr(main, "init_pool", init_pool)
    monkeypatch.setattr(
        main,
        "validate_runtime_environment",
        lambda: (_ for _ in ()).throw(RuntimePreflightError("fixture preflight failed")),
    )
    with pytest.raises(RuntimePreflightError, match="fixture preflight failed"):
        async with main.lifespan(main.app):
            pass
    init_pool.assert_not_awaited()
    assert not upload.exists()


def test_main_source_orders_preflight_before_runtime_side_effects():
    source = (
        Path(__file__).resolve().parents[1] / "app" / "main.py"
    ).read_text(encoding="utf-8")
    lifespan = source.split("async def lifespan", 1)[1].split("app = FastAPI", 1)[0]
    assert lifespan.index("allocation = validate_runtime_environment()") < lifespan.index(
        "await init_pool()"
    )
    assert lifespan.index("allocation = validate_runtime_environment()") < lifespan.index(
        "Path(UPLOAD_DIR).mkdir"
    )
    assert 'os.getenv("OMNI_SCHEDULER_ENABLED", "false")' in lifespan
    module_prefix = source.split("async def lifespan", 1)[0]
    assert "makedirs(" not in module_prefix
