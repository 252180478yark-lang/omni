#!/usr/bin/env python3
"""Canonical checksum-verifying Omni migration runner.

Every dev, Compose and CI entry point calls this file. ``--dry-run --verify``
validates repository SQL without importing a database driver or connecting.
Actual SQL execution is fail-closed unless the target is marked disposable or
an explicit shared-database R3 approval is supplied via environment.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "migrations"
RUNNER_VERSION = "omni-migration-runner-v2"
FILENAME_RE = re.compile(r"^(?P<prefix>\d{3})_[a-z0-9][a-z0-9_]*\.sql$")
TRUE_VALUES = {"1", "true", "yes", "on"}


class MigrationError(RuntimeError):
    """A safe, deterministic migration failure."""


class RepositoryDrift(MigrationError):
    """Repository migration sources violate their immutable contract."""


class LedgerDrift(MigrationError):
    """Runtime ledger and repository checksums disagree."""


@dataclass(frozen=True)
class MigrationFile:
    filename: str
    prefix: str
    path: Path
    checksum: str
    size_bytes: int

    def safe_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "prefix": self.prefix,
            "checksum": self.checksum,
            "size_bytes": self.size_bytes,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bool_env(name: str) -> bool:
    return os.environ.get(name, "").strip().casefold() in TRUE_VALUES


def normalize_dsn(value: str) -> str:
    """Convert SQLAlchemy PostgreSQL schemes without exposing credentials."""

    raw = value.strip()
    if not raw:
        raise MigrationError("DATABASE_URL is required for database verification/execution")
    parsed = urlsplit(raw)
    scheme = parsed.scheme.split("+", 1)[0].casefold()
    if scheme not in {"postgres", "postgresql"}:
        raise MigrationError("DATABASE_URL must use PostgreSQL")
    try:
        port = parsed.port
    except ValueError as exc:
        raise MigrationError("DATABASE_URL has an invalid port") from exc
    if not parsed.hostname or not parsed.path.strip("/") or port is not None and not 1 <= port <= 65535:
        raise MigrationError("DATABASE_URL requires a valid host, port, and database")
    return urlunsplit(("postgresql", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def connection_identity(value: str) -> str:
    """Return credential-free host/port/database identity."""

    parsed = urlsplit(value)
    host = (parsed.hostname or "unknown").casefold()
    port = parsed.port or 5432
    database = parsed.path.strip("/").casefold() or "unknown"
    return f"postgresql:{host}:{port}/{database}"


def target_fingerprint(value: str) -> str:
    return hashlib.sha256(connection_identity(value).encode()).hexdigest()


def validate_runner_build_identity(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    """Bind the migration process to image-baked source identity."""

    source = os.environ if environment is None else environment
    expected_commit = str(source.get("OMNI_SOURCE_COMMIT", "")).strip()
    expected_fingerprint = str(source.get("OMNI_SOURCE_FINGERPRINT", "")).strip()
    baked_commit = str(source.get("OMNI_BUILD_COMMIT", "")).strip()
    baked_fingerprint = str(source.get("OMNI_BUILD_SOURCE_FINGERPRINT", "")).strip()
    if not expected_commit or not expected_fingerprint:
        raise MigrationError("expected migration source identity is missing")
    if not baked_commit or baked_commit == "unknown" or not baked_fingerprint or baked_fingerprint == "unknown":
        raise MigrationError("migration runner baked source identity is missing")
    if baked_commit != expected_commit:
        raise MigrationError("migration runner baked commit does not match expected source")
    if baked_fingerprint != expected_fingerprint:
        raise MigrationError("migration runner baked fingerprint does not match expected source")
    return {
        "expected_commit": expected_commit,
        "expected_source_fingerprint": expected_fingerprint,
        "baked_commit": baked_commit,
        "baked_source_fingerprint": baked_fingerprint,
    }


def _parse_utc(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise MigrationError("runtime allocation has an invalid expiry") from exc
    if parsed.tzinfo is None:
        raise MigrationError("runtime allocation expiry must include UTC offset")
    return parsed.astimezone(timezone.utc)


def validate_migration_allocation(
    *,
    allocation_file: Path,
    allocation_id: str,
    dsn: str,
    expected_worktree_id: str,
    expected_source_fingerprint: str,
    expected_runtime_id: str,
    expected_canonical: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bind one migration operation to an exact live RuntimeAllocation record."""

    if not allocation_id or allocation_id == "repository-only":
        raise MigrationError("migration operation requires an allocation_id")
    if not expected_worktree_id or not expected_source_fingerprint or not expected_runtime_id:
        raise MigrationError("migration operation requires worktree, source fingerprint, and runtime identity")
    try:
        state = json.loads(allocation_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationError("runtime allocation evidence is unavailable or invalid") from exc
    if not isinstance(state, Mapping) or state.get("schema_version") != 1:
        raise MigrationError("runtime allocation evidence has unsupported schema")
    allocations = state.get("allocations")
    leases = state.get("leases")
    if not isinstance(allocations, list) or not isinstance(leases, list):
        raise MigrationError("runtime allocation evidence is incomplete")
    allocation = next(
        (item for item in allocations if isinstance(item, Mapping) and item.get("allocation_id") == allocation_id),
        None,
    )
    if allocation is None:
        raise MigrationError("runtime allocation was not found")
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if allocation.get("state") != "active" or _parse_utc(allocation.get("expires_at")) <= moment:
        raise MigrationError("runtime allocation is not active")
    if allocation.get("canonical") is not expected_canonical:
        expected_mode = "canonical" if expected_canonical else "disposable"
        raise MigrationError(f"runtime allocation is not the expected {expected_mode} database mode")
    expected = {
        "worktree_id": expected_worktree_id,
        "source_fingerprint": expected_source_fingerprint,
        "runtime_id": expected_runtime_id,
    }
    for key, value in expected.items():
        if allocation.get(key) != value:
            raise MigrationError(f"runtime allocation {key} does not match the caller")
    target_database = urlsplit(dsn).path.strip("/")
    if allocation.get("database") != target_database:
        raise MigrationError("DATABASE_URL database does not match the RuntimeAllocation")
    lease = next(
        (item for item in leases if isinstance(item, Mapping) and item.get("lease_id") == allocation.get("lease_id")),
        None,
    )
    if lease is None or lease.get("state") != "active" or _parse_utc(lease.get("expires_at")) <= moment:
        raise MigrationError("workspace lease is not active")
    if lease.get("worktree_id") != expected_worktree_id or lease.get("change_id") != allocation.get("change_id"):
        raise MigrationError("workspace lease does not match the RuntimeAllocation")
    return dict(allocation)


def validate_disposable_allocation(
    *,
    allocation_file: Path,
    allocation_id: str,
    dsn: str,
    expected_worktree_id: str,
    expected_source_fingerprint: str,
    expected_runtime_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Backward-compatible explicit disposable execution validator."""

    return validate_migration_allocation(
        allocation_file=allocation_file,
        allocation_id=allocation_id,
        dsn=dsn,
        expected_worktree_id=expected_worktree_id,
        expected_source_fingerprint=expected_source_fingerprint,
        expected_runtime_id=expected_runtime_id,
        expected_canonical=False,
        now=now,
    )


def _safe_error(exc: BaseException) -> str:
    text = str(exc)
    text = re.sub(r"(?i)(postgres(?:ql)?://)([^\s]+)", r"\1<redacted>", text)
    text = re.sub(r"(?i)(password|passwd|pwd|token|secret)\s*[=:]\s*[^\s,;]+", r"\1=<redacted>", text)
    return f"{type(exc).__name__}: {text[:300]}"


def load_migrations(directory: Path = MIGRATIONS_DIR) -> tuple[MigrationFile, ...]:
    if not directory.is_dir():
        raise RepositoryDrift(f"migrations directory missing: {directory.name}")
    records: list[MigrationFile] = []
    prefixes: dict[str, str] = {}
    collision_keys: dict[str, str] = {}
    for path in sorted(directory.glob("*.sql"), key=lambda item: item.name.casefold()):
        match = FILENAME_RE.fullmatch(path.name)
        if match is None:
            raise RepositoryDrift(f"migration filename is not canonical: {path.name}")
        prefix = match.group("prefix")
        if prefix in prefixes:
            raise RepositoryDrift(
                f"duplicate numeric migration prefix {prefix}: {prefixes[prefix]}, {path.name}"
            )
        collision = path.name.casefold()
        if collision in collision_keys:
            raise RepositoryDrift(
                f"case-insensitive migration filename collision: {collision_keys[collision]}, {path.name}"
            )
        prefixes[prefix] = path.name
        collision_keys[collision] = path.name
        raw = path.read_bytes()
        try:
            sql = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RepositoryDrift(f"migration must be UTF-8: {path.name}") from exc
        if not sql.strip():
            raise RepositoryDrift(f"migration is empty: {path.name}")
        records.append(
            MigrationFile(path.name, prefix, path, hashlib.sha256(raw).hexdigest(), len(raw))
        )
    if not records:
        raise RepositoryDrift("no migration SQL files found")
    return tuple(records)


def selected_migration_names(
    migrations: Sequence[MigrationFile], selectors: Iterable[str]
) -> frozenset[str]:
    selected = {str(item).strip() for item in selectors if str(item).strip()}
    if not selected:
        return frozenset(item.filename for item in migrations)
    names = {
        item.filename
        for item in migrations
        if item.filename in selected or item.prefix in selected
    }
    matched = names | {item.prefix for item in migrations if item.filename in names}
    missing = sorted(selected - matched)
    if missing:
        raise RepositoryDrift("requested migration selector not found: " + ", ".join(missing))
    return frozenset(names)


def migration_digest(migrations: Sequence[MigrationFile]) -> str:
    payload = "".join(f"{item.filename}\0{item.checksum}\n" for item in migrations)
    return hashlib.sha256(payload.encode()).hexdigest()


def repository_manifest(migrations: Sequence[MigrationFile]) -> dict[str, Any]:
    return {
        "head": migrations[-1].filename,
        "count": len(migrations),
        "digest": migration_digest(migrations),
        "checksums": {item.filename: item.checksum for item in migrations},
    }


def _driver() -> Any:
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise MigrationError("psycopg2-binary is required for database migration execution") from exc
    return psycopg2


def _connect(dsn: str) -> Any:
    try:
        return _driver().connect(dsn, connect_timeout=10, application_name="omni-migration-runner")
    except Exception as exc:
        raise MigrationError("database connection failed: " + _safe_error(exc)) from exc


def ensure_database_prerequisites(cur: Any) -> None:
    for statement in (
        'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"',
        "CREATE EXTENSION IF NOT EXISTS pgcrypto",
        "CREATE EXTENSION IF NOT EXISTS vector",
        "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    ):
        cur.execute(statement)


def ensure_tracking(cur: Any) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS public.schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            checksum TEXT
        )
        """
    )
    cur.execute(
        "ALTER TABLE public.schema_migrations ADD COLUMN IF NOT EXISTS checksum TEXT"
    )


def read_ledger(cur: Any) -> dict[str, str | None]:
    cur.execute("SELECT to_regclass('public.schema_migrations')")
    row = cur.fetchone()
    if not row or row[0] is None:
        return {}
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='schema_migrations' AND column_name='checksum'
        )
        """
    )
    has_checksum = bool(cur.fetchone()[0])
    if has_checksum:
        cur.execute("SELECT filename, checksum FROM public.schema_migrations ORDER BY filename")
        return {str(name): str(checksum) if checksum is not None else None for name, checksum in cur.fetchall()}
    cur.execute("SELECT filename FROM public.schema_migrations ORDER BY filename")
    return {str(row[0]): None for row in cur.fetchall()}


def verify_ledger(
    migrations: Sequence[MigrationFile],
    ledger: Mapping[str, str | None],
    *,
    allow_null_checksums: bool = False,
) -> dict[str, Any]:
    repository = {item.filename: item.checksum for item in migrations}
    unknown = sorted(set(ledger) - set(repository))
    drift = sorted(
        filename
        for filename, checksum in ledger.items()
        if filename in repository and checksum is not None and checksum != repository[filename]
    )
    if unknown:
        raise LedgerDrift("ledger contains migration(s) absent from repository: " + ", ".join(unknown))
    if drift:
        raise LedgerDrift("migration checksum drift: " + ", ".join(drift))
    null_checksums = sorted(name for name, checksum in ledger.items() if checksum is None)
    if null_checksums and not allow_null_checksums:
        raise LedgerDrift(
            "ledger checksum is missing; explicit disposable backfill required: "
            + ", ".join(null_checksums)
        )
    applied = [item.filename for item in migrations if item.filename in ledger]
    pending = [item.filename for item in migrations if item.filename not in ledger]
    nonnull = {name: value for name, value in ledger.items() if value is not None}
    digest = hashlib.sha256(
        "".join(f"{name}\0{nonnull[name]}\n" for name in sorted(nonnull)).encode()
    ).hexdigest()
    return {
        "head": applied[-1] if applied else None,
        "applied": applied,
        "pending": pending,
        "checksum_count": len(nonnull),
        "checksum_digest": digest,
        "legacy_null_checksum_count": sum(value is None for value in ledger.values()),
    }


def apply_pending(
    conn: Any,
    migrations: Sequence[MigrationFile],
    ledger: Mapping[str, str | None],
    *,
    rerun: bool = False,
    selected_names: Iterable[str] = (),
) -> list[str]:
    applied: list[str] = []
    selected = set(selected_names) or {item.filename for item in migrations}
    for migration in migrations:
        if migration.filename not in selected:
            continue
        if migration.filename in ledger and not rerun:
            continue
        sql = migration.path.read_text(encoding="utf-8")
        cur = conn.cursor()
        try:
            cur.execute(sql)
            cur.execute(
                """
                INSERT INTO public.schema_migrations(filename, checksum) VALUES (%s, %s)
                ON CONFLICT (filename) DO UPDATE
                SET checksum = CASE
                    WHEN public.schema_migrations.checksum IS NULL THEN EXCLUDED.checksum
                    ELSE public.schema_migrations.checksum
                END
                """,
                (migration.filename, migration.checksum),
            )
            conn.commit()
            applied.append(migration.filename)
        except Exception as exc:
            conn.rollback()
            raise MigrationError(f"migration failed ({migration.filename}): {_safe_error(exc)}") from exc
        finally:
            cur.close()
    return applied


def backfill_legacy_checksums(
    conn: Any,
    migrations: Sequence[MigrationFile],
    ledger: Mapping[str, str | None],
) -> list[str]:
    repository = {item.filename: item.checksum for item in migrations}
    targets = sorted(name for name, checksum in ledger.items() if checksum is None)
    if not targets:
        return []
    cur = conn.cursor()
    try:
        for filename in targets:
            cur.execute(
                "UPDATE public.schema_migrations SET checksum = %s WHERE filename = %s AND checksum IS NULL",
                (repository[filename], filename),
            )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise MigrationError("legacy checksum backfill failed: " + _safe_error(exc)) from exc
    finally:
        cur.close()
    return targets


def build_receipt(
    *,
    allocation_id: str,
    dsn: str | None,
    repository: Mapping[str, Any],
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
    applied: Sequence[str],
    mode: str,
    exit_code: int,
    backfilled_checksums: Sequence[str] = (),
    attempt_id: str | None = None,
    build_identity: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    target = target_fingerprint(dsn) if dsn else None
    before_value = dict(before or {})
    after_value = dict(after or {})
    receipt_key_source = f"{allocation_id}:{target}:{repository.get('head')}"
    generated_at = utc_now()
    attempt = attempt_id or uuid.uuid4().hex
    return {
        "schema_version": 1,
        "kind": "omni_migration_receipt",
        "receipt_id": f"migration-{attempt}",
        "receipt_key": hashlib.sha256(receipt_key_source.encode()).hexdigest(),
        "runner_version": RUNNER_VERSION,
        "allocation_id": allocation_id,
        "target_fingerprint": target,
        "mode": mode,
        "repository": dict(repository),
        "before": before_value,
        "after": after_value,
        "database_fixture": {
            "empty_database": not bool(before_value.get("applied")),
            "existing_database": bool(before_value.get("applied")),
        },
        "applied": list(applied),
        "backfilled_checksums": list(backfilled_checksums),
        "exit_code": exit_code,
        "status": "passed" if exit_code == 0 else "failed",
        "generated_at": generated_at,
        "redaction": "credential_free_target_fingerprint_only",
        "build_identity": dict(build_identity or {}),
    }


def write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(dict(receipt), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise MigrationError(f"refusing to overwrite immutable MigrationReceipt: {path}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink(missing_ok=True)
        finally:
            raise


@contextlib.contextmanager
def _receipt_lock(path: Path, *, timeout_seconds: float = 5.0) -> Iterable[None]:
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
                else:  # pragma: no cover - exercised in Linux container/CI
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise MigrationError("timed out updating migration receipt index")
                time.sleep(0.02)
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _write_json_atomic(path: Path, value: Mapping[str, Any] | Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_receipt_directory(directory: Path, receipt: Mapping[str, Any]) -> Path:
    """Append immutable receipt history and atomically move the latest pointer."""

    directory = directory.resolve()
    with _receipt_lock(directory / ".receipt-index.lock"):
        receipt_id = str(receipt.get("receipt_id") or "")
        if not re.fullmatch(r"migration-[0-9a-f]{32}", receipt_id):
            raise MigrationError("MigrationReceipt has an invalid receipt_id")
        filename = f"{receipt_id}.json"
        receipt_path = directory / filename
        write_receipt(receipt_path, receipt)
        digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        entry = {
            "receipt_id": receipt_id,
            "filename": filename,
            "sha256": digest,
            "generated_at": receipt.get("generated_at"),
            "status": receipt.get("status"),
        }
        index_path = directory / "index.json"
        if index_path.is_file():
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise MigrationError("migration receipt index is invalid") from exc
            if not isinstance(index, list):
                raise MigrationError("migration receipt index must be an array")
        else:
            index = []
        index.append(entry)
        _write_json_atomic(index_path, index)
        _write_json_atomic(directory / "latest.json", entry)
        return receipt_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="verify repository only; never import driver/connect")
    parser.add_argument("--verify", action="store_true", help="verify repository and post-run ledger parity")
    parser.add_argument("--verify-only", action="store_true", help="read-only ledger verification; execute no DDL")
    parser.add_argument(
        "--allocation-aware",
        action="store_true",
        help=(
            "single safe entry point: apply+verify only for an allocated disposable DB; "
            "otherwise read-only verify and require repository-head parity"
        ),
    )
    parser.add_argument("--only", default="", help="comma-separated exact filenames or numeric prefixes")
    parser.add_argument("--rerun", action="store_true", help="rerun selected idempotent SQL (requires execution authorization)")
    parser.add_argument("--backfill-legacy-checksums", action="store_true", help="backfill NULL ledger checksums on a verified disposable allocation")
    parser.add_argument("--migrations-dir", type=Path, default=MIGRATIONS_DIR)
    parser.add_argument("--receipt-out", type=Path)
    parser.add_argument("--receipt-dir", type=Path)
    parser.add_argument("--allocation-id", default=os.environ.get("OMNI_ALLOCATION_ID", "repository-only"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.receipt_out and args.receipt_dir:
            raise MigrationError("choose either --receipt-out or --receipt-dir")
        selectors = [item.strip() for item in args.only.split(",") if item.strip()]
        migrations = load_migrations(args.migrations_dir.resolve())
        selected_names = selected_migration_names(migrations, selectors)
        repository = repository_manifest(migrations)
        if args.dry_run:
            receipt = build_receipt(
                allocation_id=args.allocation_id,
                dsn=None,
                repository=repository,
                before=None,
                after=None,
                applied=[],
                mode="repository_verify",
                exit_code=0,
            )
            if args.receipt_out:
                write_receipt(args.receipt_out, receipt)
            if args.receipt_dir:
                write_receipt_directory(args.receipt_dir, receipt)
            print(
                json.dumps(
                    {"status": "verified", "mode": "repository_only", "head": repository["head"], "count": repository["count"], "digest": repository["digest"]},
                    sort_keys=True,
                )
            )
            return 0

        if args.allocation_aware and args.verify_only:
            raise MigrationError("--allocation-aware already selects the safe mode; do not combine --verify-only")
        dsn = normalize_dsn(os.environ.get("DATABASE_URL", ""))
        build_identity = validate_runner_build_identity()
        disposable = _bool_env("OMNI_DATABASE_DISPOSABLE")
        executing = disposable if args.allocation_aware else not args.verify_only
        require_head = args.allocation_aware or args.verify
        if args.rerun and (not executing or not selectors):
            raise MigrationError("--rerun requires database execution and an explicit --only selector")
        if args.backfill_legacy_checksums and not executing:
            raise MigrationError("legacy checksum backfill requires disposable database execution")
        if executing and _bool_env("OMNI_ALLOW_SHARED_MIGRATION"):
            raise MigrationError(
                "shared database migration execution is prohibited in this slice; a boolean environment flag is not an approval receipt"
            )
        if executing and not disposable:
            raise MigrationError(
                "shared database execution blocked before connection; only a verified disposable RuntimeAllocation is accepted"
            )
        if executing or args.allocation_aware:
            allocation_path = os.environ.get("OMNI_RUNTIME_ALLOCATION_FILE", "").strip()
            if not allocation_path:
                raise MigrationError("OMNI_RUNTIME_ALLOCATION_FILE is required for allocation-aware migration")
            validate_migration_allocation(
                allocation_file=Path(allocation_path),
                allocation_id=args.allocation_id,
                dsn=dsn,
                expected_worktree_id=os.environ.get("OMNI_WORKTREE_ID", ""),
                expected_source_fingerprint=os.environ.get("OMNI_SOURCE_FINGERPRINT", ""),
                expected_runtime_id=os.environ.get("OMNI_RUNTIME_ID", ""),
                expected_canonical=not disposable,
            )
        conn = _connect(dsn)
        if not executing:
            try:
                conn.set_session(readonly=True, autocommit=False)
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.close()
                raise MigrationError(
                    "database read-only session could not be established: " + _safe_error(exc)
                ) from exc
        before: dict[str, Any]
        after: dict[str, Any]
        applied: list[str] = []
        backfilled: list[str] = []
        lock_cursor = None
        try:
            if executing:
                lock_cursor = conn.cursor()
                lock_cursor.execute("SELECT pg_advisory_lock(hashtext('omni_migration_runner_v2'))")
                conn.commit()
            cur = conn.cursor()
            try:
                ledger = read_ledger(cur)
                before = verify_ledger(migrations, ledger, allow_null_checksums=True)
            finally:
                cur.close()
            if executing:
                cur = conn.cursor()
                try:
                    ensure_database_prerequisites(cur)
                    ensure_tracking(cur)
                    conn.commit()
                finally:
                    cur.close()
                # Re-read because tracking creation changes the empty fixture.
                cur = conn.cursor()
                try:
                    ledger = read_ledger(cur)
                finally:
                    cur.close()
                if any(value is None for value in ledger.values()):
                    if not args.backfill_legacy_checksums:
                        verify_ledger(migrations, ledger)
                    backfilled = backfill_legacy_checksums(conn, migrations, ledger)
                    cur = conn.cursor()
                    try:
                        ledger = read_ledger(cur)
                    finally:
                        cur.close()
                verified_before_apply = verify_ledger(migrations, ledger)
                outside_selection = sorted(
                    name for name in verified_before_apply["pending"] if name not in selected_names
                )
                if require_head and outside_selection:
                    raise LedgerDrift(
                        "full-head parity cannot be reached by --only selection; pending outside selection: "
                        + ", ".join(outside_selection)
                    )
                applied = apply_pending(
                    conn,
                    migrations,
                    ledger,
                    rerun=args.rerun,
                    selected_names=selected_names,
                )
            cur = conn.cursor()
            try:
                after = verify_ledger(migrations, read_ledger(cur))
            finally:
                cur.close()
            if require_head and after["pending"]:
                if executing:
                    raise LedgerDrift("post-apply migration parity has pending files")
                raise LedgerDrift(
                    "canonical database has not reached repository head; pending migrations: "
                    + ", ".join(after["pending"])
                )
        except MigrationError:
            raise
        except Exception as exc:
            raise MigrationError("database operation failed: " + _safe_error(exc)) from exc
        finally:
            if lock_cursor is not None:
                try:
                    lock_cursor.execute("SELECT pg_advisory_unlock(hashtext('omni_migration_runner_v2'))")
                    conn.commit()
                except Exception:
                    with contextlib.suppress(Exception):
                        conn.rollback()
                with contextlib.suppress(Exception):
                    lock_cursor.close()
            with contextlib.suppress(Exception):
                conn.close()

        if args.allocation_aware:
            mode = "allocation_disposable_apply_verify" if executing else "allocation_canonical_verify"
        else:
            mode = "verify_only" if args.verify_only else "apply_and_verify" if args.verify else "apply"
        receipt = build_receipt(
            allocation_id=args.allocation_id,
            dsn=dsn,
            repository=repository,
            before=before,
            after=after,
            applied=applied,
            backfilled_checksums=backfilled,
            mode=mode,
            exit_code=0,
            build_identity=build_identity,
        )
        if args.receipt_out:
            write_receipt(args.receipt_out, receipt)
        if args.receipt_dir:
            write_receipt_directory(args.receipt_dir, receipt)
        print(json.dumps({
            "status": "verified" if not after["pending"] else "pending",
            "mode": mode,
            "repository_head": repository["head"],
            "ledger_head": after["head"],
            "pending": len(after["pending"]),
            "applied": len(applied),
            "target_fingerprint": receipt["target_fingerprint"],
        }, sort_keys=True))
        return 0
    except (MigrationError, OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"[migration-runner] BLOCKED: {_safe_error(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
