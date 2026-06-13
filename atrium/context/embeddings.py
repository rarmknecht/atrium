"""Local embedding providers. Embeddings are an enhancement, never a requirement —
if the provider can't load (no network for the first model download, unsupported
platform), the librarian degrades to BM25-only and logs why.
"""

import asyncio
import logging
from typing import Protocol

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    name: str

    async def embed(self, texts: list[str]) -> np.ndarray: ...   # (n, dim) float32
    async def embed_query(self, text: str) -> np.ndarray: ...    # (dim,) float32


class FastEmbedProvider:
    """ONNX-quantized local models via fastembed (CPU-friendly)."""

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        self.name = f"fastembed:{model}"
        self._model_name = model
        self._model = None
        self._lock = asyncio.Lock()

    async def _ensure_model(self):
        if self._model is None:
            async with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    # first call downloads the model (~tens of MB), then it's cached
                    self._model = await asyncio.to_thread(TextEmbedding, self._model_name)
        return self._model

    async def embed(self, texts: list[str]) -> np.ndarray:
        model = await self._ensure_model()
        vectors = await asyncio.to_thread(lambda: list(model.embed(texts)))
        return np.asarray(vectors, dtype=np.float32)

    async def embed_query(self, text: str) -> np.ndarray:
        model = await self._ensure_model()
        vectors = await asyncio.to_thread(lambda: list(model.query_embed(text)))
        return np.asarray(vectors[0], dtype=np.float32)


def get_provider(provider: str, model: str) -> EmbeddingProvider | None:
    """Build the configured provider; None disables semantic search."""
    if provider in ("off", "none", ""):
        return None
    if provider == "fastembed":
        try:
            import fastembed  # noqa: F401 — availability probe only
        except Exception as exc:
            logger.warning("fastembed unavailable (%s) — semantic search disabled", exc)
            return None
        return FastEmbedProvider(model)
    logger.warning("unknown embeddings provider %r — semantic search disabled", provider)
    return None
