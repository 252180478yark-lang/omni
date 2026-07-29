#!/usr/bin/env python3
"""Read-only P0 migration-baseline preflight.

The command emits JSON and exits non-zero while the P0 baseline is blocked.
It never applies migrations, creates schemas, or exposes the database URL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.services.migration_baseline import (  # noqa: E402
    build_baseline_report,
    git_candidate_migration_sources,
    git_snapshot,
    read_runtime_migration_entries,
    p0_frozen_runtime_migrations,
    p0_adopted_unledgered_migrations,
    p0_excluded_repository_migrations,
    repository_migrations,
    resolve_p0_repository_root,
    versioned_capability_manifest,
)

ROOT = resolve_p0_repository_root(Path(__file__))


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="runtime database URL; defaults to DATABASE_URL",
    )
    args = parser.parse_args()
    if ROOT is None:
        print(json.dumps({"status": "blocked", "blockers": ["p0_repository_root_unavailable"]}))
        return 2
    if not args.database_url:
        print(json.dumps({"status": "blocked", "blockers": ["database_url_missing"]}))
        return 2

    runtime_entries, has_checksums = await read_runtime_migration_entries(args.database_url)
    excluded = p0_excluded_repository_migrations(ROOT)
    repo_entries = [
        item for item in repository_migrations(ROOT) if item["filename"] not in excluded
    ]
    repo_filenames = {str(item["filename"]) for item in repo_entries}
    frozen_runtime_filenames = p0_frozen_runtime_migrations(ROOT) | excluded
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
            ROOT,
            pathspecs=(
                "migrations",
                "services/knowledge-engine/config/prompts",
                "services/knowledge-engine/config/tool_models.yaml",
                "services/knowledge-engine/config/video_intent_profiles.yaml",
            ),
        ),
        capability_manifest=versioned_capability_manifest(ROOT),
        candidate_sources=git_candidate_migration_sources(ROOT, runtime_only_candidates),
        frozen_runtime_filenames=frozen_runtime_filenames,
        adopted_unledgered_filenames=p0_adopted_unledgered_migrations(ROOT),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ready" else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
