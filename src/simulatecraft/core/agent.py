"""Base Agent: identity + state + an interchangeable Brain."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from pydantic import BaseModel

from .schemas import Action, AgentState, Observation, StepResult


class Agent(BaseModel):
    """Wraps a Brain; the runner only ever talks to this interface."""

    id: str
    name: str = ""
    state: AgentState = AgentState()
    brain: Any = None  # Brain instance; typed loosely to keep Agent serializable
    metadata: dict[str, Any] = {}

    model_config = {"arbitrary_types_allowed": True}

    async def decide(self, observation: Observation) -> Action:
        result = self.brain.decide(observation)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def update(self, step_result: StepResult) -> None:
        result = self.brain.update(step_result)
        if asyncio.iscoroutine(result) or asyncio.isfuture(result):
            await result

    def on_human_message(self, sender: str, text: str) -> None:
        """Hook for human-in-the-loop chat. Brains may override via attribute."""
        handler = getattr(self.brain, "on_human_message", None)
        if handler is not None:
            handler(sender, text)
