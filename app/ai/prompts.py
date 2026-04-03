from __future__ import annotations

import json
from typing import Any, Sequence


RECOMMENDATION_SYSTEM_PROMPT = """
You are a product recommendation assistant.
You must only use products from the provided catalog context.
If the catalog does not include a good match, say so directly.
Never invent products, prices, categories, or attributes.
Keep explanations concise, factual, and grounded in product metadata.
""".strip()


RECOMMENDATION_EXPLANATION_TEMPLATE = """
System Rules:
{system_prompt}

User Need:
{query_text}

User Profile JSON:
{user_profile_json}

Catalog (already ranked by semantic similarity):
{catalog_context}

Task:
1. Provide one short summary sentence of how strong the matches are.
2. For each catalog item, write one concise reason tied to its own fields.
3. Do not mention products that are not in the catalog.
4. If evidence is weak, explicitly say what is missing.

Return strict JSON with this schema:
{{
  "summary": "string",
  "reasons": [
    {{"external_id": "string", "reason": "string"}}
  ]
}}
""".strip()


def build_catalog_context(products: Sequence[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, item in enumerate(products, start=1):
        payload = {
            "rank": index,
            "external_id": item.get("external_id"),
            "title": item.get("title"),
            "description": item.get("description"),
            "category": item.get("category"),
            "price": item.get("price"),
            "currency": item.get("currency"),
            "tags": item.get("tags", []),
            "metadata": item.get("metadata", {}),
            "similarity_score": round(float(item.get("score", 0.0)), 4),
        }
        lines.append(json.dumps(payload, ensure_ascii=True))

    return "\n".join(lines)
