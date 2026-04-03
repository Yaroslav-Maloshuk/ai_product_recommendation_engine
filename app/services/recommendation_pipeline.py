from __future__ import annotations

import hashlib
import json
import re
from typing import Any, AsyncIterator, Mapping, Sequence

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field, model_validator

from app.ai.prompts import (
    RECOMMENDATION_EXPLANATION_TEMPLATE,
    RECOMMENDATION_SYSTEM_PROMPT,
    build_catalog_context,
)
from app.core.config import Settings
from app.infrastructure.product_repository import ProductRecord, ProductRepository
from app.services.embedding_service import EmbeddingService, HuggingFaceLLMService
from app.services.ingestion_service import ProductInput, build_searchable_text, clean_text

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover - optional dependency at runtime
    Redis = Any  # type: ignore[assignment,misc]


JSON_OBJECT_RE = re.compile(r"\{.*\}", flags=re.DOTALL)


class RecommendationFilters(BaseModel):
    category: str | None = None
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    currency: str | None = None
    tags: list[str] | None = None

    @model_validator(mode="after")
    def validate_range(self) -> RecommendationFilters:
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("min_price cannot be greater than max_price")
        return self


class RecommendationItem(BaseModel):
    external_id: str
    title: str
    description: str
    category: str | None = None
    price: float | None = None
    currency: str | None = None
    tags: list[str] = Field(default_factory=list)
    score: float
    reason: str


class RecommendationResult(BaseModel):
    query: str
    recommendations: list[RecommendationItem]
    llm_summary: str | None = None


class IngestionResult(BaseModel):
    received: int
    indexed: int
    categories: list[str] = Field(default_factory=list)


class RecommendationPipeline:
    def __init__(
        self,
        settings: Settings,
        repository: ProductRepository,
        embedding_service: EmbeddingService,
        llm_service: HuggingFaceLLMService,
        redis_client: Redis | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._embedding_service = embedding_service
        self._llm_service = llm_service
        self._redis = redis_client

        self._explanation_prompt = PromptTemplate.from_template(RECOMMENDATION_EXPLANATION_TEMPLATE)
        self._explanation_chain = (
            self._explanation_prompt
            | RunnableLambda(self._invoke_llm)
            | StrOutputParser()
        )

    async def ingest_products(self, products: Sequence[ProductInput]) -> IngestionResult:
        total = len(products)
        categories = self._collect_categories(products)
        if total == 0:
            return IngestionResult(received=0, indexed=0, categories=categories)

        indexed = 0
        batch_size = max(1, self._settings.ingestion_batch_size)

        for start in range(0, total, batch_size):
            batch = products[start : start + batch_size]
            searchable_texts = [build_searchable_text(product) for product in batch]
            embeddings = await self._embedding_service.embed_texts(searchable_texts)

            records: list[ProductRecord] = []
            for product, searchable_text, embedding in zip(batch, searchable_texts, embeddings, strict=True):
                record = ProductRecord(
                    external_id=product.external_id or "",
                    title=product.title,
                    description=product.description,
                    category=product.category,
                    price=product.price,
                    currency=product.currency,
                    tags=product.tags,
                    metadata=product.metadata,
                    searchable_text=searchable_text,
                    embedding=embedding,
                )
                records.append(record)

            indexed += await self._repository.upsert_products(records)

        if indexed > 0:
            await self._invalidate_recommendation_cache()

        return IngestionResult(received=total, indexed=indexed, categories=categories)

    async def recommend(
        self,
        query: str | None,
        user_profile: Mapping[str, Any] | None,
        top_k: int,
        filters: RecommendationFilters | None = None,
    ) -> RecommendationResult:
        query_text = self._build_query_text(query, user_profile)
        normalized_top_k = max(1, min(top_k, self._settings.max_top_k))
        normalized_filters = filters or RecommendationFilters()

        cache_key = self._cache_key(
            query_text=query_text,
            top_k=normalized_top_k,
            filters=normalized_filters.model_dump(exclude_none=True),
        )

        cached = await self._cache_get(cache_key)
        if cached:
            try:
                return RecommendationResult.model_validate_json(cached)
            except Exception:
                pass

        query_embedding = await self._embedding_service.embed_query(query_text)
        records = await self._repository.search_products(
            query_embedding=query_embedding,
            top_k=normalized_top_k,
            filters=normalized_filters.model_dump(exclude_none=True),
        )

        reasons_map: dict[str, str] = {}
        llm_summary: str | None = None
        if records:
            reasons_map, llm_summary = await self._generate_reasons(
                query_text=query_text,
                user_profile=user_profile,
                records=records,
            )

        recommendations = [
            RecommendationItem(
                external_id=str(item.get("external_id", "")),
                title=str(item.get("title", "")),
                description=str(item.get("description", "")),
                category=item.get("category"),
                price=item.get("price"),
                currency=item.get("currency"),
                tags=list(item.get("tags") or []),
                score=float(item.get("score") or 0.0),
                reason=reasons_map.get(
                    str(item.get("external_id", "")),
                    self._fallback_reason(item),
                ),
            )
            for item in records
        ]
        summary_text = llm_summary or self._build_summary_from_recommendations(
            query_text=query_text,
            recommendations=recommendations,
        )

        result = RecommendationResult(
            query=query_text,
            recommendations=recommendations,
            llm_summary=summary_text,
        )

        await self._cache_set(cache_key, result.model_dump_json())
        return result

    async def recommend_stream(
        self,
        query: str | None,
        user_profile: Mapping[str, Any] | None,
        top_k: int,
        filters: RecommendationFilters | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        result = await self.recommend(
            query=query,
            user_profile=user_profile,
            top_k=top_k,
            filters=filters,
        )

        for recommendation in result.recommendations:
            yield {"event": "recommendation", "data": recommendation.model_dump()}

        if result.llm_summary:
            yield {"event": "summary", "data": {"text": result.llm_summary}}

        yield {
            "event": "done",
            "data": {
                "count": len(result.recommendations),
            },
        }

    async def indexed_product_count(self) -> int:
        return await self._repository.count_products()

    async def clear_ingested_products(self) -> int:
        deleted = await self._repository.delete_all_products()
        if deleted > 0:
            await self._invalidate_recommendation_cache()
        return deleted

    async def list_ingested_categories(self) -> list[str]:
        return await self._repository.list_categories()

    def _collect_categories(self, products: Sequence[ProductInput]) -> list[str]:
        seen: set[str] = set()
        for product in products:
            category = clean_text(product.category or "")
            if category:
                seen.add(category)
        return sorted(seen, key=str.casefold)

    async def _invoke_llm(self, prompt: Any) -> str:
        if hasattr(prompt, "to_string"):
            prompt_text = prompt.to_string()
        else:
            prompt_text = str(prompt)
        return await self._llm_service.generate(prompt_text)

    async def _generate_reasons(
        self,
        query_text: str,
        user_profile: Mapping[str, Any] | None,
        records: Sequence[dict[str, Any]],
    ) -> tuple[dict[str, str], str | None]:
        profile_json = json.dumps(dict(user_profile or {}), ensure_ascii=True)
        catalog_context = build_catalog_context(records)

        try:
            raw_response = await self._explanation_chain.ainvoke(
                {
                    "system_prompt": RECOMMENDATION_SYSTEM_PROMPT,
                    "query_text": query_text,
                    "user_profile_json": profile_json,
                    "catalog_context": catalog_context,
                }
            )
        except Exception:
            return {}, None

        parsed = _parse_json_object(raw_response)
        if not isinstance(parsed, dict):
            return {}, None

        reasons: dict[str, str] = {}
        reasons_raw = parsed.get("reasons", [])
        if isinstance(reasons_raw, list):
            for item in reasons_raw:
                if not isinstance(item, dict):
                    continue
                external_id = clean_text(str(item.get("external_id", "")))
                reason = clean_text(str(item.get("reason", "")))
                if external_id and reason:
                    reasons[external_id] = reason

        summary = parsed.get("summary")
        summary_text = clean_text(str(summary)) if isinstance(summary, str) else None
        return reasons, summary_text or None

    def _build_query_text(self, query: str | None, user_profile: Mapping[str, Any] | None) -> str:
        chunks: list[str] = []

        if query and clean_text(query):
            chunks.append(clean_text(query))

        if user_profile:
            chunks.append(f"profile: {json.dumps(dict(user_profile), ensure_ascii=True)}")

        if not chunks:
            raise ValueError("Either query or user_profile must be provided")

        return "\n".join(chunks)

    def _fallback_reason(self, product: Mapping[str, Any]) -> str:
        descriptors: list[str] = []
        category = product.get("category")
        if category:
            descriptors.append(f"category: {category}")

        tags = product.get("tags") or []
        if isinstance(tags, list) and tags:
            descriptors.append(f"tags: {', '.join(str(tag) for tag in tags[:3])}")

        price = product.get("price")
        if price is not None:
            currency = product.get("currency") or ""
            descriptors.append(f"price: {price} {currency}".strip())

        if descriptors:
            return f"Matched via semantic similarity and product attributes ({'; '.join(descriptors)})."

        return "Matched via semantic similarity to your request."

    def _build_summary_from_recommendations(
        self,
        query_text: str,
        recommendations: Sequence[RecommendationItem],
    ) -> str:
        if not recommendations:
            return "No recommendations matched this request."

        top_titles = [clean_text(item.title) for item in recommendations[:3] if clean_text(item.title)]
        category_seen: set[str] = set()
        categories: list[str] = []
        for item in recommendations:
            category = clean_text(item.category or "")
            if not category:
                continue
            normalized = category.casefold()
            if normalized in category_seen:
                continue
            category_seen.add(normalized)
            categories.append(category)

        prices = [float(item.price) for item in recommendations if isinstance(item.price, (int, float))]
        currencies = sorted(
            {clean_text(item.currency or "") for item in recommendations if isinstance(item.price, (int, float)) and item.currency}
        )

        chunks: list[str] = [f"Generated {len(recommendations)} recommendation(s) for your request."]

        primary_query = clean_text(query_text.split("\n", maxsplit=1)[0])
        if primary_query:
            chunks.append(f"Query focus: {primary_query}.")

        if top_titles:
            chunks.append(f"Top matches: {', '.join(top_titles)}.")

        if categories:
            chunks.append(f"Categories covered: {', '.join(categories[:4])}.")

        if prices:
            price_text = f"{min(prices):.2f} - {max(prices):.2f}"
            if len(currencies) == 1:
                price_text = f"{price_text} {currencies[0]}"
            chunks.append(f"Price range: {price_text}.")

        return " ".join(chunks)

    def _cache_key(self, query_text: str, top_k: int, filters: Mapping[str, Any]) -> str:
        payload = {
            "query_text": query_text,
            "top_k": top_k,
            "filters": filters,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"recommend:{digest}"

    async def _cache_get(self, key: str) -> str | None:
        if self._redis is None:
            return None

        try:
            value = await self._redis.get(key)
        except Exception:
            return None

        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    async def _cache_set(self, key: str, value: str) -> None:
        if self._redis is None:
            return

        try:
            await self._redis.set(
                key,
                value,
                ex=self._settings.redis_cache_ttl_seconds,
            )
        except Exception:
            return

    async def _invalidate_recommendation_cache(self) -> None:
        if self._redis is None:
            return

        try:
            keys = await self._redis.keys("recommend:*")
            if keys:
                await self._redis.delete(*keys)
        except Exception:
            return


def _parse_json_object(raw_text: str) -> dict[str, Any] | None:
    if not raw_text:
        return None

    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = JSON_OBJECT_RE.search(raw_text)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    if isinstance(parsed, dict):
        return parsed

    return None
