"""实时取数路由。executor 单例由 lifespan 注入（set_executor），测试可替桩。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.fetch import BatchFetchRequest, FetchRequest

router = APIRouter()
_EXECUTOR = None
_PLATFORMS = ("yuntu", "compass", "doudian")


def set_executor(executor) -> None:
    global _EXECUTOR
    _EXECUTOR = executor


def _exec():
    if _EXECUTOR is None:
        raise HTTPException(status_code=503, detail="live_fetch executor 未初始化")
    return _EXECUTOR


@router.post("/fetch")
async def fetch(req: FetchRequest):
    return await _exec().fetch(req.platform, req.endpoint, req.params, req.body)


@router.post("/fetch/batch")
async def fetch_batch(req: BatchFetchRequest):
    return await _exec().batch([r.model_dump() for r in req.requests])


@router.get("/fetch/auth-status")
async def auth_status():
    ex = _exec()
    return {p: {"has_cookies": ex.has_cookies(p)} for p in _PLATFORMS}


@router.get("/fetch/endpoints")
async def list_endpoints(platform: str | None = None, query: str | None = None,
                         verified_only: bool = False):
    return _exec().catalog.search(platform=platform, query=query, verified_only=verified_only)
