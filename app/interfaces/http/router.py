from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError, model_validator
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.config import Settings
from app.services.ingestion_service import (
    IngestProductsPayload,
    ProductInput,
    load_products_from_external_db,
    normalize_products,
    parse_products_from_upload,
)
from app.services.recommendation_pipeline import (
    IngestionResult,
    RecommendationFilters,
    RecommendationPipeline,
    RecommendationResult,
)

router = APIRouter()


class RecommendRequest(BaseModel):
    query: str | None = None
    user_profile: dict[str, Any] | None = None
    top_k: int | None = Field(default=None, ge=1, le=100)
    filters: RecommendationFilters = Field(default_factory=RecommendationFilters)
    stream: bool = False

    @model_validator(mode="after")
    def validate_input(self) -> RecommendRequest:
        if not self.query and not self.user_profile:
            raise ValueError("Provide at least one of: query or user_profile")
        return self


class HealthResponse(BaseModel):
    status: str
    indexed_products: int


class ClearIngestionResponse(BaseModel):
    deleted: int
    indexed_products: int


class CategoriesResponse(BaseModel):
    categories: list[str]


def get_pipeline(request: Request) -> RecommendationPipeline:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise RuntimeError("Recommendation pipeline is not initialized")
    return pipeline


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise RuntimeError("Settings are not initialized")
    return settings


@router.get("/health", response_model=HealthResponse)
async def health(pipeline: RecommendationPipeline = Depends(get_pipeline)) -> HealthResponse:
    count = await pipeline.indexed_product_count()
    return HealthResponse(status="ok", indexed_products=count)


@router.post("/ingest_products", response_model=IngestionResult)
async def ingest_products(
    request: Request,
    pipeline: RecommendationPipeline = Depends(get_pipeline),
) -> IngestionResult:
    """
    Accepts one of the following:
    1) multipart/form-data with file=<products.json|products.csv>
    2) JSON array of products
    3) JSON object: {"products": [...]} or {"db_source": {"dsn": "...", "query": "SELECT ..."}}
    """

    try:
        products = await _extract_products_from_request(request)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await pipeline.ingest_products(products)


@router.delete("/ingest_products", response_model=ClearIngestionResponse)
async def clear_ingested_products(
    pipeline: RecommendationPipeline = Depends(get_pipeline),
) -> ClearIngestionResponse:
    deleted = await pipeline.clear_ingested_products()
    indexed_products = await pipeline.indexed_product_count()
    return ClearIngestionResponse(deleted=deleted, indexed_products=indexed_products)


@router.get("/ingest_products/categories", response_model=CategoriesResponse)
async def list_ingested_categories(
    pipeline: RecommendationPipeline = Depends(get_pipeline),
) -> CategoriesResponse:
    categories = await pipeline.list_ingested_categories()
    return CategoriesResponse(categories=categories)


@router.post("/recommend", response_model=RecommendationResult)
async def recommend_products(
    payload: RecommendRequest,
    pipeline: RecommendationPipeline = Depends(get_pipeline),
    settings: Settings = Depends(get_settings),
) -> RecommendationResult | StreamingResponse:
    top_k = payload.top_k or settings.default_top_k

    try:
        if payload.stream:
            return StreamingResponse(
                _recommendation_stream(
                    pipeline=pipeline,
                    query=payload.query,
                    user_profile=payload.user_profile,
                    top_k=top_k,
                    filters=payload.filters,
                ),
                media_type="application/x-ndjson",
            )

        return await pipeline.recommend(
            query=payload.query,
            user_profile=payload.user_profile,
            top_k=top_k,
            filters=payload.filters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _extract_products_from_request(request: Request) -> list[ProductInput]:
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form_data = await request.form()
        uploaded = form_data.get("file")
        if not isinstance(uploaded, StarletteUploadFile):
            raise ValueError("multipart/form-data must include a file field named 'file'")

        content = await uploaded.read()
        if not content:
            raise ValueError("Uploaded file is empty")

        filename = uploaded.filename or "products.json"
        raw_products = parse_products_from_upload(filename, content)
        return normalize_products(raw_products)

    body = await request.body()
    if not body:
        raise ValueError("Request body is empty")

    try:
        raw_payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be valid JSON") from exc

    if isinstance(raw_payload, list):
        return normalize_products(raw_payload)

    if not isinstance(raw_payload, dict):
        raise ValueError("JSON payload must be an object or an array")

    payload = IngestProductsPayload.model_validate(raw_payload)

    if payload.products is not None:
        return normalize_products(payload.products)

    if payload.db_source is None:
        raise ValueError("db_source is required when products are not provided")

    db_rows = await load_products_from_external_db(payload.db_source)
    return normalize_products(db_rows)


async def _recommendation_stream(
    pipeline: RecommendationPipeline,
    query: str | None,
    user_profile: dict[str, Any] | None,
    top_k: int,
    filters: RecommendationFilters,
):
    async for chunk in pipeline.recommend_stream(
        query=query,
        user_profile=user_profile,
        top_k=top_k,
        filters=filters,
    ):
        yield json.dumps(chunk, ensure_ascii=False) + "\n"
