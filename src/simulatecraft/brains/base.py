"""Brain interface: the swappable decision-making core of an Agent.

Contract: ``decide(observation) -> Action`` and ``update(step_result)``.
Both may be sync or async; the Agent wrapper handles either.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from ..core.schemas import Action, Observation, StepResult

ObsT = TypeVar("ObsT", bound=Observation)


class Brain(ABC, Generic[ObsT]):
    """A policy. Scripted rules, RL policies, and LLM reasoning all implement this."""

    @abstractmethod
    def decide(self, observation: ObsT) -> Action | Any:
        """Choose an action for this observation. May be a coroutine function."""

    def update(self, step_result: StepResult) -> None | Any:
        """Learn / log / no-op after the action is applied. May be a coroutine."""

    def on_human_message(self, sender: str, text: str) -> None:
        """Optional sync hook for human-in-the-loop chat (queue it for next decide)."""
