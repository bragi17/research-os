"""FastAPI application factory."""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from structlog import get_logger

import apps.api.database as database
from apps.api.auth import ensure_first_admin_user
from apps.api.redis_queue import close_redis, init_redis
from apps.api.routes_auth import router as auth_router
from apps.api.routes_events import router as events_router
from apps.api.routes_files import router as files_router
from apps.api.routes_library import router as library_router
from apps.api.routes_production import router as production_router
from apps.api.routes_queue import router as queue_router
from apps.api.routes_results import router as results_router
from apps.api.routes_runs import router as runs_router
from apps.api.routes_settings import router as settings_router
from apps.api.routes_status import router as status_router
from apps.api.routes_v2 import router as v2_router
from apps.api.routes_works import router as works_router

load_dotenv()

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("research_os_starting", version="0.1.0")
    await database.init_pool()
    logger.info("database_pool_initialized")
    await ensure_first_admin_user()
    logger.info("first_admin_user_ensured")
    await init_redis()
    yield
    logger.info("research_os_shutting_down")
    await close_redis()
    await database.close_pool()
    logger.info("database_pool_closed")


def create_app() -> FastAPI:
    """Create and configure the Research OS API application."""
    app = FastAPI(
        title="Research OS",
        description="Autonomous Research Operating System API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    allowed_origins = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:3001",
    ).split(",")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(status_router)
    app.include_router(auth_router)
    app.include_router(runs_router)
    app.include_router(events_router)
    app.include_router(results_router)
    app.include_router(files_router)
    app.include_router(queue_router)
    app.include_router(v2_router)
    app.include_router(library_router)
    app.include_router(production_router)
    app.include_router(settings_router)
    app.include_router(works_router)

    return app
