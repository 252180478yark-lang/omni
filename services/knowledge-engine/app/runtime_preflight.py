"""Pure-stdlib RuntimeAllocation startup gate.

This module performs no network, database, subprocess, or filesystem writes.
Knowledge Engine must call it before initializing any runtime resource.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


MAX_EVIDENCE_BYTES = 10_000_000


class RuntimePreflightError(RuntimeError):
    """A credential-free startup identity failure safe to expose."""


def _utc_time(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RuntimePreflightError("allocation evidence has an invalid expiry") from exc
    if parsed.tzinfo is None:
        raise RuntimePreflightError("allocation evidence expiry must include UTC offset")
    return parsed.astimezone(timezone.utc)


def _digest_ports(value: object) -> str:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str)
        or not isinstance(port, int)
        or isinstance(port, bool)
        or not 1 <= port <= 65535
        for key, port in value.items()
    ):
        raise RuntimePreflightError("RuntimeAllocation port set is invalid")
    encoded = json.dumps(
        dict(sorted(value.items())), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _digest_volumes(value: object) -> str:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise RuntimePreflightError("RuntimeAllocation volume set is invalid")
    encoded = json.dumps(sorted(value), separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_allocation_evidence(
    allocation_file: Path,
    *,
    allocation_id: str,
    runtime_id: str,
    worktree_id: str,
    source_commit: str,
    source_fingerprint: str,
    compose_project: str = "",
    ports_sha256: str = "",
    volumes_sha256: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    required = {
        "allocation_id": allocation_id,
        "runtime_id": runtime_id,
        "worktree_id": worktree_id,
        "source_commit": source_commit,
        "source_fingerprint": source_fingerprint,
    }
    missing = sorted(key for key, value in required.items() if not str(value).strip())
    if missing:
        raise RuntimePreflightError(
            "allocation preflight is missing required identity: " + ", ".join(missing)
        )
    formats = {
        "allocation_id": r"allocation-[0-9a-f]{32}",
        "worktree_id": r"worktree-[0-9a-f]{16}",
        "source_commit": r"[0-9a-f]{40}",
        "source_fingerprint": r"[0-9a-f]{64}",
    }
    invalid = sorted(
        key for key, pattern in formats.items()
        if re.fullmatch(pattern, str(required[key])) is None
    )
    if invalid:
        raise RuntimePreflightError(
            "allocation preflight has invalid identity format: " + ", ".join(invalid)
        )
    if compose_project and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", compose_project) is None:
        raise RuntimePreflightError("allocation preflight has invalid compose identity")
    for name, digest in (("ports", ports_sha256), ("volumes", volumes_sha256)):
        if digest and re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise RuntimePreflightError(
                f"allocation preflight has invalid {name} digest"
            )
    try:
        if not allocation_file.is_file() or allocation_file.stat().st_size > MAX_EVIDENCE_BYTES:
            raise RuntimePreflightError(
                "allocation evidence file is missing or exceeds the size limit"
            )
        state = json.loads(allocation_file.read_text(encoding="utf-8"))
    except RuntimePreflightError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimePreflightError(
            "allocation evidence file is unreadable or invalid"
        ) from exc
    if not isinstance(state, Mapping) or state.get("schema_version") != 1:
        raise RuntimePreflightError("allocation evidence has unsupported schema")
    allocations = state.get("allocations")
    leases = state.get("leases")
    if not isinstance(allocations, list) or not isinstance(leases, list):
        raise RuntimePreflightError("allocation evidence is incomplete")
    allocation = next(
        (
            item
            for item in allocations
            if isinstance(item, Mapping) and item.get("allocation_id") == allocation_id
        ),
        None,
    )
    if allocation is None:
        raise RuntimePreflightError("RuntimeAllocation was not found")
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if allocation.get("state") != "active" or _utc_time(allocation.get("expires_at")) <= moment:
        raise RuntimePreflightError("RuntimeAllocation is not active")
    exact = {
        "runtime_id": runtime_id,
        "worktree_id": worktree_id,
        "build_sha": source_commit,
        "source_fingerprint": source_fingerprint,
    }
    if compose_project:
        exact["compose_project"] = compose_project
    for key, expected in exact.items():
        if allocation.get(key) != expected:
            raise RuntimePreflightError(
                f"RuntimeAllocation {key} does not match startup identity"
            )
    if not isinstance(allocation.get("owner"), str) or not allocation["owner"].strip():
        raise RuntimePreflightError("RuntimeAllocation owner is invalid")
    if not isinstance(allocation.get("change_id"), str) or not allocation["change_id"].strip():
        raise RuntimePreflightError("RuntimeAllocation change identity is invalid")
    if not isinstance(allocation.get("cron_owner"), bool):
        raise RuntimePreflightError("RuntimeAllocation scheduler ownership is invalid")
    if not isinstance(allocation.get("approval_worker_owner"), bool):
        raise RuntimePreflightError("RuntimeAllocation approval worker ownership is invalid")
    if not isinstance(allocation.get("canonical"), bool):
        raise RuntimePreflightError("RuntimeAllocation canonical mode is invalid")
    if str(allocation.get("risk_level")) not in {"R0", "R1", "R2", "R3"}:
        raise RuntimePreflightError("RuntimeAllocation risk level is invalid")
    port_digest = _digest_ports(allocation.get("ports"))
    volume_digest = _digest_volumes(allocation.get("volumes"))
    if ports_sha256 and ports_sha256 != port_digest:
        raise RuntimePreflightError(
            "RuntimeAllocation port set does not match startup identity"
        )
    if volumes_sha256 and volumes_sha256 != volume_digest:
        raise RuntimePreflightError(
            "RuntimeAllocation volume set does not match startup identity"
        )
    lease = next(
        (
            item
            for item in leases
            if isinstance(item, Mapping)
            and item.get("lease_id") == allocation.get("lease_id")
        ),
        None,
    )
    if (
        lease is None
        or lease.get("state") != "active"
        or _utc_time(lease.get("expires_at")) <= moment
    ):
        raise RuntimePreflightError("WorkspaceLease is not active")
    lease_exact = {
        "repository_id": allocation.get("repository_id"),
        "worktree_id": worktree_id,
        "change_id": allocation.get("change_id"),
        "owner": allocation.get("owner"),
        "risk_level": allocation.get("risk_level"),
    }
    if any(lease.get(key) != expected for key, expected in lease_exact.items()):
        raise RuntimePreflightError("WorkspaceLease does not match RuntimeAllocation")
    if lease.get("mode") not in {"read", "write"}:
        raise RuntimePreflightError("WorkspaceLease access mode is invalid")
    expected_worker_owner = (
        bool(allocation.get("cron_owner"))
        if allocation.get("canonical")
        else lease.get("mode") == "write"
    )
    if allocation.get("approval_worker_owner") is not expected_worker_owner:
        raise RuntimePreflightError(
            "RuntimeAllocation approval worker ownership does not match database ownership"
        )
    return dict(allocation)


def validate_runtime_environment(
    environ: Mapping[str, str] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    names = {
        "allocation_file": "OMNI_RUNTIME_ALLOCATION_FILE",
        "allocation_id": "OMNI_ALLOCATION_ID",
        "runtime_id": "OMNI_RUNTIME_ID",
        "worktree_id": "OMNI_WORKTREE_ID",
        "source_commit": "OMNI_SOURCE_COMMIT",
        "source_fingerprint": "OMNI_SOURCE_FINGERPRINT",
        "compose_project": "COMPOSE_PROJECT_NAME",
        "ports_sha256": "OMNI_ALLOCATED_PORTS_SHA256",
        "volumes_sha256": "OMNI_ALLOCATED_VOLUMES_SHA256",
        "baked_source_commit": "OMNI_BAKED_SOURCE_COMMIT",
        "baked_source_fingerprint": "OMNI_BAKED_SOURCE_FINGERPRINT",
    }
    values = {key: str(env.get(name, "")).strip() for key, name in names.items()}
    missing = sorted(name for key, name in names.items() if not values[key])
    if missing:
        raise RuntimePreflightError(
            "runtime environment is missing required allocation identity: "
            + ", ".join(missing)
        )
    if (
        values.pop("baked_source_commit") != values["source_commit"]
        or values.pop("baked_source_fingerprint") != values["source_fingerprint"]
    ):
        raise RuntimePreflightError(
            "baked image identity does not match RuntimeAllocation source"
        )
    return validate_allocation_evidence(
        Path(values.pop("allocation_file")), now=now, **values
    )
