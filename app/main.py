from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import Settings, get_settings
from app.infrastructure.product_repository import ProductRepository
from app.interfaces.http.router import router
from app.services.embedding_service import EmbeddingService, HuggingFaceLLMService
from app.services.recommendation_pipeline import RecommendationPipeline

logger = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parent / "web" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    repository = ProductRepository(settings)
    await repository.connect()

    embedding_service = EmbeddingService(settings)
    await embedding_service.load()

    await repository.init_schema(embedding_service.dimension)

    llm_service = HuggingFaceLLMService(settings)

    redis_client = await _build_redis_client(settings)

    pipeline = RecommendationPipeline(
        settings=settings,
        repository=repository,
        embedding_service=embedding_service,
        llm_service=llm_service,
        redis_client=redis_client,
    )

    if settings.reset_ingested_products_on_startup:
        deleted = await pipeline.clear_ingested_products()
        logger.info("Startup reset is enabled. Deleted %s ingested product(s).", deleted)

    app.state.settings = settings
    app.state.pipeline = pipeline

    try:
        yield
    finally:
        if redis_client is not None:
            await redis_client.aclose()
        await repository.close()


async def _build_redis_client(settings: Settings) -> Any | None:
    if not settings.redis_enabled:
        return None

    try:
        import redis.asyncio as redis
    except ImportError:
        logger.warning("REDIS_URL is set but redis package is not installed; caching disabled")
        return None

    client = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        logger.warning("Redis is unreachable; caching disabled: %s", exc)
        await client.aclose()
        return None

    return client


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.include_router(router)
    _configure_frontend(app)
    return app


def _configure_frontend(app: FastAPI) -> None:
    assets_dir = FRONTEND_DIR / "assets"
    if FRONTEND_DIR.exists() and assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/", include_in_schema=False)
        async def frontend_home() -> FileResponse:
            return FileResponse(FRONTEND_DIR / "index.html")

        return

    @app.get("/", include_in_schema=False)
    async def fallback_home() -> dict[str, str]:
        return {
            "message": (
                "Frontend assets were not found. Build them with "
                "`cd frontend && npm run build:sync` or use /docs for API explorer."
            )
        }


app = create_app()
