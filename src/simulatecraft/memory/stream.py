"""MemoryStream: append-only log of observations/events with importance scores."""

from __future__ import annotations

import itertools
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

ImportanceScorer = Callable[[str, str], int | Awaitable[int]]

DEFAULT_IMPORTANCE: dict[str, int] = {
    "observation": 3,
    "chat": 6,
    "human_chat": 8,
    "reflection": 9,
    "plan": 7,
    "action_result": 2,
}


class MemoryRecord(BaseModel):
    id: str
    timestamp: float
    sim_tick: int = -1
    kind: Literal["observation", "chat", "human_chat", "reflection", "plan", "action_result"] = (
        "observation"
    )
    content: str
    importance: int = Field(default=3, ge=1, le=10)
    metadata: dict[str, Any] = {}
    embedding: list[float] | None = None


class MemoryStream:
    """Append-only memory log. Records get IDs and wall-clock timestamps."""

    def __init__(self, scorer: ImportanceScorer | None = None) -> None:
        self.records: list[MemoryRecord] = []
        self._ids = itertools.count(1)
        self.scorer = scorer

    async def add(
        self,
        content: str,
        *,
        kind: str = "observation",
        sim_tick: int = -1,
        importance: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        if importance is None:
            importance = await self._score(content, kind)
        record = MemoryRecord(
            id=f"m{next(self._ids)}",
            timestamp=time.time(),
            sim_tick=sim_tick,
            content=content,
            kind=kind,  # type: ignore[arg-type]
            importance=max(1, min(10, importance)),
            metadata=metadata or {},
        )
        self.records.append(record)
        return record

    async def _score(self, content: str, kind: str) -> int:
        if self.scorer is not None:
            import inspect

            result = self.scorer(content, kind)
            if inspect.isawaitable(result):
                return int(await result)
            return int(result)
        return DEFAULT_IMPORTANCE.get(kind, 3)

    def __len__(self) -> int:
        return len(self.records)

    def recent(self, n: int = 10) -> list[MemoryRecord]:
        return self.records[-n:]

    def all(self) -> list[MemoryRecord]:
        return list(self.records)
