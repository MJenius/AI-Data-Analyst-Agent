from __future__ import annotations

import math
import re
import hashlib
from pathlib import Path
from collections import Counter
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

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
    def __init__(self, documents: list[SchemaDocument], embedding_model: Any | None = None, index_path: str | Path = "runtime/cache/vector_index") -> None:
        from agent_platform.rag.embeddings import EmbeddingModel, SentenceTransformer
        from agent_platform.rag.vector_store import FaissVectorStore, faiss

        # If sentence_transformers or faiss is not installed, degrade to keyword index
        if faiss is None or SentenceTransformer is None:
            raise ImportError("faiss-cpu and sentence-transformers are required for SemanticVectorIndex")

        self._embedding_model = embedding_model or EmbeddingModel()
        self._store = FaissVectorStore(self._embedding_model)
        fingerprint = hashlib.sha256(
            "\n".join(f"{document.id}:{document.text}" for document in documents).encode("utf-8")
        ).hexdigest()[:16]
        self.index_path = Path(index_path) / fingerprint
        
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

    STOP_WORDS = {
        "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for", "from",
        "has", "have", "how", "in", "is", "it", "most", "of", "on", "or", "per", "the",
        "to", "total", "what", "which", "with",
    }

    def __init__(self, index: VectorIndex, documents: list[SchemaDocument] | None = None) -> None:
        self._index = index
        self._documents = documents or []
        self._documents_by_id = {document.id: document for document in self._documents}

    @classmethod
    def from_documents(cls, documents: list[SchemaDocument], use_semantic: bool = True) -> "SchemaRetriever":
        if use_semantic:
            try:
                return cls(SemanticVectorIndex(documents), documents)
            except (ImportError, Exception) as exc:
                import logging
                logging.getLogger(__name__).warning("semantic_index_failed_falling_back", extra={"error": str(exc)})
        
        return cls(KeywordVectorIndex(documents), documents)

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedContext]:
        return self._index.search(query, top_k)

    def retrieve_grounded(self, query: str, max_tables: int = 6) -> list[RetrievedContext]:
        """Select schema evidence, then expand the shortest valid join paths between selected tables."""
        if not self._documents:
            return self.retrieve(query, top_k=5)

        query_terms = self._terms(query)
        ranked = self._index.search(query, top_k=len(self._documents))
        table_scores: dict[str, float] = defaultdict(float)
        matched_terms: list[tuple[float, SchemaDocument]] = []

        for rank, item in enumerate(ranked):
            document = self._documents_by_id.get(item.id)
            if document is None:
                continue
            lexical = self._overlap(query_terms, self._terms(document.text))
            score = min(item.score + lexical + 0.05 / (rank + 1), 0.99)
            kind = document.metadata.get("kind")
            if kind in {"table", "column"}:
                table = document.metadata.get("table")
                if table:
                    table_scores[table] = max(table_scores[table], score)
            elif kind == "business_term":
                term_match = self._coverage(query_terms, self._terms(document.metadata.get("term", "")))
                if term_match < 0.5:
                    continue
                term_score = 1.0 + term_match
                matched_terms.append((score + term_score, document))
                for table in document.metadata.get("tables", "").split(","):
                    if table:
                        table_scores[table] = max(table_scores[table], term_score)

        for document in self._documents:
            table = document.metadata.get("table")
            if table and document.metadata.get("kind") in {"table", "column"}:
                identifier = table
                if document.metadata.get("column"):
                    identifier += " " + document.metadata["column"]
                exact = self._coverage(query_terms, self._terms(identifier))
                if exact >= 0.75:
                    table_scores[table] = max(table_scores[table], 1.0 + exact)

        if "english" in query_terms and table_scores.get("products", 0.0) > 0:
            table_scores["product_category_name_translation"] = max(
                table_scores.get("product_category_name_translation", 0.0),
                table_scores["products"] + 0.1,
            )

        grounded_columns: set[str] = set()
        for _, document in matched_terms:
            for qualified in document.metadata.get("columns", "").split(","):
                if qualified and "." in qualified:
                    grounded_columns.add(qualified.strip())

        ordered_tables = sorted(table_scores, key=lambda table: (-table_scores[table], table))
        if not ordered_tables:
            ordered_tables = [
                document.metadata["table"]
                for document in self._documents
                if document.metadata.get("kind") == "table"
            ][:1]
        best = table_scores.get(ordered_tables[0], 0.0)
        seeds = [
            table for table in ordered_tables
            if table_scores.get(table, 0.0) >= max(0.2, best * 0.55)
        ][:3] or ordered_tables[:1]

        graph: dict[str, set[str]] = defaultdict(set)
        for document in self._documents:
            if document.metadata.get("kind") != "relationship":
                continue
            left, right = document.metadata.get("from_table"), document.metadata.get("to_table")
            if left and right:
                graph[left].add(right)
                graph[right].add(left)

        selected = set(seeds)
        for index, left in enumerate(seeds):
            for right in seeds[index + 1:]:
                selected.update(self._shortest_path(graph, left, right))
        if len(selected) > max_tables:
            selected = set(sorted(selected, key=lambda table: (-table_scores.get(table, 0.0), table))[:max_tables])

        contexts = [
            RetrievedContext(
                id="grounded:summary",
                text=(
                    f"Grounded schema subset. Physical tables allowed in SQL: {', '.join(sorted(selected))}. "
                    "Every base column and join must appear in the packets below."
                ),
                score=1.0,
                metadata={"kind": "schema_summary", "tables": ",".join(sorted(selected))},
            )
        ]
        for table in sorted(selected, key=lambda name: (-table_scores.get(name, 0.0), name)):
            document = self._documents_by_id.get(f"table:{table}")
            if document:
                contexts.append(self._context(document, table_scores.get(table, 0.0)))
        for document in self._documents:
            if (
                document.metadata.get("kind") == "relationship"
                and document.metadata.get("from_table") in selected
                and document.metadata.get("to_table") in selected
            ):
                contexts.append(self._context(document, 1.0))
        included_ids = {item.id for item in contexts}
        for table in sorted(selected, key=lambda name: (-table_scores.get(name, 0.0), name)):
            column_candidates: list[tuple[float, SchemaDocument]] = []
            for document in self._documents:
                if document.metadata.get("kind") != "column" or document.metadata.get("table") != table:
                    continue
                column_name = document.metadata.get("column", "")
                lexical = self._overlap(query_terms, self._terms(f"{table} {column_name}"))
                if lexical > 0:
                    column_candidates.append((lexical, document))
            for _, document in sorted(column_candidates, key=lambda item: -item[0])[:2]:
                if document.id not in included_ids:
                    contexts.append(self._context(document, 0.9))
                    included_ids.add(document.id)
        for qualified in sorted(grounded_columns):
            table, column = qualified.split(".", 1)
            column_id = f"column:{table}.{column}"
            column_document = self._documents_by_id.get(column_id)
            if column_document and column_id not in included_ids:
                contexts.append(self._context(column_document, 1.0))
                included_ids.add(column_id)
        seen = set()
        for score, document in sorted(matched_terms, key=lambda item: -item[0]):
            if document.id not in seen:
                contexts.append(self._context(document, score))
                seen.add(document.id)
            if len(seen) == 3:
                break
        return contexts

    def full_context(self) -> list[RetrievedContext]:
        """Return the non-duplicated full schema reference context."""
        return [
            self._context(document, 1.0)
            for document in self._documents
            if document.metadata.get("kind") != "column"
        ]

    @classmethod
    def _terms(cls, text: str) -> set[str]:
        words = set(re.findall(r"[a-z0-9]+", text.lower().replace("_", " ")))
        normalized = set()
        for word in words - cls.STOP_WORDS:
            normalized.add(word)
            if len(word) > 4 and word.endswith("s"):
                normalized.add(word[:-1])
            if len(word) > 5 and word.endswith("ly"):
                normalized.add(word[:-2])
        return normalized

    @staticmethod
    def _overlap(left: set[str], right: set[str]) -> float:
        return len(left & right) / max(len(left), 1)

    @staticmethod
    def _coverage(query_terms: set[str], target_terms: set[str]) -> float:
        return len(query_terms & target_terms) / max(len(target_terms), 1)

    @staticmethod
    def _shortest_path(graph: dict[str, set[str]], start: str, end: str) -> list[str]:
        queue = deque([(start, [start])])
        visited = {start}
        while queue:
            node, path = queue.popleft()
            if node == end:
                return path
            for neighbor in sorted(graph.get(node, ())):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        return []

    @staticmethod
    def _context(document: SchemaDocument, score: float) -> RetrievedContext:
        return RetrievedContext(document.id, document.text, score, document.metadata)
