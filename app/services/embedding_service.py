from __future__ import annotations

import asyncio
from typing import Any, Sequence

from sentence_transformers import SentenceTransformer
from transformers import (
    AutoModelForCausalLM,
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    pipeline as hf_pipeline,
)
from transformers.pipelines import PIPELINE_REGISTRY

from app.core.config import Settings


class EmbeddingService:
    """Loads a sentence-transformer model and produces embeddings asynchronously."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: SentenceTransformer | None = None
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        if self._model is not None:
            return

        self._model = await asyncio.to_thread(
            SentenceTransformer,
            self._settings.embedding_model_name,
        )

    @property
    def dimension(self) -> int:
        if self._model is None:
            raise RuntimeError("Embedding model is not loaded")
        return int(self._model.get_sentence_embedding_dimension())

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        await self.load()
        if self._model is None:
            raise RuntimeError("Embedding model failed to initialize")

        async with self._lock:
            vectors = await asyncio.to_thread(
                self._model.encode,
                list(texts),
                batch_size=self._settings.embedding_batch_size,
                normalize_embeddings=self._settings.embedding_normalize,
                convert_to_numpy=True,
                show_progress_bar=False,
            )

        return vectors.tolist()

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_texts([text])
        return vectors[0]


class HuggingFaceLLMService:
    """Lightweight async wrapper around HuggingFace text generation."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pipeline: Any | None = None
        self._task: str | None = None
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        if self._pipeline is not None:
            return

        self._task, self._pipeline = await asyncio.to_thread(self._build_pipeline_sync)

    def _build_pipeline_sync(self) -> tuple[str, Any]:
        tokenizer = AutoTokenizer.from_pretrained(self._settings.llm_model_name)

        # Try seq2seq first (instruction-tuned models like Flan-T5), then causal LM.
        try:
            model = AutoModelForSeq2SeqLM.from_pretrained(self._settings.llm_model_name)
            task = self._resolve_pipeline_task("text2text-generation")
        except Exception:
            model = AutoModelForCausalLM.from_pretrained(self._settings.llm_model_name)
            task = self._resolve_pipeline_task("text-generation")

        generator = hf_pipeline(
            task=task,
            model=model,
            tokenizer=tokenizer,
            device=self._settings.llm_device,
        )
        return task, generator

    def _resolve_pipeline_task(self, preferred_task: str) -> str:
        supported_tasks = set(PIPELINE_REGISTRY.get_supported_tasks())
        if preferred_task in supported_tasks:
            return preferred_task

        # Newer transformers versions removed "text2text-generation".
        if preferred_task == "text2text-generation" and "text-generation" in supported_tasks:
            return "text-generation"

        return preferred_task

    async def generate(self, prompt: str) -> str:
        await self.load()

        if self._pipeline is None or self._task is None:
            raise RuntimeError("LLM pipeline failed to initialize")

        async with self._lock:
            return await asyncio.to_thread(self._generate_sync, prompt)

    def _generate_sync(self, prompt: str) -> str:
        if self._pipeline is None or self._task is None:
            raise RuntimeError("LLM pipeline failed to initialize")

        kwargs: dict[str, Any] = {"max_new_tokens": self._settings.llm_max_new_tokens}
        if self._settings.llm_temperature > 0:
            kwargs["temperature"] = self._settings.llm_temperature
            kwargs["do_sample"] = True
        else:
            kwargs["do_sample"] = False

        if self._task == "text-generation":
            kwargs["return_full_text"] = False

        outputs = self._pipeline(prompt, **kwargs)
        if not outputs:
            return ""

        first = outputs[0]
        if isinstance(first, dict):
            text = first.get("generated_text", "")
        else:
            text = str(first)
        return text.strip()
