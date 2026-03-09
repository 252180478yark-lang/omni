from fastapi import FastAPI

from app.config import settings
from app.routers.ai import router as ai_router
from app.routers.v1 import router as v1_router
from app.runtime import bootstrap_providers

app = FastAPI(title=settings.service_name)
app.include_router(v1_router)
app.include_router(ai_router)


@app.on_event("startup")
async def startup() -> None:
    bootstrap_providers()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": settings.service_name}
