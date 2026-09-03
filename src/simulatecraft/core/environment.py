"""Base Environment: subclass for any domain without touching the runner."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable
from typing import Any

from pydantic import BaseModel

from .schemas import Action, Observation, StepResult


class Snapshot(BaseModel):
    """Domain-agnostic full-state snapshot served over REST / rendered by viewers."""

    tick: int = 0
    agents: dict[str, dict[str, Any]] = {}
    world: dict[str, Any] = {}


class Environment(ABC):
    """Owns all mutable simulation state.

    Contract:
      - ``observe`` may return partial state (partial observability is supported).
      - ``step`` mutates state for one agent and returns a StepResult.
      - ``agent_ids`` must reflect dynamic membership (spawn/death/exit).
      - ``tick`` advances environment-owned state (weather, NPC timers, physics).
    """

    def __init__(self) -> None:
        self._tick_count: int = 0
        self._registered: set[str] = set()

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def agent_ids(self) -> list[str]:
        return sorted(self._registered)

    def register_agent(self, agent_id: str) -> None:
        self._registered.add(agent_id)

    def unregister_agent(self, agent_id: str) -> None:
        self._registered.discard(agent_id)

    @abstractmethod
    def observe(self, agent_id: str) -> Observation | Awaitable[Observation]:
        """Return the state visible to ``agent_id`` (may be partial)."""

    @abstractmethod
    def step(self, agent_id: str, action: Action) -> StepResult | Awaitable[StepResult]:
        """Apply ``action`` for ``agent_id``, mutating environment state."""

    def tick(self) -> None | Awaitable[None]:
        """Advance environment-owned dynamics once per simulation tick."""
        self._tick_count += 1
        return None

    def reset(self, seed: int | None = None) -> None:
        """Reset to the initial episode state. Subclasses should override."""
        self._tick_count = 0

    def snapshot(self) -> Snapshot:
        """Full-state view for REST/viewers. Override to include world details."""
        return Snapshot(tick=self._tick_count)
