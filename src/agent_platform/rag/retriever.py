from __future__ import annotations

import math
import re
from pathlib import Path
from collections import Counter
from dataclasses import dataclass

from agent_platform.rag.ingestion.schema_context import SchemaDocument


TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]+")


@dataclass(slots=True)
class RetrievedContext:
    id: str
    text: str
    score: float
    metadata: dict[str, str]


class VectorIndex:
    """Pluggable vector index interface; FAISS can back this in production."""

    def search(self, query: str, top_k: int) -> list[RetrievedContext]:
        raise NotImplementedError


class KeywordVectorIndex(VectorIndex):
    """Dependency-free vector fallback using normalized token overlap."""

    def __init__(self, documents: list[SchemaDocument]) -> None:
        self._documents = documents
        self._vectors = [self._vectorize(document.text) for document in documents]

    def search(self, query: str, top_k: int) -> list[RetrievedContext]:
        query_vector = self._vectorize(query)
        scored = []
        for document, vector in zip(self._documents, self._vectors):
            score = self._cosine(query_vector, vector)
            boosted = score + self._semantic_boost(query, document.text)
            scored.append(
                RetrievedContext(
                    id=document.id,
                    text=document.text,
                    score=boosted,
                    metadata=document.metadata,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]

    def _vectorize(self, text: str) -> Counter[str]:
        return Counter(token.lower() for token in TOKEN_RE.findall(text))

    def _cosine(self, left: Counter[str], right: Counter[str]) -> float:
        if not left or not right:
            return 0.0
        overlap = set(left) & set(right)
        numerator = sum(left[token] * right[token] for token in overlap)
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        return numerator / (left_norm * right_norm)

    def _semantic_boost(self, query: str, text: str) -> float:
        boost = 0.0
        lowered_query = query.lower()
        lowered_text = text.lower()
        if "revenue" in lowered_query and "order_items" in lowered_text:
            boost += 0.35
        if "product" in lowered_query and "products" in lowered_text:
            boost += 0.35
        if "region" in lowered_query and "region" in lowered_text:
            boost += 0.2
        if "growth" in lowered_query and "growth" in lowered_text:
            boost += 0.2
        return boost


class SemanticVectorIndex(VectorIndex):
    """Semantic vector index using FAISS and local embeddings with persistence."""

    def __init__(self, documents: list[SchemaDocument], embedding_model: EmbeddingModel | None = None, index_path: str | Path = "runtime/cache/vector_index") -> None:
        from agent_platform.rag.embeddings import EmbeddingModel
        from agent_platform.rag.vector_store import FaissVectorStore, faiss

        # FaissVectorStore intentionally degrades to a no-op when FAISS is not
        # installed.  A no-op index is not a valid semantic retriever, however:
        # callers must receive the keyword fallback rather than an empty result
        # set.  Raising here is handled by SchemaRetriever.from_documents.
        if faiss is None:
            raise ImportError("faiss-cpu is required for SemanticVectorIndex")

        self._embedding_model = embedding_model or EmbeddingModel()
        self._store = FaissVectorStore(self._embedding_model)
        self.index_path = Path(index_path)
        
        # Try loading existing index first
        if not self._store.load(self.index_path):
            self._store.add_documents(documents)
            self._store.save(self.index_path)

    def search(self, query: str, top_k: int) -> list[RetrievedContext]:
        results = self._store.search(query, top_k)
        return [
            RetrievedContext(
                id=doc.id,
                text=doc.text,
                score=1.0 / (1.0 + dist),
                metadata=doc.metadata,
            )
            for doc, dist in results
        ]


class SchemaRetriever:
    """Retrieves relevant schema and business context for analytics questions."""

    def __init__(self, index: VectorIndex) -> None:
        self._index = index

    @classmethod
    def from_documents(cls, documents: list[SchemaDocument], use_semantic: bool = True) -> "SchemaRetriever":
        if use_semantic:
            try:
                return cls(SemanticVectorIndex(documents))
            except (ImportError, Exception) as exc:
                import logging
                logging.getLogger(__name__).warning("semantic_index_failed_falling_back", extra={"error": str(exc)})
        
        return cls(KeywordVectorIndex(documents))

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedContext]:
        return self._index.search(query, top_k)
