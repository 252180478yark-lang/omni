"""Persist and verify redacted, fail-closed evidence before resuming W5.

This is deliberately not a W5 writer.  It reads the dirty linked worktree,
validates every supplied CI receipt through one memoized bounded-live verifier,
and writes a path/status-only recovery manifest outside every worktree.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence


class RecoveryEvidenceError(ValueError):
    """Recovery evidence is incomplete or cannot be safely interpreted."""


W5_CHANGE_ID = "2026-08-02-omni-unified-ai-workbench-w5"
ALLOWED_W5_RECOVERY_RESIDUAL_PATHS = (
    "docs/prds/2026-07-29-omni-fde-system-convergence-master-prd/implementation-status.yaml",
    "frontend/tests/agent-chat/unit/canonical-artifact-client.test.ts",
)
# This is the authoritative historical-delivery inventory for W5 recovery.
# It is deliberately not a caller parameter: recovery cannot approve a smaller
# receipt set just because that smaller set happens to validate faster.
AUTHORITATIVE_W5_HISTORICAL_DELIVERY_IDS = (
    "2026-08-01-system-convergence-s4-s6-static",
    "2026-08-01-system-convergence-s4-s6-gap-closure",
    "2026-08-01-system-convergence-s7-s14",
    "2026-08-02-omni-unified-ai-workbench-w0",
    "2026-08-02-omni-unified-ai-workbench-w1-shell-ia",
    "2026-08-02-omni-unified-ai-workbench-g1-shell-bootstrap",
    "2026-08-02-omni-workbench-g2-context-semantics",
    "2026-08-04-w5-ownership-provenance-fail-closed",
    "2026-08-04-s8-s10-supersession-handoff",
)
# Exact, redacted finding fingerprints from the preserved W5 source.  A path
# and rule match alone is not sufficient: added occurrences fail closed.
W5_FIXTURE_SECRET_ALLOWLIST = (
    ("frontend/tests/agent-chat/unit/host-bridge-client.test.ts", "bearer_token", "222342cc5fed3f72b79b2ba747d803db07d7b89c7e15a8f844c10f2de41d9f1b"),
    ("frontend/tests/agent-chat/unit/workbench-binding.test.ts", "bearer_token", "aa62eaa577e536cd3f7c28efdd1bef9834ffac2f9bb106bbb947194a49f11a44"),
    ("frontend/tests/agent-chat/unit/workbench-binding.test.ts", "private_key", "9a6e4b537996371998c26d4679d47de3d6e1953095904439e819b69b417cebcb"),
    ("services/host-bridge/tests/test_w5_acceptance.py", "bearer_token", "0115773b857e39faf4a359a29b61ac739265bcf622a79a697e6a8595bc875d53"),
    ("services/host-bridge/tests/test_w5_acceptance.py", "bearer_token", "01163f3b5646a560a9574e0db748533f5638dce86dce368ebd126e7fe2632c7e"),
    ("services/host-bridge/tests/test_w5_acceptance.py", "bearer_token", "1adea3293b110f7d7af36f6baadc125c1d0c008078bdd46e38f6bb59d7b313a8"),
    ("services/host-bridge/tests/test_w5_acceptance.py", "bearer_token", "7b7170199d70d391d4a66d6b10bd20f5cc47db50baba9daf8dceeb40892ded4e"),
    ("services/host-bridge/tests/test_w5_acceptance.py", "bearer_token", "a342eb92f347563aa4e3f9e1e406b071927310000e78c66e28a66d0f2ebdb3f8"),
    ("services/host-bridge/tests/test_w5_acceptance.py", "bearer_token", "c4015510c663fb354a3b22a51ed178b19b8f64886d3d40ab9799ba9e9cd1066e"),
    ("services/host-bridge/tests/test_w5_acceptance.py", "bearer_token", "f995698f18662c52414e0a04ca97f637ac1385e97f67cba0963a25297a04fc68"),
    ("services/host-bridge/tests/test_w5_acceptance.py", "credential_assignment", "2ce4788e0cbcd14698ecbfb6bd90836da08abf619ee7625c7d3b36e3a732c80f"),
)
_SECRET_SCAN_LOCK = threading.RLock()


def _load_sibling(name: str) -> ModuleType:
    path = Path(__file__).resolve().with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"omni_w5_recovery_{name}", path)
    if spec is None or spec.loader is None:
        raise RecoveryEvidenceError(f"cannot load {name}: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ownership = _load_sibling("workspace_ownership")
projection = _load_sibling("generate_implementation_status")
runtime = _load_sibling("runtime_allocation")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _status_snapshot(source_worktree: Path) -> dict[str, Any]:
    source = ownership.repository_root(source_worktree)
    # Ownership reporting caches status during a single inventory.  Recovery
    # evidence deliberately takes independent samples, so no cached status may
    # bridge the source-anchor comparison.
    ownership._status_entries.cache_clear()
    entries = ownership._status_entries(source)
    rows = []
    for path, status in entries:
        candidate = source / path
        try:
            content = candidate.read_bytes() if candidate.is_file() else None
        except OSError as exc:
            raise RecoveryEvidenceError(f"cannot fingerprint recovery path: {path}: {exc}") from exc
        content_sha256 = _sha256(content) if content is not None else "<missing>"
        rows.append(
            {"path": path, "git_status": status, "content_sha256": content_sha256}
        )
    # This exact format is the recovery anchor: sorted relative path, a tab,
    # lowercase content SHA-256, and LF.  Git status remains separately
    # visible but cannot substitute for content identity.
    encoded = "".join(
        f"{row['path']}\t{row['content_sha256'].lower()}\n" for row in rows
    ).encode("utf-8")
    counts = {
        "total": len(rows),
        "modified": sum(1 for row in rows if row["git_status"] == " M"),
        "untracked": sum(1 for row in rows if row["git_status"] == "??"),
        "staged": sum(
            1
            for row in rows
            if row["git_status"][0] not in {" ", "?"}
        ),
    }
    return {
        "head": ownership._git_head(source),
        "paths": rows,
        "status_sha256": _sha256(encoded),
        "status_counts": counts,
        "runtime_source_fingerprint": runtime.source_tree_fingerprint(source),
    }


def _secret_hygiene(source_worktree: Path) -> dict[str, Any]:
    source = ownership.repository_root(source_worktree)
    ownership._status_entries.cache_clear()
    # The shared scanner normally unions a repository-wide default allowlist.
    # Recovery must not inherit that implicit policy: only this exact
    # path/rule/fingerprint registry may excuse preserved W5 fixtures.
    with _SECRET_SCAN_LOCK:
        defaults = ownership.DEFAULT_SECRET_ALLOWLIST
        ownership.DEFAULT_SECRET_ALLOWLIST = ()
        try:
            raw = ownership.scan_secrets(
                source, scope="changed", _repository_root_resolved=True
            )
        finally:
            ownership.DEFAULT_SECRET_ALLOWLIST = defaults
    raw_findings = tuple(raw.get("findings", ()))
    allowed = {
        (path, rule, fingerprint)
        for path, rule, fingerprint in W5_FIXTURE_SECRET_ALLOWLIST
    }
    allowlisted = tuple(
        item
        for item in raw_findings
        if (item.get("path"), item.get("rule"), item.get("fingerprint")) in allowed
    )
    remaining = tuple(item for item in raw_findings if item not in allowlisted)
    return {
        "status": "passed" if not remaining else "failed",
        "raw_finding_count": len(raw_findings),
        "allowlisted_fixture_finding_count": len(allowlisted),
        "unexpected_finding_count": len(remaining),
        "raw_findings": list(raw_findings),
        "allowlisted_findings": list(allowlisted),
        "unexpected_findings": list(remaining),
        "allowlist": [
            {"path": path, "rule": rule, "fingerprint": fingerprint}
            for path, rule, fingerprint in W5_FIXTURE_SECRET_ALLOWLIST
        ],
        "default_allowlist_merged": False,
        "redaction": "path_rule_fingerprint_only",
    }


def _memoized_live_verifier(timeout_seconds: float):
    raw = projection.bounded_live_provenance(timeout_seconds)
    cache: dict[tuple[str, str], Mapping[str, Any]] = {}

    def verify(
        root: Path, receipt: Mapping[str, Any], receipt_path: Path | None = None
    ) -> Mapping[str, Any]:
        key = (
            str(receipt_path.resolve()) if receipt_path is not None else "inline",
            _sha256(
                json.dumps(
                    receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ),
        )
        if key not in cache:
            cache[key] = raw(root, receipt, receipt_path)
        return cache[key]

    return verify, cache


def _read_receipts(paths: Iterable[Path]) -> tuple[tuple[Path, Mapping[str, Any]], ...]:
    values: list[tuple[Path, Mapping[str, Any]]] = []
    for path in paths:
        resolved = path.resolve()
        try:
            value = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecoveryEvidenceError(f"cannot read receipt: {resolved.name}: {exc}") from exc
        if not isinstance(value, Mapping):
            raise RecoveryEvidenceError(f"receipt must be a mapping: {resolved.name}")
        values.append((resolved, value))
    return tuple(values)


def _receipt_change_ids(receipt: Mapping[str, Any]) -> tuple[str, ...]:
    contracts = receipt.get("contracts")
    found = (
        [str(item.get("change_id") or "").strip() for item in contracts if isinstance(item, Mapping)]
        if isinstance(contracts, list)
        else []
    )
    if receipt.get("change_id"):
        found.append(str(receipt["change_id"]).strip())
    return tuple(value for value in dict.fromkeys(found) if value)


def _resolve_named_receipts(
    root: Path,
    receipts: Iterable[tuple[Path, Mapping[str, Any]]],
    required_change_ids: Iterable[str],
    verifier: Any,
) -> dict[str, dict[str, Any]]:
    """Resolve only explicitly named receipt files, never ambient cache entries."""

    required = set(required_change_ids)
    resolved: dict[str, dict[str, Any]] = {}
    for path, receipt in receipts:
        for change_id in _receipt_change_ids(receipt):
            if change_id not in required or change_id in resolved:
                continue
            result = projection.verify_delivery_receipt(
                root,
                receipt,
                change_id,
                receipt_path=path,
                provenance_verifier=verifier,
            )
            if result.get("valid") is True:
                resolved[change_id] = result
    return resolved


def _source_ownership_projection(
    root: Path,
    source_worktree: Path,
    delivered: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Project only the preserved source paths through verified owners.

    The generic inventory intentionally scans every dirty sibling. Recovery
    handoff instead needs a bounded source proof, so it uses the same active
    scope and attested-retirement primitives without silently importing
    additional local receipt caches or unrelated dirty paths.
    """

    source = ownership.repository_root(source_worktree)
    retirements = ownership.trusted_retirements(root, delivered)
    scopes = ownership.active_contract_scopes(
        root, delivered_ids=delivered, retirements=retirements
    )
    rows = []
    for path, _status in ownership._status_entries(source):
        owners = ownership.owners_for_path(path, scopes)
        rows.append(
            {
                "path": path,
                "scope_owners": list(owners),
                "expected_owner": W5_CHANGE_ID,
            }
        )
    # A unique owner is insufficient: a historical or unrelated contract must
    # not silently become authority for a preserved W5 product path.  Only the
    # explicit W5 contract may own non-residual source paths.
    residuals = [
        row for row in rows if row["scope_owners"] != [W5_CHANGE_ID]
    ]
    return {
        "retired_source_change_ids": sorted(
            str(item.get("source_change_id") or "") for item in retirements
        ),
        "source_paths": rows,
        "source_residuals": residuals,
    }


def _source_runtime_lease_audit(root: Path, source_worktree: Path) -> dict[str, Any]:
    """Validate the entire allocation store before proving source leases are zero.

    The source worktree is only allowed to recover when the global lease store is
    internally trustworthy.  In particular, this deliberately does *not* select
    source-worktree rows before validation: a malformed or orphan row elsewhere
    makes the shared runtime evidence untrustworthy as well.
    """

    state_path = runtime.default_state_dir(root) / "allocations.json"
    expected = runtime.worktree_id(source_worktree)
    if not state_path.is_file():
        return {"status": "missing", "active_count": None, "records": []}
    try:
        state = runtime._read_state(state_path)
    except Exception as exc:  # allocation state is external evidence, fail closed
        return {"status": "error", "active_count": None, "records": [], "reason": type(exc).__name__}
    if not isinstance(state, Mapping):
        return {"status": "invalid", "active_count": None, "records": [], "validation_errors": ["state_not_mapping"]}
    leases = state.get("leases")
    allocations = state.get("allocations")
    if not isinstance(leases, list) or not isinstance(allocations, list):
        return {"status": "invalid", "active_count": None, "records": [], "validation_errors": ["state_collections_invalid"]}

    lease_text_fields = (
        "lease_id", "repository_id", "worktree_id", "change_id", "owner",
        "mode", "risk_level", "created_at", "expires_at", "state",
    )
    allocation_text_fields = (
        "allocation_id", "lease_id", "repository_id", "worktree_id",
        "change_id", "owner", "runtime_id", "compose_project", "database",
        "database_schema", "redis_namespace", "risk_level", "build_sha",
        "source_fingerprint", "created_at", "expires_at", "state",
    )
    valid_states = {"active", "stale", "released"}
    valid_modes = {"read", "write"}
    valid_risks = {"R0", "R1", "R2", "R3"}
    validation_errors: set[str] = set()

    def nonempty_text(item: Mapping[str, Any], field: str, prefix: str) -> bool:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            validation_errors.add(f"{prefix}_{field}_missing")
            return False
        return True

    def valid_timestamp(item: Mapping[str, Any], field: str, prefix: str) -> bool:
        if not nonempty_text(item, field, prefix):
            return False
        try:
            runtime.parse_time(str(item[field]))
        except Exception:
            validation_errors.add(f"{prefix}_{field}_invalid")
            return False
        return True

    def validate_lease(item: Any) -> bool:
        if not isinstance(item, Mapping):
            validation_errors.add("lease_not_mapping")
            return False
        valid = all(nonempty_text(item, field, "lease") for field in lease_text_fields)
        valid = valid_timestamp(item, "created_at", "lease") and valid
        valid = valid_timestamp(item, "expires_at", "lease") and valid
        path_globs = item.get("path_globs")
        if not isinstance(path_globs, list) or not path_globs or any(not isinstance(value, str) or not value for value in path_globs):
            validation_errors.add("lease_path_globs_invalid")
            valid = False
        if item.get("mode") not in valid_modes:
            validation_errors.add("lease_mode_invalid")
            valid = False
        if item.get("risk_level") not in valid_risks:
            validation_errors.add("lease_risk_level_invalid")
            valid = False
        if item.get("state") not in valid_states:
            validation_errors.add("lease_state_invalid")
            valid = False
        if type(item.get("revision")) is not int:
            validation_errors.add("lease_revision_invalid")
            valid = False
        return valid

    def validate_allocation(item: Any) -> bool:
        if not isinstance(item, Mapping):
            validation_errors.add("allocation_not_mapping")
            return False
        valid = all(nonempty_text(item, field, "allocation") for field in allocation_text_fields)
        valid = valid_timestamp(item, "created_at", "allocation") and valid
        valid = valid_timestamp(item, "expires_at", "allocation") and valid
        ports = item.get("ports")
        if not isinstance(ports, Mapping) or any(
            not isinstance(name, str) or not name or type(port) is not int or not 1 <= port <= 65535
            for name, port in ports.items()
        ):
            validation_errors.add("allocation_ports_invalid")
            valid = False
        volumes = item.get("volumes")
        if not isinstance(volumes, list) or any(not isinstance(value, str) or not value for value in volumes):
            validation_errors.add("allocation_volumes_invalid")
            valid = False
        for field in ("canonical", "cron_owner", "approval_worker_owner"):
            if type(item.get(field)) is not bool:
                validation_errors.add(f"allocation_{field}_invalid")
                valid = False
        if item.get("risk_level") not in valid_risks:
            validation_errors.add("allocation_risk_level_invalid")
            valid = False
        if item.get("state") not in valid_states:
            validation_errors.add("allocation_state_invalid")
            valid = False
        if type(item.get("revision")) is not int:
            validation_errors.add("allocation_revision_invalid")
            valid = False
        return valid

    for lease in leases:
        validate_lease(lease)
    for allocation in allocations:
        validate_allocation(allocation)

    valid_leases = [item for item in leases if isinstance(item, Mapping)]
    valid_allocations = [item for item in allocations if isinstance(item, Mapping)]
    lease_ids = [item.get("lease_id") for item in valid_leases if isinstance(item.get("lease_id"), str) and item.get("lease_id")]
    allocation_ids = [item.get("allocation_id") for item in valid_allocations if isinstance(item.get("allocation_id"), str) and item.get("allocation_id")]
    allocation_lease_ids = [item.get("lease_id") for item in valid_allocations if isinstance(item.get("lease_id"), str) and item.get("lease_id")]
    if len(lease_ids) != len(set(lease_ids)):
        validation_errors.add("duplicate_lease_id")
    if len(allocation_ids) != len(set(allocation_ids)):
        validation_errors.add("duplicate_allocation_id")
    if len(allocation_lease_ids) != len(set(allocation_lease_ids)):
        validation_errors.add("duplicate_allocation_lease_id")

    lease_by_id = {str(item.get("lease_id")): item for item in valid_leases if isinstance(item.get("lease_id"), str) and item.get("lease_id")}
    allocation_by_lease = {
        str(item.get("lease_id")): item
        for item in valid_allocations
        if isinstance(item.get("lease_id"), str) and item.get("lease_id")
    }
    linkage_fields = ("repository_id", "worktree_id", "change_id", "owner")
    now = datetime.now(timezone.utc)

    def effective_state(item: Mapping[str, Any], prefix: str) -> str:
        """Derive a fail-closed effective state from the record's own expiry."""

        state_value = item.get("state")
        try:
            expires_at = runtime.parse_time(str(item.get("expires_at")))
        except Exception:
            validation_errors.add(f"{prefix}_effective_state_invalid")
            return "invalid"
        if state_value == "stale" and expires_at > now:
            validation_errors.add(f"{prefix}_stale_before_expiry")
            return "invalid"
        if state_value == "active" and expires_at <= now:
            return "stale"
        return str(state_value)

    for allocation in valid_allocations:
        lease_id = allocation.get("lease_id")
        linked = lease_by_id.get(str(lease_id)) if isinstance(lease_id, str) and lease_id else None
        if linked is None:
            validation_errors.add("orphan_active_allocation" if allocation.get("state") == "active" else "orphan_allocation")
            continue
        if any(allocation.get(field) != linked.get(field) for field in linkage_fields):
            validation_errors.add("allocation_lease_ownership_mismatch")
        lease_effective = effective_state(linked, "lease")
        allocation_effective = effective_state(allocation, "allocation")
        if linked.get("state") != allocation.get("state"):
            validation_errors.add("lease_allocation_state_mismatch")
        if lease_effective != allocation_effective:
            validation_errors.add("lease_allocation_effective_state_mismatch")
        try:
            if runtime.parse_time(str(linked.get("expires_at"))) != runtime.parse_time(str(allocation.get("expires_at"))):
                validation_errors.add("lease_allocation_expiry_mismatch")
        except Exception:
            validation_errors.add("lease_allocation_expiry_invalid")
    for lease in valid_leases:
        allocation = allocation_by_lease.get(str(lease.get("lease_id")))
        if allocation is None:
            validation_errors.add("orphan_lease")
            if lease.get("state") == "active":
                validation_errors.add("active_lease_without_allocation")

    records: list[dict[str, Any]] = []
    active_count = 0
    for lease in valid_leases:
        if lease.get("worktree_id") != expected:
            continue
        lease_id = str(lease.get("lease_id") or "")
        allocation = allocation_by_lease.get(lease_id)
        effective = effective_state(lease, "lease")
        if not lease_id or allocation is None or allocation.get("worktree_id") != expected:
            effective = "invalid"
        if effective == "active":
            active_count += 1
        records.append({"lease_id": lease_id, "effective_state": effective})
    return {
        "status": "invalid" if validation_errors else "passed",
        "active_count": None if validation_errors else active_count,
        "records": records,
        "state_path": str(state_path),
        "schema_validated_every_record": not validation_errors,
        "global_lease_count": len(leases),
        "global_allocation_count": len(allocations),
        "validation_errors": sorted(validation_errors),
    }


def _is_reparse_point(path: Path) -> bool:
    """Return whether an existing path is a Windows reparse point or symlink."""

    try:
        stat_result = os.lstat(path)
    except OSError:
        return False
    file_attributes = getattr(stat_result, "st_file_attributes", 0)
    return path.is_symlink() or bool(file_attributes & 0x0400)  # FILE_ATTRIBUTE_REPARSE_POINT


def _manifest_directory(root: Path, requested: Path | None = None) -> Path:
    common = runtime.git_common_dir(root)
    if _is_reparse_point(common):
        raise RecoveryEvidenceError("recovery manifest output may not traverse a reparse point")
    try:
        common_actual = common.resolve(strict=True)
    except OSError as exc:
        raise RecoveryEvidenceError("git common-dir is unavailable") from exc
    runtime_dir = common / "omni-runtime"
    expected = runtime_dir / "w5-recovery-evidence"
    if requested is not None and requested.resolve(strict=False) != expected.resolve(strict=False):
        raise RecoveryEvidenceError("recovery manifest output must be the dedicated git common-dir directory")

    def assert_canonical_layer(path: Path, relative: Path) -> None:
        if path.exists() and _is_reparse_point(path):
            raise RecoveryEvidenceError("recovery manifest output may not traverse a reparse point")
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(common_actual)
        except ValueError as exc:
            raise RecoveryEvidenceError("recovery manifest output escaped the git common-dir") from exc
        if resolved != common_actual / relative:
            raise RecoveryEvidenceError("recovery manifest output escaped the git common-dir")

    assert_canonical_layer(common, Path("."))
    assert_canonical_layer(runtime_dir, Path("omni-runtime"))
    assert_canonical_layer(expected, Path("omni-runtime") / "w5-recovery-evidence")
    expected.mkdir(parents=True, exist_ok=True)
    assert_canonical_layer(runtime_dir, Path("omni-runtime"))
    assert_canonical_layer(expected, Path("omni-runtime") / "w5-recovery-evidence")
    return expected


def _append_manifest(directory: Path, payload: Mapping[str, Any]) -> tuple[Path, str]:
    run_id = str(payload["run_id"])
    target = directory / f"{run_id}.json"
    if target.exists() or target.is_symlink():
        raise RecoveryEvidenceError("recovery manifest run UUID already exists")
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with target.open("xb") as handle:
        handle.write(encoded)
    return target, _sha256(encoded)


def build_recovery_evidence(
    root: Path,
    source_worktree: Path,
    *,
    receipt_paths: Iterable[Path],
    expected_status_sha256: str,
    expected_runtime_source_fingerprint: str,
    output_dir: Path | None = None,
    live_timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Build evidence, persisting it only after every guard passes.

    No caller can provide delivered IDs.  Only the same memoized live verifier
    used by both delivery resolution and ownership inventory may establish
    delivery or supersession facts.
    """

    root = ownership.repository_root(root)
    source = ownership.repository_root(source_worktree)
    required = AUTHORITATIVE_W5_HISTORICAL_DELIVERY_IDS
    if not expected_status_sha256 or not expected_runtime_source_fingerprint:
        raise RecoveryEvidenceError("expected status and runtime fingerprints are required")

    snapshot = _status_snapshot(source)
    hygiene = _secret_hygiene(source)
    receipts = _read_receipts(receipt_paths)
    verifier, verifier_cache = _memoized_live_verifier(live_timeout_seconds)
    resolved = _resolve_named_receipts(
        root, receipts, required, verifier
    )
    ownership_projection = _source_ownership_projection(root, source, resolved)
    residuals = tuple(ownership_projection["source_residuals"])
    second_snapshot = _status_snapshot(source)
    actual_residual_paths = tuple(sorted(item["path"] for item in residuals))
    expected_residuals = tuple(sorted(ALLOWED_W5_RECOVERY_RESIDUAL_PATHS))
    missing_receipts = tuple(sorted(set(required) - set(resolved)))
    retired_sources = set(ownership_projection["retired_source_change_ids"])
    source_lease_audit = _source_runtime_lease_audit(root, source)
    failures: list[str] = []
    if snapshot["status_sha256"] != expected_status_sha256:
        failures.append("status_fingerprint_mismatch")
    if snapshot["runtime_source_fingerprint"] != expected_runtime_source_fingerprint:
        failures.append("runtime_source_fingerprint_mismatch")
    if missing_receipts:
        failures.append("required_receipt_not_verified")
    if hygiene["unexpected_finding_count"]:
        failures.append("unexpected_secret_finding")
    if actual_residual_paths != expected_residuals:
        failures.append("source_residual_paths_mismatch")
    if "2026-08-01-system-convergence-s8-s10" not in retired_sources:
        failures.append("s8_s10_supersession_not_verified")
    if source_lease_audit.get("status") != "passed":
        failures.append("source_runtime_lease_unknown_or_invalid")
    elif source_lease_audit.get("active_count") != 0:
        failures.append("source_runtime_lease_still_active")
    if second_snapshot != snapshot:
        failures.append("source_sample_drift")

    run_id = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": "omni_w5_recovery_evidence",
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": snapshot,
        "second_source_sample": second_snapshot,
        "expected": {
            "status_sha256": expected_status_sha256,
            "runtime_source_fingerprint": expected_runtime_source_fingerprint,
            "residual_paths": list(expected_residuals),
        },
        "secret_hygiene": hygiene,
        "delivery": {
            "required_change_ids": list(required),
            "resolved_change_ids": sorted(resolved),
            "missing_change_ids": list(missing_receipts),
            "live_verifier_cache_entries": len(verifier_cache),
        },
        "ownership": {
            "retired_source_change_ids": sorted(retired_sources),
            "source_residuals": list(residuals),
            "source_runtime_lease_audit": source_lease_audit,
        },
        "policy": {
            "source_mutated": False,
            "runtime_or_lease_mutated": False,
            "delivered_ids_injected": False,
            "manifest_contains_source_content": False,
            "provenance_verifier": "one_memoized_bounded_live_instance",
        },
        "status": "recovery_ready" if not failures else "blocked",
        "failures": failures,
    }
    # A stable source anchor is recoverable evidence even when a separate
    # receipt or ownership gate blocks handoff. Never persist after drift:
    # that would make distinct source states look identical.
    if "source_sample_drift" in failures:
        return payload
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["record_sha256"] = _sha256(canonical)
    destination = _manifest_directory(root, output_dir)
    target, manifest_sha256 = _append_manifest(destination, payload)
    payload["manifest"] = {
        "path": str(target),
        "sha256": manifest_sha256,
    }
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source-worktree", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, action="append", required=True)
    parser.add_argument("--expected-status-sha256", required=True)
    parser.add_argument("--expected-runtime-source-fingerprint", required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--live-timeout-seconds", type=float, default=30.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = build_recovery_evidence(
            args.root,
            args.source_worktree,
            receipt_paths=args.receipt,
            expected_status_sha256=args.expected_status_sha256,
            expected_runtime_source_fingerprint=args.expected_runtime_source_fingerprint,
            output_dir=args.output_dir,
            live_timeout_seconds=args.live_timeout_seconds,
        )
    except (RecoveryEvidenceError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "failures": [str(exc)]}, ensure_ascii=False))
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if payload["status"] == "recovery_ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
