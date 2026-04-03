# Architecture Overview

This project follows a layered architecture optimized for AI products that combine retrieval, ranking, and LLM-based reasoning.

## Layer map

- `app/core/`
  - Application configuration and cross-cutting settings.
- `app/interfaces/http/`
  - FastAPI request/response boundary and transport-level validation.
- `app/services/`
  - Business logic: ingestion workflow, embedding/LLM services, recommendation pipeline.
- `app/infrastructure/`
  - Database repository and persistence concerns.
- `app/ai/`
  - Prompt templates and LLM context builders.
- `app/web/static/`
  - Built frontend assets served by FastAPI.
- `frontend/`
  - React + TypeScript + Tailwind source code (Vite project).

## Dependency direction

Dependencies should flow inward:

`interfaces -> services -> infrastructure/core/ai`

Rules:

- `infrastructure` must not import `interfaces`.
- `services` should be transport-agnostic (callable from API, jobs, and tests).
- `core` contains environment-aware setup, not domain workflow logic.

## Entry point

- App bootstrap: `app/main.py`
- API router: `app/interfaces/http/router.py`
- Frontend source: `frontend/src/`
