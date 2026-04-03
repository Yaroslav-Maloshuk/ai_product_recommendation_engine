<img src="https://github.com/Yaroslav-Maloshuk/ai_product_recommendation_engine/blob/main/ai_product_recommendation_engine.png" width="1000" height="1000">

# AI Product Recommendation Engine
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-336791?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Hugging Face](https://img.shields.io/badge/Hugging%20Face-FF47E0?style=for-the-badge&logo=huggingface&logoColor=white)](https://huggingface.co/)
[![React](https://img.shields.io/badge/React-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind%20CSS-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)
[![LangChain](https://img.shields.io/badge/LangChain-000000?style=for-the-badge&logo=langchain&logoColor=white)](https://langchain.com/)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)

A full-stack semantic product recommendation service built with FastAPI, PostgreSQL + pgvector, Hugging Face models, and a React/Tailwind web UI.

It ingests product catalogs from JSON, CSV, or an external SQL source, computes embeddings, runs vector similarity search with optional filters, and returns ranked recommendations with grounded reasons and an optional summary.

## What This Project Does

- Ingests product catalogs via API (`JSON`, `CSV`, file upload, or external DB query).
- Stores product vectors in PostgreSQL using `pgvector`.
- Retrieves semantically similar products for a user query/profile.
- Adds explanation text for each recommendation via an LLM.
- Supports both normal JSON responses and `NDJSON` streaming.
- Serves a built React frontend directly from FastAPI (or runs Vite in dev mode).

## Tech Stack

Backend:
- `FastAPI`
- `asyncpg` + `pgvector`
- `sentence-transformers`
- `transformers` (Hugging Face)
- `langchain-core` building blocks
- Optional `redis` for recommendation response caching

Frontend:
- `React 18`
- `TypeScript`
- `Tailwind CSS`
- `Vite`

Infrastructure:
- Docker multi-stage build
- Docker Compose (`api`, `db`, `redis`)

## Architecture

This project follows a layered architecture:

- `app/interfaces/http/` - HTTP transport and request validation.
- `app/services/` - ingestion, embedding/LLM wrappers, recommendation workflow.
- `app/infrastructure/` - PostgreSQL repository and SQL operations.
- `app/core/` - environment-driven app settings.
- `app/ai/` - prompt templates and catalog context shaping.
- `frontend/` - source code for the web UI.
- `app/web/static/` - built frontend assets served by FastAPI.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for more details.

## Repository Layout

```text
app/
  ai/
  core/
  infrastructure/
  interfaces/http/
  services/
  web/static/
frontend/
  src/
docker/
  postgres/init/
docs/
  ARCHITECTURE.md
tests/
  unit/
  integration/
requirements.txt
docker-compose.yml
Dockerfile
```

## Quick Start (Docker Compose)

### Prerequisites

- Docker + Docker Compose

### 1) Start the full stack

```bash
docker compose up --build -d
```

Services started:
- `api` (FastAPI) on `http://localhost:8000` by default
- `db` (PostgreSQL 16 + pgvector)
- `redis` (optional cache backend, enabled in compose)

To use a different API port:

```bash
API_PORT=8010 docker compose up --build -d
```

### 2) Verify

```bash
curl http://localhost:8000/health
```

Open:
- App UI: `http://localhost:8000`
- API docs (Swagger): `http://localhost:8000/docs`

### 3) Stop

```bash
docker compose down
```

## Local Development

Use this mode if you want FastAPI + Vite running separately.

### Prerequisites

- Python `3.12` recommended
- Node.js `22+`
- PostgreSQL `16+` with `vector` extension
- Redis optional

### 1) Backend dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2) Environment variables

```bash
cp .env.example .env
set -a
source .env
set +a
```

Note: settings are loaded via `os.getenv` (no implicit `.env` loader), so variables must be exported in your shell.

### 3) PostgreSQL setup (if running manually)

```sql
CREATE DATABASE recommendations;
\c recommendations
CREATE EXTENSION IF NOT EXISTS vector;
```

### 4) Run backend API

When Vite runs on `:8000`, run API on `:8001`:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

### 5) Run frontend dev server

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:8000`.

Vite proxies API routes (`/health`, `/ingest_products`, `/recommend`) to `VITE_API_PROXY_TARGET` (default `http://localhost:8001`).

## Build Frontend Into FastAPI Static Assets

To make FastAPI serve the UI directly from `app/web/static`:

```bash
cd frontend
npm run build:sync
```

This runs a production build and copies files into `app/web/static/`.

## API Overview

### `GET /health`
Returns service health and indexed product count.

Example response:

```json
{
  "status": "ok",
  "indexed_products": 100
}
```

### `POST /ingest_products`
Ingest products from one of these formats:

1. `multipart/form-data` with `file=<products.json|products.csv>`
2. JSON array of products
3. JSON object with one source:
   - `{ "products": [...] }`
   - `{ "db_source": { "dsn": "...", "query": "SELECT ..." } }`

Rules:
- `db_source.query` must start with `SELECT` or `WITH`.
- Exactly one source (`products` or `db_source`) is required.
- Missing `external_id` is auto-generated.

### `DELETE /ingest_products`
Deletes all indexed products.

### `GET /ingest_products/categories`
Returns distinct non-empty categories from ingested products.

### `POST /recommend`
Runs semantic retrieval + optional filtering + LLM reasoning.

Request body:

```json
{
  "query": "travel-friendly over-ear headphones under 250 USD",
  "user_profile": {"preferred_brands": ["SonicWave"]},
  "top_k": 5,
  "filters": {
    "category": "audio",
    "min_price": 50,
    "max_price": 250,
    "currency": "USD",
    "tags": ["wireless", "anc"]
  },
  "stream": false
}
```

Behavior:
- At least one of `query` or `user_profile` is required.
- `top_k` defaults to `DEFAULT_TOP_K` and is capped by `MAX_TOP_K`.
- If `stream=true`, returns `application/x-ndjson` events:
  - `recommendation`
  - `summary`
  - `done`

## Product Schema

```json
{
  "external_id": "p-001",
  "title": "Noise Cancelling Headphones",
  "description": "Wireless ANC headphones with 30h battery life",
  "category": "audio",
  "price": 199.99,
  "currency": "USD",
  "tags": ["wireless", "anc", "travel"],
  "metadata": {
    "brand": "SonicWave",
    "color": "black"
  }
}
```

CSV notes:
- Header row is required.
- `tags` can be comma-separated or pipe-separated.
- `metadata` can be a JSON string.

## Demo Flow

A sample catalog is provided in `products_100.json`.

### 1) Ingest sample catalog

```bash
curl -X POST "http://localhost:8000/ingest_products" \
  -H "Content-Type: application/json" \
  --data-binary @products_100.json
```

### 2) Request recommendations

```bash
curl -X POST "http://localhost:8000/recommend" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "travel-friendly over-ear headphones under 250 USD",
    "top_k": 5,
    "filters": {
      "category": "audio",
      "max_price": 250,
      "currency": "USD"
    }
  }'
```

### 3) Streaming mode example

```bash
curl -N -X POST "http://localhost:8000/recommend" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "lightweight laptop for software development",
    "top_k": 5,
    "stream": true
  }'
```

## Configuration

Main environment variables (from `app/core/config.py`):

| Variable | Default | Description |
|---|---|---|
| `APP_NAME` | `AI Product Recommendation Engine` | FastAPI app title |
| `APP_ENV` | `development` | Environment label |
| `DEBUG` | `false` | FastAPI debug mode |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/recommendations` | Postgres DSN |
| `REDIS_URL` | `None` | Optional Redis DSN for recommendation cache |
| `REDIS_CACHE_TTL_SECONDS` | `300` | Cache TTL for `/recommend` responses |
| `EMBEDDING_MODEL_NAME` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |
| `EMBEDDING_BATCH_SIZE` | `64` | Batch size for embedding generation |
| `EMBEDDING_NORMALIZE` | `true` | Normalize embedding vectors |
| `LLM_MODEL_NAME` | `google/flan-t5-base` | Hugging Face model for reasoning |
| `LLM_MAX_NEW_TOKENS` | `192` | Max generated tokens |
| `LLM_TEMPERATURE` | `0.0` | Generation temperature |
| `LLM_DEVICE` | `-1` | HF device id (`-1` = CPU) |
| `DEFAULT_TOP_K` | `5` | Default recommendation count |
| `MAX_TOP_K` | `25` | Hard cap for `top_k` |
| `INGESTION_BATCH_SIZE` | `128` | Ingestion embedding batch size |
| `REQUEST_TIMEOUT_SECONDS` | `180` | DB command timeout |
| `RESET_INGESTED_PRODUCTS_ON_STARTUP` | `false` | Clear indexed products on startup |
| `VITE_API_PROXY_TARGET` | `http://localhost:8001` | Frontend dev proxy target |

## Operational Notes

- First startup may take longer due to Hugging Face model download/warm-up.
- If `REDIS_URL` is set but Redis is unavailable, the app logs a warning and continues without cache.
- FastAPI serves frontend assets only if `app/web/static/` exists; otherwise `/` returns a fallback message.
- In Docker Compose, `RESET_INGESTED_PRODUCTS_ON_STARTUP` is set to `true` by default.

## Testing Status

`tests/unit/` and `tests/integration/` directories exist, but there are currently no implemented test cases.

## Useful Commands

```bash
# Tail API logs in Docker
docker compose logs -f api

# Rebuild and restart stack
docker compose up --build -d

# Run API locally
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
