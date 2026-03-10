from fastapi import APIRouter

from app.api.archive_routes import router as archive_router
from app.api.article_routes import router as article_router
from app.api.fetch_routes import router as fetch_router
from app.api.health_routes import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(fetch_router, prefix="/api/v1/news")
api_router.include_router(article_router, prefix="/api/v1/news")
api_router.include_router(archive_router, prefix="/api/v1/news")
