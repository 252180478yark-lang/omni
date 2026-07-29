#!/usr/bin/env python3
"""Backfill verified checksums for the active P0 migration track.

This command never applies SQL migrations and never changes frozen historical
tracks.  It only fills a NULL checksum after the filename resolves to the exact
canonical repository source.  A non-NULL mismatch is fail-closed.
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
    p0_adopted_unledgered_migrations,
    p0_excluded_repository_migrations,
    p0_frozen_runtime_migrations,
    read_runtime_migration_entries,
    repository_migrations,
    resolve_p0_repository_root,
)

ROOT = resolve_p0_repository_root(Path(__file__))


_ADOPTION_PROBES = {
    "051_pipeline_prompt_nodes.sql": """
        SELECT count(*) = 5
        FROM knowledge.prompt_nodes
        WHERE id = ANY($1::text[])
          AND EXISTS (
              SELECT 1 FROM information_schema.columns
              WHERE table_schema='knowledge' AND table_name='prompt_rules'
                AND column_name='source_tool_call_id'
          )
    """,
    "052_experiment_lab.sql": """
        SELECT to_regclass('pipeline.experiments') IS NOT NULL
           AND to_regclass('pipeline.experiment_rounds') IS NOT NULL
           AND to_regclass('pipeline.experiment_arms') IS NOT NULL
           AND to_regclass('pipeline.v_experiment_round_results') IS NOT NULL
    """,
    "053_experiment_ai_track.sql": """
        SELECT count(*) = 3 FROM information_schema.columns
        WHERE (table_schema,table_name,column_name) IN (
            ('pipeline','experiments','track'),
            ('pipeline','experiment_arms','production_mode'),
            ('pipeline','assets','visual_prescreen')
        )
    """,
    "054_experiment_view_production_mode.sql": """
        SELECT to_regclass('pipeline.v_experiment_round_results') IS NOT NULL
    """,
    "058_message_feedback_to_rules.sql": """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='knowledge' AND table_name='prompt_rules'
              AND column_name='source_message_feedback_id'
        )
    """,
    "064_experiment_exposure_in_view.sql": """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='pipeline' AND table_name='v_experiment_round_results'
              AND column_name='impressions_sum'
        )
    """,
    "065_content_version_changelog.sql": """
        SELECT to_regclass('pipeline.v_content_version_changelog') IS NOT NULL
    """,
    "066_match_vectors.sql": """
        SELECT to_regclass('pipeline.audience_vectors') IS NOT NULL
           AND to_regclass('pipeline.content_vectors') IS NOT NULL
    """,
}


async def _probe_adopted_migration(connection, filename: str) -> bool:
    sql = _ADOPTION_PROBES.get(filename)
    if not sql:
        return False
    if filename == "051_pipeline_prompt_nodes.sql":
        return bool(
            await connection.fetchval(
                sql,
                [
                    "pipeline.selling_points_matrix",
                    "pipeline.audience_match",
                    "pipeline.audience_portrait",
                    "pipeline.director_brief",
                    "pipeline.creative_pack",
                ],
            )
        )
    return bool(await connection.fetchval(sql))


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    args = parser.parse_args()
    if ROOT is None:
        print(json.dumps({"status": "blocked", "blockers": ["p0_repository_root_unavailable"]}))
        return 2
    if not args.database_url:
        print(json.dumps({"status": "blocked", "blockers": ["database_url_missing"]}))
        return 2

    runtime, has_checksums = await read_runtime_migration_entries(args.database_url)
    if not has_checksums:
        print(json.dumps({"status": "blocked", "blockers": ["checksum_column_missing"]}))
        return 3
    frozen = p0_frozen_runtime_migrations(ROOT) | p0_excluded_repository_migrations(ROOT)
    adopted_unledgered = p0_adopted_unledgered_migrations(ROOT)
    excluded = p0_excluded_repository_migrations(ROOT)
    sources = {
        item["filename"]: item["sha256"]
        for item in repository_migrations(ROOT)
        if item["filename"] not in excluded
    }
    active_runtime = [item for item in runtime if item["filename"] not in frozen]
    runtime_names = {item["filename"] for item in active_runtime}
    unknown = sorted(runtime_names - set(sources))
    missing = sorted(set(sources) - runtime_names - adopted_unledgered)
    mismatched = sorted(
        item["filename"]
        for item in active_runtime
        if item.get("checksum") and item["checksum"] != sources[item["filename"]]
    )
    if unknown or missing or mismatched:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "unknown_active_runtime": unknown,
                    "missing_active_runtime": missing,
                    "checksum_mismatch": mismatched,
                },
                ensure_ascii=False,
            )
        )
        return 3

    import asyncpg

    connection = await asyncpg.connect(args.database_url)
    try:
        async with connection.transaction():
            updated = []
            adopted = []
            for filename in sorted(adopted_unledgered - runtime_names):
                if not await _probe_adopted_migration(connection, filename):
                    raise RuntimeError(f"adoption_schema_probe_failed:{filename}")
                await connection.execute(
                    """
                    INSERT INTO public.schema_migrations(filename, checksum)
                    VALUES($1,$2)
                    ON CONFLICT (filename) DO NOTHING
                    """,
                    filename,
                    sources[filename],
                )
                adopted.append(filename)
            for item in active_runtime:
                filename = item["filename"]
                if item.get("checksum"):
                    continue
                result = await connection.execute(
                    """
                    UPDATE public.schema_migrations
                    SET checksum=$2
                    WHERE filename=$1 AND checksum IS NULL
                    """,
                    filename,
                    sources[filename],
                )
                if result.endswith("1"):
                    updated.append(filename)
        print(
            json.dumps(
                {
                    "status": "ready",
                    "updated": updated,
                    "adopted": adopted,
                    "frozen_runtime_migrations": sorted(
                        item["filename"] for item in runtime if item["filename"] in frozen
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        await connection.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
