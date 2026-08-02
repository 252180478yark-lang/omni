#!/usr/bin/env python3
"""Deterministic acceptance checks for the unified-workbench W0 gate.

The checker is intentionally read-only.  It verifies the immutable Git
baseline, every reserved W1 path fingerprint, the preserved primary-worktree
sidebar edit, trusted live CI delivery receipts, target-scoped contract
ownership, supersession records, and active runtime leases.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence

import yaml


CHANGE_ID = "2026-08-02-omni-unified-ai-workbench-w0"
CONTRACT_REL = Path("docs/dev-changes") / CHANGE_ID
MANIFEST_REL = CONTRACT_REL / "path-ownership-fingerprint.yaml"
FIXED_W0_PATHS = {
    (CONTRACT_REL / name).as_posix()
    for name in (
        "completion.yaml",
        "impact.yaml",
        "parallel-development-order.md",
        "path-ownership-fingerprint.yaml",
        "verify_w0.py",
    )
}
FIXED_W1_PATHS = {
    "frontend/src/app/globals.css",
    "frontend/src/app/layout.tsx",
    "frontend/src/app/page.tsx",
    "frontend/src/components/app-shell.tsx",
    "frontend/src/components/app-sidebar.tsx",
    "frontend/src/components/beginner-guide.tsx",
    "frontend/src/generated/feature-registry.v1.json",
    "frontend/src/lib/feature-registry.ts",
}
FEATURE_ROOT = "services/knowledge-engine/config/features"
PROVENANCE_ATTEMPT_TIMEOUT_SECONDS = 30
MAX_PROVENANCE_ATTEMPTS = 2
RETRIABLE_PROVENANCE_REASONS = {
    "github_run_unverifiable",
    "live_provenance_total_deadline_exhausted",
    "signed_artifact_content_unverifiable",
}
TRUSTED_COLLECTOR_PATHS = {
    "workspace_ownership": "scripts/workspace_ownership.py",
    "delivery_verifier": "scripts/generate_implementation_status.py",
    "contract_validator": ".agents/skills/omni-feature-development/scripts/dev_contract.py",
}


class W0GateError(RuntimeError):
    """A W0 acceptance invariant is not satisfied."""


def run(
    command: Sequence[str],
    *,
    cwd: Path,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=text,
        encoding="utf-8" if text else None,
        errors="replace" if text else None,
        check=False,
    )
    if check and result.returncode != 0:
        stdout = result.stdout.strip() if text else ""
        stderr = result.stderr.strip() if text else ""
        detail = stderr or stdout or f"exit {result.returncode}"
        raise W0GateError(f"command failed: {' '.join(command)}: {detail}")
    return result


def git(root: Path, *args: str, check: bool = True) -> str:
    return run(("git", *args), cwd=root, check=check).stdout.rstrip()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_git_diff(root: Path, path: str) -> str:
    result = subprocess.run(
        ["git", "diff", "--binary", "--", path],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise W0GateError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def repository_root() -> Path:
    result = run(("git", "rev-parse", "--show-toplevel"), cwd=Path.cwd())
    return Path(result.stdout.strip()).resolve()


def read_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_REL
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise W0GateError(f"cannot read manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise W0GateError("manifest root must be a mapping")
    if value.get("change_id") != CHANGE_ID:
        raise W0GateError("manifest change_id mismatch")
    return value


def status_paths(root: Path) -> set[str]:
    raw = git(root, "status", "--porcelain=v1", "--untracked-files=all", "-z")
    paths: set[str] = set()
    for item in raw.split("\0"):
        if not item:
            continue
        if len(item) < 4:
            raise W0GateError(f"unexpected porcelain status entry: {item!r}")
        paths.add(item[3:].replace("\\", "/"))
    return paths


def resolve_git_dir(root: Path) -> Path:
    value = Path(git(root, "rev-parse", "--git-common-dir"))
    return value.resolve() if value.is_absolute() else (root / value).resolve()


def verify_collector_fingerprints(
    root: Path,
    manifest: Mapping[str, Any],
    baseline_ref: str,
) -> dict[str, dict[str, str]]:
    records = manifest.get("collector") or {}
    if not isinstance(records, Mapping) or set(records) != set(TRUSTED_COLLECTOR_PATHS):
        raise W0GateError("collector authority set drift")
    verified: dict[str, dict[str, str]] = {}
    for collector_id, expected_path in TRUSTED_COLLECTOR_PATHS.items():
        record = records.get(collector_id) or {}
        if not isinstance(record, Mapping) or record.get("path") != expected_path:
            raise W0GateError(f"collector path drift: {collector_id}")
        observed_blob = git(root, "rev-parse", f"{baseline_ref}:{expected_path}")
        observed_sha = sha256_file(root / expected_path)
        if observed_blob != str(record.get("git_blob") or ""):
            raise W0GateError(f"collector Git blob drift: {collector_id}")
        if observed_sha != str(record.get("sha256") or ""):
            raise W0GateError(f"collector SHA-256 drift: {collector_id}")
        verified[collector_id] = {
            "path": expected_path,
            "git_blob": observed_blob,
            "sha256": observed_sha,
        }
    return verified


def verify_baseline(root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    baseline = manifest.get("baseline") or {}
    expected = str(baseline.get("head") or "")
    observed = {
        "branch": git(root, "branch", "--show-current"),
        "head": git(root, "rev-parse", "HEAD"),
        "origin_main": git(root, "rev-parse", "origin/main"),
        "merge_base": git(root, "merge-base", "HEAD", "origin/main"),
    }
    for key in ("branch", "origin_main", "merge_base"):
        if observed[key] != str(baseline.get(key) or ""):
            raise W0GateError(
                f"baseline {key} drift: expected {baseline.get(key)!r}, observed {observed[key]!r}"
            )
    if not expected or len(expected) != 40:
        raise W0GateError("baseline head must be a full commit SHA")
    collectors = verify_collector_fingerprints(root, manifest, expected)
    if run(("git", "merge-base", "--is-ancestor", expected, "origin/main"), cwd=root, check=False).returncode:
        raise W0GateError("frozen baseline is not reachable from origin/main")
    if run(("git", "merge-base", "--is-ancestor", expected, "HEAD"), cwd=root, check=False).returncode:
        raise W0GateError("W0 candidate is not descended from the frozen baseline")

    manifest_allowed = {str(path) for path in manifest.get("w0_allowed_paths") or []}
    if manifest_allowed != FIXED_W0_PATHS:
        raise W0GateError(
            "manifest W0 path authority drift: "
            f"expected={sorted(FIXED_W0_PATHS)}, observed={sorted(manifest_allowed)}"
        )
    allowed = FIXED_W0_PATHS
    worktree_changed = status_paths(root)
    committed_changed = {
        path.replace("\\", "/")
        for path in git(root, "diff", "--name-only", f"{expected}..HEAD").splitlines()
        if path
    }
    history_changed: set[str] = set()
    for revision in git(root, "rev-list", "--parents", f"{expected}..HEAD").splitlines():
        parts = revision.split()
        if len(parts) != 2:
            raise W0GateError(f"W0 candidate history must be linear: {revision}")
        commit = parts[0]
        history_changed.update(
            path.replace("\\", "/")
            for path in git(
                root,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-m",
                "-z",
                commit,
            ).split("\0")
            if path
        )
    historical_unexpected = sorted(path for path in history_changed if path not in allowed)
    if historical_unexpected:
        raise W0GateError(
            f"W0 candidate history has out-of-scope paths: {historical_unexpected}"
        )
    changed = worktree_changed | committed_changed
    missing = sorted(path for path in allowed if path not in changed)
    unexpected = sorted(path for path in changed if path not in allowed)
    if missing or unexpected:
        raise W0GateError(
            f"W0 candidate path set mismatch: missing={missing}, unexpected={unexpected}"
        )
    if git(root, "diff", "--name-only", "--", ".", f":(exclude){CONTRACT_REL.as_posix()}/**"):
        raise W0GateError("tracked product-tree diff is not empty")
    if git(root, "diff", "--cached", "--name-only", "--", ".", f":(exclude){CONTRACT_REL.as_posix()}/**"):
        raise W0GateError("staged product-tree diff is not empty")
    return {
        **observed,
        "baseline": expected,
        "collectors": collectors,
        "committed_changed_paths": sorted(committed_changed),
        "history_changed_paths": sorted(history_changed),
        "worktree_changed_paths": sorted(worktree_changed),
        "changed_paths": sorted(changed),
    }


def verify_fingerprints(root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    baseline = manifest.get("baseline") or {}
    baseline_ref = str(baseline.get("head") or "")
    if not baseline_ref or len(baseline_ref) != 40:
        raise W0GateError("baseline head must be a full commit SHA")
    completion_path = root / CONTRACT_REL / "completion.yaml"
    try:
        completion = yaml.safe_load(completion_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise W0GateError(f"cannot read completion snapshot: {exc}") from exc
    if not isinstance(completion, Mapping):
        raise W0GateError("completion root must be a mapping")
    manifest_snapshot = f"sha256:{sha256_file(root / MANIFEST_REL)}"
    recorded_snapshot = str(
        ((completion.get("graph_diff") or {}).get("snapshot_after") or "")
    )
    if recorded_snapshot != manifest_snapshot:
        raise W0GateError(
            "manifest snapshot drift: "
            f"expected {manifest_snapshot!r}, recorded {recorded_snapshot!r}"
        )
    target_items = manifest.get("target_paths") or []
    if not isinstance(target_items, list) or not target_items:
        raise W0GateError("target_paths must be a non-empty list")
    target_by_path = {str(item.get("path")): item for item in target_items if isinstance(item, Mapping)}
    feature_paths = set(
        git(root, "ls-tree", "-r", "--name-only", baseline_ref, FEATURE_ROOT).splitlines()
    )
    expected_paths = FIXED_W1_PATHS | feature_paths
    if set(target_by_path) != expected_paths:
        missing = sorted(expected_paths - set(target_by_path))
        extra = sorted(set(target_by_path) - expected_paths)
        raise W0GateError(f"target path inventory drift: missing={missing}, extra={extra}")

    for path in sorted(expected_paths):
        item = target_by_path[path]
        observed_blob = git(root, "rev-parse", f"{baseline_ref}:{path}")
        if observed_blob != str(item.get("git_blob") or ""):
            raise W0GateError(f"Git blob drift: {path}")
        observed_sha = sha256_file(root / path)
        if observed_sha != str(item.get("sha256") or ""):
            raise W0GateError(f"SHA-256 drift: {path}")
        baseline_entry = git(root, "ls-tree", baseline_ref, "--", path)
        candidate_entry = git(root, "ls-tree", "HEAD", "--", path)
        if not baseline_entry or candidate_entry != baseline_entry:
            raise W0GateError(f"candidate tree entry drift: {path}")
        if git(root, "status", "--short", "--", path):
            raise W0GateError(f"reserved product path is dirty in W0 worktree: {path}")

    feature_tree = manifest.get("feature_tree") or {}
    observed_tree = git(root, "rev-parse", f"{baseline_ref}:{FEATURE_ROOT}")
    if observed_tree != str(feature_tree.get("git_tree") or ""):
        raise W0GateError("Feature Registry source tree fingerprint drift")
    if git(root, "rev-parse", f"HEAD:{FEATURE_ROOT}") != observed_tree:
        raise W0GateError("candidate Feature Registry source tree drift")

    ownership = load_module("w0_ownership_fingerprint", root / "scripts/workspace_ownership.py")
    primary = ownership.primary_worktree(root)
    dirty = manifest.get("primary_dirty_evidence") or {}
    path = str(dirty.get("path") or "")
    observed_dirty = {
        "status": git(primary, "status", "--short", "--", path),
        "head_blob": git(primary, "rev-parse", f"HEAD:{path}"),
        "index_blob": git(primary, "rev-parse", f":{path}"),
        "worktree_blob": git(primary, "hash-object", path),
        "worktree_sha256": sha256_file(primary / path),
        "scoped_diff_sha256": sha256_git_diff(primary, path),
    }
    for key, value in observed_dirty.items():
        if value != str(dirty.get(key) or ""):
            raise W0GateError(
                f"primary dirty evidence drift for {key}: expected {dirty.get(key)!r}, observed {value!r}"
            )
    return {
        "target_path_count": len(expected_paths),
        "feature_tree": observed_tree,
        "manifest_snapshot": manifest_snapshot,
        "primary_dirty": observed_dirty,
    }


def verify_delivery_with_retry(
    status: ModuleType,
    root: Path,
    receipt: Mapping[str, Any],
    change_id: str,
    receipt_path: Path,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for attempt in range(1, MAX_PROVENANCE_ATTEMPTS + 1):
        result = status.verify_delivery_receipt(
            root,
            receipt,
            change_id,
            receipt_path=receipt_path,
            provenance_verifier=status.bounded_live_provenance(
                PROVENANCE_ATTEMPT_TIMEOUT_SECONDS
            ),
        )
        if result.get("valid") is True:
            return result
        reasons = {str(reason) for reason in result.get("reasons") or []}
        if not reasons or not reasons.issubset(RETRIABLE_PROVENANCE_REASONS):
            return result
    return result


def read_live_artifact_metadata(
    root: Path,
    repository: str,
    artifact_id: str,
) -> dict[str, Any]:
    if not artifact_id.isdigit():
        raise W0GateError(f"delivery artifact id is invalid: {artifact_id!r}")
    detail = ""
    for _attempt in range(MAX_PROVENANCE_ATTEMPTS):
        try:
            result = subprocess.run(
                (
                    "gh",
                    "api",
                    f"repos/{repository}/actions/artifacts/{artifact_id}",
                ),
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            detail = str(exc)
            continue
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            continue
        try:
            metadata = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            detail = str(exc)
            continue
        if isinstance(metadata, dict):
            return metadata
        detail = "artifact metadata root is not a mapping"
    raise W0GateError(f"delivery artifact metadata unavailable: {artifact_id}: {detail}")


def verify_receipts(
    root: Path,
    manifest: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    status = load_module("w0_delivery_status", root / "scripts/generate_implementation_status.py")
    records = manifest.get("verified_deliveries") or []
    git_dir = resolve_git_dir(root)
    cache_root = (git_dir / "omni-delivery" / "verified-receipts" / "w0").resolve()
    delivered: dict[str, dict[str, Any]] = {}
    actual_paths: dict[str, set[str]] = {}
    seen_artifacts: set[str] = set()
    if not isinstance(records, list) or not records:
        raise W0GateError("verified_deliveries must be a non-empty list")
    for record in records:
        if not isinstance(record, Mapping):
            raise W0GateError("verified_deliveries entries must be mappings")
        change_id = str(record.get("change_id") or "")
        artifact_id = str(record.get("artifact_id") or "")
        if not change_id or change_id in delivered:
            raise W0GateError(f"duplicate or empty delivery change id: {change_id!r}")
        if not artifact_id or artifact_id in seen_artifacts:
            raise W0GateError(f"duplicate or empty delivery artifact id: {artifact_id!r}")
        seen_artifacts.add(artifact_id)
        receipt_path = (git_dir / str(record.get("cache_path") or "")).resolve()
        if receipt_path.parent != cache_root:
            raise W0GateError(f"delivery receipt cache escapes W0 cache root: {change_id}")
        if not receipt_path.is_file():
            raise W0GateError(f"delivery receipt cache missing: {receipt_path}")
        if sha256_file(receipt_path) != str(record.get("raw_sha256") or ""):
            raise W0GateError(f"delivery receipt raw hash drift: {change_id}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        result = verify_delivery_with_retry(
            status,
            root,
            receipt,
            change_id,
            receipt_path,
        )
        if result.get("valid") is not True:
            raise W0GateError(f"delivery receipt invalid for {change_id}: {result.get('reasons')}")
        if result.get("subject_commit") != str(record.get("subject_commit") or ""):
            raise W0GateError(f"delivery subject drift: {change_id}")
        workflow_run_id = str(record.get("workflow_run_id") or "")
        artifact_name = str(record.get("artifact_name") or "")
        repository = str(receipt.get("repository") or "")
        if workflow_run_id != str(receipt.get("workflow_run_id") or ""):
            raise W0GateError(f"delivery workflow run drift: {change_id}")
        if artifact_name != str(receipt.get("attestation_artifact_name") or ""):
            raise W0GateError(f"delivery artifact name drift: {change_id}")
        expected_run_url = f"https://github.com/{repository}/actions/runs/{workflow_run_id}"
        if str(record.get("run_url") or "") != expected_run_url:
            raise W0GateError(f"delivery run URL drift: {change_id}")
        artifact = read_live_artifact_metadata(root, repository, artifact_id)
        if str(artifact.get("id") or "") != artifact_id:
            raise W0GateError(f"live delivery artifact id drift: {change_id}")
        if str(artifact.get("name") or "") != artifact_name:
            raise W0GateError(f"live delivery artifact metadata name drift: {change_id}")
        if str(artifact.get("digest") or "") != str(record.get("artifact_digest") or ""):
            raise W0GateError(f"live delivery artifact digest drift: {change_id}")
        if artifact.get("expired") is True:
            raise W0GateError(f"live delivery artifact expired: {change_id}")
        if str(((artifact.get("workflow_run") or {}).get("id") or "")) != workflow_run_id:
            raise W0GateError(f"live delivery artifact run drift: {change_id}")
        contract = next(
            (
                item
                for item in receipt.get("contracts") or []
                if isinstance(item, Mapping) and item.get("change_id") == change_id
            ),
            None,
        )
        if contract is None:
            raise W0GateError(f"receipt contract missing: {change_id}")
        delivered[change_id] = result
        actual_paths[change_id] = {str(path) for path in contract.get("actual_paths") or []}
    return delivered, actual_paths


def verify_ownership(root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    delivered, delivery_paths = verify_receipts(root, manifest)
    ownership = load_module("w0_ownership_live", root / "scripts/workspace_ownership.py")
    scopes = ownership.active_contract_scopes(root, delivered_ids=delivered)
    leases, _lease_audit = ownership._runtime_lease_inventory(root)

    superseded_by_path: dict[str, set[str]] = {}
    for record in manifest.get("superseded_predecessors") or []:
        change_id = str(record.get("change_id") or "")
        successor = str(record.get("superseded_by_delivery") or "")
        if successor not in delivered:
            raise W0GateError(f"superseding delivery is not verified: {successor}")
        for path in record.get("paths") or []:
            normalized = str(path)
            if normalized not in delivery_paths[successor]:
                raise W0GateError(
                    f"superseding delivery {successor} does not contain {normalized}"
                )
            superseded_by_path.setdefault(normalized, set()).add(change_id)

        candidate = record.get("candidate") or {}
        candidate_path = Path(str(candidate.get("worktree") or ""))
        if not candidate_path.is_dir():
            raise W0GateError(f"superseded candidate worktree missing: {candidate_path}")
        if git(candidate_path, "branch", "--show-current") != str(candidate.get("branch") or ""):
            raise W0GateError(f"superseded candidate branch drift: {change_id}")
        if git(candidate_path, "rev-parse", "HEAD") != str(candidate.get("head") or ""):
            raise W0GateError(f"superseded candidate HEAD drift: {change_id}")
        if git(candidate_path, "status", "--porcelain=v1", "--untracked-files=all"):
            raise W0GateError(f"superseded candidate is dirty: {change_id}")

    target_paths = [str(item.get("path")) for item in manifest.get("target_paths") or []]
    target_results: list[dict[str, Any]] = []
    for path in target_paths:
        owners = set(ownership.owners_for_path(path, scopes))
        allowed = superseded_by_path.get(path, set())
        if owners != allowed:
            raise W0GateError(
                f"target owner drift for {path}: observed={sorted(owners)}, allowed={sorted(allowed)}"
            )
        lease_owners = ownership._lease_owners_for_path(path, leases)
        if lease_owners:
            raise W0GateError(f"target path has an active lease: {path}: {lease_owners}")
        target_results.append(
            {
                "path": path,
                "known_superseded_owners": sorted(owners),
                "lease_owners": [],
            }
        )

    successor = manifest.get("successor") or {}
    if successor.get("status") != "reserved_pending_contract_lock":
        raise W0GateError("successor reservation is not locked")
    if successor.get("owner") != "codex":
        raise W0GateError("unexpected successor owner")
    if successor.get("product_write_authorized") is not False:
        raise W0GateError("W0 must not authorize W1 product writes")

    return {
        "verified_deliveries": sorted(delivered),
        "target_path_count": len(target_results),
        "known_superseded_claim_count": sum(
            len(item["known_superseded_owners"]) for item in target_results
        ),
        "unknown_shared_writer_count": 0,
        "active_target_lease_count": 0,
        "successor": successor.get("change_id"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--section",
        choices=("baseline", "fingerprints", "ownership", "all"),
        default="all",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = repository_root()
        manifest = read_manifest(root)
        if manifest.get("lock_status") != "locked":
            raise W0GateError("manifest lock_status is not locked")
        results: dict[str, Any] = {}
        baseline_result = verify_baseline(root, manifest)
        if args.section in {"baseline", "all"}:
            results["baseline"] = baseline_result
        if args.section in {"fingerprints", "all"}:
            results["fingerprints"] = verify_fingerprints(root, manifest)
        if args.section in {"ownership", "all"}:
            results["ownership"] = verify_ownership(root, manifest)
        print(
            json.dumps(
                {"status": "W0_LOCKED", "section": args.section, "results": results},
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
        )
    except (W0GateError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[w0-verify] ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
