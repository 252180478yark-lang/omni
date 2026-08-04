from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "omni_dev_runtime_environment_tests",
    ROOT / "scripts" / "dev_runtime_environment.py",
)
assert SPEC is not None and SPEC.loader is not None
runtime_env = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime_env
SPEC.loader.exec_module(runtime_env)


def _allocation_environment() -> dict[str, str]:
    return {
        "OMNI_DATABASE_DISPOSABLE": "true",
        "OMNI_ALLOCATION_ID": "allocation-" + "a" * 32,
        "OMNI_RUNTIME_ID": "runtime-fixture",
        "OMNI_WORKTREE_ID": "worktree-" + "b" * 16,
        "OMNI_SOURCE_FINGERPRINT": "c" * 64,
        "POSTGRES_USER": "fixture-user",
        "POSTGRES_PASSWORD": "not-printed:/@ password",
        "POSTGRES_DB": "omni_verify_fixture",
        "REDIS_PASSWORD": "redis-not-printed:/@ password",
        "OMNI_IDENTITY_JWT_SECRET_FILE": str((ROOT / "tests" / "fixtures" / "identity-jwt.key").resolve()),
        "OMNI_APPROVAL_HMAC_SECRET_FILE": str((ROOT / "tests" / "fixtures" / "approval-hmac.key").resolve()),
        "OMNI_COMPATIBILITY_TOKEN_FILE": str((ROOT / "tests" / "fixtures" / "compatibility-token.key").resolve()),
        "POSTGRES_PORT": "25432",
        "REDIS_PORT": "26379",
        "IDENTITY_SERVICE_PORT": "28000",
        "AI_PROVIDER_HUB_PORT": "28001",
        "KNOWLEDGE_ENGINE_PORT": "28002",
        "NEWS_AGGREGATOR_PORT": "28005",
        "VIDEO_ANALYSIS_PORT": "28006",
        "LIVESTREAM_ANALYSIS_PORT": "28007",
        "AD_REVIEW_PORT": "28008",
        "SCOUT_AGENT_PORT": "28009",
        "FRONTEND_PORT": "23000",
    }


def test_service_environment_uses_only_allocated_database_redis_and_service_ports() -> None:
    source = _allocation_environment()
    environment = runtime_env.build_service_environment("identity-service", source)
    database = urlsplit(environment["DATABASE_URL"])
    redis = urlsplit(environment["REDIS_URL"])

    assert database.scheme == "postgresql+asyncpg"
    assert (database.hostname, database.port, database.path) == (
        "127.0.0.1",
        25432,
        "/omni_verify_fixture",
    )
    assert (redis.hostname, redis.port, redis.path) == ("127.0.0.1", 26379, "/3")
    assert environment["AI_PROVIDER_HUB_URL"] == "http://127.0.0.1:28001"
    assert environment["KNOWLEDGE_ENGINE_URL"] == "http://127.0.0.1:28002"
    assert environment["VIDEO_ANALYSIS_SERVICE_URL"] == "http://127.0.0.1:28006"
    assert environment["NEXT_PUBLIC_OMNI_API_BASE_URL"] == "http://127.0.0.1:23000"
    assert environment["JWT_SECRET_KEY_FILE"] == source["OMNI_IDENTITY_JWT_SECRET_FILE"]
    assert "OMNI_COMPATIBILITY_TOKEN_FILE" not in environment
    assert "JWT_SECRET_KEY" not in environment
    assert database.port != 5432
    assert redis.port != 6379


def test_frontend_overrides_inherited_canonical_database_and_redis_endpoints() -> None:
    source = _allocation_environment()
    source["DATABASE_URL"] = "postgresql://should-not-survive"
    source.update(
        {
            "PGHOST": "127.0.0.1",
            "PGPORT": "5432",
            "PGUSER": "canonical-user",
            "PGPASSWORD": "canonical-password",
            "PGDATABASE": "canonical-database",
            "REDIS_URL": "redis://:canonical-password@127.0.0.1:6379/0",
            "OMNI_KE_URL": "http://127.0.0.1:8002",
            "OMNI_APPROVAL_SERVICE_TOKEN": "canonical-inline-token",
        }
    )
    environment = runtime_env.build_service_environment("frontend", source)
    assert "DATABASE_URL" not in environment
    assert environment["PGHOST"] == "127.0.0.1"
    assert environment["PGPORT"] == "25432"
    assert environment["PGUSER"] == source["POSTGRES_USER"]
    assert environment["PGPASSWORD"] == source["POSTGRES_PASSWORD"]
    assert environment["PGDATABASE"] == source["POSTGRES_DB"]
    redis = urlsplit(environment["REDIS_URL"])
    assert (redis.hostname, redis.port, redis.path) == ("127.0.0.1", 26379, "/1")
    assert environment["OMNI_KE_URL"] == "http://127.0.0.1:28002"
    assert environment["OMNI_APPROVAL_SERVICE_SECRET_FILE"] == source["OMNI_APPROVAL_HMAC_SECRET_FILE"]
    assert environment["OMNI_COMPATIBILITY_TOKEN_FILE"] == source["OMNI_COMPATIBILITY_TOKEN_FILE"]
    assert "OMNI_APPROVAL_SERVICE_TOKEN" not in environment
    assert "OMNI_APPROVAL_SERVICE_SECRET_FILE" not in source

    source["OMNI_DATABASE_DISPOSABLE"] = "false"
    with pytest.raises(runtime_env.DevEnvironmentError, match="disposable"):
        runtime_env.build_service_environment("frontend", source)


@pytest.mark.parametrize(
    ("service", "source_name"),
    (
        ("identity-service", "OMNI_IDENTITY_JWT_SECRET_FILE"),
        ("frontend", "OMNI_APPROVAL_HMAC_SECRET_FILE"),
        ("frontend", "OMNI_COMPATIBILITY_TOKEN_FILE"),
    ),
)
def test_host_secret_file_mappings_require_absolute_paths(service: str, source_name: str) -> None:
    source = _allocation_environment()
    source[source_name] = "relative-secret.key"
    with pytest.raises(runtime_env.DevEnvironmentError, match="not absolute"):
        runtime_env.build_service_environment(service, source)


def test_cli_stdout_is_pid_only_while_identity_secret_alias_exists_only_in_child(
    tmp_path: Path,
) -> None:
    source = {**os.environ, **_allocation_environment()}
    source.pop("JWT_SECRET_KEY_FILE", None)
    source["JWT_SECRET_KEY"] = "inherited-inline-value-must-not-reach-child"
    probe = tmp_path / "identity_probe.py"
    probe.write_text(
        """
import json, os
print(json.dumps({
    'file_alias_matches': os.environ.get('JWT_SECRET_KEY_FILE') == os.environ.get('OMNI_IDENTITY_JWT_SECRET_FILE'),
    'inline_absent': 'JWT_SECRET_KEY' not in os.environ,
}, sort_keys=True), flush=True)
""".lstrip(),
        encoding="utf-8",
    )
    child_stdout = tmp_path / "identity.out"
    child_stderr = tmp_path / "identity.err"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "scripts" / "dev_runtime_environment.py"),
            "launch",
            "--service",
            "identity-service",
            "--cwd",
            str(tmp_path),
            "--stdout",
            str(child_stdout),
            "--stderr",
            str(child_stderr),
            "--",
            sys.executable,
            str(probe),
        ],
        cwd=ROOT,
        env=source,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert set(json.loads(result.stdout)) == {"pid"}
    assert source["OMNI_IDENTITY_JWT_SECRET_FILE"] not in result.stdout + result.stderr
    assert source["POSTGRES_PASSWORD"] not in result.stdout + result.stderr
    assert "JWT_SECRET_KEY_FILE" not in source

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and (
        not child_stdout.exists() or not child_stdout.read_text(encoding="utf-8", errors="replace").strip()
    ):
        time.sleep(0.02)
    observed = json.loads(child_stdout.read_text(encoding="utf-8"))
    assert observed == {"file_alias_matches": True, "inline_absent": True}
    assert child_stderr.read_text(encoding="utf-8") == ""


def test_frontend_child_gets_allocated_pg_redis_ke_and_file_backed_approval(
    tmp_path: Path,
) -> None:
    source = {**os.environ, **_allocation_environment()}
    source.pop("OMNI_APPROVAL_SERVICE_SECRET_FILE", None)
    source.update(
        {
            "PGHOST": "canonical-postgres",
            "PGPORT": "5432",
            "PGDATABASE": "canonical-database",
            "REDIS_URL": "redis://canonical-redis:6379/0",
            "OMNI_KE_URL": "http://127.0.0.1:8002",
            "OMNI_APPROVAL_SERVICE_TOKEN": "inherited-inline-token",
            "OMNI_COMPATIBILITY_TOKEN": "inherited-inline-compatibility-token",
        }
    )
    probe = tmp_path / "frontend_probe.py"
    probe.write_text(
        """
import json, os
from urllib.parse import urlsplit
redis = urlsplit(os.environ['REDIS_URL'])
print(json.dumps({
    'approval_file_matches': os.environ.get('OMNI_APPROVAL_SERVICE_SECRET_FILE') == os.environ.get('OMNI_APPROVAL_HMAC_SECRET_FILE'),
    'compatibility_file_matches': bool(os.environ.get('OMNI_COMPATIBILITY_TOKEN_FILE')),
    'inline_absent': 'OMNI_APPROVAL_SERVICE_TOKEN' not in os.environ,
    'compatibility_inline_absent': 'OMNI_COMPATIBILITY_TOKEN' not in os.environ,
    'pg_host': os.environ.get('PGHOST'),
    'pg_port': os.environ.get('PGPORT'),
    'pg_database': os.environ.get('PGDATABASE'),
    'redis_host': redis.hostname,
    'redis_port': redis.port,
    'redis_database': redis.path,
    'ke_url': os.environ.get('OMNI_KE_URL'),
}, sort_keys=True), flush=True)
""".lstrip(),
        encoding="utf-8",
    )
    child_stdout = tmp_path / "frontend.out"
    child_stderr = tmp_path / "frontend.err"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "scripts" / "dev_runtime_environment.py"),
            "launch",
            "--service",
            "frontend",
            "--cwd",
            str(tmp_path),
            "--stdout",
            str(child_stdout),
            "--stderr",
            str(child_stderr),
            "--",
            sys.executable,
            str(probe),
        ],
        cwd=ROOT,
        env=source,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert set(json.loads(result.stdout)) == {"pid"}
    combined = result.stdout + result.stderr
    assert source["OMNI_APPROVAL_HMAC_SECRET_FILE"] not in combined
    assert source["OMNI_COMPATIBILITY_TOKEN_FILE"] not in combined
    assert source["POSTGRES_PASSWORD"] not in combined
    assert source["REDIS_PASSWORD"] not in combined
    assert "OMNI_APPROVAL_SERVICE_SECRET_FILE" not in source

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and (
        not child_stdout.exists() or not child_stdout.read_text(encoding="utf-8", errors="replace").strip()
    ):
        time.sleep(0.02)
    observed = json.loads(child_stdout.read_text(encoding="utf-8"))
    assert observed == {
        "approval_file_matches": True,
        "compatibility_file_matches": True,
        "compatibility_inline_absent": True,
        "inline_absent": True,
        "ke_url": "http://127.0.0.1:28002",
        "pg_database": "omni_verify_fixture",
        "pg_host": "127.0.0.1",
        "pg_port": "25432",
        "redis_database": "/1",
        "redis_host": "127.0.0.1",
        "redis_port": 26379,
    }
    assert child_stderr.read_text(encoding="utf-8") == ""


def test_compatibility_token_is_projected_only_to_its_two_host_consumers() -> None:
    source = _allocation_environment()
    for service in runtime_env.ALLOWED_SERVICES:
        environment = runtime_env.build_service_environment(service, source)
        if service == "frontend":
            assert environment["OMNI_COMPATIBILITY_TOKEN_FILE"] == source["OMNI_COMPATIBILITY_TOKEN_FILE"]
        else:
            assert "OMNI_COMPATIBILITY_TOKEN_FILE" not in environment


def test_spawned_child_observes_allocated_environment_without_emitting_passwords(
    tmp_path: Path,
) -> None:
    source = _allocation_environment()
    probe = tmp_path / "probe.py"
    probe.write_text(
        """
import hashlib, json, os
from urllib.parse import urlsplit
database = urlsplit(os.environ['DATABASE_URL'])
redis = urlsplit(os.environ['REDIS_URL'])
print(json.dumps({
    'database_host': database.hostname,
    'database_port': database.port,
    'database_name': database.path,
    'database_sha256': hashlib.sha256(os.environ['DATABASE_URL'].encode()).hexdigest(),
    'redis_host': redis.hostname,
    'redis_port': redis.port,
    'hub_url': os.environ['AI_PROVIDER_HUB_URL'],
    'knowledge_url': os.environ['KNOWLEDGE_ENGINE_URL'],
    'allocation_id': os.environ['OMNI_ALLOCATION_ID'],
}, sort_keys=True), flush=True)
""".lstrip(),
        encoding="utf-8",
    )
    stdout_path = tmp_path / "probe.out"
    stderr_path = tmp_path / "probe.err"

    runtime_env.launch_process(
        "news-aggregator",
        [sys.executable, str(probe)],
        cwd=tmp_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        source=source,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not stdout_path.read_text(encoding="utf-8", errors="replace").strip():
        time.sleep(0.02)

    stdout = stdout_path.read_text(encoding="utf-8")
    stderr = stderr_path.read_text(encoding="utf-8")
    observed = json.loads(stdout)
    expected_environment = runtime_env.build_service_environment("news-aggregator", source)
    assert observed == {
        "allocation_id": source["OMNI_ALLOCATION_ID"],
        "database_host": "127.0.0.1",
        "database_name": "/omni_verify_fixture",
        "database_port": 25432,
        "database_sha256": hashlib.sha256(expected_environment["DATABASE_URL"].encode()).hexdigest(),
        "hub_url": "http://127.0.0.1:28001",
        "knowledge_url": "http://127.0.0.1:28002",
        "redis_host": "127.0.0.1",
        "redis_port": 26379,
    }
    combined = stdout + stderr
    assert source["POSTGRES_PASSWORD"] not in combined
    assert source["REDIS_PASSWORD"] not in combined


def test_dev_start_boots_core_services_in_the_same_root_compose_allocation() -> None:
    script = (ROOT / "dev-start.ps1").read_text(encoding="utf-8")
    assert "docker compose -f $composeFile up -d postgres redis" in script
    assert "docker compose -f $composeFile up -d ai-provider-hub knowledge-engine" in script
    assert 'docker-compose.dev.yml" up -d' not in script
    assert "scripts\\dev_runtime_environment.py" in script
    assert "localhost:8001" not in script
    assert "localhost:8002" not in script
