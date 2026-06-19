import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import get_engine
from app.models import Base
from app.routers.connections import router as connections_router
from app.routers.dashboard import router as dashboard_router
from app.routers.health import router as health_router
from app.routers.oauth import router as oauth_router
from app.routers.settings import router as settings_router
from app.routers.workflows import router as workflows_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate()

    data_dir = Path("/app/data") if os.path.exists("/app") else Path("./data")
    data_dir.mkdir(parents=True, exist_ok=True)

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Starting app env=%s", settings.app_env)

    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Digest Docs",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.include_router(health_router)
    app.include_router(dashboard_router)
    app.include_router(settings_router)
    app.include_router(oauth_router)
    app.include_router(connections_router)
    app.include_router(workflows_router)

    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


app = create_app()
