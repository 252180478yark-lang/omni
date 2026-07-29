from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "omni_migration_runner_contract_tests", ROOT / "scripts" / "apply_migrations.py"
)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def _migration(directory: Path, prefix: int, name: str, sql: str = "SELECT 1;\n") -> Path:
    path = directory / f"{prefix:03d}_{name}.sql"
    path.write_text(sql, encoding="utf-8")
    return path


def _allocation_file(
    tmp_path: Path, *, database: str = "isolated_db", canonical: bool = False
) -> tuple[Path, dict[str, str]]:
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    allocation_id = "allocation-" + "a" * 32
    lease_id = "lease-" + "b" * 32
    fingerprint = "c" * 64
    worktree_id = "worktree-" + "d" * 16
    runtime_id = "isolated-runtime"
    state = {
        "schema_version": 1,
        "generation": 1,
        "leases": [
            {
                "lease_id": lease_id,
                "change_id": "change-a",
                "worktree_id": worktree_id,
                "state": "active",
                "expires_at": expires,
            }
        ],
        "allocations": [
            {
                "allocation_id": allocation_id,
                "lease_id": lease_id,
                "change_id": "change-a",
                "worktree_id": worktree_id,
                "source_fingerprint": fingerprint,
                "runtime_id": runtime_id,
                "database": database,
                "canonical": canonical,
                "state": "active",
                "expires_at": expires,
            }
        ],
    }
    path = tmp_path / "allocations.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    return path, {
        "allocation_id": allocation_id,
        "worktree_id": worktree_id,
        "source_fingerprint": fingerprint,
        "runtime_id": runtime_id,
    }


class _VerifyCursor:
    def close(self) -> None:
        return None


class _VerifyConnection:
    def __init__(self) -> None:
        self.readonly = False
        self.closed = False

    def set_session(self, *, readonly: bool, autocommit: bool) -> None:
        assert autocommit is False
        self.readonly = readonly

    def cursor(self) -> _VerifyCursor:
        return _VerifyCursor()

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("at_head, expected", [(True, 0), (False, 1)])
def test_allocation_aware_canonical_mode_is_read_only_and_requires_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    at_head: bool,
    expected: int,
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    migration_path = _migration(migrations_dir, 1, "first")
    checksum = runner.hashlib.sha256(migration_path.read_bytes()).hexdigest()
    allocation_path, identity = _allocation_file(
        tmp_path, database="canonical_db", canonical=True
    )
    connection = _VerifyConnection()
    monkeypatch.setattr(runner, "_connect", lambda _dsn: connection)
    monkeypatch.setattr(
        runner,
        "read_ledger",
        lambda _cur: {"001_first.sql": checksum} if at_head else {},
    )
    monkeypatch.setattr(
        runner,
        "apply_pending",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("canonical verification must not apply DDL")
        ),
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:redacted@localhost:5432/canonical_db")
    monkeypatch.setenv("OMNI_DATABASE_DISPOSABLE", "false")
    monkeypatch.setenv("OMNI_RUNTIME_ALLOCATION_FILE", str(allocation_path))
    monkeypatch.setenv("OMNI_ALLOCATION_ID", identity["allocation_id"])
    monkeypatch.setenv("OMNI_WORKTREE_ID", identity["worktree_id"])
    monkeypatch.setenv("OMNI_SOURCE_FINGERPRINT", identity["source_fingerprint"])
    monkeypatch.setenv("OMNI_SOURCE_COMMIT", "e" * 40)
    monkeypatch.setenv("OMNI_BUILD_COMMIT", "e" * 40)
    monkeypatch.setenv("OMNI_BUILD_SOURCE_FINGERPRINT", identity["source_fingerprint"])
    monkeypatch.setenv("OMNI_RUNTIME_ID", identity["runtime_id"])

    result = runner.main(
        ["--allocation-aware", "--migrations-dir", str(migrations_dir)]
    )

    assert result == expected
    assert connection.readonly is True
    assert connection.closed is True
    output = capsys.readouterr()
    if at_head:
        assert '"mode": "allocation_canonical_verify"' in output.out
        assert '"pending": 0' in output.out
    else:
        assert "has not reached repository head" in output.err


def test_repository_manifest_is_always_full_even_when_only_selects_one(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _migration(migrations_dir, 1, "first")
    _migration(migrations_dir, 2, "second")
    migrations = runner.load_migrations(migrations_dir)

    selected = runner.selected_migration_names(migrations, ["002"])
    manifest = runner.repository_manifest(migrations)
    ledger = runner.verify_ledger(migrations, {})

    assert selected == {"002_second.sql"}
    assert manifest["count"] == 2
    assert manifest["head"] == "002_second.sql"
    assert ledger["pending"] == ["001_first.sql", "002_second.sql"]
    assert [name for name in ledger["pending"] if name not in selected] == ["001_first.sql"]


def test_duplicate_prefix_checksum_drift_unknown_and_null_ledger_fail_closed(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _migration(migrations_dir, 1, "first")
    _migration(migrations_dir, 1, "duplicate")
    with pytest.raises(runner.RepositoryDrift, match="duplicate numeric"):
        runner.load_migrations(migrations_dir)

    (migrations_dir / "001_duplicate.sql").unlink()
    migrations = runner.load_migrations(migrations_dir)
    with pytest.raises(runner.LedgerDrift, match="absent from repository"):
        runner.verify_ledger(migrations, {"999_unknown.sql": "f" * 64})
    with pytest.raises(runner.LedgerDrift, match="checksum drift"):
        runner.verify_ledger(migrations, {"001_first.sql": "f" * 64})
    with pytest.raises(runner.LedgerDrift, match="checksum is missing"):
        runner.verify_ledger(migrations, {"001_first.sql": None})
    audit = runner.verify_ledger(
        migrations, {"001_first.sql": None}, allow_null_checksums=True
    )
    assert audit["legacy_null_checksum_count"] == 1


def test_disposable_execution_is_bound_to_active_allocation_and_exact_database(tmp_path: Path) -> None:
    path, identity = _allocation_file(tmp_path)
    allocation = runner.validate_disposable_allocation(
        allocation_file=path,
        allocation_id=identity["allocation_id"],
        dsn="postgresql://user:redacted@localhost:5432/isolated_db",
        expected_worktree_id=identity["worktree_id"],
        expected_source_fingerprint=identity["source_fingerprint"],
        expected_runtime_id=identity["runtime_id"],
    )
    assert allocation["database"] == "isolated_db"

    with pytest.raises(runner.MigrationError, match="does not match"):
        runner.validate_disposable_allocation(
            allocation_file=path,
            allocation_id=identity["allocation_id"],
            dsn="postgresql://user:redacted@localhost:5432/shared_db",
            expected_worktree_id=identity["worktree_id"],
            expected_source_fingerprint=identity["source_fingerprint"],
            expected_runtime_id=identity["runtime_id"],
        )


def test_disposable_boolean_and_shared_boolean_cannot_reach_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _migration(migrations_dir, 1, "first")
    connected = False

    def forbidden_connect(_dsn: str):
        nonlocal connected
        connected = True
        raise AssertionError("must not connect")

    monkeypatch.setattr(runner, "_connect", forbidden_connect)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:redacted-never-print-me@localhost:5432/shared")
    monkeypatch.setenv("OMNI_DATABASE_DISPOSABLE", "true")
    monkeypatch.setenv("OMNI_SOURCE_COMMIT", "a" * 40)
    monkeypatch.setenv("OMNI_BUILD_COMMIT", "a" * 40)
    monkeypatch.setenv("OMNI_SOURCE_FINGERPRINT", "b" * 64)
    monkeypatch.setenv("OMNI_BUILD_SOURCE_FINGERPRINT", "b" * 64)
    assert runner.main(["--migrations-dir", str(migrations_dir)]) == 1
    assert connected is False
    assert "never-print-me" not in capsys.readouterr().err

    monkeypatch.setenv("OMNI_ALLOW_SHARED_MIGRATION", "true")
    assert runner.main(["--migrations-dir", str(migrations_dir)]) == 1
    assert connected is False


def test_migration_runner_rejects_old_baked_image_identity() -> None:
    with pytest.raises(runner.MigrationError, match="baked commit"):
        runner.validate_runner_build_identity(
            {
                "OMNI_SOURCE_COMMIT": "b" * 40,
                "OMNI_SOURCE_FINGERPRINT": "c" * 64,
                "OMNI_BUILD_COMMIT": "a" * 40,
                "OMNI_BUILD_SOURCE_FINGERPRINT": "c" * 64,
            }
        )
    verified = runner.validate_runner_build_identity(
        {
            "OMNI_SOURCE_COMMIT": "b" * 40,
            "OMNI_SOURCE_FINGERPRINT": "c" * 64,
            "OMNI_BUILD_COMMIT": "b" * 40,
            "OMNI_BUILD_SOURCE_FINGERPRINT": "c" * 64,
        }
    )
    assert verified["baked_commit"] == "b" * 40


def test_receipt_directory_retains_two_runs_and_updates_latest_atomically(tmp_path: Path) -> None:
    repository = {"head": "001_first.sql", "count": 1, "digest": "a" * 64, "checksums": {}}
    first = runner.build_receipt(
        allocation_id="allocation-a",
        dsn=None,
        repository=repository,
        before=None,
        after=None,
        applied=[],
        mode="repository_verify",
        exit_code=0,
    )
    second = runner.build_receipt(
        allocation_id="allocation-a",
        dsn=None,
        repository=repository,
        before=None,
        after=None,
        applied=[],
        mode="repository_verify",
        exit_code=0,
    )
    directory = tmp_path / "receipts"
    first_path = runner.write_receipt_directory(directory, first)
    second_path = runner.write_receipt_directory(directory, second)

    assert first_path != second_path
    assert first_path.is_file() and second_path.is_file()
    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    latest = json.loads((directory / "latest.json").read_text(encoding="utf-8"))
    assert len(index) == 2
    assert latest["receipt_id"] == second["receipt_id"]
    assert (directory / ".receipt-index.lock").stat().st_size == 1


class _BackfillCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[str, str]]] = []

    def execute(self, statement: str, params: tuple[str, str]) -> None:
        self.executed.append((statement, params))

    def close(self) -> None:
        return None


class _BackfillConnection:
    def __init__(self) -> None:
        self.cur = _BackfillCursor()
        self.commits = 0

    def cursor(self) -> _BackfillCursor:
        return self.cur

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        raise AssertionError("backfill should not roll back")


def test_legacy_null_checksum_backfill_is_explicit_and_auditable(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _migration(migrations_dir, 1, "first")
    migrations = runner.load_migrations(migrations_dir)
    conn = _BackfillConnection()

    updated = runner.backfill_legacy_checksums(conn, migrations, {"001_first.sql": None})

    assert updated == ["001_first.sql"]
    assert conn.commits == 1
    assert conn.cur.executed[0][1] == (migrations[0].checksum, "001_first.sql")
