"""Read-only feature health endpoints."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.schemas.system_health import HealthState, OperationError, SystemHealthResponse
from app.services.health_registry import HealthRegistry


router = APIRouter(prefix="/api/v1", tags=["system-health"])


def get_health_registry() -> HealthRegistry:
    return HealthRegistry()


@router.get("/system/health", response_model=SystemHealthResponse)
@router.get("/system-health/features", response_model=SystemHealthResponse, include_in_schema=False)
async def read_system_health(
    registry: HealthRegistry = Depends(get_health_registry),
) -> SystemHealthResponse:
    return await registry.collect()


@router.get("/system/health/features/{feature_id}")
async def read_feature_health(
    feature_id: str,
    registry: HealthRegistry = Depends(get_health_registry),
):
    result = await registry.collect()
    feature = next((item for item in result.features if item.feature_id == feature_id), None)
    if feature is None:
        error = OperationError(
            code="unknown_feature",
            message=f"Unknown feature: {feature_id}",
            source="feature-definition",
            status=404,
            retryable=False,
        )
        return JSONResponse(status_code=404, content=error.model_dump(mode="json"))
    if feature.state is not HealthState.HEALTHY:
        status = 503 if feature.state in {HealthState.UNAVAILABLE, HealthState.UNKNOWN} else 502
        error = OperationError(
            code=f"feature_{feature.state.value}",
            message=f"Feature {feature_id} is {feature.state.value}.",
            source=feature_id,
            status=status,
            retryable=feature.state in {HealthState.UNAVAILABLE, HealthState.UNKNOWN},
            details={"feature": feature.model_dump(mode="json")},
        )
        return JSONResponse(status_code=status, content=error.model_dump(mode="json"))
    return feature
