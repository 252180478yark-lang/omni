#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply all SQL files under migrations/ in lexical order, idempotent.

Usage:
    python scripts/apply_migrations.py
    python scripts/apply_migrations.py --dry-run
    python scripts/apply_migrations.py --only 004,005

Reads connection from env DATABASE_URL or defaults to dev compose:
    postgresql://omni_user:changeme_in_production@localhost:5432/omni_vibe_db

Tracking table:
    public.schema_migrations(filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ)
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
from pathlib import Path

# Force stdout to UTF-8 so we don't trip Windows GBK codepage on ✓/✗ chars.
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)
except Exception:
    pass

import psycopg2  # type: ignore[import-not-found]
from psycopg2 import errors

DEFAULT_DSN = (
    "postgresql://omni_user:changeme_in_production@localhost:5432/omni_vibe_db"
)
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def load_dsn() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DSN)


def ensure_tracking(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS public.schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            checksum TEXT
        )
        """
    )


def tracking_has_checksums(cur) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='schema_migrations'
              AND column_name='checksum'
        )
        """
    )
    return bool(cur.fetchone()[0])


def ensure_database_prerequisites(cur) -> None:
    """Install extensions required before the first historical migration.

    Migration 001 already uses ``uuid_generate_v4`` and later migrations use
    ``gen_random_uuid``.  Relying on an image-init side effect made a clean,
    reproducible database impossible from this runner.
    """

    cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def list_migrations(only: list[str] | None) -> list[Path]:
    if not MIGRATIONS_DIR.exists():
        print(f"[!] migrations dir not found: {MIGRATIONS_DIR}", file=sys.stderr)
        return []
    files = sorted(p for p in MIGRATIONS_DIR.glob("*.sql") if p.is_file())
    if only:
        wanted = set(only)
        files = [f for f in files if any(f.name.startswith(prefix) for prefix in wanted)]
    return files


def applied_set(cur) -> set[str]:
    cur.execute("SELECT filename FROM public.schema_migrations")
    return {r[0] for r in cur.fetchall()}


def apply_one(conn, path: Path, *, dry_run: bool) -> bool:
    sql = path.read_text(encoding="utf-8")
    if not sql.strip():
        return False
    if dry_run:
        print(f"   (dry-run) would execute {path.name} ({len(sql)} bytes)")
        return False
    cur = conn.cursor()
    try:
        cur.execute(sql)
        if tracking_has_checksums(cur):
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            cur.execute(
                """
                INSERT INTO public.schema_migrations(filename, checksum) VALUES (%s, %s)
                ON CONFLICT (filename) DO UPDATE
                SET checksum=COALESCE(public.schema_migrations.checksum, EXCLUDED.checksum)
                """,
                (path.name, checksum),
            )
        else:
            cur.execute(
                "INSERT INTO public.schema_migrations(filename) VALUES (%s) "
                "ON CONFLICT (filename) DO NOTHING",
                (path.name,),
            )
        conn.commit()
        return True
    except errors.Error as exc:
        conn.rollback()
        print(f"[FAIL] {path.name}: {exc}", file=sys.stderr)
        raise
    finally:
        cur.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--only",
        type=str,
        default="",
        help="comma-separated filename prefixes (e.g. 004,005)",
    )
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="忽略已应用记录，强制再跑一次（仍是幂等 SQL，自担风险）",
    )
    args = parser.parse_args()

    dsn = load_dsn()
    only = [s.strip() for s in args.only.split(",") if s.strip()] or None
    files = list_migrations(only)
    if not files:
        print("[i] no migrations to apply.")
        return 0

    print(f"[i] connecting to {dsn.split('@')[-1]}")
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor()
        ensure_database_prerequisites(cur)
        ensure_tracking(cur)
        conn.commit()
        already = applied_set(cur)
        cur.close()

        pending = [f for f in files if args.rerun or f.name not in already]
        if not pending:
            print(f"[OK] all {len(files)} migrations already applied.")
            return 0

        print(f"[i] {len(pending)} pending migration(s):")
        for p in pending:
            print(f"     - {p.name}")

        for p in pending:
            print(f"[..] applying {p.name}")
            applied = apply_one(conn, p, dry_run=args.dry_run)
            if applied:
                print(f"[OK] {p.name} applied")
            elif args.dry_run:
                pass
            else:
                print(f"[ ] {p.name} skipped (empty)")

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
