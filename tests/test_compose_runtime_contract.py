from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.dev.yml",
    "services/docker-compose.sp1-sp4.yml",
    "services/infra-core/docker-compose.infra.yml",
)
BUILD_IDENTIFIED_SERVICES = {
    "identity-service",
    "frontend",
    "ai-provider-hub",
    "knowledge-engine",
    "news-aggregator",
    "video-analysis",
    "livestream-analysis",
    "ad-review-service",
    "scout-agent",
}


def _compose() -> list[str]:
    if not shutil.which("docker"):
        pytest.skip("Docker CLI is unavailable")
    check = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True, check=False)
    if check.returncode != 0:
        pytest.skip("Docker Compose plugin is unavailable")
    return ["docker", "compose"]


def _environment(tmp_path: Path) -> dict[str, str]:
    allocation = tmp_path / "allocations.json"
    allocation.write_text('{"schema_version":1,"leases":[],"allocations":[]}', encoding="utf-8")
    approval = tmp_path / "approval-secret-ref"
    approval.write_text("fixture-path-only", encoding="utf-8")
    identity = tmp_path / "identity-secret-ref"
    identity.write_text("fixture-path-only-identity-secret", encoding="utf-8")
    compatibility = tmp_path / "compatibility-token-ref"
    compatibility.write_text("fixture-path-only-compatibility-token", encoding="utf-8")
    return {
        **os.environ,
        "COMPOSE_PROJECT_NAME": "omni-contract-fixture",
        "OMNI_RUNTIME_ID": "runtime-fixture",
        "OMNI_ALLOCATION_ID": "allocation-" + "a" * 32,
        "OMNI_WORKTREE_ID": "worktree-" + "b" * 16,
        "OMNI_WORKTREE_ROOT": str(ROOT).replace("\\", "/"),
        "OMNI_SOURCE_COMMIT": "c" * 40,
        "OMNI_SOURCE_FINGERPRINT": "d" * 64,
        "OMNI_ALLOCATED_PORTS_SHA256": "e" * 64,
        "OMNI_ALLOCATED_VOLUMES_SHA256": "f" * 64,
        "OMNI_RUNTIME_ALLOCATION_SOURCE": str(allocation).replace("\\", "/"),
        "OMNI_DATABASE_DISPOSABLE": "true",
        "OMNI_RESTART_POLICY": "no",
        "OMNI_APPROVAL_WORKER_ENABLED": "true",
        "OMNI_APPROVAL_WORKER_ROLE": "owner",
        "OMNI_APPROVAL_HMAC_SECRET_FILE": str(approval).replace("\\", "/"),
        "OMNI_IDENTITY_JWT_SECRET_FILE": str(identity).replace("\\", "/"),
        "OMNI_COMPATIBILITY_TOKEN_FILE": str(compatibility).replace("\\", "/"),
        "POSTGRES_USER": "omni_user",
        "POSTGRES_PASSWORD": "fixture-placeholder",
        "REDIS_PASSWORD": "fixture-placeholder",
    }


def _config(relative: str, env: dict[str, str], *, migration_profile: bool = False) -> dict:
    profile = ["--profile", "migration"] if migration_profile else []
    result = subprocess.run(
        [*_compose(), "-f", relative, *profile, "config", "--format", "json"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.lstrip("\ufeff"))


def _depends_on_preflight(services: dict, service: str, seen: set[str] | None = None) -> bool:
    if service == "runtime-preflight":
        return True
    visited = set(seen or ())
    if service in visited:
        return False
    visited.add(service)
    dependencies = services[service].get("depends_on") or {}
    if "runtime-preflight" in dependencies:
        return dependencies["runtime-preflight"].get("condition") == "service_completed_successfully"
    return any(
        dependency in services and _depends_on_preflight(services, dependency, visited) for dependency in dependencies
    )


def _depends_on_service(services: dict, service: str, required: str, seen: set[str] | None = None) -> bool:
    if service == required:
        return True
    visited = set(seen or ())
    if service in visited:
        return False
    visited.add(service)
    dependencies = services[service].get("depends_on") or {}
    if required in dependencies:
        return dependencies[required].get("condition") == "service_completed_successfully"
    return any(
        dependency in services and _depends_on_service(services, dependency, required, visited)
        for dependency in dependencies
    )


def test_direct_compose_config_fails_before_runtime_without_allocation(
    tmp_path: Path,
) -> None:
    env = _environment(tmp_path)
    for name in (
        "COMPOSE_PROJECT_NAME",
        "OMNI_RUNTIME_ID",
        "OMNI_ALLOCATION_ID",
        "OMNI_WORKTREE_ID",
        "OMNI_WORKTREE_ROOT",
        "OMNI_SOURCE_COMMIT",
        "OMNI_SOURCE_FINGERPRINT",
        "OMNI_RUNTIME_ALLOCATION_SOURCE",
    ):
        env.pop(name, None)
    result = subprocess.run(
        [*_compose(), "-f", "docker-compose.yml", "config", "--quiet"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "RuntimeAllocation" in result.stderr or "required variable" in result.stderr


@pytest.mark.parametrize("relative", COMPOSE_FILES)
def test_parsed_compose_requires_preflight_and_bakes_build_identity(relative: str, tmp_path: Path) -> None:
    config = _config(relative, _environment(tmp_path))
    services = config["services"]
    preflight = services["runtime-preflight"]
    assert preflight["command"] == ["allocation-preflight", "--json"]
    assert preflight["entrypoint"] == [
        "python",
        "-B",
        "/workspace/scripts/runtime_guard.py",
    ]
    assert any(
        item["target"] == "/runtime-state/allocations.json" and item["read_only"] for item in preflight["volumes"]
    )
    assert all(_depends_on_preflight(services, name) for name in services)
    for name in ("runtime-preflight", "migrate"):
        arguments = services[name]["build"]["args"]
        assert arguments["OMNI_BUILD_COMMIT"] == "c" * 40
        assert arguments["OMNI_BUILD_SOURCE_FINGERPRINT"] == "d" * 64

    for service in services.values():
        build = service.get("build")
        if not isinstance(build, dict):
            continue
        labels = build.get("labels") or {}
        assert labels["io.omni.build.source_commit"] == "c" * 40
        assert labels["io.omni.build.source_fingerprint"] == "d" * 64

    migration_dockerfile = (ROOT / "services" / "infra-core" / "migrations" / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG OMNI_BUILD_COMMIT=" in migration_dockerfile
    assert "OMNI_BUILD_COMMIT=${OMNI_BUILD_COMMIT}" in migration_dockerfile


def test_parsed_knowledge_engine_environment_is_not_unknown(tmp_path: Path) -> None:
    for relative in ("docker-compose.yml", "services/docker-compose.sp1-sp4.yml"):
        config = _config(relative, _environment(tmp_path), migration_profile=True)
        engine = config["services"]["knowledge-engine"]
        environment = engine["environment"]
        assert environment["OMNI_ALLOCATION_ID"] == "allocation-" + "a" * 32
        assert environment["OMNI_WORKTREE_ID"] == "worktree-" + "b" * 16
        assert "OMNI_BUILD_COMMIT" not in environment
        assert environment["OMNI_EXPECTED_COMMIT"] == "c" * 40
        assert environment["OMNI_SOURCE_FINGERPRINT"] == "d" * 64
        assert engine["build"]["args"]["OMNI_BUILD_COMMIT"] == "c" * 40
        assert engine["build"]["args"]["OMNI_BUILD_SOURCE_FINGERPRINT"] == "d" * 64
        assert environment["OMNI_APPROVAL_WORKER_ENABLED"] == "true"
        assert environment["OMNI_SCHEDULER_ENABLED"] == "false"
        assert engine["labels"]["io.omni.approval_worker_role"] == "owner"
        assert environment["OMNI_APPROVAL_SERVICE_SECRET_FILE"] == "/run/secrets/omni_approval_hmac"
        assert "OMNI_APPROVAL_SERVICE_TOKEN" not in environment
        assert any(
            item["target"] == "/run/secrets/omni_approval_hmac" and item["read_only"] for item in engine["volumes"]
        )
        labels = engine["labels"]
        assert labels["io.omni.worktree_id"] == "worktree-" + "b" * 16
        assert "io.omni.worktree_root" not in labels
        assert str(ROOT).replace("\\", "/").casefold() not in json.dumps(labels).casefold()


def test_every_compose_built_application_bakes_observed_source_identity(
    tmp_path: Path,
) -> None:
    for relative in ("docker-compose.yml", "services/docker-compose.sp1-sp4.yml"):
        services = _config(relative, _environment(tmp_path))["services"]
        for name in BUILD_IDENTIFIED_SERVICES & set(services):
            arguments = services[name]["build"]["args"]
            assert arguments["OMNI_BUILD_COMMIT"] == "c" * 40, (relative, name)
            assert arguments["OMNI_BUILD_SOURCE_FINGERPRINT"] == "d" * 64, (
                relative,
                name,
            )

    dockerfiles = {
        "identity-service": "services/identity-service/Dockerfile",
        "ai-provider-hub": "services/ai-provider-hub/Dockerfile",
        "news-aggregator": "services/news-aggregator/Dockerfile",
        "video-analysis": "services/video-analysis/Dockerfile",
        "livestream-analysis": "services/livestream-analysis/Dockerfile",
        "ad-review-service": "services/ad-review-service/Dockerfile",
        "scout-agent": "services/scout-agent/Dockerfile",
    }
    for name, relative in dockerfiles.items():
        content = (ROOT / relative).read_text(encoding="utf-8")
        assert "ARG OMNI_BUILD_COMMIT=" in content, name
        assert "ARG OMNI_BUILD_SOURCE_FINGERPRINT=" in content, name
        assert "OMNI_BUILD_COMMIT=${OMNI_BUILD_COMMIT}" in content, name
        assert "OMNI_BUILD_SOURCE_FINGERPRINT=${OMNI_BUILD_SOURCE_FINGERPRINT}" in content, name
    news = (ROOT / dockerfiles["news-aggregator"]).read_text(encoding="utf-8")
    assert "alembic upgrade" not in news


def test_verified_root_compose_does_not_bind_mount_over_baked_application_code(
    tmp_path: Path,
) -> None:
    services = _config("docker-compose.yml", _environment(tmp_path))["services"]
    forbidden = {
        "knowledge-engine": {"/app/app", "/app/config", "/app/scripts", "/app/tests"},
        "scout-agent": {"/app/app", "/app/catalog", "/app/scripts"},
    }
    for service, targets in forbidden.items():
        observed = {item["target"] for item in services[service].get("volumes", [])}
        assert observed.isdisjoint(targets), (service, observed & targets)


def test_frontend_uses_container_identity_service_and_file_backed_approval_secret(
    tmp_path: Path,
) -> None:
    for relative in ("docker-compose.yml", "services/docker-compose.sp1-sp4.yml"):
        config = _config(relative, _environment(tmp_path))
        frontend = config["services"]["frontend"]
        environment = frontend["environment"]
        assert environment["IDENTITY_SERVICE_URL"] == "http://identity-service:8000"
        assert environment["OMNI_APPROVAL_SERVICE_SECRET_FILE"] == ("/run/secrets/omni_approval_hmac")
        assert "OMNI_APPROVAL_SERVICE_TOKEN" not in environment
        assert any(
            item["target"] == "/run/secrets/omni_approval_hmac" and item["read_only"] for item in frontend["volumes"]
        )
        assert environment["OMNI_COMPATIBILITY_TOKEN_FILE"] == ("/run/secrets/omni_compatibility")
        assert any(
            item["target"] == "/run/secrets/omni_compatibility" and item["read_only"] for item in frontend["volumes"]
        )
        knowledge = config["services"]["knowledge-engine"]
        assert knowledge["environment"]["OMNI_COMPATIBILITY_TOKEN_FILE"] == ("/run/secrets/omni_compatibility")
        assert any(
            item["target"] == "/run/secrets/omni_compatibility" and item["read_only"] for item in knowledge["volumes"]
        )
        identity = config["services"]["identity-service"]
        assert frontend["depends_on"]["identity-service"]["condition"] == "service_healthy"
        if relative == "docker-compose.yml":
            assert identity["depends_on"] == {
                "migrate": {
                    "condition": "service_completed_successfully",
                    "required": True,
                },
                "postgres": {"condition": "service_healthy", "required": True},
                "redis": {"condition": "service_healthy", "required": True},
            }
        assert identity["environment"]["JWT_SECRET_KEY_FILE"] == ("/run/secrets/omni_identity_jwt")
        assert "JWT_SECRET_KEY" not in identity["environment"]
        assert any(
            item["target"] == "/run/secrets/omni_identity_jwt" and item["read_only"] for item in identity["volumes"]
        )


def test_frontend_build_receives_explicit_unified_shell_rollback_flag(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    environment["NEXT_PUBLIC_OMNI_UNIFIED_SHELL"] = "0"
    for relative in ("docker-compose.yml", "services/docker-compose.sp1-sp4.yml"):
        config = _config(relative, environment)
        assert config["services"]["frontend"]["build"]["args"]["NEXT_PUBLIC_OMNI_UNIFIED_SHELL"] == "0"
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    arg = "ARG NEXT_PUBLIC_OMNI_UNIFIED_SHELL=true"
    env = "ENV NEXT_PUBLIC_OMNI_UNIFIED_SHELL=${NEXT_PUBLIC_OMNI_UNIFIED_SHELL}"
    assert arg in dockerfile and env in dockerfile
    assert dockerfile.index(arg) < dockerfile.index(env) < dockerfile.index("RUN npm run build")


def test_noncanonical_scheduler_is_disabled_in_all_parsed_surfaces(
    tmp_path: Path,
) -> None:
    manifest = json.loads((ROOT / "config" / "runtime-manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["scheduler"]["default_enabled"] is False
    assert manifest["scheduler"]["canonical_enablement"] == ("explicit_runtime_allocation_only")
    assert manifest["services"]["knowledge-engine"]["scheduler_default"] is False
    for relative in ("docker-compose.yml", "services/docker-compose.sp1-sp4.yml"):
        config = _config(relative, _environment(tmp_path))
        for service in config["services"].values():
            environment = service.get("environment") or {}
            scheduler_values = [
                environment[key] for key in ("OMNI_SCHEDULER_ENABLED", "ENABLE_SCHEDULER") if key in environment
            ]
            assert all(str(value).casefold() == "false" for value in scheduler_values)
            labels = service.get("labels") or {}
            if "io.omni.scheduler_role" in labels:
                assert labels["io.omni.scheduler_role"] == "disabled"
    root = _config("docker-compose.yml", _environment(tmp_path))
    assert root["services"]["postgres"]["restart"] == "no"
    assert root["services"]["scout-agent"]["restart"] == "no"


def test_every_writable_application_waits_for_full_migration_runner(
    tmp_path: Path,
) -> None:
    non_writers = {
        "runtime-preflight",
        "postgres",
        "redis",
        "nginx",
        "frontend",
        "migrate",
    }
    for relative in COMPOSE_FILES:
        config = _config(relative, _environment(tmp_path))
        services = config["services"]
        assert "migrate" in services
        for name in set(services) - non_writers:
            assert _depends_on_service(services, name, "migrate"), f"{relative}:{name}"


def test_migration_service_uses_canonical_runner_and_immutable_receipt_directory(
    tmp_path: Path,
) -> None:
    for relative in COMPOSE_FILES:
        config = _config(relative, _environment(tmp_path))
        migration = config["services"]["migrate"]
        assert migration["command"] == [
            "--allocation-aware",
            "--receipt-dir",
            "/migration-receipts",
        ]
        assert migration["build"]["dockerfile"] == "services/infra-core/migrations/Dockerfile"
        assert "OMNI_ALLOW_SHARED_MIGRATION" not in migration["environment"]
        assert any(item["target"] == "/runtime-state/allocations.json" for item in migration["volumes"])
