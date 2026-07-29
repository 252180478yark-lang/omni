"""Runtime-accessible P0 baseline preflight.

The CLI preflight is useful in CI, but the owner needs the same reproducible
manifest inside ``/sku-pipeline`` before an order may be created.  This module
is read-only: a missing source mount is a blocked gate, never an excuse to
invent a baseline from the live database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import settings
from app.services.migration_baseline import (
    build_baseline_report,
    git_candidate_migration_sources,
    git_snapshot,
    p0_adopted_unledgered_migrations,
    p0_excluded_repository_migrations,
    p0_frozen_runtime_migrations,
    read_runtime_migration_entries,
    resolve_p0_repository_root,
    repository_migrations,
    versioned_capability_manifest,
)


async def run_video_production_preflight() -> dict[str, Any]:
    """Return the immutable-ready baseline manifest or a fail-closed error."""

    root = resolve_p0_repository_root(Path(__file__))
    if root is None:
        return {
            "ok": False,
            "status": "blocked",
            "error": "baseline_source_unavailable",
            "blockers": [
                {
                    "code": "p0_repository_root_unavailable",
                    "detail": "mount the checkout read-only and set P0_REPOSITORY_ROOT",
                }
            ],
        }
    try:
        runtime_entries, has_checksums = await read_runtime_migration_entries(settings.database_url)
        excluded = p0_excluded_repository_migrations(root)
        repo_entries = [
            item for item in repository_migrations(root) if item["filename"] not in excluded
        ]
        # Git history is only evidence for rows that exist in the runtime
        # ledger but not in the canonical repository ledger.  Asking Git to
        # search every healthy migration turns this read-only preflight into
        # dozens of expensive full-worktree operations on the owner's large
        # checkout, without contributing to the decision.
        repo_filenames = {str(item["filename"]) for item in repo_entries}
        frozen_runtime_filenames = p0_frozen_runtime_migrations(root) | excluded
        runtime_only_candidates = (
            str(item["filename"])
            for item in runtime_entries
            if str(item["filename"]) not in repo_filenames
            and str(item["filename"]) not in frozen_runtime_filenames
        )
        report = build_baseline_report(
            repo_migration_entries=repo_entries,
            runtime_migration_entries=runtime_entries,
            tracking_has_checksums=has_checksums,
            git=git_snapshot(
                root,
                pathspecs=(
                    "migrations",
                    "services/knowledge-engine/config/prompts",
                    "services/knowledge-engine/config/tool_models.yaml",
                    "services/knowledge-engine/config/video_intent_profiles.yaml",
                ),
            ),
            capability_manifest=versioned_capability_manifest(root),
            candidate_sources=git_candidate_migration_sources(root, runtime_only_candidates),
            frozen_runtime_filenames=frozen_runtime_filenames,
            adopted_unledgered_filenames=p0_adopted_unledgered_migrations(root),
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "blocked",
            "error": "baseline_preflight_failed",
            "blockers": [{"code": "baseline_preflight_failed", "detail": str(exc)[:500]}],
        }
    return {
        "ok": report["status"] == "ready",
        "status": report["status"],
        "baseline_manifest": report,
        "source_root": str(root),
        "blockers": report["blockers"],
    }


__all__ = ["run_video_production_preflight"]
