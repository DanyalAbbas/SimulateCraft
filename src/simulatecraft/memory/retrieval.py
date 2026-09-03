"""Retrieval: recency + importance + embedding-similarity scoring over a MemoryStream."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np

from .stream import MemoryRecord, MemoryStream


class EmbeddingBackend:
    """Swappable embedding backend. Implement ``embed(list[str]) -> (n, dim) float32``."""

    def embed(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError


class HashingEmbedding(EmbeddingBackend):
    """Dependency-free deterministic embeddings via character n-gram hashing.

    Quality is far below a real model but it keeps tests and offline demos
    working with zero downloads. Swap in SentenceTransformerBackend for real use.
    """

    def __init__(self, dim: int = 128, ngram: int = 3) -> None:
        self.dim = dim
        self.ngram = ngram

    def _embed_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        normalized = f" {text.lower().strip()} "
        for i in range(len(normalized) - self.ngram + 1):
            gram = normalized[i : i + self.ngram]
            digest = hashlib.md5(gram.encode()).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._embed_one(t) for t in texts])


class SentenceTransformerEmbedding(EmbeddingBackend):
    """Local sentence-transformers model (downloaded on first use)."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self.model.encode(texts), dtype=np.float32)


@dataclass
class RetrievedMemory:
    record: MemoryRecord
    score: float
    relevance: float
    recency: float
    importance: float


class Retriever:
    """Weighted relevance+recency+importance retrieval (Generative Agents style)."""

    def __init__(
        self,
        stream: MemoryStream,
        embedding_backend: EmbeddingBackend | None = None,
        *,
        w_relevance: float = 1.0,
        w_recency: float = 1.0,
        w_importance: float = 1.0,
        recency_decay: float = 0.995,
    ) -> None:
        self.stream = stream
        self.embedding_backend = embedding_backend or HashingEmbedding()
        self.w_relevance = w_relevance
        self.w_recency = w_recency
        self.w_importance = w_importance
        self.recency_decay = recency_decay

    def ensure_embeddings(self) -> list[MemoryRecord]:
        missing = [r for r in self.stream.records if r.embedding is None]
        if missing:
            vectors = self.embedding_backend.embed([r.content for r in missing])
            for record, vector in zip(missing, vectors, strict=True):
                record.embedding = vector.tolist()
        return self.stream.records

    def retrieve(
        self, query: str, *, top_k: int = 5, min_score: float = 0.0
    ) -> list[RetrievedMemory]:
        records = self.ensure_embeddings()
        if not records:
            return []
        query_vec = self.embedding_backend.embed([query])[0]

        n = len(records)
        results: list[RetrievedMemory] = []
        for i, record in enumerate(records):
            recency = math.pow(self.recency_decay, n - 1 - i)
            importance = (record.importance - 1) / 9.0
            emb = np.asarray(record.embedding, dtype=np.float32)
            denom = float(np.linalg.norm(query_vec) * np.linalg.norm(emb))
            relevance = float(np.dot(query_vec, emb) / denom) if denom > 0 else 0.0
            score = (
                self.w_relevance * max(relevance, 0.0)
                + self.w_recency * recency
                + self.w_importance * importance
            )
            results.append(
                RetrievedMemory(
                    record=record,
                    score=score,
                    relevance=relevance,
                    recency=recency,
                    importance=importance,
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return [r for r in results[:top_k] if r.score >= min_score]


def default_backend(prefer_transformer: bool = False) -> EmbeddingBackend:
    """Use hashing embeddings by default (zero downloads).

    Pass ``prefer_transformer=True`` or set ``SIMULATECRAFT_EMBEDDINGS=transformer``
    to load sentence-transformers (requires the optional ``embeddings`` extra).
    """
    import os

    if os.getenv("SIMULATECRAFT_EMBEDDINGS", "").strip().lower() in {"transformer", "st", "hf"}:
        prefer_transformer = True
    if prefer_transformer:
        try:
            return SentenceTransformerEmbedding()
        except Exception:
            pass
    return HashingEmbedding()
