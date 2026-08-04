#!/usr/bin/env python3
"""Read-only ownership inventory for dirty Omni worktrees.

The primary worktree is treated as user-owned evidence: every existing dirty
path is reported as ``preserved_external_user`` and this command never stages,
moves, rewrites or deletes it.  Linked worktree paths are matched against
active impact contracts so concurrent tasks can detect ambiguous ownership.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - surfaced as a deterministic input error
    yaml = None  # type: ignore[assignment]


# DISCOVERED is intentionally excluded: at that point the contract is still
# gathering requirements and has not locked an impact revision.  Path
# ownership begins at IMPACT_LOCKED and remains active until an external
# delivery attestation closes GRAPH_DIFF_READY.
ACTIVE_STATES = {"IMPACT_LOCKED", "IMPLEMENTING", "VERIFYING", "GRAPH_DIFF_READY"}
ACTIVE_STATE_ORDER = {
    "IMPACT_LOCKED": 0,
    "IMPLEMENTING": 1,
    "VERIFYING": 2,
    "GRAPH_DIFF_READY": 3,
}
BLOCKING_OWNERSHIP_COUNT_KEYS = (
    "conflict",
    "unassigned",
    "dirty_scope_conflict",
    "contract_scope_conflict",
    "contract_owner_ambiguity",
    "scope_conflict",
    "lease_conflict",
)
DEFAULT_SECRET_ALLOWLIST = (
    # This fixture exists specifically to prove downstream graph redaction.  It
    # is source text, not a runtime credential, and stays narrowly path+rule scoped.
    "services/knowledge-engine/tests/test_system_graph_redaction.py:*",
)


class OwnershipInputError(ValueError):
    """Repository ownership cannot be determined safely."""


@dataclass(frozen=True)
class DirtyPath:
    path: str
    worktree_id: str
    git_status: str
    ownership: str
    owner_id: str
    disposition: str
    evidence: str
    hygiene_class: str = "retained_source"
    recovery_action: str = "none"
    scope_owners: tuple[str, ...] = ()
    scope_conflict: bool = False
    lease_owners: tuple[str, ...] = ()
    lease_conflict: bool = False


@dataclass(frozen=True)
class ContractScope:
    change_id: str
    state: str
    patterns: tuple[str, ...]
    source_worktrees: tuple[str, ...] = ()


def _run(command: Sequence[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OwnershipInputError(f"cannot run {' '.join(command)}: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OwnershipInputError(f"command failed ({result.returncode}): {' '.join(command)}: {detail}")
    return result


def repository_root(candidate: Path | None = None) -> Path:
    start = (candidate or Path.cwd()).resolve()
    result = _run(("git", "rev-parse", "--show-toplevel"), cwd=start)
    return Path(result.stdout.strip()).resolve()


def git_common_dir(root: Path) -> Path:
    result = _run(("git", "rev-parse", "--git-common-dir"), cwd=root)
    value = Path(result.stdout.strip())
    return (root / value).resolve() if not value.is_absolute() else value.resolve()


def primary_worktree(root: Path) -> Path:
    common = git_common_dir(root)
    if common.name.casefold() == ".git" and common.parent.is_dir():
        return common.parent.resolve()
    result = _run(("git", "worktree", "list", "--porcelain"), cwd=root)
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            return Path(line.removeprefix("worktree ")).resolve()
    raise OwnershipInputError("git worktree list returned no primary worktree")


def worktree_id(path: Path, *, primary: Path) -> str:
    if path.resolve() == primary.resolve():
        return "primary"
    digest = hashlib.sha256(str(path.resolve()).casefold().encode("utf-8")).hexdigest()[:12]
    return f"linked-{digest}"


def all_worktrees(root: Path) -> tuple[Path, ...]:
    result = _run(("git", "worktree", "list", "--porcelain"), cwd=root)
    values = [
        Path(line.removeprefix("worktree ")).resolve()
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    ]
    return tuple(path for path in values if path.is_dir())


@lru_cache(maxsize=1)
def _development_policy() -> ModuleType:
    path = Path(__file__).resolve().with_name("development_policy.py")
    spec = importlib.util.spec_from_file_location("omni_development_policy_ownership", path)
    if spec is None or spec.loader is None:
        raise OwnershipInputError(f"cannot load development policy: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def normalize_path(value: str) -> str:
    try:
        return str(_development_policy().normalize_path(value))
    except ValueError as exc:
        raise OwnershipInputError(str(exc)) from exc


def _glob_regex(pattern: str) -> re.Pattern[str]:
    pattern = normalize_path(pattern)
    pieces: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    pieces.append("(?:.*/)?")
                    index += 1
                else:
                    pieces.append(".*")
                continue
            pieces.append("[^/]*")
        elif char == "?":
            pieces.append("[^/]")
        else:
            pieces.append(re.escape(char))
        index += 1
    return re.compile("^" + "".join(pieces) + "$")


def path_matches(path: str, pattern: str) -> bool:
    return bool(_development_policy().path_matches(path, pattern))


@lru_cache(maxsize=256)
def _status_entries(worktree: Path) -> tuple[tuple[str, str], ...]:
    result = _run(
        ("git", "-c", "core.quotepath=false", "status", "--porcelain=v1", "-z", "-uall"),
        cwd=worktree,
    )
    raw = result.stdout.split("\0")
    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(raw):
        record = raw[index]
        index += 1
        if not record or len(record) < 4:
            continue
        status = record[:2]
        path = record[3:]
        if status[0] in {"R", "C"} or status[1] in {"R", "C"}:
            # Porcelain -z emits the destination in the status record and the
            # origin as the following NUL field. Ownership follows destination.
            index += 1
        entries.append((normalize_path(path), status))
    return tuple(sorted(set(entries)))


def _load_yaml(path: Path) -> Mapping[str, Any]:
    if yaml is None:
        raise OwnershipInputError("PyYAML is required to inspect active contracts")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise OwnershipInputError(f"cannot read contract {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise OwnershipInputError(f"contract must be a mapping: {path}")
    return value


def _load_delivery_resolver(root: Path) -> ModuleType:
    path = root / "scripts" / "generate_implementation_status.py"
    spec = importlib.util.spec_from_file_location("omni_delivery_projection", path)
    if spec is None or spec.loader is None:
        raise OwnershipInputError(f"delivery resolver cannot be loaded: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def delivered_contracts(
    root: Path,
    attestation_paths: Iterable[Path] = (),
    *,
    provenance_verifier: Any = None,
) -> dict[str, dict[str, Any]]:
    """Return only contracts proved by the caller's explicit verifier.

    Omitting the verifier deliberately uses the projection's offline
    fail-closed verifier.  Callers cannot declare delivery by supplying ids.
    """

    resolver = _load_delivery_resolver(root)
    try:
        return dict(
            resolver.resolve_delivered_contracts(
                root,
                attestation_paths,
                provenance_verifier=provenance_verifier,
            )
        )
    except (ValueError, OSError) as exc:
        raise OwnershipInputError(f"delivery receipts cannot be resolved: {exc}") from exc


def active_contract_scopes(
    root: Path,
    *,
    delivered_ids: Iterable[str] = (),
) -> tuple[ContractScope, ...]:
    root = repository_root(root)
    primary = primary_worktree(root)
    collected: dict[str, dict[str, Any]] = {}
    delivered = set(delivered_ids)
    candidates = list(all_worktrees(root))
    if root not in candidates:
        candidates.append(root)
    for worktree in candidates:
        contract_root = worktree / "docs" / "dev-changes"
        if not contract_root.is_dir():
            continue
        wid = worktree_id(worktree, primary=primary)
        for path in sorted(contract_root.glob("*/impact.yaml")):
            impact = _load_yaml(path)
            state = str(impact.get("state", ""))
            if state not in ACTIVE_STATES:
                continue
            change_id = str(impact.get("change_id") or path.parent.name)
            if change_id in delivered:
                continue
            patterns: set[str] = {f"docs/dev-changes/{change_id}/**"}
            for change in impact.get("planned_changes") or []:
                if isinstance(change, Mapping):
                    patterns.update(
                        normalize_path(str(item))
                        for item in change.get("paths") or []
                        if str(item).strip()
                    )
            patterns.update(
                normalize_path(str(item))
                for item in impact.get("allowed_unplanned_paths") or []
                if str(item).strip()
            )
            record = collected.setdefault(
                change_id,
                {"state": state, "patterns": set(), "source_worktrees": set()},
            )
            record["patterns"].update(patterns)
            record["source_worktrees"].add(wid)
            # If copies disagree, retain the most advanced active state as an
            # audit fact instead of silently depending on traversal order.
            if ACTIVE_STATE_ORDER[state] > ACTIVE_STATE_ORDER[str(record["state"])]:
                record["state"] = state
    return tuple(
        ContractScope(
            change_id,
            str(record["state"]),
            tuple(sorted(record["patterns"])),
            tuple(sorted(record["source_worktrees"])),
        )
        for change_id, record in sorted(collected.items())
    )


def owners_for_path(path: str, scopes: Iterable[ContractScope]) -> tuple[str, ...]:
    return tuple(
        sorted(
            scope.change_id
            for scope in scopes
            if any(path_matches(path, pattern) for pattern in scope.patterns)
        )
    )


def contract_scope_overlaps(scopes: Iterable[ContractScope]) -> tuple[dict[str, Any], ...]:
    """Report conflicts even when both owning worktrees are currently clean."""

    values = sorted(scopes, key=lambda item: item.change_id)
    overlaps: list[dict[str, Any]] = []
    for index, left in enumerate(values):
        for right in values[index + 1 :]:
            # Two nested contracts intentionally maintained by the same
            # single worktree have one writer. Keep multi-worktree and
            # ambiguous ownership blocking, but do not invent a concurrency
            # conflict where there is no second owner.
            if (
                len(left.source_worktrees) == 1
                and left.source_worktrees == right.source_worktrees
            ):
                continue
            pair = next(
                (
                    (left_pattern, right_pattern)
                    for left_pattern in left.patterns
                    for right_pattern in right.patterns
                    if _development_policy().glob_patterns_overlap(left_pattern, right_pattern)
                ),
                None,
            )
            if pair is None:
                continue
            overlaps.append(
                {
                    "left_change_id": left.change_id,
                    "right_change_id": right.change_id,
                    "left_pattern": pair[0],
                    "right_pattern": pair[1],
                    "left_worktrees": list(left.source_worktrees),
                    "right_worktrees": list(right.source_worktrees),
                }
            )
    return tuple(overlaps)


def contract_owner_ambiguities(
    scopes: Iterable[ContractScope],
) -> tuple[dict[str, Any], ...]:
    """Retain duplicate active worktree ownership instead of merging it away."""

    return tuple(
        {
            "change_id": scope.change_id,
            "state": scope.state,
            "source_worktrees": list(scope.source_worktrees),
            "patterns": list(scope.patterns),
            "reason": "active_change_id_in_multiple_worktrees",
        }
        for scope in sorted(scopes, key=lambda item: item.change_id)
        if len(scope.source_worktrees) > 1
    )


def blocking_ownership_states(counts: Mapping[str, Any]) -> tuple[str, ...]:
    """Return every ownership counter that must make the strict CLI fail."""

    return tuple(
        key
        for key in BLOCKING_OWNERSHIP_COUNT_KEYS
        if int(counts.get(key, 0) or 0) > 0
    )


def _runtime_lease_inventory(root: Path) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    path = root / "scripts" / "runtime_allocation.py"
    if not path.is_file():
        return (), ()
    spec = importlib.util.spec_from_file_location("omni_runtime_allocation_ownership", path)
    if spec is None or spec.loader is None:
        return (), ()
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        state_path = module.default_state_dir(root) / "allocations.json"
        if not state_path.is_file():
            return (), ()
        state = module._read_state(state_path)
        now = datetime.now(timezone.utc)
        audit: list[dict[str, Any]] = []
        blocking: list[dict[str, Any]] = []
        for item in state.get("leases", []):
            safe = dict(item)
            effective_state = str(item.get("state") or "unknown")
            if effective_state == "active":
                try:
                    if module.parse_time(str(item.get("expires_at"))) <= now:
                        effective_state = "stale"
                except (RuntimeError, ValueError):
                    effective_state = "invalid"
            safe["effective_state"] = effective_state
            audit.append(safe)
            if effective_state == "active":
                blocking.append(safe)
        return tuple(blocking), tuple(audit)
    except (OSError, RuntimeError, ValueError):
        return (), ()


def _lease_owners_for_path(path: str, leases: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(sorted({
        f"{lease.get('change_id')}@{lease.get('owner')}"
        for lease in leases
        if any(path_matches(path, str(pattern)) for pattern in lease.get("path_globs") or [])
    }))


ARCHIVE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", "coverage"}
ARCHIVE_SUFFIXES = {".pyc", ".pyo", ".coverage"}
BINARY_SECRET_SCAN_SUFFIXES = {
    ".7z", ".avi", ".avif", ".bmp", ".class", ".dll", ".doc", ".docx",
    ".eot", ".exe", ".gif", ".gz", ".ico", ".jar", ".jpeg", ".jpg",
    ".mov", ".mp3", ".mp4", ".otf", ".pdf", ".png", ".ppt", ".pptx",
    ".pyc", ".so", ".tar", ".tif", ".tiff", ".ttf", ".wav", ".webm",
    ".webp", ".woff", ".woff2", ".xls", ".xlsx", ".zip",
}


def archive_candidate(path: str) -> bool:
    normalized = normalize_path(path)
    parts = {part.casefold() for part in normalized.split("/")}
    name = normalized.rsplit("/", 1)[-1].casefold()
    return bool(parts & ARCHIVE_PARTS) or any(name.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)


def _scan_paths(root: Path, scope: str) -> tuple[str, ...]:
    if scope == "changed":
        return tuple(path for path, _status in _status_entries(root))
    if scope != "tracked":
        raise OwnershipInputError(f"unsupported secret scan scope: {scope}")
    result = _run(("git", "-c", "core.quotepath=false", "ls-files", "-z", "--"), cwd=root)
    return tuple(sorted(normalize_path(item) for item in result.stdout.split("\0") if item))


def _placeholder_secret(value: str) -> bool:
    folded = value.casefold()
    return (
        not value
        or value.startswith(("${", "{", "<"))
        or folded.startswith(("not-", "not_", "local-", "local_", "your-", "your_", "replace-", "sample-"))
        or folded in {"password", "secret", "token", "api-key", "apikey", "your-password", "your-secret"}
        or ("password" in folded and not any(character.isdigit() for character in folded))
        or any(
            marker in folded
            for marker in (
                "changeme", "example", "dummy", "redacted", "placeholder",
                "top-secret", "do-not-print", "test-token", "not-needed",
                "local-only", "replace-me", "omni_pass",
            )
        )
    )


def scan_secrets(
    root: Path,
    *,
    scope: str = "changed",
    allowlist: Iterable[str] = (),
    max_bytes: int = 1_000_000,
    _repository_root_resolved: bool = False,
) -> dict[str, Any]:
    """Scan changed/tracked text without ever returning the matched value."""

    root = root.resolve() if _repository_root_resolved else repository_root(root)
    allowed = tuple(dict.fromkeys((*DEFAULT_SECRET_ALLOWLIST, *(str(item).replace("\\", "/") for item in allowlist))))
    private_marker = "-----BEGIN " + "PRIVATE KEY-----"
    rules: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("private_key", re.compile(re.escape(private_marker))),
        ("bearer_token", re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._~+/=-]{20,})")),
        ("authorization_header", re.compile(r"(?i)\bAuthorization\b\s*[:=]\s*[\"'](?:Basic|Token)\s+([A-Za-z0-9._~+/=-]{16,})[\"']")),
        ("cookie_header", re.compile(r"(?i)\b(?:Cookie|Set-Cookie)\b\s*[:=]\s*[\"']([^\r\n\"']{0,512}=[^\r\n\"']{16,})[\"']")),
        ("session_credential", re.compile(r"(?i)\b(?:session(?:id|_id|_token)?|sid|csrf(?:token|_token)?|refresh[_-]?token)\b\s*[:=]\s*[\"']([A-Za-z0-9.%_~+/|=-]{16,})[\"']")),
        ("credential_dsn", re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|redis|mongodb(?:\+srv)?)://[^\s:@/]+:([^\s@/]+)@")),
        ("credential_assignment", re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)\b\s*[:=]\s*[\"']([A-Za-z0-9._~+/=-]{12,})[\"']")),
        ("credential_env_assignment", re.compile(r"(?i)^(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)\s*=\s*([A-Za-z0-9._~+/=-]{16,})\s*$")),
        ("long_credential", re.compile(r"(?i)\b(?:cookie[_-]?str|credential|client[_-]?secret|private[_-]?token)\b\s*[:=]\s*[\"']([^\r\n\"']{48,})[\"']")),
    )
    findings: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    scanned = 0
    for relative in _scan_paths(root, scope):
        path = root / relative
        if not path.is_file():
            continue
        try:
            if path.suffix.casefold() in BINARY_SECRET_SCAN_SUFFIXES:
                skipped.append({"path": relative, "reason": "binary_extension"})
                continue
            if path.stat().st_size > max_bytes:
                skipped.append({"path": relative, "reason": "size_limit"})
                continue
            raw = path.read_bytes()
            if b"\x00" in raw:
                skipped.append({"path": relative, "reason": "binary"})
                continue
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            skipped.append({"path": relative, "reason": "unreadable_text"})
            continue
        scanned += 1
        for line_number, line in enumerate(text.splitlines(), start=1):
            for rule_id, pattern in rules:
                for match in pattern.finditer(line):
                    allow_key = f"{relative}:{rule_id}"
                    if any(fnmatch.fnmatchcase(allow_key, item) for item in allowed):
                        continue
                    captured = match.group(1) if match.lastindex else match.group(0)
                    if rule_id != "private_key" and _placeholder_secret(captured.strip("\"'")):
                        continue
                    fingerprint = hashlib.sha256(
                        f"{relative}:{line_number}:{rule_id}:{match.group(0)}".encode("utf-8")
                    ).hexdigest()
                    findings.append({"path": relative, "rule": rule_id, "fingerprint": fingerprint})
    findings.sort(key=lambda item: (item["path"], item["rule"], item["fingerprint"]))
    return {
        "scope": scope,
        "status": "passed" if not findings else "failed",
        "scanned_files": scanned,
        "finding_count": len(findings),
        "findings": findings,
        "skipped": skipped,
        "redaction": "path_rule_fingerprint_only",
    }


def inventory_workspace(
    root: Path,
    *,
    include_primary: bool = True,
    attestation_paths: Iterable[Path] = (),
    provenance_verifier: Any = None,
    secret_scope: str = "tracked",
    secret_allowlist: Iterable[str] = (),
) -> dict[str, Any]:
    root = repository_root(root)
    primary = primary_worktree(root)
    delivered = delivered_contracts(
        root,
        attestation_paths,
        provenance_verifier=provenance_verifier,
    )
    scopes = active_contract_scopes(root, delivered_ids=delivered)
    scope_overlaps = contract_scope_overlaps(scopes)
    owner_ambiguities = contract_owner_ambiguities(scopes)
    scope_source_worktrees = {
        scope.change_id: set(scope.source_worktrees) for scope in scopes
    }
    leases, lease_audit = _runtime_lease_inventory(root)
    candidates = list(all_worktrees(root))
    if not include_primary:
        candidates = [path for path in candidates if path != primary]
    if root not in candidates:
        candidates.append(root)

    max_workers = min(8, max(1, len(candidates)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        status_by_worktree = dict(zip(candidates, executor.map(_status_entries, candidates)))

    facts: list[DirtyPath] = []
    current_worktree_id = worktree_id(root, primary=primary)
    for worktree in candidates:
        is_primary = worktree == primary
        is_current = worktree == root
        wid = worktree_id(worktree, primary=primary)
        for path, status in status_by_worktree[worktree]:
            hygiene = "archive_candidate" if archive_candidate(path) else "retained_source"
            recovery = "archive_to_change_scoped_recovery_bundle" if hygiene == "archive_candidate" else "none"
            scope_owners = owners_for_path(path, scopes)
            lease_owners = _lease_owners_for_path(path, leases)
            matching_lease_changes = {item.split("@", 1)[0] for item in lease_owners}
            # A path is audit-only only when every matching contract is owned
            # by this exact external worktree and none is also owned by the
            # current candidate. This narrowly permits nested contracts with
            # one physical writer; current-scope and foreign-scope overlaps
            # remain blocking merge/concurrency risks.
            aligned_external_scope = bool(scope_owners) and all(
                scope_source_worktrees.get(owner, set()) == {wid}
                and current_worktree_id not in scope_source_worktrees.get(owner, set())
                for owner in scope_owners
            )
            if is_primary:
                facts.append(
                    DirtyPath(
                        path=path,
                        worktree_id=wid,
                        git_status=status,
                        ownership="preserved_external_user",
                        owner_id="external-user:primary-worktree",
                        disposition="preserve_in_place",
                        evidence="git_status_primary_worktree",
                        hygiene_class=hygiene,
                        recovery_action=recovery,
                        scope_owners=scope_owners,
                        scope_conflict=bool(scope_owners) and not aligned_external_scope,
                        lease_owners=lease_owners,
                        lease_conflict=bool(lease_owners),
                    )
                )
                continue
            if not is_current:
                ownership = "preserved_external_worktree"
                owner_id = f"external-worktree:{wid}"
                disposition = "preserve_in_place"
            elif len(scope_owners) == 1:
                ownership, owner_id, disposition = "active_change", scope_owners[0], "owned_candidate"
            elif len(scope_owners) > 1:
                ownership, owner_id, disposition = "conflict", ",".join(scope_owners), "block_new_write"
            else:
                ownership, owner_id, disposition = "unassigned", "", "assign_before_write"
            owning_scope = next(
                (scope for scope in scopes if scope.change_id in scope_owners and wid in scope.source_worktrees),
                None,
            )
            owner_ambiguity = any(
                scope.change_id in scope_owners and len(scope.source_worktrees) > 1
                for scope in scopes
            )
            scope_conflict = bool(
                not aligned_external_scope
                and (
                    len(scope_owners) > 1
                    or bool(scope_owners and owning_scope is None)
                    or owner_ambiguity
                )
            )
            lease_conflict = bool(
                lease_owners
                and not (
                    is_current
                    and len(scope_owners) == 1
                    and matching_lease_changes == set(scope_owners)
                )
            )
            facts.append(
                DirtyPath(
                    path=path,
                    worktree_id=wid,
                    git_status=status,
                    ownership=ownership,
                    owner_id=owner_id,
                    disposition=disposition,
                    evidence="active_contract_scope",
                    hygiene_class=hygiene,
                    recovery_action=recovery,
                    scope_owners=scope_owners,
                    scope_conflict=scope_conflict,
                    lease_owners=lease_owners,
                    lease_conflict=lease_conflict,
                )
            )

    counts = {
        kind: sum(1 for fact in facts if fact.ownership == kind)
        for kind in ("active_change", "preserved_external_user", "preserved_external_worktree", "conflict", "unassigned")
    }
    counts["dirty_scope_conflict"] = sum(1 for fact in facts if fact.scope_conflict)
    counts["external_scope_overlap"] = sum(
        1
        for fact in facts
        if fact.scope_owners
        and not fact.scope_conflict
        and fact.ownership in {"preserved_external_user", "preserved_external_worktree"}
    )
    counts["contract_scope_conflict"] = len(scope_overlaps)
    counts["contract_owner_ambiguity"] = len(owner_ambiguities)
    counts["scope_conflict"] = (
        counts["dirty_scope_conflict"]
        + counts["contract_scope_conflict"]
        + counts["contract_owner_ambiguity"]
    )
    counts["lease_conflict"] = sum(1 for fact in facts if fact.lease_conflict)
    counts["archive_candidate"] = sum(1 for fact in facts if fact.hygiene_class == "archive_candidate")
    # The deliverable worktree is gated against every tracked file. Other
    # worktrees are preserved, but their local deltas are still audited so a
    # dirty sibling cannot hide a newly introduced credential.
    current_secret_scan = scan_secrets(root, scope=secret_scope, allowlist=secret_allowlist)
    worktree_secret_audit: list[dict[str, Any]] = []
    external_finding_count = 0
    external_worktrees = [worktree for worktree in candidates if worktree != root]

    def scan_external(worktree: Path) -> tuple[Path, dict[str, Any]]:
        return worktree, scan_secrets(
            worktree,
            scope="changed",
            allowlist=secret_allowlist,
            _repository_root_resolved=True,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        external_results = list(executor.map(scan_external, external_worktrees))
    for worktree, result in external_results:
        worktree_secret_audit.append(
            {
                "worktree_id": worktree_id(worktree, primary=primary),
                "scope": "changed",
                "status": result["status"],
                "scanned_files": result["scanned_files"],
                "finding_count": result["finding_count"],
                "findings": result["findings"],
                "skipped": result["skipped"],
                "redaction": result["redaction"],
            }
        )
        external_finding_count += int(result["finding_count"])
    secret_scan = dict(current_secret_scan)
    secret_scan["coverage"] = "current_tracked_baseline"
    secret_scan["external_worktree_audit_count"] = len(worktree_secret_audit)
    secret_scan["external_worktree_finding_count"] = external_finding_count
    return {
        "schema_version": 1,
        "kind": "omni_workspace_ownership_inventory",
        "repository": {"current_worktree": worktree_id(root, primary=primary), "primary_worktree": "primary"},
        "policy": {
            "primary_dirty_paths": "preserved_external_user",
            "mutates_files": False,
            "conflict_behavior": "block_new_write_only",
            "external_scope_overlap": "audit_only_when_all_scope_sources_match_external_worktree",
            "blocking_count_keys": list(BLOCKING_OWNERSHIP_COUNT_KEYS),
        },
        "active_contracts": [
            {
                "change_id": scope.change_id,
                "state": scope.state,
                "patterns": list(scope.patterns),
                "source_worktrees": list(scope.source_worktrees),
            }
            for scope in scopes
        ],
        "contract_scope_overlaps": list(scope_overlaps),
        "contract_owner_ambiguities": list(owner_ambiguities),
        "runtime_lease_audit": list(lease_audit),
        "delivered_contracts": [delivered[key] for key in sorted(delivered)],
        "counts": counts,
        "paths": [asdict(fact) for fact in sorted(facts, key=lambda item: (item.worktree_id, item.path))],
        "secret_scan": secret_scan,
        "worktree_secret_audit": worktree_secret_audit,
        "cleanup": {
            "archive_candidate_count": counts["archive_candidate"],
            "mutated": False,
            "default_recovery_action": "archive_to_change_scoped_recovery_bundle",
        },
    }


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--current-only", action="store_true", help="do not inspect the primary worktree")
    parser.add_argument("--output", type=Path, help="optional atomic JSON snapshot path")
    parser.add_argument("--fail-unassigned", action="store_true")
    parser.add_argument("--attestation", type=Path, action="append", default=[])
    parser.add_argument("--secret-scope", choices=("changed", "tracked"), default="tracked")
    parser.add_argument("--secret-allow", action="append", default=[])
    parser.add_argument("--fail-secrets", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        payload = inventory_workspace(
            args.root,
            include_primary=not args.current_only,
            attestation_paths=args.attestation,
            secret_scope=args.secret_scope,
            secret_allowlist=args.secret_allow,
        )
        if args.output:
            _write_json_atomic(args.output, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    except OwnershipInputError as exc:
        print(f"[workspace-ownership] ERROR: {exc}", file=sys.stderr)
        return 2
    if args.fail_unassigned and blocking_ownership_states(payload["counts"]):
        return 1
    if args.fail_secrets and payload["secret_scan"]["status"] != "passed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
