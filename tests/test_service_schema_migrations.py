from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_identity_schema_is_owned_by_root_runner_without_default_credentials():
    migration = text("migrations/099_identity_users_schema.sql")
    assert "CREATE TYPE public.user_role AS ENUM ('admin', 'user')" in migration
    assert "CREATE TABLE IF NOT EXISTS public.users" in migration
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email" in migration
    assert "information_schema.columns" in migration
    assert "actual.udt_schema <> expected.udt_schema" in migration
    assert "actual.udt_name <> expected.udt_name" in migration
    assert "INSERT INTO public.users" not in migration

    main = text("services/identity-service/app/main.py")
    assert "Base.metadata.create_all" not in main
    assert 'text("SELECT 1")' in main


def test_news_schema_is_owned_by_root_runner_and_is_alembic_compatible():
    migration = text("migrations/100_news_aggregator_schema.sql")
    for table in ("fetch_jobs", "source_configs", "articles"):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in migration
    for index in (
        "idx_fetch_jobs_status",
        "idx_articles_status_fetched",
        "idx_articles_tags",
        "idx_articles_archived",
    ):
        assert f"CREATE INDEX IF NOT EXISTS {index}" in migration
    assert "CONSTRAINT uq_articles_url UNIQUE (url)" in migration
    assert "ON CONFLICT (id) DO NOTHING" in migration
    assert "information_schema.columns" in migration


def test_admin_bootstrap_is_explicit_and_never_accepts_password_argv_or_env():
    source = text("services/identity-service/scripts/bootstrap_admin.py")
    assert 'parser.add_argument("--email", required=True)' in source
    assert '"--password-stdin"' in source
    assert '"--promote-existing"' in source
    assert "getpass.getpass" in source
    assert "--password\"" not in source
    assert "PASSWORD" not in source
    assert "bootstrap_admin" not in text("services/identity-service/app/main.py")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "services/identity-service/scripts/bootstrap_admin.py"),
            "--help",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--password-stdin" in result.stdout
