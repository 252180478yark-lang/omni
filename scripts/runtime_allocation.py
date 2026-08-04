#!/usr/bin/env python3
"""Atomic WorkspaceLease and RuntimeAllocation store for Omni worktrees.

Production state lives below ``git rev-parse --git-common-dir`` so every linked
worktree competes on the same lock and generation.  Tests may inject an isolated
``--state-dir``.  The store contains resource identities only and never stores
or prints database credentials or complete DSNs.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from functools import lru_cache
from types import ModuleType
from typing import Any, Iterable, Iterator, Mapping, Sequence


SCHEMA_VERSION = 1
DEFAULT_TTL_SECONDS = 8 * 60 * 60
BLOCKING_STATES = {"active"}
PORT_ENV = {
    "postgres": "POSTGRES_PORT",
    "redis": "REDIS_PORT",
    "frontend": "FRONTEND_PORT",
    "ai-provider-hub": "AI_PROVIDER_HUB_PORT",
    "knowledge-engine": "KNOWLEDGE_ENGINE_PORT",
    "ad-review-service": "AD_REVIEW_PORT",
    "identity-service": "IDENTITY_SERVICE_PORT",
    "news-aggregator": "NEWS_AGGREGATOR_PORT",
    "video-analysis": "VIDEO_ANALYSIS_PORT",
    "livestream-analysis": "LIVESTREAM_ANALYSIS_PORT",
    "scout-agent": "SCOUT_AGENT_PORT",
    "nginx-http": "NGINX_HTTP_PORT",
    "nginx-https": "NGINX_HTTPS_PORT",
}


class AllocationError(RuntimeError):
    """Base allocation failure safe to display."""


class AllocationConflict(AllocationError):
    def __init__(self, conflicts: Sequence[Mapping[str, Any]]):
        self.conflicts = tuple(dict(item) for item in conflicts)
        super().__init__(f"{len(self.conflicts)} lease/resource conflict(s)")


class CompareAndSwapConflict(AllocationError):
    """The caller evaluated an older store generation."""


@dataclass(frozen=True)
class WorkspaceLease:
    lease_id: str
    repository_id: str
    worktree_id: str
    change_id: str
    owner: str
    path_globs: tuple[str, ...]
    mode: str
    risk_level: str
    created_at: str
    expires_at: str
    state: str
    revision: int

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["path_globs"] = list(self.path_globs)
        return value


@dataclass(frozen=True)
class RuntimeAllocation:
    allocation_id: str
    lease_id: str
    repository_id: str
    worktree_id: str
    change_id: str
    owner: str
    canonical: bool
    runtime_id: str
    compose_project: str
    ports: Mapping[str, int]
    database: str
    database_schema: str
    volumes: tuple[str, ...]
    redis_namespace: str
    cron_owner: bool
    approval_worker_owner: bool
    risk_level: str
    build_sha: str
    source_fingerprint: str
    created_at: str
    expires_at: str
    state: str
    revision: int

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["ports"] = dict(sorted(self.ports.items()))
        value["volumes"] = list(self.volumes)
        return value


def _run(command: Sequence[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AllocationError(f"cannot run {' '.join(command)}: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise AllocationError(f"command failed ({result.returncode}): {' '.join(command)}: {detail}")
    return result


def _run_bytes(command: Sequence[str], *, cwd: Path) -> bytes:
    try:
        result = subprocess.run(list(command), cwd=cwd, capture_output=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AllocationError(f"cannot run {command[0]} for source fingerprint: {exc}") from exc
    if result.returncode != 0:
        raise AllocationError(f"source fingerprint command failed: {command[0]}")
    return result.stdout


def _run_bytes_optional(command: Sequence[str], *, cwd: Path) -> bytes | None:
    try:
        result = subprocess.run(list(command), cwd=cwd, capture_output=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AllocationError(f"cannot run {command[0]} for source fingerprint: {exc}") from exc
    return result.stdout if result.returncode == 0 else None


def repository_root(candidate: Path | None = None) -> Path:
    start = (candidate or Path.cwd()).resolve()
    result = _run(("git", "rev-parse", "--show-toplevel"), cwd=start)
    return Path(result.stdout.strip()).resolve()


def git_common_dir(root: Path) -> Path:
    result = _run(("git", "rev-parse", "--git-common-dir"), cwd=root)
    value = Path(result.stdout.strip())
    return (root / value).resolve() if not value.is_absolute() else value.resolve()


def default_state_dir(root: Path) -> Path:
    return git_common_dir(root) / "omni-runtime"


def _default_runtime_secret_path(root: Path, filename: str, label: str) -> Path:
    repo_key = repository_id(root)
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    elif os.environ.get("XDG_STATE_HOME"):
        base = Path(os.environ["XDG_STATE_HOME"])
    else:
        base = Path(tempfile.gettempdir()) / "omni-local-state"
    path = (base / "Omni" / "runtime-secrets" / repo_key / filename).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return path
    raise AllocationError(f"{label} secret path must remain outside the repository")


def default_approval_secret_path(root: Path) -> Path:
    """Return a stable repository-external approval HMAC secret reference."""

    return _default_runtime_secret_path(root, "approval-hmac.key", "approval HMAC")


def default_identity_jwt_secret_path(root: Path) -> Path:
    """Return an independent repository-external identity JWT secret reference."""

    return _default_runtime_secret_path(root, "identity-jwt.key", "identity JWT")


def default_compatibility_token_path(root: Path) -> Path:
    """Return an independent repository-external compatibility token reference."""

    return _default_runtime_secret_path(root, "compatibility-token.key", "compatibility token")


def _ensure_runtime_secret(
    root: Path,
    *,
    target: Path,
    label: str,
    secret_factory: Any,
) -> Path:
    target = target.resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        pass
    else:
        raise AllocationError(f"{label} secret path must remain outside the repository")
    if target.exists():
        if not target.is_file() or target.stat().st_size < 32:
            raise AllocationError(f"{label} secret reference is invalid")
        if os.name != "nt":
            target.chmod(0o600)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(secret_factory())
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def ensure_approval_hmac_secret(root: Path, *, path: Path | None = None) -> Path:
    """Create once with private permissions; never read or return its value."""

    return _ensure_runtime_secret(
        root,
        target=path or default_approval_secret_path(root),
        label="approval HMAC",
        secret_factory=lambda: secrets.token_bytes(48),
    )


def ensure_identity_jwt_secret(root: Path, *, path: Path | None = None) -> Path:
    """Create a distinct printable JWT key once without returning its value."""

    return _ensure_runtime_secret(
        root,
        target=path or default_identity_jwt_secret_path(root),
        label="identity JWT",
        secret_factory=lambda: secrets.token_urlsafe(48).encode("ascii"),
    )


def ensure_compatibility_token(root: Path, *, path: Path | None = None) -> Path:
    """Create a distinct printable compatibility token without returning its value."""

    return _ensure_runtime_secret(
        root,
        target=path or default_compatibility_token_path(root),
        label="compatibility token",
        secret_factory=lambda: secrets.token_urlsafe(48).encode("ascii"),
    )


def primary_worktree(root: Path) -> Path:
    common = git_common_dir(root)
    if common.name.casefold() == ".git":
        return common.parent.resolve()
    result = _run(("git", "worktree", "list", "--porcelain"), cwd=root)
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            return Path(line.removeprefix("worktree ")).resolve()
    raise AllocationError("cannot identify primary worktree")


def _identity(value: str) -> str:
    return hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()


def repository_id(root: Path) -> str:
    return "repo-" + _identity(str(git_common_dir(root)))[:16]


def worktree_id(root: Path) -> str:
    return "worktree-" + _identity(str(root.resolve()).replace("\\", "/"))[:16]


FINGERPRINT_EXCLUDED_PARTS = {
    ".git",
    ".runtime",
    ".omni-runtime",
    "node_modules",
    "dist",
    "dist-electron",
    "release",
    ".next",
    "out",
    "build",
    "logs",
    ".dev-logs",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "downloads",
    "exports",
    "output",
}
FINGERPRINT_SECRET_NAMES = {
    ".env",
    ".env.local",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}


def _fingerprint_path_allowed(relative: str) -> bool:
    normalized = relative.replace("\\", "/")
    parts = [part.casefold() for part in normalized.split("/")]
    name = parts[-1]
    if any(part in FINGERPRINT_EXCLUDED_PARTS for part in parts):
        return False
    if name in FINGERPRINT_SECRET_NAMES or name.startswith(".env."):
        return False
    if any(marker in name for marker in ("credential", "secret", "private_key")):
        return False
    if name.endswith((".pem", ".key", ".p12", ".pfx", ".pyc", ".log")):
        return False
    # Documentation/test fixtures do not alter the runnable source identity.
    if parts[0] == "docs" or "tests" in parts or "__tests__" in parts:
        return False
    return True


def source_tree_fingerprint(root: Path) -> str:
    """Hash source state, including dirty contents but never mtimes or secret files."""

    root = repository_root(root)
    digest = hashlib.sha256()
    head = _run(("git", "rev-parse", "HEAD"), cwd=root).stdout.strip().lower()
    digest.update(f"head:{head}\0".encode())
    for label, names_command in (
        (
            "staged",
            (
                "git",
                "-c",
                "core.quotepath=false",
                "diff",
                "--cached",
                "--name-only",
                "-z",
                "HEAD",
                "--",
            ),
        ),
        (
            "unstaged",
            ("git", "-c", "core.quotepath=false", "diff", "--name-only", "-z", "--"),
        ),
    ):
        raw_names = _run_bytes(names_command, cwd=root)
        for raw_path in sorted(item for item in raw_names.split(b"\0") if item):
            try:
                relative = raw_path.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if not _fingerprint_path_allowed(relative):
                continue
            if label == "staged":
                content = _run_bytes_optional(("git", "show", f":{relative}"), cwd=root)
            else:
                path = root / relative
                try:
                    content = path.read_bytes() if path.is_file() else None
                except OSError:
                    content = None
            content_digest = hashlib.sha256(content).digest() if content is not None else b"<deleted>"
            digest.update(label.encode() + b":" + raw_path + b":" + content_digest + b"\0")
    raw_untracked = _run_bytes(
        (
            "git",
            "-c",
            "core.quotepath=false",
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
        ),
        cwd=root,
    )
    for raw_path in sorted(item for item in raw_untracked.split(b"\0") if item):
        try:
            relative = raw_path.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not _fingerprint_path_allowed(relative):
            continue
        path = root / relative
        try:
            if not path.is_file() or path.stat().st_size > 5_000_000:
                continue
            content_digest = hashlib.sha256(path.read_bytes()).digest()
        except OSError:
            continue
        digest.update(b"untracked:" + raw_path + b":" + content_digest + b"\0")
    return digest.hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AllocationError(f"invalid UTC timestamp in allocation store: {value!r}") from exc
    return parsed.astimezone(timezone.utc)


@lru_cache(maxsize=1)
def _development_policy() -> ModuleType:
    path = Path(__file__).resolve().with_name("development_policy.py")
    spec = importlib.util.spec_from_file_location("omni_development_policy_allocation", path)
    if spec is None or spec.loader is None:
        raise AllocationError("development policy cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def normalize_glob(value: str) -> str:
    try:
        return str(_development_policy().normalize_path(value))
    except ValueError as exc:
        raise AllocationError(str(exc)) from exc


def _glob_tokens(pattern: str) -> tuple[tuple[str, str | None], ...]:
    tokens: list[tuple[str, str | None]] = []
    index = 0
    for _ in range(len(pattern) + 1):
        if index >= len(pattern):
            break
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                tokens.append(("many_any", None))
                index += 2
                continue
            tokens.append(("many_segment", None))
        elif char == "?":
            tokens.append(("one_segment", None))
        else:
            tokens.append(("literal", char))
        index += 1
    return tuple(tokens)


def _tokens_share(left: tuple[str, str | None], right: tuple[str, str | None]) -> bool:
    lk, lv = left
    rk, rv = right
    if lk == "literal" and rk == "literal":
        return lv == rv
    if lk == "literal":
        return lv != "/" or rk == "many_any"
    if rk == "literal":
        return rv != "/" or lk == "many_any"
    return True


def globs_overlap(left: str, right: str) -> bool:
    try:
        return bool(_development_policy().glob_patterns_overlap(left, right))
    except ValueError as exc:
        raise AllocationError(str(exc)) from exc


@contextlib.contextmanager
def _file_lock(path: Path, *, timeout_seconds: float = 5.0) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    deadline = time.monotonic() + timeout_seconds
    locked = False
    try:
        while not locked:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover - exercised in Linux CI
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise AllocationError("timed out acquiring runtime allocation lock")
                time.sleep(0.02)
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover - exercised in Linux CI
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generation": 0,
        "leases": [],
        "allocations": [],
    }


def _read_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _empty_state()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AllocationError(f"runtime allocation store is invalid: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise AllocationError("runtime allocation store has unsupported schema")
    if not isinstance(value.get("leases"), list) or not isinstance(value.get("allocations"), list):
        raise AllocationError("runtime allocation store lists are invalid")
    return value


def _write_state(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _mark_stale(state: dict[str, Any], now: datetime) -> None:
    for collection in ("leases", "allocations"):
        for item in state[collection]:
            if item.get("state") == "active" and parse_time(str(item.get("expires_at"))) <= now:
                item["state"] = "stale"


def _slug(value: str, *, maximum: int = 24) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "change"
    return result[:maximum].rstrip("-")


def _pg_identifier(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]", "_", value.casefold())
    if not normalized or normalized[0].isdigit():
        normalized = "omni_" + normalized
    return normalized[:63].rstrip("_")


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / "config" / "runtime-manifest.yaml"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AllocationError(f"runtime manifest is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise AllocationError("runtime manifest root must be a mapping")
    return value


def _canonical_ports(manifest: Mapping[str, Any]) -> dict[str, int]:
    ports: dict[str, int] = {}
    for service, config in (manifest.get("services") or {}).items():
        if isinstance(config, Mapping) and config.get("published_ports"):
            ports[str(service)] = int(config["published_ports"][0])
    ports.setdefault("nginx-http", 80)
    ports.setdefault("nginx-https", 443)
    return ports


def _allocated_ports(state: Mapping[str, Any]) -> set[int]:
    return {
        int(port)
        for allocation in state.get("allocations", [])
        if allocation.get("state") in BLOCKING_STATES
        for port in (allocation.get("ports") or {}).values()
    }


def _isolated_ports(
    canonical: Mapping[str, int],
    state: Mapping[str, Any],
    seed: str,
    requested: Mapping[str, int],
) -> dict[str, int]:
    occupied = _allocated_ports(state)
    result: dict[str, int] = {}
    offset = 1000 + (int(hashlib.sha256(seed.encode()).hexdigest()[:4], 16) % 12000)
    for index, (service, base) in enumerate(sorted(canonical.items())):
        if service in requested:
            candidate = int(requested[service])
        else:
            candidate = 10000 + ((int(base) + offset + index * 97) % 45000)
        while candidate in occupied or candidate in result.values():
            candidate += 1
            if candidate > 65535:
                candidate = 10000
        result[service] = candidate
    for service, candidate in requested.items():
        if service not in result:
            result[service] = int(candidate)
    return result


def _conflicts(
    state: Mapping[str, Any],
    lease: WorkspaceLease,
    allocation: RuntimeAllocation,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for existing in state.get("leases", []):
        if existing.get("state") not in BLOCKING_STATES or existing.get("repository_id") != lease.repository_id:
            continue
        if (
            existing.get("owner") == lease.owner
            and existing.get("change_id") == lease.change_id
            and existing.get("worktree_id") == lease.worktree_id
        ):
            continue
        if existing.get("mode") == "read" and lease.mode == "read":
            continue
        for left in lease.path_globs:
            for right in existing.get("path_globs") or []:
                if globs_overlap(left, str(right)):
                    conflicts.append(
                        {
                            "kind": "path",
                            "resource": f"{left} <-> {right}",
                            "owner": existing.get("owner"),
                            "change_id": existing.get("change_id"),
                            "expires_at": existing.get("expires_at"),
                            "state": existing.get("state"),
                        }
                    )
    for existing in state.get("allocations", []):
        if existing.get("state") not in BLOCKING_STATES:
            continue
        if (
            existing.get("owner") == allocation.owner
            and existing.get("change_id") == allocation.change_id
            and existing.get("worktree_id") == allocation.worktree_id
        ):
            continue
        resources: list[tuple[str, str]] = []
        current_ports = {int(value): key for key, value in allocation.ports.items()}
        for service, value in (existing.get("ports") or {}).items():
            if int(value) in current_ports:
                resources.append(("port", f"{int(value)} ({current_ports[int(value)]}/{service})"))
        if allocation.database == existing.get("database"):
            resources.append(("database", allocation.database))
        for volume in sorted(set(allocation.volumes) & set(existing.get("volumes") or [])):
            resources.append(("volume", volume))
        if allocation.redis_namespace == existing.get("redis_namespace"):
            resources.append(("redis_namespace", allocation.redis_namespace))
        if allocation.cron_owner and existing.get("cron_owner"):
            resources.append(("cron_owner", "canonical-writer"))
        for kind, resource in resources:
            conflicts.append(
                {
                    "kind": kind,
                    "resource": resource,
                    "owner": existing.get("owner"),
                    "change_id": existing.get("change_id"),
                    "expires_at": existing.get("expires_at"),
                    "state": existing.get("state"),
                }
            )
    return conflicts


def _build_records(
    root: Path,
    state: Mapping[str, Any],
    *,
    change_id: str,
    owner: str,
    path_globs: Iterable[str],
    mode: str,
    ttl_seconds: int,
    canonical: bool,
    requested_ports: Mapping[str, int],
    risk_level: str,
    now: datetime,
) -> tuple[WorkspaceLease, RuntimeAllocation]:
    if mode not in {"read", "write"}:
        raise AllocationError("lease mode must be read or write")
    if risk_level not in {"R0", "R1", "R2", "R3"}:
        raise AllocationError("risk_level must be R0, R1, R2, or R3")
    if ttl_seconds < 60 or ttl_seconds > 7 * 24 * 60 * 60:
        raise AllocationError("ttl_seconds must be between 60 and 604800")
    if not change_id.strip() or not owner.strip():
        raise AllocationError("change_id and owner are required")
    normalized_globs = tuple(sorted({normalize_glob(value) for value in path_globs}))
    if mode == "write" and not normalized_globs:
        raise AllocationError("write lease requires at least one path glob")
    if canonical and root.resolve() != primary_worktree(root):
        raise AllocationError("canonical allocation is available only from the primary worktree")

    manifest = _load_manifest(root)
    canonical_ports = _canonical_ports(manifest)
    build_sha = _run(("git", "rev-parse", "HEAD"), cwd=root).stdout.strip().lower()
    sha8 = build_sha[:8]
    slug = _slug(change_id)
    runtime_id = "omni-main" if canonical else f"{slug}-{sha8}"
    compose_project = "omni" if canonical else f"omni-{slug}-{sha8}"[:63].rstrip("-")
    ports = dict(canonical_ports) if canonical else _isolated_ports(canonical_ports, state, runtime_id, requested_ports)
    if canonical:
        ports.update({key: int(value) for key, value in requested_ports.items()})
    database = (
        str(manifest.get("canonical_runtime", {}).get("database", "omni_vibe_db"))
        if canonical
        else _pg_identifier(f"omni_verify_{slug}_{sha8}")
    )
    database_schema = "public" if canonical else _pg_identifier(f"wt_{slug}_{sha8}")
    volumes = (
        ("omni_postgres_data", "omni_redis_data", "omni_knowledge_data")
        if canonical
        else (
            f"{compose_project}_postgres_data",
            f"{compose_project}_redis_data",
            f"{compose_project}_knowledge_data",
        )
    )
    created = isoformat(now)
    expires = isoformat(now + timedelta(seconds=ttl_seconds))
    lease_id = "lease-" + uuid.uuid4().hex
    allocation_id = "allocation-" + uuid.uuid4().hex
    repo_id = repository_id(root)
    wt_id = worktree_id(root)
    source_fingerprint = source_tree_fingerprint(root)
    lease = WorkspaceLease(
        lease_id,
        repo_id,
        wt_id,
        change_id,
        owner,
        normalized_globs,
        mode,
        risk_level,
        created,
        expires,
        "active",
        1,
    )
    allocation = RuntimeAllocation(
        allocation_id,
        lease_id,
        repo_id,
        wt_id,
        change_id,
        owner,
        canonical,
        runtime_id,
        compose_project,
        ports,
        database,
        database_schema,
        volumes,
        "omni-main" if canonical else runtime_id,
        canonical,
        canonical or mode == "write",
        risk_level,
        build_sha,
        source_fingerprint,
        created,
        expires,
        "active",
        1,
    )
    return lease, allocation


def allocation_environment(allocation: Mapping[str, Any], *, worktree: Path | None = None) -> dict[str, str]:
    ports = allocation.get("ports") or {}
    env = {
        "COMPOSE_PROJECT_NAME": str(allocation["compose_project"]),
        "OMNI_RUNTIME_ID": str(allocation["runtime_id"]),
        "OMNI_ALLOCATION_ID": str(allocation["allocation_id"]),
        "POSTGRES_DB": str(allocation["database"]),
        "OMNI_DB_SCHEMA": str(allocation["database_schema"]),
        "OMNI_REDIS_NAMESPACE": str(allocation["redis_namespace"]),
        "OMNI_SCHEDULER_ENABLED": "true" if allocation.get("cron_owner") else "false",
        "OMNI_SCHEDULER_ROLE": "owner" if allocation.get("cron_owner") else "disabled",
        "ENABLE_SCHEDULER": "true" if allocation.get("cron_owner") else "false",
        "OMNI_APPROVAL_WORKER_ENABLED": "true" if allocation.get("approval_worker_owner") else "false",
        "OMNI_APPROVAL_WORKER_ROLE": "owner" if allocation.get("approval_worker_owner") else "disabled",
        "OMNI_SOURCE_COMMIT": str(allocation["build_sha"]),
        "OMNI_BUILD_COMMIT": str(allocation["build_sha"]),
        "OMNI_EXPECTED_COMMIT": str(allocation["build_sha"]),
        "OMNI_SOURCE_FINGERPRINT": str(allocation["source_fingerprint"]),
        # Host-mode dev runs execute this exact checkout rather than a baked
        # image. Project both halves of the verified identity pair so the
        # pre-side-effect guard can compare commit and source fingerprint.
        # Compose does not forward these host values into service containers;
        # container Dockerfiles still supply their own baked build identity.
        "OMNI_BUILD_SOURCE_FINGERPRINT": str(allocation["source_fingerprint"]),
        "OMNI_DATABASE_DISPOSABLE": "false" if allocation.get("canonical") else "true",
        "OMNI_RESTART_POLICY": "unless-stopped" if allocation.get("canonical") else "no",
        "OMNI_NETWORK_NAME": f"{allocation['compose_project']}-network",
        "OMNI_WORKTREE_ID": str(allocation["worktree_id"]),
        "OMNI_RISK_LEVEL": str(allocation.get("risk_level", "R1")),
        "OMNI_ALLOCATED_PORTS_SHA256": hashlib.sha256(
            json.dumps(dict(sorted(ports.items())), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "OMNI_ALLOCATED_VOLUMES_SHA256": hashlib.sha256(
            json.dumps(sorted(allocation.get("volumes") or []), separators=(",", ":")).encode()
        ).hexdigest(),
    }
    # Host paths never enter labels, API payloads, or container environment;
    # the opaque worktree_id is the only runtime identity.
    for service, port in ports.items():
        env[PORT_ENV.get(str(service), f"OMNI_{str(service).upper().replace('-', '_')}_PORT")] = str(port)
    volumes = list(allocation.get("volumes") or [])
    if len(volumes) >= 3:
        env.update(
            {
                "POSTGRES_VOLUME_NAME": volumes[0],
                "REDIS_VOLUME_NAME": volumes[1],
                "KNOWLEDGE_VOLUME_NAME": volumes[2],
            }
        )
    return dict(sorted(env.items()))


def acquire(
    root: Path,
    *,
    change_id: str,
    owner: str,
    path_globs: Iterable[str],
    mode: str = "write",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    canonical: bool = False,
    requested_ports: Mapping[str, int] | None = None,
    risk_level: str = "R1",
    state_dir: Path | None = None,
    expected_generation: int | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = repository_root(root)
    store_dir = (state_dir or default_state_dir(root)).resolve()
    state_path = store_dir / "allocations.json"
    lock_path = store_dir / "allocations.lock"
    moment = now or utc_now()
    with _file_lock(lock_path):
        state = _read_state(state_path)
        _mark_stale(state, moment)
        generation = int(state.get("generation", 0))
        if expected_generation is not None and generation != expected_generation:
            raise CompareAndSwapConflict(
                f"allocation generation changed: expected {expected_generation}, found {generation}"
            )
        for existing in state["allocations"]:
            if (
                existing.get("state") == "active"
                and existing.get("change_id") == change_id
                and existing.get("owner") == owner
                and existing.get("worktree_id") == worktree_id(root)
            ):
                lease = next(
                    (item for item in state["leases"] if item.get("lease_id") == existing.get("lease_id")),
                    None,
                )
                requested_globs = tuple(sorted({normalize_glob(value) for value in path_globs}))
                mismatch = (
                    not isinstance(lease, Mapping)
                    or tuple(lease.get("path_globs") or []) != requested_globs
                    or lease.get("mode") != mode
                    or existing.get("canonical") is not canonical
                    or existing.get("approval_worker_owner") is not (canonical or mode == "write")
                    or existing.get("risk_level", "R1") != risk_level
                    or existing.get("source_fingerprint") != source_tree_fingerprint(root)
                    or any(
                        int(existing.get("ports", {}).get(key, -1)) != int(value)
                        for key, value in (requested_ports or {}).items()
                    )
                )
                if mismatch:
                    raise CompareAndSwapConflict(
                        "active allocation request differs in paths, ports, mode, canonical flag, risk, or source fingerprint; release/renew with CAS"
                    )
                approval_secret = ensure_approval_hmac_secret(root)
                identity_secret = ensure_identity_jwt_secret(root)
                compatibility_token = ensure_compatibility_token(root)
                return {
                    "schema_version": SCHEMA_VERSION,
                    "generation": generation,
                    "created": False,
                    "lease": lease,
                    "allocation": existing,
                    "environment": {
                        **allocation_environment(existing, worktree=root),
                        "OMNI_RUNTIME_STATE_DIR": str(store_dir).replace("\\", "/"),
                        "OMNI_RUNTIME_ALLOCATION_SOURCE": str(state_path).replace("\\", "/"),
                        "OMNI_RUNTIME_ALLOCATION_FILE": "/runtime-state/allocations.json",
                        "OMNI_APPROVAL_HMAC_SECRET_FILE": str(approval_secret).replace("\\", "/"),
                        "OMNI_IDENTITY_JWT_SECRET_FILE": str(identity_secret).replace("\\", "/"),
                        "OMNI_COMPATIBILITY_TOKEN_FILE": str(compatibility_token).replace("\\", "/"),
                    },
                    "state_path": "git-common-dir/omni-runtime/allocations.json"
                    if state_dir is None
                    else str(state_path),
                }
        lease, allocation = _build_records(
            root,
            state,
            change_id=change_id,
            owner=owner,
            path_globs=path_globs,
            mode=mode,
            ttl_seconds=ttl_seconds,
            canonical=canonical,
            requested_ports=requested_ports or {},
            risk_level=risk_level,
            now=moment,
        )
        conflicts = _conflicts(state, lease, allocation)
        if conflicts:
            raise AllocationConflict(conflicts)
        approval_secret = default_approval_secret_path(root) if dry_run else ensure_approval_hmac_secret(root)
        identity_secret = default_identity_jwt_secret_path(root) if dry_run else ensure_identity_jwt_secret(root)
        compatibility_token = default_compatibility_token_path(root) if dry_run else ensure_compatibility_token(root)
        new_generation = generation + 1
        if not dry_run:
            state["leases"].append(lease.to_dict())
            state["allocations"].append(allocation.to_dict())
            state["generation"] = new_generation
            _write_state(state_path, state)
        return {
            "schema_version": SCHEMA_VERSION,
            "generation": new_generation if not dry_run else generation,
            "created": not dry_run,
            "dry_run": dry_run,
            "lease": lease.to_dict(),
            "allocation": allocation.to_dict(),
            "environment": {
                **allocation_environment(allocation.to_dict(), worktree=root),
                "OMNI_RUNTIME_STATE_DIR": str(store_dir).replace("\\", "/"),
                "OMNI_RUNTIME_ALLOCATION_SOURCE": str(state_path).replace("\\", "/"),
                "OMNI_RUNTIME_ALLOCATION_FILE": "/runtime-state/allocations.json",
                "OMNI_APPROVAL_HMAC_SECRET_FILE": str(approval_secret).replace("\\", "/"),
                "OMNI_IDENTITY_JWT_SECRET_FILE": str(identity_secret).replace("\\", "/"),
                "OMNI_COMPATIBILITY_TOKEN_FILE": str(compatibility_token).replace("\\", "/"),
            },
            "state_path": "git-common-dir/omni-runtime/allocations.json" if state_dir is None else str(state_path),
        }


def list_state(root: Path, *, state_dir: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    root = repository_root(root)
    store_dir = (state_dir or default_state_dir(root)).resolve()
    state_path = store_dir / "allocations.json"
    lock_path = store_dir / "allocations.lock"
    with _file_lock(lock_path):
        state = _read_state(state_path)
        _mark_stale(state, now or utc_now())
    # Do not persist automatic stale transitions: expiry is derived evidence and
    # cleanup/reclamation still requires an explicit owner action.
    return state


def _glob_matches_path(path: str, pattern: str) -> bool:
    pattern = normalize_glob(pattern)
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
    return re.fullmatch("".join(pieces), normalize_glob(path)) is not None


def resolve_path_conflict(
    root: Path,
    path: str,
    change_id: str,
    read_only: bool = True,
    state_dir: Path | None = None,
) -> dict[str, Any]:
    """Return lease ownership for a Hook without mutating or reclaiming state."""

    root = repository_root(root)
    state_path = ((state_dir or default_state_dir(root)).resolve()) / "allocations.json"
    empty = {
        "known": False,
        "conflict": False,
        "owner": None,
        "change_id": None,
        "expires_at": None,
        "stale": False,
    }
    if not state_path.is_file():
        return empty
    state = _read_state(state_path)
    moment = utc_now()
    matches: list[dict[str, Any]] = []
    for lease in state.get("leases", []):
        if lease.get("state") not in {"active", "stale"}:
            continue
        if not any(_glob_matches_path(path, str(pattern)) for pattern in lease.get("path_globs") or []):
            continue
        item = dict(lease)
        item["derived_stale"] = lease.get("state") == "stale" or parse_time(str(lease.get("expires_at"))) <= moment
        matches.append(item)
    if not matches:
        return {**empty, "known": True}
    matches.sort(
        key=lambda item: (bool(item["derived_stale"]), str(item.get("expires_at"))),
        reverse=False,
    )
    other = next((item for item in matches if item.get("change_id") != change_id), None)
    selected = other or matches[0]
    stale = bool(selected["derived_stale"])
    # Expired leases remain visible for audit but are not an eternal lock. Reads
    # are non-mutating and therefore do not conflict with either lease mode.
    conflict = bool(other is not None and not read_only and not stale and selected.get("state") == "active")
    return {
        "known": True,
        "conflict": conflict,
        "owner": selected.get("owner"),
        "change_id": selected.get("change_id"),
        "expires_at": selected.get("expires_at"),
        "stale": stale,
    }


def release(
    root: Path,
    allocation_id: str,
    *,
    owner: str,
    expected_revision: int,
    state_dir: Path | None = None,
) -> dict[str, Any]:
    root = repository_root(root)
    store_dir = (state_dir or default_state_dir(root)).resolve()
    state_path = store_dir / "allocations.json"
    lock_path = store_dir / "allocations.lock"
    with _file_lock(lock_path):
        state = _read_state(state_path)
        allocation = next(
            (item for item in state["allocations"] if item.get("allocation_id") == allocation_id),
            None,
        )
        if allocation is None:
            raise AllocationError(f"allocation not found: {allocation_id}")
        if allocation.get("owner") != owner:
            raise AllocationError("only the allocation owner may release it")
        if int(allocation.get("revision", 0)) != expected_revision:
            raise CompareAndSwapConflict(
                f"allocation revision changed: expected {expected_revision}, found {allocation.get('revision')}"
            )
        if allocation.get("state") == "released":
            return allocation
        allocation["state"] = "released"
        allocation["revision"] = expected_revision + 1
        allocation["released_at"] = isoformat(utc_now())
        for lease in state["leases"]:
            if lease.get("lease_id") == allocation.get("lease_id"):
                lease["state"] = "released"
                lease["revision"] = int(lease.get("revision", 0)) + 1
                lease["released_at"] = allocation["released_at"]
        state["generation"] = int(state.get("generation", 0)) + 1
        _write_state(state_path, state)
        return allocation


def _parse_ports(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        if "=" not in value:
            raise AllocationError(f"port must use service=host_port: {value!r}")
        service, raw = value.split("=", 1)
        try:
            port = int(raw)
        except ValueError as exc:
            raise AllocationError(f"port is not an integer: {value!r}") from exc
        if not service or not 1 <= port <= 65535:
            raise AllocationError(f"invalid port allocation: {value!r}")
        result[service] = port
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--state-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    acquire_parser = sub.add_parser("acquire")
    acquire_parser.add_argument("--change-id", required=True)
    acquire_parser.add_argument("--owner", required=True)
    acquire_parser.add_argument("--path", action="append", default=[])
    acquire_parser.add_argument("--mode", choices=("read", "write"), default="write")
    acquire_parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    acquire_parser.add_argument("--canonical", action="store_true")
    acquire_parser.add_argument("--port", action="append", default=[])
    acquire_parser.add_argument("--risk-level", choices=("R0", "R1", "R2", "R3"), default="R1")
    acquire_parser.add_argument("--expected-generation", type=int)
    acquire_parser.add_argument("--dry-run", action="store_true")
    acquire_parser.add_argument("--json", action="store_true")
    list_parser = sub.add_parser("list")
    list_parser.add_argument("--json", action="store_true")
    release_parser = sub.add_parser("release")
    release_parser.add_argument("--allocation-id", required=True)
    release_parser.add_argument("--owner", required=True)
    release_parser.add_argument("--expected-revision", type=int, required=True)
    release_parser.add_argument("--json", action="store_true")
    return parser


def _emit(payload: Mapping[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        allocation = payload.get("allocation", payload)
        print(
            f"runtime_id={allocation.get('runtime_id')} allocation_id={allocation.get('allocation_id')} state={allocation.get('state')}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "acquire":
            payload = acquire(
                args.root,
                change_id=args.change_id,
                owner=args.owner,
                path_globs=args.path,
                mode=args.mode,
                ttl_seconds=args.ttl_seconds,
                canonical=args.canonical,
                requested_ports=_parse_ports(args.port),
                risk_level=args.risk_level,
                state_dir=args.state_dir,
                expected_generation=args.expected_generation,
                dry_run=args.dry_run,
            )
            _emit(payload, args.json)
            return 0
        if args.command == "list":
            payload = list_state(args.root, state_dir=args.state_dir)
            _emit(payload, args.json)
            return 0
        payload = release(
            args.root,
            args.allocation_id,
            owner=args.owner,
            expected_revision=args.expected_revision,
            state_dir=args.state_dir,
        )
        _emit(payload, args.json)
        return 0
    except AllocationConflict as exc:
        print(
            json.dumps(
                {"status": "conflict", "conflicts": list(exc.conflicts)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    except (AllocationError, ValueError) as exc:
        print(f"[runtime-allocation] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
