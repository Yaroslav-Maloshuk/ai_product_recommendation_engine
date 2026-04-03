from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from typing import Any, Iterable, Sequence

import asyncpg
from pydantic import BaseModel, Field, field_validator, model_validator


WHITESPACE_RE = re.compile(r"\s+")


class ProductInput(BaseModel):
    external_id: str | None = Field(default=None, max_length=255)
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(default="", max_length=5000)
    category: str | None = Field(default=None, max_length=255)
    price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=12)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "description", "category", "currency", mode="before")
    @classmethod
    def normalize_text_fields(cls, value: Any) -> str | None:
        if value is None:
            return None
        return clean_text(str(value))

    @field_validator("currency")
    @classmethod
    def normalize_currency_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = clean_text(value)
        if not normalized:
            return None
        return normalized.upper()

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [clean_text(tag) for tag in value.split(",") if clean_text(tag)]
        if isinstance(value, list):
            tags: list[str] = []
            for raw in value:
                normalized = clean_text(str(raw))
                if normalized:
                    tags.append(normalized)
            return tags
        return []

    @model_validator(mode="after")
    def ensure_external_id(self) -> ProductInput:
        if self.external_id:
            self.external_id = clean_text(self.external_id)
            return self

        payload = {
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "price": self.price,
            "currency": self.currency,
            "tags": self.tags,
            "metadata": self.metadata,
        }
        digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]
        self.external_id = f"auto-{digest}"
        return self


class DatabaseSource(BaseModel):
    dsn: str = Field(min_length=1)
    query: str = Field(min_length=1)

    @field_validator("query")
    @classmethod
    def select_only(cls, value: str) -> str:
        cleaned = clean_text(value)
        lowered = cleaned.lower()
        if not (lowered.startswith("select") or lowered.startswith("with")):
            raise ValueError("Only SELECT/CTE queries are allowed for ingestion")
        return cleaned


class IngestProductsPayload(BaseModel):
    products: list[ProductInput] | None = None
    db_source: DatabaseSource | None = None

    @model_validator(mode="after")
    def validate_input_source(self) -> IngestProductsPayload:
        source_count = int(self.products is not None) + int(self.db_source is not None)
        if source_count != 1:
            raise ValueError("Provide exactly one source: products or db_source")
        return self


def clean_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip()


def build_searchable_text(product: ProductInput) -> str:
    components = [
        product.title,
        product.description,
        product.category or "",
        " ".join(product.tags),
        _metadata_to_text(product.metadata),
    ]
    return clean_text(" ".join([part for part in components if part]))


def _metadata_to_text(metadata: dict[str, Any]) -> str:
    if not metadata:
        return ""

    flattened: list[str] = []
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            flattened.append(f"{key}: {value}")
            continue
        flattened.append(f"{key}: {json.dumps(value, ensure_ascii=True)}")
    return " ".join(flattened)


def parse_products_from_upload(filename: str, content: bytes) -> list[dict[str, Any]]:
    extension = filename.lower().rsplit(".", maxsplit=1)[-1] if "." in filename else ""

    if extension == "json":
        return parse_json_products(content)
    if extension == "csv":
        return parse_csv_products(content)

    # Best-effort fallback when extension is missing.
    try:
        return parse_json_products(content)
    except ValueError:
        return parse_csv_products(content)


def parse_json_products(content: bytes) -> list[dict[str, Any]]:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid JSON file") from exc

    if isinstance(payload, list):
        return _coerce_dict_list(payload)

    if isinstance(payload, dict):
        products = payload.get("products")
        if isinstance(products, list):
            return _coerce_dict_list(products)

    raise ValueError("JSON payload must be a list or an object with a 'products' list")


def parse_csv_products(content: bytes) -> list[dict[str, Any]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 encoded") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV file must include a header row")

    rows: list[dict[str, Any]] = []
    for row in reader:
        if not any(value for value in row.values()):
            continue
        normalized = dict(row)
        if "tags" in normalized and isinstance(normalized["tags"], str):
            raw_tags = normalized["tags"]
            delimiter = "|" if "|" in raw_tags else ","
            normalized["tags"] = [tag.strip() for tag in raw_tags.split(delimiter) if tag.strip()]
        if "metadata" in normalized and isinstance(normalized["metadata"], str) and normalized["metadata"].strip():
            try:
                normalized["metadata"] = json.loads(normalized["metadata"])
            except json.JSONDecodeError:
                # Keep raw value in metadata string to avoid dropping useful content.
                normalized["metadata"] = {"raw": normalized["metadata"]}
        rows.append(normalized)

    return rows


def normalize_products(raw_products: Sequence[dict[str, Any]] | Sequence[ProductInput]) -> list[ProductInput]:
    products: list[ProductInput] = []
    for raw in raw_products:
        if isinstance(raw, ProductInput):
            products.append(raw)
            continue
        products.append(ProductInput.model_validate(raw))
    return products


async def load_products_from_external_db(source: DatabaseSource) -> list[dict[str, Any]]:
    connection = await asyncpg.connect(source.dsn)
    try:
        records = await connection.fetch(source.query)
    finally:
        await connection.close()

    return [dict(record) for record in records]


def _coerce_dict_list(items: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each product must be a JSON object")
        rows.append(item)
    return rows
