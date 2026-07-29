from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import httpx
import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.schemas.system_health import DependencyRegistration, HealthState, ProbeResult
from app.services.health_registry import (
    DependencySpec,
    FeatureSpec,
    HealthRegistry,
    current_build_identity,
    aggregate_state,
    derive_dependency_health,
    derive_feature_health,
    http_probe,
    local_approval_worker_probe,
    readiness_state,
)


NOW = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)


def sample(**changes) -> ProbeResult:
    values = {
        "availability": True,
        "authenticated": True,
        "readable": True,
        "latest_data_at": NOW,
        "observed_build": "abc1234",
        "observed_at": NOW,
    }
    values.update(changes)
    return ProbeResult(**values)


def dependency(probe: ProbeResult, **registration_changes):
    spec = DependencySpec(ref="health_registration:service:svc", dependency_id="svc", required=True)
    registration = DependencyRegistration(
        dependency_id="svc",
        freshness_seconds=60,
        expected_build="abc1234",
        **registration_changes,
    )
    return derive_dependency_health(spec=spec, registration=registration, probe=probe, now=NOW)


@pytest.mark.parametrize(
    ("probe", "state", "reason"),
    [
        (sample(), HealthState.HEALTHY, None),
        (sample(availability=False), HealthState.UNAVAILABLE, "availability_failed"),
        (sample(availability=None), HealthState.UNKNOWN, "availability_unknown"),
        (
            sample(latest_data_at=NOW - timedelta(seconds=61)),
            HealthState.STALE,
            "data_stale",
        ),
        (sample(observed_build="old"), HealthState.STALE, "build_identity_mismatch"),
    ],
)
def test_dependency_derives_five_state_evidence(probe, state, reason):
    result = dependency(probe)
    assert result.state is state
    if reason:
        assert reason in result.reason_codes


def test_missing_expected_build_is_unknown_not_green():
    spec = DependencySpec(ref="svc", dependency_id="svc", required=True)
    result = derive_dependency_health(
        spec=spec,
        registration=DependencyRegistration(dependency_id="svc"),
        probe=sample(),
        now=NOW,
    )
    assert result.state is HealthState.UNKNOWN
    assert "build_identity_unknown" in result.reason_codes


def test_optional_failure_degrades_but_required_unknown_stays_unknown():
    spec = FeatureSpec(
        feature_id="example",
        title="Example",
        dependencies=(
            DependencySpec(ref="required", dependency_id="required", required=True),
            DependencySpec(ref="optional", dependency_id="optional", required=False),
        ),
    )
    required = dependency(sample()).model_copy(
        update={"dependency_id": "required", "ref": "required", "required": True}
    )
    optional = dependency(sample(availability=False)).model_copy(
        update={"dependency_id": "optional", "ref": "optional", "required": False}
    )
    assert derive_feature_health(spec, [required, optional]).state is HealthState.DEGRADED

    unknown = required.model_copy(update={"state": HealthState.UNKNOWN})
    assert derive_feature_health(spec, [unknown, optional]).state is HealthState.UNKNOWN


def test_aggregate_keeps_deterministic_unavailable_over_partial_unknown():
    unavailable = derive_feature_health(
        FeatureSpec(
            feature_id="down",
            title="Down",
            dependencies=(DependencySpec(ref="down", dependency_id="down", required=True),),
        ),
        [dependency(sample(availability=False)).model_copy(update={"dependency_id": "down", "ref": "down"})],
    )
    unknown = unavailable.model_copy(update={"feature_id": "unknown", "state": HealthState.UNKNOWN})
    assert aggregate_state([unavailable, unknown]) is HealthState.UNAVAILABLE


def test_readiness_build_mismatch_and_unknown_are_not_healthy():
    from app.schemas.system_health import BuildIdentity

    mismatch = BuildIdentity(expected_commit="new", observed_commit="old")
    unknown = BuildIdentity(expected_commit="new")
    assert readiness_state(readable=True, identity=mismatch) == (
        HealthState.STALE,
        "build_identity_mismatch",
    )
    assert readiness_state(readable=True, identity=unknown) == (
        HealthState.UNKNOWN,
        "build_identity_unknown",
    )
    missing_baked_source = BuildIdentity(
        expected_commit="new",
        observed_commit="new",
        expected_source_fingerprint="sha256:expected",
    )
    assert readiness_state(readable=True, identity=missing_baked_source) == (
        HealthState.UNKNOWN,
        "build_source_fingerprint_unknown",
    )


def test_build_identity_exposes_runtime_allocation_coordinates(monkeypatch):
    monkeypatch.setenv("OMNI_DELIVERY_COMMIT", "expected")
    monkeypatch.setenv("OMNI_BUILD_COMMIT", "observed")
    monkeypatch.setenv("OMNI_SOURCE_FINGERPRINT", "sha256:expected")
    monkeypatch.setenv("OMNI_BUILD_SOURCE_FINGERPRINT", "sha256:abc")
    monkeypatch.setenv("OMNI_WORKTREE_ID", "wt-1")
    monkeypatch.setenv("OMNI_ALLOCATION_ID", "alloc-1")
    monkeypatch.setenv("OMNI_RUNTIME_ID", "runtime-1")
    identity = current_build_identity()
    assert identity.model_dump() == {
        "expected_commit": "expected",
        "observed_commit": "observed",
        "expected_source_fingerprint": "sha256:expected",
        "source_fingerprint": "sha256:abc",
        "worktree_id": "wt-1",
        "allocation_id": "alloc-1",
        "runtime_id": "runtime-1",
    }


def test_build_identity_never_uses_or_exposes_a_worktree_path(monkeypatch):
    monkeypatch.delenv("OMNI_WORKTREE_ID", raising=False)
    monkeypatch.setenv("OMNI_WORKTREE_ROOT", r"E:\agent\omni\.worktrees\private")
    assert current_build_identity().worktree_id is None

    monkeypatch.setenv("OMNI_WORKTREE_ID", r"E:\agent\omni\.worktrees\private")
    assert current_build_identity().worktree_id is None

    monkeypatch.setenv("OMNI_WORKTREE_ID", "wt-opaque-7")
    assert current_build_identity().worktree_id == "wt-opaque-7"


def test_runtime_expected_source_fingerprint_cannot_self_attest(monkeypatch):
    monkeypatch.delenv("OMNI_BUILD_SOURCE_FINGERPRINT", raising=False)
    monkeypatch.setenv("OMNI_SOURCE_FINGERPRINT", "sha256:runtime-expected")
    identity = current_build_identity()
    assert identity.expected_source_fingerprint == "sha256:runtime-expected"
    assert identity.source_fingerprint is None


def test_remote_dependency_identity_does_not_inherit_local_runtime_coordinates(monkeypatch):
    monkeypatch.setenv("OMNI_WORKTREE_ID", "local-wt")
    monkeypatch.setenv("OMNI_ALLOCATION_ID", "local-allocation")
    monkeypatch.setenv("OMNI_RUNTIME_ID", "local-runtime")
    result = dependency(sample())
    assert result.build_identity.model_dump() == {
        "expected_commit": "abc1234",
        "observed_commit": "abc1234",
        "expected_source_fingerprint": None,
        "source_fingerprint": None,
        "worktree_id": None,
        "allocation_id": None,
        "runtime_id": None,
    }


def test_naive_or_far_future_freshness_timestamp_is_unknown_not_green():
    naive = dependency(sample(latest_data_at=NOW.replace(tzinfo=None)))
    assert naive.state is HealthState.UNKNOWN
    assert "timestamp_timezone_unknown" in naive.reason_codes

    future = dependency(sample(latest_data_at=NOW + timedelta(seconds=301)))
    assert future.state is HealthState.UNKNOWN
    assert "freshness_in_future" in future.reason_codes

    tolerated_clock_skew = dependency(sample(latest_data_at=NOW + timedelta(seconds=30)))
    assert tolerated_clock_skew.state is HealthState.HEALTHY


def test_build_source_fingerprint_match_and_mismatch_are_evidence_based():
    spec = DependencySpec(ref="health:remote", dependency_id="remote", required=True)
    registration = DependencyRegistration(
        dependency_id="remote",
        expected_build="abc1234",
        expected_source_fingerprint="sha256:new",
    )
    matching = derive_dependency_health(
        spec=spec,
        registration=registration,
        probe=sample(observed_source_fingerprint="sha256:new"),
        now=NOW,
    )
    assert matching.state is HealthState.HEALTHY

    mismatch = derive_dependency_health(
        spec=spec,
        registration=registration,
        probe=sample(observed_source_fingerprint="sha256:old"),
        now=NOW,
    )
    assert mismatch.state is HealthState.STALE
    assert "build_source_fingerprint_mismatch" in mismatch.reason_codes

    missing = derive_dependency_health(
        spec=spec,
        registration=registration,
        probe=sample(observed_source_fingerprint=None),
        now=NOW,
    )
    assert missing.state is HealthState.UNKNOWN
    assert "build_source_fingerprint_unknown" in missing.reason_codes


@pytest.mark.asyncio
async def test_http_200_with_non_json_read_body_is_not_readable(monkeypatch):
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"commit": "abc1234"})
        return httpx.Response(200, text="<html>not a data contract</html>")

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        http_probe.__globals__["httpx"],
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, timeout=kwargs.get("timeout")),
    )
    result = await http_probe(
        DependencyRegistration(
            dependency_id="remote",
            base_url="http://remote.test",
            read_path="/read",
            expected_build="abc1234",
        )
    )
    assert result.availability is True
    assert result.readable is False
    assert "read_response_invalid_json" in result.reason_codes


@pytest.mark.asyncio
async def test_http_200_with_declared_unhealthy_status_is_unavailable(monkeypatch):
    real_client = httpx.AsyncClient
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "unhealthy", "commit": "abc1234"})
        return httpx.Response(200, json={"readable": True})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        http_probe.__globals__["httpx"],
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, timeout=kwargs.get("timeout")),
    )
    result = await http_probe(
        DependencyRegistration(
            dependency_id="remote",
            base_url="http://remote.test",
            read_path="/read",
            expected_build="abc1234",
        )
    )
    assert result.availability is False
    assert result.readable is False
    assert "health_status_unhealthy" in result.reason_codes
    assert requested_paths == ["/health"]


@pytest.mark.asyncio
async def test_identity_readiness_requires_semantic_read_and_auth_evidence(monkeypatch):
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={
                    "status": "healthy",
                    "build_commit": "abc1234",
                    "build_source_fingerprint": "sha256:new",
                },
            )
        return httpx.Response(
            200,
            json={"status": "healthy", "readable": True, "authenticated": False},
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        http_probe.__globals__["httpx"],
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, timeout=kwargs.get("timeout")),
    )
    result = await http_probe(
        DependencyRegistration(
            dependency_id="identity-service",
            base_url="http://identity.test",
            read_path="/health/readiness",
            expected_build="abc1234",
            expected_source_fingerprint="sha256:new",
        )
    )
    health = derive_dependency_health(
        spec=DependencySpec(
            ref="health_registration:service:identity-service",
            dependency_id="identity-service",
            required=True,
        ),
        registration=DependencyRegistration(
            dependency_id="identity-service",
            expected_build="abc1234",
            expected_source_fingerprint="sha256:new",
        ),
        probe=result,
        now=NOW,
    )
    assert result.readable is True
    assert result.authenticated is False
    assert health.state is HealthState.UNAVAILABLE
    assert "authentication_failed" in health.reason_codes


@pytest.mark.asyncio
async def test_approval_worker_disabled_is_unavailable_not_healthy(monkeypatch):
    monkeypatch.delenv("OMNI_APPROVAL_WORKER_ENABLED", raising=False)
    probe = await local_approval_worker_probe(
        DependencyRegistration(dependency_id="approval-worker")
    )
    health = derive_dependency_health(
        spec=DependencySpec(
            ref="health_registration:service:approval-worker",
            dependency_id="approval-worker",
            required=True,
        ),
        registration=DependencyRegistration(dependency_id="approval-worker"),
        probe=probe,
        now=NOW,
    )
    assert probe.readable is False
    assert "approval_worker_disabled" in probe.reason_codes
    assert health.state is HealthState.UNAVAILABLE


@pytest.mark.asyncio
async def test_approval_worker_health_is_independent_from_cron_scheduler(monkeypatch):
    from app.workers.approval_operations import APPROVAL_WORKER_RUNTIME

    monkeypatch.setenv("OMNI_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("OMNI_APPROVAL_WORKER_ENABLED", "true")
    monkeypatch.setattr(APPROVAL_WORKER_RUNTIME, "running", True)
    monkeypatch.setattr(APPROVAL_WORKER_RUNTIME, "last_error_code", None)
    probe = await local_approval_worker_probe(
        DependencyRegistration(dependency_id="approval-worker")
    )
    assert probe.readable is True
    assert "approval_worker_disabled" not in probe.reason_codes


@pytest.mark.asyncio
async def test_registry_keeps_partial_probe_failure_unknown_and_out_of_percentage(tmp_path: Path):
    definition = tmp_path / "example.yaml"
    definition.write_text(
        "schema_version: 1\n"
        "feature_id: example\n"
        "title: Example\n"
        "dependencies:\n"
        "- ref: health_registration:service:svc\n"
        "  required: true\n",
        encoding="utf-8",
    )

    async def broken(_registration):
        raise RuntimeError("probe unavailable")

    registry = HealthRegistry(
        feature_directory=tmp_path,
        registrations={"svc": DependencyRegistration(dependency_id="svc", timeout_seconds=0.2)},
        probes={"svc": broken},
        now=lambda: NOW,
    )
    result = await registry.collect()

    assert result.state is HealthState.UNKNOWN
    assert result.healthy_percentage == 0
    assert result.partial is True
    assert result.errors[0].code == "probe_failed"
    assert result.features[0].state is HealthState.UNKNOWN


@pytest.mark.asyncio
async def test_registry_never_calls_http_for_unregistered_dependency(tmp_path: Path):
    (tmp_path / "example.yaml").write_text(
        "feature_id: example\ndependencies:\n- ref: health_registration:service:missing\n  required: true\n",
        encoding="utf-8",
    )
    result = await HealthRegistry(feature_directory=tmp_path, registrations={}, probes={}, now=lambda: NOW).collect()
    assert result.state is HealthState.UNKNOWN
    assert result.errors[0].code == "dependency_not_registered"


@pytest.mark.asyncio
async def test_registry_isolates_probe_interpretation_failure(tmp_path: Path, monkeypatch):
    (tmp_path / "example.yaml").write_text(
        "feature_id: example\ndependencies:\n- ref: health_registration:service:svc\n  required: true\n",
        encoding="utf-8",
    )

    async def successful_probe(_registration):
        return sample()

    def broken_interpreter(**_kwargs):
        raise RuntimeError("bad timestamp adapter")

    monkeypatch.setitem(
        HealthRegistry._one.__globals__, "derive_dependency_health", broken_interpreter
    )
    result = await HealthRegistry(
        feature_directory=tmp_path,
        registrations={"svc": DependencyRegistration(dependency_id="svc", expected_build="abc1234")},
        probes={"svc": successful_probe},
        now=lambda: NOW,
    ).collect()

    assert result.state is HealthState.UNKNOWN
    assert result.partial is True
    assert result.features[0].dependencies[0].state is HealthState.UNKNOWN
    assert result.errors[0].code == "probe_interpretation_failed"


@pytest.mark.asyncio
async def test_unmapped_visible_route_is_synthetic_unknown_and_prevents_100_percent(tmp_path: Path):
    (tmp_path / "mapped.yaml").write_text(
        "feature_id: mapped\n"
        "title: Mapped\n"
        "routes:\n  canonical: /mapped\n  visible: true\n"
        "aliases: []\n"
        "dependencies:\n- ref: health_registration:service:svc\n  required: true\n",
        encoding="utf-8",
    )

    async def successful_probe(_registration):
        return sample()

    result = await HealthRegistry(
        feature_directory=tmp_path,
        registrations={"svc": DependencyRegistration(dependency_id="svc", expected_build="abc1234")},
        probes={"svc": successful_probe},
        now=lambda: NOW,
        visible_hrefs=["/mapped", "/missing"],
    ).collect()

    assert result.state is HealthState.UNKNOWN
    assert result.healthy_percentage == 50
    assert result.partial is True
    assert {feature.href for feature in result.features} == {"/mapped", "/missing"}
    assert any(error.code == "visible_feature_definition_missing" for error in result.errors)


@pytest.mark.asyncio
async def test_unmapped_home_feature_id_is_synthetic_unknown(tmp_path: Path):
    (tmp_path / "mapped.yaml").write_text(
        "feature_id: mapped\n"
        "title: Mapped\n"
        "routes:\n  canonical: /mapped\n  visible: true\n"
        "aliases: []\n"
        "dependencies:\n- ref: health_registration:service:svc\n  required: true\n",
        encoding="utf-8",
    )

    async def successful_probe(_registration):
        return sample()

    result = await HealthRegistry(
        feature_directory=tmp_path,
        registrations={"svc": DependencyRegistration(dependency_id="svc", expected_build="abc1234")},
        probes={"svc": successful_probe},
        now=lambda: NOW,
        visible_hrefs=["/mapped"],
        visible_feature_ids=["missing-home"],
    ).collect()

    missing = next(feature for feature in result.features if feature.feature_id == "missing-home")
    assert missing.state is HealthState.UNKNOWN
    assert missing.href is None
    assert result.healthy_percentage == 50
    assert result.partial is True
