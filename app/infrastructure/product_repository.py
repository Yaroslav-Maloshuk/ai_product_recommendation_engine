from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

import asyncpg
from pgvector.asyncpg import register_vector

from app.core.config import Settings


@dataclass(slots=True)
class ProductRecord:
    external_id: str
    title: str
    description: str
    category: str | None
    price: float | None
    currency: str | None
    tags: list[str]
    metadata: dict[str, Any]
    searchable_text: str
    embedding: list[float]


class ProductRepository:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is not None:
            return

        self._pool = await asyncpg.create_pool(
            dsn=self._settings.database_url,
            min_size=1,
            max_size=10,
            command_timeout=self._settings.request_timeout_seconds,
            init=self._init_connection,
        )

    async def close(self) -> None:
        if self._pool is None:
            return

        await self._pool.close()
        self._pool = None

    async def _init_connection(self, connection: asyncpg.Connection) -> None:
        await register_vector(connection)

    async def init_schema(self, embedding_dim: int) -> None:
        pool = self._require_pool()

        if embedding_dim <= 0:
            raise ValueError("Embedding dimension must be positive")

        schema_sql = f"""
        CREATE EXTENSION IF NOT EXISTS vector;

        CREATE TABLE IF NOT EXISTS products (
            id BIGSERIAL PRIMARY KEY,
            external_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT,
            price NUMERIC(12, 2),
            currency TEXT,
            tags TEXT[] NOT NULL DEFAULT '{{}}',
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            searchable_text TEXT NOT NULL,
            embedding VECTOR({embedding_dim}) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
        CREATE INDEX IF NOT EXISTS idx_products_price ON products(price);
        CREATE INDEX IF NOT EXISTS idx_products_tags ON products USING GIN(tags);
        CREATE INDEX IF NOT EXISTS idx_products_metadata ON products USING GIN(metadata);
        CREATE INDEX IF NOT EXISTS idx_products_embedding_cosine
            ON products USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);

        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS products_set_updated_at ON products;
        CREATE TRIGGER products_set_updated_at
        BEFORE UPDATE ON products
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
        """

        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(schema_sql)

    async def upsert_products(self, products: Sequence[ProductRecord]) -> int:
        if not products:
            return 0

        pool = self._require_pool()

        rows = [
            (
                item.external_id,
                item.title,
                item.description,
                item.category,
                item.price,
                item.currency,
                item.tags,
                json.dumps(item.metadata, ensure_ascii=True),
                item.searchable_text,
                item.embedding,
            )
            for item in products
        ]

        query = """
        INSERT INTO products (
            external_id,
            title,
            description,
            category,
            price,
            currency,
            tags,
            metadata,
            searchable_text,
            embedding
        )
        VALUES (
            $1,
            $2,
            $3,
            $4,
            $5,
            $6,
            $7,
            $8,
            $9,
            $10::vector
        )
        ON CONFLICT (external_id)
        DO UPDATE SET
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            category = EXCLUDED.category,
            price = EXCLUDED.price,
            currency = EXCLUDED.currency,
            tags = EXCLUDED.tags,
            metadata = EXCLUDED.metadata,
            searchable_text = EXCLUDED.searchable_text,
            embedding = EXCLUDED.embedding,
            updated_at = NOW();
        """

        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.executemany(query, rows)

        return len(rows)

    async def search_products(
        self,
        query_embedding: Sequence[float],
        top_k: int,
        filters: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        pool = self._require_pool()

        params: list[Any] = [list(query_embedding)]
        where_clauses: list[str] = []

        if filters:
            category = filters.get("category")
            if category:
                params.append(str(category).strip())
                where_clauses.append(f"LOWER(category) = LOWER(${len(params)})")

            min_price = filters.get("min_price")
            if min_price is not None:
                params.append(float(min_price))
                where_clauses.append(f"price >= ${len(params)}")

            max_price = filters.get("max_price")
            if max_price is not None:
                params.append(float(max_price))
                where_clauses.append(f"price <= ${len(params)}")

            currency = filters.get("currency")
            if currency:
                params.append(str(currency).strip())
                where_clauses.append(f"LOWER(currency) = LOWER(${len(params)})")

            tags = filters.get("tags")
            if tags:
                normalized_tags = [str(tag).strip().lower() for tag in list(tags) if str(tag).strip()]
                if normalized_tags:
                    params.append(normalized_tags)
                    where_clauses.append(
                        f"""EXISTS (
                            SELECT 1
                            FROM unnest(tags) AS product_tag
                            WHERE LOWER(product_tag) = ANY(${len(params)}::text[])
                        )"""
                    )

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        params.append(top_k)
        limit_position = len(params)

        query = f"""
        SELECT
            external_id,
            title,
            description,
            category,
            price,
            currency,
            tags,
            metadata,
            searchable_text,
            1 - (embedding <=> $1::vector) AS score
        FROM products
        {where_sql}
        ORDER BY embedding <=> $1::vector
        LIMIT ${limit_position};
        """

        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SET LOCAL ivfflat.probes = 100;")
                rows = await connection.fetch(query, *params)

        products: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if isinstance(item.get("price"), Decimal):
                item["price"] = float(item["price"])
            item["score"] = float(item.get("score") or 0.0)
            products.append(item)

        return products

    async def count_products(self) -> int:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            value = await connection.fetchval("SELECT COUNT(*) FROM products")
        return int(value or 0)

    async def delete_all_products(self) -> int:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            result = await connection.execute("DELETE FROM products")

        # asyncpg returns strings like "DELETE 8".
        try:
            return int(str(result).split()[-1])
        except (ValueError, IndexError):
            return 0

    async def list_categories(self) -> list[str]:
        pool = self._require_pool()
        query = """
        SELECT DISTINCT category
        FROM products
        WHERE category IS NOT NULL AND btrim(category) <> ''
        ORDER BY category ASC;
        """
        async with pool.acquire() as connection:
            rows = await connection.fetch(query)
        return [str(row["category"]) for row in rows]

    def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database pool is not initialized")
        return self._pool
