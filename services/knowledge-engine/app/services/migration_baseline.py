"""Reproducible migration-baseline preflight for the P0 production gate.

This module deliberately reports a blocked baseline rather than attempting to
repair schema drift.  A production migration can only be added after the
repository ledger, the runtime ledger, and their checksums have a single,
auditable interpretation.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


BASELINE_SCHEMA_VERSION = "p0.baseline.v1"
_MIGRATION_PREFIX_LENGTH = 3
_P0_TRACK_MANIFEST = "migrations/p0_track_manifest.json"
_VERSIONED_PATHS = (
    "services/knowledge-engine/config/prompts",
    "services/knowledge-engine/config/tool_models.yaml",
    "services/knowledge-engine/config/video_intent_profiles.yaml",
)


def resolve_p0_repository_root(anchor: Path | None = None) -> Path | None:
    """Find the one checkout whose migration sources are authoritative.

    The owner-facing service receives a read-only ``/workspace`` mount in
    Compose, while CLI callers normally run from the checkout.  Both must
    resolve the same canonical tree instead of inferring one from ``/app``.
    """

    candidates: list[Path] = []
    configured = os.getenv("P0_REPOSITORY_ROOT", "").strip()
    if configured:
        candidates.append(Path(configured))
    candidates.append(Path("/workspace"))
    if anchor is not None:
        try:
            resolved_anchor = anchor.resolve()
        except OSError:
            resolved_anchor = anchor
        candidates.extend(resolved_anchor.parents)

    for root in candidates:
        if (root / "migrations").is_dir() and (
            root / "services" / "knowledge-engine" / "config"
        ).is_dir():
            return root
    return None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _migration_prefix(filename: str) -> str | None:
    prefix = filename.split("_", 1)[0]
    if len(prefix) == _MIGRATION_PREFIX_LENGTH and prefix.isdigit():
        return prefix
    return None


def repository_migrations(repo_root: Path) -> list[dict[str, str]]:
    """Return the committed migration ledger in execution order."""

    migrations_dir = repo_root / "migrations"
    return [
        {"filename": path.name, "sha256": _sha256_file(path)}
        for path in sorted(migrations_dir.glob("*.sql"))
        if path.is_file()
    ]


def _p0_track_manifest(repo_root: Path) -> Mapping[str, Any]:
    """Return legacy migration rows explicitly frozen outside the P0 scope.

    The manifest is an acknowledgement boundary, not an instruction to import
    or execute those branches.  Unknown runtime rows remain fail-closed.
    """

    path = repo_root / _P0_TRACK_MANIFEST
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"p0_track_manifest_invalid: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("p0_track_manifest_invalid: root")
    return payload


def p0_frozen_runtime_migrations(repo_root: Path) -> set[str]:
    """Return legacy migration rows explicitly frozen outside the P0 scope."""

    payload = _p0_track_manifest(repo_root)
    tracks = payload.get("frozen_tracks")
    if not isinstance(tracks, Mapping):
        raise ValueError("p0_track_manifest_invalid: frozen_tracks")
    filenames: set[str] = set()
    for track, metadata in tracks.items():
        if not isinstance(track, str) or not isinstance(metadata, Mapping):
            raise ValueError("p0_track_manifest_invalid: track")
        entries = metadata.get("runtime_migrations")
        if not isinstance(entries, list) or not all(
            isinstance(entry, str) and entry.endswith(".sql") for entry in entries
        ):
            raise ValueError(f"p0_track_manifest_invalid: {track}")
        filenames.update(entries)
    return filenames


def p0_adopted_unledgered_migrations(repo_root: Path) -> set[str]:
    """Return active migrations whose old ledger rows must be evidence-adopted."""

    payload = _p0_track_manifest(repo_root)
    entries = payload.get("adopted_unledgered_active_migrations", [])
    if not isinstance(entries, list) or not all(
        isinstance(entry, str) and entry.endswith(".sql") for entry in entries
    ):
        raise ValueError("p0_track_manifest_invalid: adopted_unledgered_active_migrations")
    return set(entries)


def p0_excluded_repository_migrations(repo_root: Path) -> set[str]:
    """Return repository migrations deliberately outside the P0 gate."""

    payload = _p0_track_manifest(repo_root)
    entries = payload.get("excluded_repository_migrations", [])
    if not isinstance(entries, list) or not all(
        isinstance(entry, str) and entry.endswith(".sql") for entry in entries
    ):
        raise ValueError("p0_track_manifest_invalid: excluded_repository_migrations")
    return set(entries)


def versioned_capability_manifest(repo_root: Path) -> list[dict[str, str]]:
    """Hash prompt/model/capability inputs without reading any secret config."""

    entries: list[dict[str, str]] = []
    for relative in _VERSIONED_PATHS:
        target = repo_root / relative
        files = sorted(target.rglob("*")) if target.is_dir() else [target]
        for path in files:
            if path.is_file():
                entries.append(
                    {
                        "path": path.relative_to(repo_root).as_posix(),
                        "sha256": _sha256_file(path),
                    }
                )
    return entries


def git_snapshot(
    repo_root: Path, *, pathspecs: Iterable[str] | None = None
) -> dict[str, Any]:
    """Capture the relevant checkout identity without mutating the worktree.

    A P0 baseline is determined by migrations and versioned capability inputs,
    not by unrelated applications in this large monorepo.  Restricting the
    dirty check to those paths both documents that boundary and keeps the
    owner-facing preflight responsive.
    """

    def _run(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_root), *args],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except OSError:
            return "unknown"
        return result.stdout.strip() if result.returncode == 0 else "unknown"

    scoped_paths = tuple(str(path) for path in (pathspecs or ()))
    status_args = ["status", "--porcelain=v1", "--untracked-files=all"]
    if scoped_paths:
        status_args.extend(("--", *scoped_paths))
    status = _run(*status_args)
    dirty_paths = [line for line in status.splitlines() if line] if status != "unknown" else []
    return {
        "commit": _run("rev-parse", "HEAD"),
        "branch": _run("branch", "--show-current"),
        "dirty": status != "unknown" and bool(status),
        "dirty_paths": dirty_paths,
        "untracked_paths": [line[3:] for line in dirty_paths if line.startswith("?? ")],
        "scope_paths": list(scoped_paths),
    }


def git_candidate_migration_sources(
    repo_root: Path, filenames: Iterable[str]
) -> dict[str, str]:
    """Find recoverable Git evidence without treating another branch as canonical."""

    candidates: dict[str, str] = {}
    for filename in sorted(set(filenames)):
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "log",
                    "--all",
                    "--format=%H",
                    "--",
                    f"migrations/{filename}",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except OSError:
            continue
        if result.returncode == 0 and result.stdout.strip():
            candidates[filename] = result.stdout.splitlines()[0]
    return candidates


def build_baseline_report(
    *,
    repo_migration_entries: Iterable[Mapping[str, Any]],
    runtime_migration_entries: Iterable[Mapping[str, Any]],
    tracking_has_checksums: bool,
    git: Mapping[str, Any] | None = None,
    capability_manifest: Iterable[Mapping[str, Any]] = (),
    candidate_sources: Mapping[str, str] | None = None,
    frozen_runtime_filenames: Iterable[str] = (),
    adopted_unledgered_filenames: Iterable[str] = (),
) -> dict[str, Any]:
    """Compare ledgers and return a fail-closed P0 gate decision.

    ``runtime_migration_entries`` should contain the exact rows read from
    ``public.schema_migrations``.  Only a canonical migration map may turn a
    missing source file or duplicated numeric prefix into a passing result.
    """

    repo = [dict(item) for item in repo_migration_entries]
    runtime = [dict(item) for item in runtime_migration_entries]
    repo_names = {str(item["filename"]) for item in repo}
    runtime_names = {str(item["filename"]) for item in runtime}
    frozen = {str(item) for item in frozen_runtime_filenames}
    adopted_unledgered = {str(item) for item in adopted_unledgered_filenames}
    frozen_present = sorted(runtime_names & frozen)
    active_runtime_names = runtime_names - frozen

    runtime_by_prefix: dict[str, list[str]] = defaultdict(list)
    repo_by_prefix: dict[str, list[str]] = defaultdict(list)
    for item in runtime:
        filename = str(item["filename"])
        if filename in frozen:
            continue
        prefix = _migration_prefix(filename)
        if prefix:
            runtime_by_prefix[prefix].append(filename)
    for item in repo:
        filename = str(item["filename"])
        prefix = _migration_prefix(filename)
        if prefix:
            repo_by_prefix[prefix].append(filename)

    runtime_duplicate_prefixes = {
        prefix: sorted(names)
        for prefix, names in runtime_by_prefix.items()
        if len(names) > 1
    }
    repo_duplicate_prefixes = {
        prefix: sorted(names)
        for prefix, names in repo_by_prefix.items()
        if len(names) > 1
    }
    runtime_only = sorted(active_runtime_names - repo_names)
    adopted_missing = sorted(adopted_unledgered - active_runtime_names)
    repo_not_recorded = sorted(
        repo_names - active_runtime_names - adopted_unledgered
    )

    blockers: list[dict[str, Any]] = []
    if runtime_duplicate_prefixes:
        blockers.append(
            {
                "code": "runtime_duplicate_numeric_prefix",
                "detail": runtime_duplicate_prefixes,
            }
        )
    if repo_duplicate_prefixes:
        blockers.append(
            {
                "code": "repository_duplicate_numeric_prefix",
                "detail": repo_duplicate_prefixes,
            }
        )
    if runtime_only:
        blockers.append(
            {
                "code": "runtime_migration_missing_from_repository",
                "detail": runtime_only,
            }
        )
    if repo_not_recorded:
        blockers.append(
            {
                "code": "repository_migration_missing_from_runtime_ledger",
                "detail": repo_not_recorded,
            }
        )
    if adopted_missing:
        blockers.append(
            {
                "code": "active_migration_ledger_adoption_required",
                "detail": adopted_missing,
            }
        )
    if not tracking_has_checksums:
        blockers.append(
            {
                "code": "runtime_migration_checksums_unavailable",
                "detail": "public.schema_migrations has no canonical checksum ledger",
            }
        )

    # Unit callers from the pre-checksum era omit this key entirely.  The live
    # reader always supplies it once the checksum column exists, including None
    # for an unreconciled historical row.
    if tracking_has_checksums and any("checksum" in item for item in runtime):
        expected = {str(item["filename"]): str(item["sha256"]) for item in repo}
        runtime_checksums = {
            str(item["filename"]): item.get("checksum") for item in runtime
        }
        checksum_missing = sorted(
            filename
            for filename in active_runtime_names & repo_names
            if not isinstance(runtime_checksums.get(filename), str)
            or not str(runtime_checksums[filename]).strip()
        )
        checksum_mismatch = sorted(
            filename
            for filename in active_runtime_names & repo_names
            if isinstance(runtime_checksums.get(filename), str)
            and str(runtime_checksums[filename]).strip()
            and str(runtime_checksums[filename]) != expected[filename]
        )
        if checksum_missing:
            blockers.append(
                {"code": "active_migration_checksums_unreconciled", "detail": checksum_missing}
            )
        if checksum_mismatch:
            blockers.append(
                {"code": "active_migration_checksum_mismatch", "detail": checksum_mismatch}
            )

    git_snapshot_data = dict(git or {})
    untracked_paths = [str(path) for path in git_snapshot_data.get("untracked_paths", [])]
    if untracked_paths:
        blockers.append(
            {
                "code": "canonical_source_untracked",
                "detail": untracked_paths,
            }
        )

    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if not blockers else "blocked",
        "production_entity_changes_allowed": not blockers,
        "git": git_snapshot_data,
        "repository": {
            "count": len(repo),
            "head": repo[-1] if repo else None,
            "migrations": repo,
        },
        "runtime": {
            "count": len(runtime),
            "head": runtime[-1] if runtime else None,
            "migrations": runtime,
            "tracking_has_checksums": tracking_has_checksums,
        },
        "capability_manifest": [dict(item) for item in capability_manifest],
        "reconciliation": {
            "runtime_only": runtime_only,
            "repository_not_recorded": repo_not_recorded,
            "runtime_duplicate_prefixes": runtime_duplicate_prefixes,
            "repository_duplicate_prefixes": repo_duplicate_prefixes,
            "runtime_only_candidate_sources": {
                filename: commit
                for filename, commit in dict(candidate_sources or {}).items()
                if filename in runtime_only
            },
            "frozen_runtime_migrations": frozen_present,
            "adopted_unledgered_migrations": sorted(adopted_unledgered),
        },
        "blockers": blockers,
        "next_step": (
            "Create and verify a canonical migration mapping before adding any "
            "new production entities."
            if blockers
            else "Run clean/existing database verification and the P0 contract suite."
        ),
    }


async def read_runtime_migration_entries(database_url: str) -> tuple[list[dict[str, Any]], bool]:
    """Read the runtime ledger using the project's async PostgreSQL client."""

    import asyncpg

    # Docker supplies the SQLAlchemy spelling while asyncpg itself accepts the
    # plain PostgreSQL URL.  Keeping this normalization here lets the runtime
    # P0 preflight use the same DB setting as the application pool.
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(dsn)
    try:
        columns = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'schema_migrations'
            """
        )
        names = {str(row["column_name"]) for row in columns}
        selected_columns = "filename, applied_at" + (", checksum" if "checksum" in names else "")
        rows = await conn.fetch(
            f"SELECT {selected_columns} FROM public.schema_migrations ORDER BY filename"
        )
        return (
            [
                {
                    "filename": str(row["filename"]),
                    "applied_at": row["applied_at"].isoformat()
                    if row["applied_at"] is not None
                    else None,
                    **({"checksum": row["checksum"]} if "checksum" in names else {}),
                }
                for row in rows
            ],
            "checksum" in names,
        )
    finally:
        await conn.close()
