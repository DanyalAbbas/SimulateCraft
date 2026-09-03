"""Core cross-boundary data models shared by environments, agents, brains, and viewers."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Action(StrictModel):
    """Base class for domain-specific actions.

    Subclass this in your environment package (e.g. ``MoveAction(kind="move")``)
    and pass the discriminated union to brains so LLM/RL outputs arrive validated.
    """

    kind: str = Field(default="noop", description="Discriminator identifying the action type.")

    def render(self) -> str:
        return f"{self.kind}: {self.model_dump(exclude={'kind'})}"


class NoOpAction(Action):
    kind: str = Field(default="noop", frozen=True)


class Observation(StrictModel):
    """Structured state visible to one agent. Supports partial observability.

    The ``data`` payload is domain-specific; define typed subclasses for richer
    schemas (e.g. ``GridObservation``) when you want validation at the edges.
    """

    agent_id: str
    tick: int = 0
    data: dict[str, Any] = Field(default_factory=dict)

    def render(self) -> str:
        return json.dumps(self.data, sort_keys=True, default=str)


class StepResult(StrictModel):
    """Outcome of applying one action for one agent."""

    reward: float = 0.0
    terminated: bool = False
    truncated: bool = False
    info: dict[str, Any] = Field(default_factory=dict)


class AgentState(StrictModel):
    """Flexible per-agent state container (position, inventory, mood, ...)."""

    data: dict[str, Any] = Field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)
