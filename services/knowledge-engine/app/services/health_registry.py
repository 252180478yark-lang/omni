"""FeatureDefinition-backed, five-state health aggregation.

HTTP 200 or a running container is only an availability signal.  A dependency
is healthy only after its configured read/auth/freshness/build checks have
enough evidence.  Probe failures remain typed partial results.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.schemas.system_health import (
    BuildIdentity,
    DependencyHealth,
    DependencyRegistration,
    FeatureHealth,
    HealthState,
    OperationError,
    ProbeResult,
    SystemHealthResponse,
)


Probe = Callable[[DependencyRegistration], Awaitable[ProbeResult]]
MAX_FUTURE_SKEW_SECONDS = 300


@dataclass(frozen=True)
class DependencySpec:
    ref: str
    dependency_id: str
    required: bool


@dataclass(frozen=True)
class FeatureSpec:
    feature_id: str
    title: str
    dependencies: tuple[DependencySpec, ...]
    href: str | None = None
    aliases: tuple[str, ...] = ()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _opaque_identifier(value: str | None) -> str | None:
    """Return an opaque runtime coordinate, never a host filesystem path."""

    if value is None:
        return None
    candidate = value.strip()
    if not candidate or "/" in candidate or "\\" in candidate or candidate in {".", ".."}:
        return None
    return candidate[:200]


def _build_evidence(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    return None if not candidate or candidate.lower() in {"unknown", "unset", "none"} else candidate


def current_build_identity() -> BuildIdentity:
    return BuildIdentity(
        expected_commit=_build_evidence(
            os.getenv("OMNI_DELIVERY_COMMIT")
            or os.getenv("OMNI_EXPECTED_COMMIT")
            or os.getenv("OMNI_SOURCE_COMMIT")
            or None
        ),
        observed_commit=_build_evidence(os.getenv("OMNI_BUILD_COMMIT")),
        expected_source_fingerprint=_build_evidence(os.getenv("OMNI_SOURCE_FINGERPRINT")),
        # Only image/build-time evidence is observed identity.  A runtime
        # expected fingerprint must never be able to self-attest an old image.
        source_fingerprint=_build_evidence(os.getenv("OMNI_BUILD_SOURCE_FINGERPRINT")),
        worktree_id=_opaque_identifier(os.getenv("OMNI_WORKTREE_ID")),
        allocation_id=_opaque_identifier(
            os.getenv("OMNI_ALLOCATION_ID") or os.getenv("OMNI_RUNTIME_ALLOCATION_ID")
        ),
        runtime_id=_opaque_identifier(os.getenv("OMNI_RUNTIME_ID")),
    )


def readiness_state(*, readable: bool | None, identity: BuildIdentity) -> tuple[HealthState, str]:
    if readable is False:
        return HealthState.UNAVAILABLE, "database_read_failed"
    if readable is None:
        return HealthState.UNKNOWN, "database_read_unknown"
    if not identity.expected_commit or not identity.observed_commit:
        return HealthState.UNKNOWN, "build_identity_unknown"
    if identity.expected_commit != identity.observed_commit:
        return HealthState.STALE, "build_identity_mismatch"
    if identity.expected_source_fingerprint:
        if not identity.source_fingerprint:
            return HealthState.UNKNOWN, "build_source_fingerprint_unknown"
        if identity.expected_source_fingerprint != identity.source_fingerprint:
            return HealthState.STALE, "build_source_fingerprint_mismatch"
    return HealthState.HEALTHY, "readiness_verified"


async def service_readiness() -> tuple[HealthState, str, BuildIdentity]:
    """Minimal trusted readiness: a real DB read plus comparable build identity."""

    from app.database import get_pool

    identity = current_build_identity()
    try:
        readable = await get_pool().fetchval("SELECT 1") == 1
    except Exception:
        readable = False
    state, reason = readiness_state(readable=readable, identity=identity)
    return state, reason, identity


def derive_dependency_health(
    *,
    spec: DependencySpec,
    registration: DependencyRegistration,
    probe: ProbeResult,
    now: datetime | None = None,
) -> DependencyHealth:
    now = now or utc_now()
    if now.tzinfo is None or now.utcoffset() is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    reasons = list(probe.reason_codes)
    state = HealthState.HEALTHY
    if probe.availability is False:
        state = HealthState.UNAVAILABLE
        reasons.append("availability_failed")
    elif probe.availability is None:
        state = HealthState.UNKNOWN
        reasons.append("availability_unknown")
    elif probe.authenticated is False:
        state = HealthState.UNAVAILABLE
        reasons.append("authentication_failed")
    elif probe.authenticated is None:
        state = HealthState.UNKNOWN
        reasons.append("authentication_unknown")
    elif probe.readable is False:
        state = HealthState.UNAVAILABLE
        reasons.append("read_failed")
    elif probe.readable is None:
        state = HealthState.UNKNOWN
        reasons.append("read_unknown")

    expected = registration.expected_build
    if state is HealthState.HEALTHY:
        if not expected or not probe.observed_build:
            state = HealthState.UNKNOWN
            reasons.append("build_identity_unknown")
        elif probe.observed_build != expected:
            state = HealthState.STALE
            reasons.append("build_identity_mismatch")

    if state is HealthState.HEALTHY and registration.expected_source_fingerprint:
        if not probe.observed_source_fingerprint:
            state = HealthState.UNKNOWN
            reasons.append("build_source_fingerprint_unknown")
        elif probe.observed_source_fingerprint != registration.expected_source_fingerprint:
            state = HealthState.STALE
            reasons.append("build_source_fingerprint_mismatch")

    if state is HealthState.HEALTHY and registration.freshness_seconds:
        if probe.latest_data_at is None:
            state = HealthState.UNKNOWN
            reasons.append("freshness_unknown")
        elif probe.latest_data_at.tzinfo is None or probe.latest_data_at.utcoffset() is None:
            state = HealthState.UNKNOWN
            reasons.append("timestamp_timezone_unknown")
        else:
            latest_data_at = probe.latest_data_at.astimezone(timezone.utc)
            future_skew = (latest_data_at - now).total_seconds()
            if future_skew > MAX_FUTURE_SKEW_SECONDS:
                state = HealthState.UNKNOWN
                reasons.append("freshness_in_future")
            elif max(0.0, (now - latest_data_at).total_seconds()) > registration.freshness_seconds:
                state = HealthState.STALE
                reasons.append("data_stale")

    return DependencyHealth(
        dependency_id=spec.dependency_id,
        ref=spec.ref,
        required=spec.required,
        state=state,
        reason_codes=list(dict.fromkeys(reasons)),
        latest_data_at=probe.latest_data_at,
        freshness_seconds=registration.freshness_seconds,
        build_identity=BuildIdentity(
            expected_commit=expected,
            observed_commit=probe.observed_build,
            expected_source_fingerprint=registration.expected_source_fingerprint,
            source_fingerprint=probe.observed_source_fingerprint,
        ),
        observed_at=probe.observed_at,
    )


def derive_feature_health(spec: FeatureSpec, dependencies: Sequence[DependencyHealth]) -> FeatureHealth:
    required = [item for item in dependencies if item.required]
    optional = [item for item in dependencies if not item.required]
    required_states = {item.state for item in required}
    if HealthState.UNAVAILABLE in required_states:
        state = HealthState.UNAVAILABLE
    elif HealthState.STALE in required_states:
        state = HealthState.STALE
    elif HealthState.UNKNOWN in required_states or not required:
        state = HealthState.UNKNOWN
    elif HealthState.DEGRADED in required_states:
        state = HealthState.DEGRADED
    elif any(item.state is not HealthState.HEALTHY for item in optional):
        state = HealthState.DEGRADED
    else:
        state = HealthState.HEALTHY
    reasons = [
        f"{item.dependency_id}:{reason}"
        for item in dependencies
        if item.state is not HealthState.HEALTHY
        for reason in (item.reason_codes or [item.state.value])
    ]
    return FeatureHealth(
        feature_id=spec.feature_id,
        title=spec.title,
        href=spec.href,
        state=state,
        dependencies=list(dependencies),
        reason_codes=reasons,
    )


def aggregate_state(features: Sequence[FeatureHealth]) -> HealthState:
    states = {feature.state for feature in features}
    if not features:
        return HealthState.UNKNOWN
    if HealthState.UNAVAILABLE in states:
        return HealthState.UNAVAILABLE
    if HealthState.STALE in states:
        return HealthState.STALE
    if HealthState.UNKNOWN in states:
        return HealthState.UNKNOWN
    if HealthState.DEGRADED in states:
        return HealthState.DEGRADED
    return HealthState.HEALTHY


def _dependency_id(ref: str) -> str:
    return ref.rsplit(":", 1)[-1]


def _frontend_projection(repo: Path) -> list[Mapping[str, Any]]:
    path = repo / "frontend" / "src" / "generated" / "feature-registry.v1.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        values = raw.get("frontend_registry", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [value for value in values if isinstance(value, Mapping)]


def discover_visible_frontend_hrefs(repo: Path) -> set[str]:
    """Read visible navigation from the generated canonical projection."""

    hrefs: set[str] = set()
    for item in _frontend_projection(repo):
        placements = set(item.get("placements") or [])
        if not item.get("visible") or not placements.intersection({"sidebar", "home", "onboarding"}):
            continue
        href = item.get("href")
        if isinstance(href, str):
            hrefs.add(href)
        for alias in item.get("aliases") or []:
            if isinstance(alias, Mapping) and isinstance(alias.get("href"), str):
                hrefs.add(alias["href"])
    return hrefs


def discover_visible_frontend_feature_ids(repo: Path) -> set[str]:
    return {
        str(item["feature_id"])
        for item in _frontend_projection(repo)
        if item.get("visible") and "home" in (item.get("placements") or []) and item.get("feature_id")
    }


def load_feature_specs(directory: Path) -> tuple[list[FeatureSpec], list[OperationError]]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return [], [
            OperationError(
                code="feature_definition_parser_unavailable",
                message="FeatureDefinition YAML parser is unavailable.",
                source="feature-definition",
                status=503,
                retryable=False,
            )
        ]
    features: list[FeatureSpec] = []
    errors: list[OperationError] = []
    seen_feature_ids: set[str] = set()
    for path in sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml")):
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(value, Mapping):
                raise ValueError("definition root must be an object")
            routes = value.get("routes")
            if isinstance(routes, Mapping) and routes.get("visible") is False:
                continue
            if value.get("lifecycle") in {"deprecated", "archived"}:
                continue
            href = routes.get("canonical") if isinstance(routes, Mapping) else None
            if href is not None and (not isinstance(href, str) or not href.startswith("/")):
                raise ValueError("routes.canonical must be an absolute application path")
            feature_id = str(value["feature_id"])
            if feature_id in seen_feature_ids:
                raise ValueError(f"duplicate feature_id: {feature_id}")
            raw_dependencies = value.get("dependencies", [])
            if not isinstance(raw_dependencies, Sequence) or isinstance(raw_dependencies, (str, bytes)):
                raise ValueError("dependencies must be an array")
            dependencies: list[DependencySpec] = []
            for raw in raw_dependencies:
                if not isinstance(raw, Mapping) or not raw.get("ref"):
                    raise ValueError("dependency ref is required")
                ref = str(raw["ref"])
                dependencies.append(
                    DependencySpec(ref=ref, dependency_id=_dependency_id(ref), required=bool(raw.get("required", True)))
                )
            raw_aliases = value.get("aliases", [])
            if not isinstance(raw_aliases, Sequence) or isinstance(raw_aliases, (str, bytes)):
                raise ValueError("aliases must be an array")
            aliases: list[str] = []
            for raw_alias in raw_aliases:
                if not isinstance(raw_alias, Mapping) or not isinstance(raw_alias.get("href"), str):
                    raise ValueError("alias href is required")
                alias = str(raw_alias["href"])
                if not alias.startswith("/"):
                    raise ValueError("alias href must be an absolute application path")
                aliases.append(alias)
            features.append(
                FeatureSpec(
                    feature_id=feature_id,
                    title=str(value.get("title") or value["feature_id"]),
                    dependencies=tuple(dependencies),
                    href=href,
                    aliases=tuple(aliases),
                )
            )
            seen_feature_ids.add(feature_id)
        except Exception as exc:
            errors.append(
                OperationError(
                    code="feature_definition_invalid",
                    message=str(exc),
                    source=path.name,
                    status=503,
                    retryable=False,
                )
            )
    if not features and not errors:
        errors.append(
            OperationError(
                code="feature_definition_unavailable",
                message="No FeatureDefinition was available; feature health is unknown.",
                source=str(directory),
                status=503,
                retryable=True,
            )
        )
    return features, errors


async def http_probe(registration: DependencyRegistration) -> ProbeResult:
    observed_at = utc_now()
    if not registration.base_url:
        return ProbeResult(observed_at=observed_at, reason_codes=["probe_not_registered"])
    base = registration.base_url.rstrip("/")
    timeout = httpx.Timeout(registration.timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        health_response = await client.get(f"{base}{registration.health_path}")
        availability = health_response.is_success
        authenticated: bool | None = None
        readable: bool | None = None
        observed_build: str | None = None
        observed_source_fingerprint: str | None = None
        latest_data_at: datetime | None = None
        reason_codes: list[str] = []
        body: Any = None
        if health_response.is_success:
            try:
                body = health_response.json()
            except ValueError:
                body = None
        if isinstance(body, Mapping):
            observed_build = str(body.get("build_commit") or body.get("commit") or "") or None
            observed_source_fingerprint = str(
                body.get("build_source_fingerprint") or body.get("source_fingerprint") or ""
            ) or None
            declared_status = str(body.get("status") or "").strip().lower()
            if (
                declared_status in {"unhealthy", "unavailable", "error", "down", "failed"}
                or body.get("success") is False
            ):
                availability = False
                reason_codes.append("health_status_unhealthy")
        if registration.read_path and availability:
            read_response = await client.get(f"{base}{registration.read_path}")
            authenticated = read_response.status_code not in {401, 403}
            if read_response.is_success:
                try:
                    read_body = read_response.json()
                except ValueError:
                    read_body = None
                    readable = False
                    reason_codes.append("read_response_invalid_json")
                else:
                    readable = isinstance(read_body, (Mapping, list))
                    if not readable:
                        reason_codes.append("read_response_invalid_schema")
                    elif isinstance(read_body, Mapping) and (
                        read_body.get("success") is False
                        or bool(read_body.get("error"))
                        or (
                            isinstance(read_body.get("code"), int)
                            and read_body.get("code") not in {0, 200}
                        )
                    ):
                        readable = False
                        reason_codes.append("read_response_error_envelope")
                if isinstance(read_body, Mapping):
                    if isinstance(read_body.get("authenticated"), bool):
                        authenticated = bool(read_body["authenticated"])
                        if not authenticated:
                            reason_codes.append("read_response_authentication_failed")
                    if isinstance(read_body.get("readable"), bool):
                        readable = bool(read_body["readable"])
                        if not readable:
                            reason_codes.append("read_response_declared_unreadable")
                    value = read_body.get("latest_data_at") or read_body.get("updated_at")
                    if isinstance(value, str):
                        try:
                            latest_data_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
                        except ValueError:
                            reason_codes.append("latest_data_timestamp_invalid")
            else:
                readable = False
        elif registration.read_path:
            readable = False
        return ProbeResult(
            availability=availability,
            authenticated=authenticated,
            readable=readable,
            latest_data_at=latest_data_at,
            observed_build=observed_build,
            observed_source_fingerprint=observed_source_fingerprint,
            observed_at=observed_at,
            reason_codes=reason_codes,
        )


async def local_knowledge_probe(registration: DependencyRegistration) -> ProbeResult:
    """Use a real DB read for the in-process knowledge-engine dependency."""

    from app.database import get_pool

    observed_at = utc_now()
    try:
        value = await get_pool().fetchval("SELECT 1")
    except Exception as exc:
        return ProbeResult(
            availability=True,
            authenticated=True,
            readable=False,
            observed_build=_build_evidence(os.getenv("OMNI_BUILD_COMMIT")),
            observed_source_fingerprint=_build_evidence(
                os.getenv("OMNI_BUILD_SOURCE_FINGERPRINT")
            ),
            observed_at=observed_at,
            reason_codes=[f"read_probe_failed:{type(exc).__name__}"],
        )
    return ProbeResult(
        availability=True,
        authenticated=True,
        readable=value == 1,
        observed_build=_build_evidence(os.getenv("OMNI_BUILD_COMMIT")),
        observed_source_fingerprint=_build_evidence(os.getenv("OMNI_BUILD_SOURCE_FINGERPRINT")),
        observed_at=observed_at,
    )


async def local_approval_worker_probe(
    registration: DependencyRegistration,
) -> ProbeResult:
    """Verify that the non-blocking approval worker is enabled and actually running."""

    from app.workers.approval_operations import APPROVAL_WORKER_RUNTIME

    observed_at = utc_now()
    enabled = os.getenv("OMNI_APPROVAL_WORKER_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    reasons: list[str] = []
    if not enabled:
        reasons.append("approval_worker_disabled")
    elif not APPROVAL_WORKER_RUNTIME.running:
        reasons.append("approval_worker_not_running")
    elif APPROVAL_WORKER_RUNTIME.last_error_code:
        reasons.append(APPROVAL_WORKER_RUNTIME.last_error_code)
    readable = enabled and APPROVAL_WORKER_RUNTIME.running and not APPROVAL_WORKER_RUNTIME.last_error_code
    return ProbeResult(
        availability=True,
        authenticated=True,
        readable=readable,
        latest_data_at=APPROVAL_WORKER_RUNTIME.last_success_at,
        observed_build=_build_evidence(os.getenv("OMNI_BUILD_COMMIT")),
        observed_source_fingerprint=_build_evidence(
            os.getenv("OMNI_BUILD_SOURCE_FINGERPRINT")
        ),
        observed_at=observed_at,
        reason_codes=reasons,
    )


class HealthRegistry:
    def __init__(
        self,
        *,
        feature_directory: Path | None = None,
        registrations: Mapping[str, DependencyRegistration] | None = None,
        probes: Mapping[str, Probe] | None = None,
        now: Callable[[], datetime] = utc_now,
        visible_hrefs: Sequence[str] | None = None,
        visible_feature_ids: Sequence[str] | None = None,
    ) -> None:
        default_directory = Path(__file__).resolve().parents[2] / "config" / "features"
        self.feature_directory = feature_directory or default_directory
        expected = current_build_identity().expected_commit
        expected_source_fingerprint = current_build_identity().expected_source_fingerprint
        self.registrations = dict(
            registrations
            or {
                "knowledge-engine": DependencyRegistration(
                    dependency_id="knowledge-engine",
                    expected_build=expected,
                    expected_source_fingerprint=expected_source_fingerprint,
                ),
                "ai-provider-hub": DependencyRegistration(
                    dependency_id="ai-provider-hub",
                    base_url=settings.ai_provider_hub_url,
                    health_path="/health",
                    read_path="/api/v1/ai/providers",
                    expected_build=expected,
                    expected_source_fingerprint=expected_source_fingerprint,
                ),
                "video-analysis": DependencyRegistration(
                    dependency_id="video-analysis",
                    base_url=settings.video_analysis_service_url,
                    health_path="/health",
                    read_path="/api/v1/video-analysis/videos",
                    expected_build=expected,
                    expected_source_fingerprint=expected_source_fingerprint,
                ),
                "livestream-analysis": DependencyRegistration(
                    dependency_id="livestream-analysis",
                    base_url=os.getenv(
                        "LIVESTREAM_ANALYSIS_SERVICE_URL", "http://livestream-analysis:8007"
                    ),
                    health_path="/health",
                    read_path="/api/v1/livestream-analysis/videos",
                    expected_build=expected,
                    expected_source_fingerprint=expected_source_fingerprint,
                ),
                "ad-review-service": DependencyRegistration(
                    dependency_id="ad-review-service",
                    base_url=settings.ad_review_service_url,
                    health_path="/health",
                    read_path="/api/v1/ad-review/products",
                    expected_build=expected,
                    expected_source_fingerprint=expected_source_fingerprint,
                ),
                "news-aggregator": DependencyRegistration(
                    dependency_id="news-aggregator",
                    base_url=os.getenv("NEWS_AGGREGATOR_URL", "http://news-aggregator:8005"),
                    health_path="/health",
                    read_path="/api/v1/news/articles?limit=1",
                    expected_build=expected,
                    expected_source_fingerprint=expected_source_fingerprint,
                ),
                "scout-agent": DependencyRegistration(
                    dependency_id="scout-agent",
                    base_url=settings.scout_agent_url,
                    health_path="/health",
                    read_path="/api/v1/scout/runs?limit=1",
                    expected_build=expected,
                    expected_source_fingerprint=expected_source_fingerprint,
                ),
                "identity-service": DependencyRegistration(
                    dependency_id="identity-service",
                    base_url=os.getenv("IDENTITY_SERVICE_URL", "http://identity-service:8000"),
                    health_path="/health",
                    read_path="/health/readiness",
                    expected_build=expected,
                    expected_source_fingerprint=expected_source_fingerprint,
                ),
                "approval-worker": DependencyRegistration(
                    dependency_id="approval-worker",
                    freshness_seconds=15,
                    expected_build=expected,
                    expected_source_fingerprint=expected_source_fingerprint,
                ),
            }
        )
        self.probes = dict(
            probes
            or {
                "knowledge-engine": local_knowledge_probe,
                "approval-worker": local_approval_worker_probe,
            }
        )
        self.now = now
        repo = self.feature_directory.parents[3] if len(self.feature_directory.parents) > 3 else Path()
        self.visible_hrefs = (
            set(visible_hrefs) if visible_hrefs is not None else discover_visible_frontend_hrefs(repo)
        )
        self.visible_feature_ids = (
            set(visible_feature_ids)
            if visible_feature_ids is not None
            else discover_visible_frontend_feature_ids(repo)
        )

    async def _one(
        self, spec: DependencySpec
    ) -> tuple[DependencyHealth, OperationError | None]:
        registration = self.registrations.get(spec.dependency_id)
        observed_at = self.now()
        if registration is None:
            registration = DependencyRegistration(dependency_id=spec.dependency_id)
            probe = ProbeResult(observed_at=observed_at, reason_codes=["dependency_not_registered"])
            error = OperationError(
                code="dependency_not_registered",
                message=f"No health registration exists for {spec.dependency_id}.",
                source=spec.ref,
                status=503,
                retryable=False,
            )
            try:
                health = derive_dependency_health(
                    spec=spec, registration=registration, probe=probe, now=observed_at
                )
            except Exception as exc:
                health = DependencyHealth(
                    dependency_id=spec.dependency_id,
                    ref=spec.ref,
                    required=spec.required,
                    state=HealthState.UNKNOWN,
                    reason_codes=[f"probe_interpretation_failed:{type(exc).__name__}"],
                    observed_at=probe.observed_at,
                )
                error = OperationError(
                    code="probe_interpretation_failed",
                    message=f"Health evidence could not be interpreted for {spec.dependency_id}.",
                    source=spec.ref,
                    status=503,
                    retryable=True,
                )
            return health, error
        probe_function = self.probes.get(spec.dependency_id, http_probe)
        try:
            probe = await asyncio.wait_for(
                probe_function(registration), timeout=registration.timeout_seconds
            )
        except TimeoutError:
            probe = ProbeResult(observed_at=observed_at, reason_codes=["probe_timeout"])
            error = OperationError(
                code="probe_timeout",
                message=f"Health probe timed out for {spec.dependency_id}.",
                source=spec.ref,
                status=503,
                retryable=True,
            )
        except Exception as exc:
            probe = ProbeResult(
                observed_at=observed_at,
                reason_codes=[f"probe_failed:{type(exc).__name__}"],
            )
            error = OperationError(
                code="probe_failed",
                message=f"Health probe failed for {spec.dependency_id}: {type(exc).__name__}",
                source=spec.ref,
                status=503,
                retryable=True,
            )
        else:
            error = None
        try:
            health = derive_dependency_health(
                spec=spec, registration=registration, probe=probe, now=self.now()
            )
        except Exception as exc:
            health = DependencyHealth(
                dependency_id=spec.dependency_id,
                ref=spec.ref,
                required=spec.required,
                state=HealthState.UNKNOWN,
                reason_codes=[f"probe_interpretation_failed:{type(exc).__name__}"],
                build_identity=BuildIdentity(
                    expected_commit=registration.expected_build,
                    observed_commit=probe.observed_build,
                    expected_source_fingerprint=registration.expected_source_fingerprint,
                    source_fingerprint=probe.observed_source_fingerprint,
                ),
                observed_at=probe.observed_at,
            )
            error = OperationError(
                code="probe_interpretation_failed",
                message=f"Health evidence could not be interpreted for {spec.dependency_id}.",
                source=spec.ref,
                status=503,
                retryable=True,
            )
        return health, error

    async def collect(self) -> SystemHealthResponse:
        specs, definition_errors = load_feature_specs(self.feature_directory)
        defined_feature_ids = {spec.feature_id for spec in specs}
        for feature_id in sorted(self.visible_feature_ids - defined_feature_ids):
            specs.append(
                FeatureSpec(
                    feature_id=feature_id,
                    title=f"未登记首页功能：{feature_id}",
                    dependencies=(),
                )
            )
            definition_errors.append(
                OperationError(
                    code="visible_feature_definition_missing",
                    message="A visible homepage feature has no canonical FeatureDefinition.",
                    source=f"feature:{feature_id}",
                    status=503,
                    retryable=False,
                )
            )
        covered_hrefs = {
            href
            for spec in specs
            for href in ((spec.href,) + spec.aliases)
            if href is not None
        }
        for href in sorted(self.visible_hrefs - covered_hrefs):
            digest = hashlib.sha256(href.encode("utf-8")).hexdigest()[:12]
            specs.append(
                FeatureSpec(
                    feature_id=f"unregistered-visible-route-{digest}",
                    title=f"未登记可见入口：{href}",
                    dependencies=(),
                    href=href,
                )
            )
            definition_errors.append(
                OperationError(
                    code="visible_feature_definition_missing",
                    message="A visible frontend route has no canonical FeatureDefinition.",
                    source=href,
                    status=503,
                    retryable=False,
                )
            )
        features: list[FeatureHealth] = []
        errors = list(definition_errors)
        representative_dependencies: dict[str, DependencySpec] = {}
        for spec in specs:
            for dependency in spec.dependencies:
                representative_dependencies.setdefault(dependency.dependency_id, dependency)
        probed = await asyncio.gather(
            *(self._one(dependency) for dependency in representative_dependencies.values())
        )
        health_by_dependency = {
            dependency_id: result[0]
            for dependency_id, result in zip(representative_dependencies, probed, strict=True)
        }
        errors.extend(result[1] for result in probed if result[1] is not None)
        for spec in specs:
            dependencies = [
                health_by_dependency[dependency.dependency_id].model_copy(
                    update={"ref": dependency.ref, "required": dependency.required}
                )
                for dependency in spec.dependencies
            ]
            features.append(derive_feature_health(spec, dependencies))
        state = aggregate_state(features)
        healthy_count = sum(feature.state is HealthState.HEALTHY for feature in features)
        percentage = round((healthy_count / len(features)) * 100, 1) if features else 0.0
        return SystemHealthResponse(
            state=state,
            healthy_percentage=percentage,
            partial=bool(errors) or any(feature.state is HealthState.UNKNOWN for feature in features),
            generated_at=self.now(),
            build_identity=current_build_identity(),
            features=features,
            errors=errors,
        )
