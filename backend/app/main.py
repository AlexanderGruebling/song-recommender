"""FastAPI application entry point.

Owns application lifecycle: database init, background scheduler, download
queue and serving of the built frontend from ``backend/static`` when present.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .config import get_settings
from .db import init_db
from .logging_conf import configure_logging
from .services.downloader import DownloadManager
from .tasks import Scheduler

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@dataclass
class AppState:
    download_manager: DownloadManager
    scheduler: Scheduler


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        manager = DownloadManager(settings)
        scheduler = Scheduler(settings)
        app.state.fm4_state = AppState(download_manager=manager, scheduler=scheduler)
        # Reconcile downloads interrupted by a previous run.
        await manager.reconcile_interrupted()
        manager.start()
        scheduler.start()
        logger.info("FM4 Top 40 downloader started")
        yield
        await scheduler.stop()
        await manager.stop()

    app = FastAPI(title="FM4 Top 40 Downloader", lifespan=lifespan)
    app.include_router(api_router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # Serve the built frontend (SPA) if present.
    if STATIC_DIR.is_dir():
        assets = STATIC_DIR / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/", include_in_schema=False)
        @app.get("/charts", include_in_schema=False)
        @app.get("/charts/{path:path}", include_in_schema=False)
        @app.get("/songs/{path:path}", include_in_schema=False)
        def spa(path: str = ""):
            index = STATIC_DIR / "index.html"
            if index.is_file():
                return FileResponse(index)
            return JSONResponse(
                {"detail": "Frontend not built. Run `npm run build` in frontend/."},
                status_code=503,
            )

    return app


app = create_app()