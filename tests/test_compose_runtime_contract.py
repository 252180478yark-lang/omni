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
CORE_SERVICES = {
    "runtime-preflight",
    "postgres",
    "redis",
    "migrate",
    "ai-provider-hub",
    "knowledge-engine",
    "frontend",
}
CONTENT_SERVICES = CORE_SERVICES | {
    "video-analysis",
    "livestream-analysis",
    "scout-agent",
}
FULL_SERVICES = CONTENT_SERVICES | {
    "news-aggregator",
    "ad-review-service",
    "nginx",
}
ONE_SHOT_SERVICES = {"runtime-preflight", "migrate"}


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
    runtime_trace = tmp_path / "runtime-trace-token-ref"
    runtime_trace.write_text("fixture-path-only-runtime-trace-token", encoding="utf-8")
    return {
        **os.environ,
        "COMPOSE_PROJECT_NAME": "omni-contract-fixture",
        "OMNI_RUNTIME_ID": "runtime-fixture",
        "OMNI_RUNTIME_PROFILE": "core",
        "COMPOSE_PROFILES": "",
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
        "OMNI_RUNTIME_TRACE_TOKEN_FILE": str(runtime_trace).replace("\\", "/"),
        "OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE": str(runtime_trace).replace("\\", "/"),
        "POSTGRES_USER": "omni_user",
        "POSTGRES_PASSWORD": "fixture-placeholder",
        "REDIS_PASSWORD": "fixture-placeholder",
    }


def _config(
    relative: str,
    env: dict[str, str],
    *,
    profiles: tuple[str, ...] = (),
    migration_profile: bool = False,
) -> dict:
    requested_profiles = (*profiles, *(("migration",) if migration_profile else ()))
    profile = [item for name in requested_profiles for item in ("--profile", name)]
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


def _root_config(tmp_path: Path, *profiles: str) -> dict:
    return _config("docker-compose.yml", _environment(tmp_path), profiles=profiles)


def _dependency_conditions(service: dict) -> dict[str, str]:
    return {
        name: specification["condition"]
        for name, specification in (service.get("depends_on") or {}).items()
    }


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


@pytest.mark.parametrize(
    ("profiles", "expected_services"),
    (
        ((), CORE_SERVICES),
        (("content",), CONTENT_SERVICES),
        (("full",), FULL_SERVICES),
    ),
)
def test_root_compose_projects_exact_runtime_service_sets(
    tmp_path: Path,
    profiles: tuple[str, ...],
    expected_services: set[str],
) -> None:
    config = _root_config(tmp_path, *profiles)
    assert set(config["services"]) == expected_services
    assert set(config["services"]) - ONE_SHOT_SERVICES == expected_services - ONE_SHOT_SERVICES


@pytest.mark.parametrize(
    ("runtime_profile", "compose_profiles", "expected_services"),
    (
        ("core", "", CORE_SERVICES),
        ("content", "content", CONTENT_SERVICES),
        ("full", "full", FULL_SERVICES),
    ),
)
def test_allocation_profile_environment_selects_exact_compose_projection(
    tmp_path: Path,
    runtime_profile: str,
    compose_profiles: str,
    expected_services: set[str],
) -> None:
    env = _environment(tmp_path)
    env["OMNI_RUNTIME_PROFILE"] = runtime_profile
    env["COMPOSE_PROFILES"] = compose_profiles
    config = _config("docker-compose.yml", env)
    assert set(config["services"]) == expected_services


def test_runtime_manifest_is_the_profile_and_required_service_truth() -> None:
    manifest = json.loads((ROOT / "config" / "runtime-manifest.yaml").read_text(encoding="utf-8"))
    runtime_profiles = manifest["runtime_profiles"]
    assert runtime_profiles["default"] == "core"

    expected_sets = {
        "core": CORE_SERVICES,
        "content": CONTENT_SERVICES,
        "full": FULL_SERVICES,
    }
    assert set(runtime_profiles["profiles"]) == set(expected_sets)
    for profile_name, expected_services in expected_sets.items():
        specification = runtime_profiles["profiles"][profile_name]
        assert set(specification["services"]) == expected_services
        assert set(specification["long_lived_services"]) == expected_services - ONE_SHOT_SERVICES
        assert set(specification["one_shot_services"]) == ONE_SHOT_SERVICES

    assert runtime_profiles["profiles"]["core"]["compose_profiles"] == []
    assert runtime_profiles["profiles"]["content"]["compose_profiles"] == ["content"]
    assert runtime_profiles["profiles"]["full"]["compose_profiles"] == ["full"]

    services = manifest["services"]
    assert set(services) == FULL_SERVICES | {"identity-service"}
    assert {name for name, specification in services.items() if specification["required"]} == (
        CORE_SERVICES - ONE_SHOT_SERVICES
    )
    for service_name in FULL_SERVICES:
        expected_membership = [
            profile_name
            for profile_name in ("core", "content", "full")
            if service_name in expected_sets[profile_name]
        ]
        assert services[service_name]["runtime_profiles"] == expected_membership


def test_full_profile_preserves_dependency_contract_except_optional_frontend_edges(
    tmp_path: Path,
) -> None:
    services = _root_config(tmp_path, "full")["services"]
    expected = {
        "runtime-preflight": {},
        "postgres": {"runtime-preflight": "service_completed_successfully"},
        "redis": {"runtime-preflight": "service_completed_successfully"},
        "migrate": {"postgres": "service_healthy"},
        "ai-provider-hub": {
            "migrate": "service_completed_successfully",
            "postgres": "service_healthy",
            "redis": "service_healthy",
        },
        "knowledge-engine": {
            "migrate": "service_completed_successfully",
            "postgres": "service_healthy",
            "redis": "service_healthy",
        },
        "frontend": {
            "migrate": "service_completed_successfully",
            "runtime-preflight": "service_completed_successfully",
            "ai-provider-hub": "service_started",
            "knowledge-engine": "service_started",
        },
        "video-analysis": {
            "migrate": "service_completed_successfully",
            "postgres": "service_healthy",
            "ai-provider-hub": "service_started",
        },
        "livestream-analysis": {
            "migrate": "service_completed_successfully",
            "postgres": "service_healthy",
            "ai-provider-hub": "service_started",
        },
        "scout-agent": {
            "migrate": "service_completed_successfully",
            "postgres": "service_healthy",
            "ai-provider-hub": "service_started",
            "knowledge-engine": "service_started",
        },
        "news-aggregator": {
            "migrate": "service_completed_successfully",
            "postgres": "service_healthy",
            "redis": "service_healthy",
            "ai-provider-hub": "service_started",
            "knowledge-engine": "service_started",
        },
        "ad-review-service": {
            "migrate": "service_completed_successfully",
            "postgres": "service_healthy",
            "redis": "service_healthy",
            "ai-provider-hub": "service_started",
            "knowledge-engine": "service_started",
            "video-analysis": "service_started",
        },
        "nginx": {
            "postgres": "service_healthy",
            "redis": "service_healthy",
            "frontend": "service_started",
            "ai-provider-hub": "service_started",
            "knowledge-engine": "service_started",
            "news-aggregator": "service_started",
            "video-analysis": "service_started",
            "livestream-analysis": "service_started",
            "ad-review-service": "service_started",
        },
    }
    assert {name: _dependency_conditions(service) for name, service in services.items()} == expected
    assert "ad-review-service" not in services["frontend"]["depends_on"]
    assert "scout-agent" not in services["frontend"]["depends_on"]


def test_full_profile_preserves_published_ports_and_named_volumes(tmp_path: Path) -> None:
    config = _root_config(tmp_path, "full")
    services = config["services"]
    observed_ports = {
        (service_name, int(binding["target"])): int(binding["published"])
        for service_name, service in services.items()
        for binding in service.get("ports", [])
    }
    assert observed_ports == {
        ("postgres", 5432): 5432,
        ("redis", 6379): 6379,
        ("nginx", 80): 80,
        ("nginx", 443): 443,
        ("frontend", 3000): 3000,
        ("ad-review-service", 8008): 8008,
        ("ai-provider-hub", 8001): 8001,
        ("knowledge-engine", 8002): 8002,
        ("scout-agent", 8009): 8009,
    }

    expected_volume_names = {
        "postgres_data": "omni_postgres_data",
        "redis_data": "omni_redis_data",
        "ai_hub_data": "omni-contract-fixture_ai_hub_data",
        "knowledge_data": "omni_knowledge_data",
        "video_analysis_data": "omni-contract-fixture_video_analysis_data",
        "livestream_analysis_data": "omni-contract-fixture_livestream_analysis_data",
        "ad_review_data": "omni-contract-fixture_ad_review_data",
    }
    assert {name: definition["name"] for name, definition in config["volumes"].items()} == expected_volume_names
    volume_contract = {
        "postgres": ("postgres_data", "/var/lib/postgresql/data"),
        "redis": ("redis_data", "/data"),
        "ai-provider-hub": ("ai_hub_data", "/app/data"),
        "knowledge-engine": ("knowledge_data", "/app/data"),
        "video-analysis": ("video_analysis_data", "/app/data"),
        "livestream-analysis": ("livestream_analysis_data", "/app/data"),
        "ad-review-service": ("ad_review_data", "/app/data"),
    }
    for service_name, (volume_name, target) in volume_contract.items():
        assert any(
            mount["type"] == "volume"
            and mount["source"] == volume_name
            and mount["target"] == target
            for mount in services[service_name].get("volumes", [])
        ), service_name


@pytest.mark.parametrize(
    ("profile_name", "compose_profiles"),
    (
        ("core", ()),
        ("content", ("content",)),
        ("full", ("full",)),
    ),
)
def test_every_profile_long_lived_service_has_a_consistent_health_contract(
    tmp_path: Path,
    profile_name: str,
    compose_profiles: tuple[str, ...],
) -> None:
    manifest = json.loads((ROOT / "config" / "runtime-manifest.yaml").read_text(encoding="utf-8"))
    compose_services = _root_config(tmp_path, *compose_profiles)["services"]
    long_lived_services = manifest["runtime_profiles"]["profiles"][profile_name][
        "long_lived_services"
    ]
    docker_probe_tokens = {
        "postgres": "pg_isready",
        "redis": "redis-cli",
        "identity-service": "127.0.0.1:8000/health",
        "news-aggregator": "127.0.0.1:8005/health",
        "video-analysis": "127.0.0.1:8006/health",
        "livestream-analysis": "127.0.0.1:8007/health",
        "nginx": "127.0.0.1/health",
    }

    for service_name in long_lived_services:
        manifest_health = manifest["services"][service_name].get("health") or {}
        assert manifest_health.get("kind") in {"docker", "http"}, service_name

        compose_service = compose_services[service_name]
        compose_healthcheck = compose_service.get("healthcheck") or {}
        compose_probe = " ".join(compose_healthcheck.get("test") or ())
        host_published_targets = {
            int(binding["target"])
            for binding in compose_service.get("ports", [])
            if binding.get("published") is not None
        }

        if manifest_health["kind"] == "docker":
            assert compose_probe, service_name
            assert docker_probe_tokens[service_name] in compose_probe, service_name
            continue

        manifest_ports = {int(port) for port in manifest["services"][service_name]["published_ports"]}
        assert manifest_ports <= host_published_targets, service_name
        path = str(manifest_health.get("path") or "").strip("/")
        if compose_probe:
            assert any(
                f"127.0.0.1:{port}/" + path in compose_probe
                for port in manifest_ports
            ), service_name


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
        if relative == "docker-compose.yml":
            assert environment["OMNI_APPROVAL_AUTH_MODE"] == "trusted-local"
            assert "OMNI_APPROVAL_SERVICE_SECRET_FILE" not in environment
            assert not any(item["target"] == "/run/secrets/omni_approval_hmac" for item in engine["volumes"])
        else:
            assert environment["OMNI_APPROVAL_SERVICE_SECRET_FILE"] == "/run/secrets/omni_approval_hmac"
            assert any(
                item["target"] == "/run/secrets/omni_approval_hmac" and item["read_only"] for item in engine["volumes"]
            )
        assert "OMNI_APPROVAL_SERVICE_TOKEN" not in environment
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
    services = _root_config(tmp_path, "full")["services"]
    forbidden = {
        "knowledge-engine": {"/app/app", "/app/config", "/app/scripts", "/app/tests"},
        "scout-agent": {"/app/app", "/app/catalog", "/app/scripts"},
    }
    for service, targets in forbidden.items():
        observed = {item["target"] for item in services[service].get("volumes", [])}
        assert observed.isdisjoint(targets), (service, observed & targets)


def test_root_frontend_uses_single_user_local_trust_without_product_identity_or_internal_auth_secrets(
    tmp_path: Path,
) -> None:
    config = _config("docker-compose.yml", _environment(tmp_path))
    assert "identity-service" not in config["services"]
    frontend = config["services"]["frontend"]
    knowledge = config["services"]["knowledge-engine"]
    assert "identity-service" not in frontend["depends_on"]
    assert "IDENTITY_SERVICE_URL" not in frontend["environment"]
    for service in (frontend, knowledge):
        environment = service["environment"]
        assert environment["OMNI_APPROVAL_AUTH_MODE"] == "trusted-local"
        assert "OMNI_APPROVAL_SERVICE_SECRET_FILE" not in environment
        assert "OMNI_RUNTIME_TRACE_TOKEN_FILE" not in environment
        assert "OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE" not in environment
        targets = {item["target"] for item in service.get("volumes", [])}
        assert "/run/secrets/omni_approval_hmac" not in targets
        assert "/run/secrets/omni_runtime_trace" not in targets
    assert knowledge["environment"]["OMNI_TRUSTED_LOCAL_PRINCIPAL"] == "local-owner"


def test_runtime_trace_token_is_file_backed_for_only_the_compose_consumers(
    tmp_path: Path,
) -> None:
    for relative in ("docker-compose.yml", "services/docker-compose.sp1-sp4.yml"):
        fixture_environment = _environment(tmp_path)
        fixture_environment["OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE"] = str(
            tmp_path / "must-not-be-mounted-runtime-trace-token"
        ).replace("\\", "/")
        config = _config(
            relative,
            fixture_environment,
            profiles=(("full",) if relative == "docker-compose.yml" else ()),
        )
        services = config["services"]
        expected_aliases = (
            {"scout-agent": "OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE"}
            if relative == "docker-compose.yml"
            else {"frontend": "OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE", "knowledge-engine": "OMNI_RUNTIME_TRACE_TOKEN_FILE"}
        )

        for service_name, alias in expected_aliases.items():
            service = services[service_name]
            environment = service.get("environment") or {}
            assert environment[alias] == "/run/secrets/omni_runtime_trace"
            assert any(
                item["target"] == "/run/secrets/omni_runtime_trace"
                and item["read_only"]
                and item["source"] == fixture_environment["OMNI_RUNTIME_TRACE_TOKEN_FILE"]
                for item in service.get("volumes", [])
            ), (relative, service_name)

        if relative == "docker-compose.yml":
            assert services["scout-agent"]["environment"]["OMNI_KE_URL"] == "http://knowledge-engine:8002"
            assert services["scout-agent"]["depends_on"]["knowledge-engine"]["condition"] == "service_started"

        for service_name, service in services.items():
            environment = service.get("environment") or {}
            aliases = {
                key for key in environment
                if key in {"OMNI_RUNTIME_TRACE_TOKEN_FILE", "OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE"}
            }
            expected = {expected_aliases[service_name]} if service_name in expected_aliases else set()
            assert aliases == expected, (relative, service_name, aliases)
            assert "OMNI_RUNTIME_TRACE_TOKEN" not in environment
            assert "OMNI_RUNTIME_TRACE_SERVICE_TOKEN" not in environment

        serialized = json.dumps(config, sort_keys=True)
        assert "fixture-path-only-runtime-trace-token" not in serialized


def test_runtime_trace_user_configuration_exposes_only_the_canonical_source() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    host_bridge = (ROOT / "docs" / "multi-device" / "host-bridge.md").read_text(encoding="utf-8")
    assert "OMNI_RUNTIME_TRACE_TOKEN_FILE=" in example
    assert "OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE=" not in example
    assert "OMNI_RUNTIME_TRACE_TOKEN_FILE" in host_bridge
    assert "OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE" not in host_bridge


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
    root = _root_config(tmp_path, "full")
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
        config = _config(
            relative,
            _environment(tmp_path),
            profiles=(("full",) if relative == "docker-compose.yml" else ()),
        )
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
