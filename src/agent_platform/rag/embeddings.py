from __future__ import annotations

import logging
from typing import Any

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

import json
import hashlib
from pathlib import Path

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Wrapper for local sentence-transformers embedding model with disk caching."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", cache_dir: str = "runtime/cache/embeddings") -> None:
        self.model_name = model_name
        self._model = None
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_model(self) -> Any:
        if self._model is None:
            if SentenceTransformer is None:
                raise ImportError(
                    "sentence-transformers is not installed. "
                    "Run 'pip install sentence-transformers' to use embedding-based RAG."
                )
            logger.info("loading_embedding_model", extra={"model": self.model_name})
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def _get_cache_path(self, text: str) -> Path:
        text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{text_hash}.json"

    def embed_text(self, text: str) -> list[float]:
        cache_path = self._get_cache_path(text)
        if cache_path.exists():
            with open(cache_path, "r") as f:
                return json.load(f)
        
        model = self._ensure_model()
        embedding = model.encode(text).tolist()
        
        with open(cache_path, "w") as f:
            json.dump(embedding, f)
            
        return embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []
        
        # 1. Check cache first
        for idx, text in enumerate(texts):
            cache_path = self._get_cache_path(text)
            if cache_path.exists():
                try:
                    with open(cache_path, "r") as f:
                        results[idx] = json.load(f)
                except Exception as exc:
                    logger.warning(f"Failed to read cached embedding, will re-embed: {exc}")
                    uncached_indices.append(idx)
                    uncached_texts.append(text)
            else:
                uncached_indices.append(idx)
                uncached_texts.append(text)
                
        # 2. Batch encode any uncached texts
        if uncached_texts:
            model = self._ensure_model()
            logger.info(f"Batch encoding {len(uncached_texts)} uncached text items...")
            embeddings = model.encode(uncached_texts, batch_size=32).tolist()
            
            # Save to cache and populate results
            for idx, text, emb in zip(uncached_indices, uncached_texts, embeddings):
                results[idx] = emb
                cache_path = self._get_cache_path(text)
                try:
                    with open(cache_path, "w") as f:
                        json.dump(emb, f)
                except Exception as exc:
                    logger.warning(f"Failed to write cache for embedding: {exc}")
                    
        # Verify all elements are populated
        return [r for r in results if r is not None]
