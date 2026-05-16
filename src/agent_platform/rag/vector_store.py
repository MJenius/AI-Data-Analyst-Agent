from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Any

import numpy as np

try:
    import faiss
except ImportError:
    faiss = None

from agent_platform.rag.embeddings import EmbeddingModel
from agent_platform.rag.ingestion.schema_context import SchemaDocument

logger = logging.getLogger(__name__)


class FaissVectorStore:
    """FAISS-backed vector store for semantic schema retrieval."""

    def __init__(self, embedding_model: EmbeddingModel) -> None:
        self._embedding_model = embedding_model
        self._index = None
        self._documents: list[SchemaDocument] = []

    def save(self, path: str | Path) -> None:
        if self._index is None or faiss is None:
            return
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(path / "index.faiss"))
        with open(path / "documents.json", "w") as f:
            # Simple serialization of SchemaDocument
            docs_data = [
                {"id": doc.id, "text": doc.text, "metadata": doc.metadata}
                for doc in self._documents
            ]
            json.dump(docs_data, f)
        logger.info("saved_faiss_index", extra={"path": str(path)})

    def load(self, path: str | Path) -> bool:
        if faiss is None:
            return False
        path = Path(path)
        if not (path / "index.faiss").exists() or not (path / "documents.json").exists():
            return False
        
        self._index = faiss.read_index(str(path / "index.faiss"))
        with open(path / "documents.json", "r") as f:
            docs_data = json.load(f)
            self._documents = [
                SchemaDocument(id=d["id"], text=d["text"], metadata=d["metadata"])
                for d in docs_data
            ]
        logger.info("loaded_faiss_index", extra={"path": str(path)})
        return True

    def add_documents(self, documents: list[SchemaDocument]) -> None:
        if faiss is None:
            logger.warning("faiss_not_installed_skipping_semantic_indexing")
            return

        # Check if we already have these documents to avoid duplicates
        existing_ids = {doc.id for doc in self._documents}
        new_docs = [doc for doc in documents if doc.id not in existing_ids]
        
        if not new_docs:
            return

        self._documents.extend(new_docs)
        texts = [doc.text for doc in new_docs]
        embeddings = self._embedding_model.embed_batch(texts)
        embeddings_np = np.array(embeddings).astype("float32")

        dimension = embeddings_np.shape[1]
        if self._index is None:
            self._index = faiss.IndexFlatL2(dimension)
        
        self._index.add(embeddings_np)
        logger.info("added_documents_to_faiss", extra={"count": len(new_docs)})

    def search(self, query: str, top_k: int = 5) -> list[tuple[SchemaDocument, float]]:
        if self._index is None or not self._documents:
            return []

        query_embedding = self._embedding_model.embed_text(query)
        query_np = np.array([query_embedding]).astype("float32")
        
        distances, indices = self._index.search(query_np, top_k)
        
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx != -1 and idx < len(self._documents):
                results.append((self._documents[idx], float(dist)))
        
        return results
