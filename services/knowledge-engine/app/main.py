from fastapi import FastAPI

from app.config import settings
from app.routers.knowledge import router as knowledge_router
from app.services.ingestion import init_db

app = FastAPI(title=settings.service_name)
app.include_router(knowledge_router)


@app.on_event("startup")
async def startup() -> None:
    init_db()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": settings.service_name}
