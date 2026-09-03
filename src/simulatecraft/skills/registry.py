"""Voyager-style skill registry: store, verify, and reuse action sequences.

Skills are looked up by embedding similarity between a query (intent /
situation description) and stored skill descriptions, so an LLM brain can
reuse a proven plan instead of re-deriving it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from ..memory.retrieval import EmbeddingBackend, HashingEmbedding


class Skill(BaseModel):
    name: str
    description: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    verified: bool = False
    times_used: int = 0
    success_count: int = 0
    embedding: list[float] | None = None

    def record_use(self, success: bool) -> None:
        self.times_used += 1
        if success:
            self.success_count += 1


class SkillRegistry:
    def __init__(
        self,
        embedding_backend: EmbeddingBackend | None = None,
        *,
        persistence_path: str | Path | None = None,
        similarity_threshold: float = 0.4,
    ) -> None:
        self.skills: list[Skill] = []
        self.embedding_backend = embedding_backend or HashingEmbedding()
        self.persistence_path = Path(persistence_path) if persistence_path else None
        self.similarity_threshold = similarity_threshold
        if self.persistence_path and self.persistence_path.exists():
            self._load()

    def register(
        self,
        name: str,
        description: str,
        steps: list[dict[str, Any]],
        *,
        verified: bool = False,
    ) -> Skill:
        existing = self.get(name)
        skill = existing if existing else Skill(name=name, description=description)
        skill.description = description
        skill.steps = steps
        skill.verified = verified
        skill.embedding = self.embedding_backend.embed([description])[0].tolist()
        if not existing:
            self.skills.append(skill)
        self._save()
        return skill

    def get(self, name: str) -> Skill | None:
        return next((s for s in self.skills if s.name == name), None)

    async def verify(self, name: str, achieved: bool) -> bool:
        """Mark whether executing the skill achieved its intended effect."""
        skill = self.get(name)
        if skill is None:
            return False
        skill.verified = bool(achieved)
        skill.record_use(achieved)
        self._save()
        return skill.verified

    def find(self, query: str, *, require_verified: bool = True) -> Skill | None:
        """Best matching skill above threshold, or None."""
        candidates = [s for s in self.skills if s.verified or not require_verified]
        if not candidates:
            return None
        missing = [s for s in candidates if s.embedding is None]
        if missing:
            vectors = self.embedding_backend.embed([s.description for s in missing])
            for skill, vector in zip(missing, vectors, strict=True):
                skill.embedding = vector.tolist()
        query_vec = self.embedding_backend.embed([query])[0]
        best: Skill | None = None
        best_score = -1.0
        for skill in candidates:
            emb = np.asarray(skill.embedding, dtype=np.float32)
            denom = float(np.linalg.norm(query_vec) * np.linalg.norm(emb))
            score = float(np.dot(query_vec, emb) / denom) if denom > 0 else 0.0
            if score > best_score:
                best, best_score = skill, score
        if best is None or best_score < self.similarity_threshold:
            return None
        return best

    def _save(self) -> None:
        if self.persistence_path is None:
            return
        self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            s.model_dump(exclude={"embedding"}) | {"has_embedding": s.embedding is not None}
            for s in self.skills
        ]
        self.persistence_path.write_text(json.dumps(payload, indent=2))

    def _load(self) -> None:
        assert self.persistence_path is not None
        raw: list[dict[str, Any]] = json.loads(self.persistence_path.read_text())
        for item in raw:
            item.pop("has_embedding", None)
            self.skills.append(Skill.model_validate(item))
