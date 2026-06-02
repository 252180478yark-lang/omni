import asyncio
import sys

# Windows: Playwright drives Chromium via asyncio.create_subprocess_exec, which
# only works on ProactorEventLoop. uvicorn's default Selector loop raises
# NotImplementedError. Set the policy before anything else imports asyncio loops.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db, close_db
from app.scheduler import start_scheduler, stop_scheduler
from app.routers import health, runbooks, runs, sessions, anomalies, skus, dashboard, fetch

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log.info("scout-agent: DB pool ready")

    try:
        import json
        from pathlib import Path
        from app.services.catalog_loader import CatalogLoader
        from app.services.live_fetch import LiveFetchExecutor
        from app.routers.fetch import set_executor

        cat_dir = Path(__file__).resolve().parent.parent / "catalog"
        files = {p: cat_dir / f"{p}.json" for p in ("yuntu", "compass", "doudian")
                 if (cat_dir / f"{p}.json").exists()}
        context = json.loads((cat_dir / "context.json").read_text("utf-8")) if (cat_dir / "context.json").exists() else {}
        sessions_root = Path(getattr(settings, "sessions_dir", "./sessions"))
        set_executor(LiveFetchExecutor(CatalogLoader.from_files(files, context), sessions_root))
        log.info("scout-agent: live_fetch executor ready (%d catalog files)", len(files))
    except Exception as exc:
        log.warning("live_fetch executor init failed: %s", exc)

    # Bootstrap SKUs on startup (non-blocking)
    try:
        from app.services.sku_bootstrapper import bootstrap_skus
        import asyncio
        asyncio.create_task(bootstrap_skus())
    except Exception as exc:
        log.warning("sku_bootstrapper startup task failed to enqueue: %s", exc)

    start_scheduler()
    yield
    stop_scheduler()
    await close_db()
    log.info("scout-agent: shutdown complete")


app = FastAPI(title="Omni Scout Agent", version="1.5", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(runbooks.router, prefix="/api/v1/scout")
app.include_router(runs.router, prefix="/api/v1/scout")
app.include_router(sessions.router, prefix="/api/v1/scout")
app.include_router(anomalies.router, prefix="/api/v1/scout")
app.include_router(skus.router, prefix="/api/v1/scout")
app.include_router(dashboard.router, prefix="/api/v1/scout")
app.include_router(fetch.router, prefix="/api/v1/scout")
