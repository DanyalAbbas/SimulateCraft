"""Hierarchical plan generation & re-planning. Optional: brains without
long-horizon needs can ignore this module entirely.

LLM calls are injected as callables, keeping this module dependency-free.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field


class Plan(BaseModel):
    goal: str = ""
    steps: list[str] = Field(default_factory=list)
    current_step: int = 0

    def current(self) -> str | None:
        if 0 <= self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None

    def advance(self) -> str | None:
        step = self.current()
        if step is not None:
            self.current_step += 1
        return step

    def render(self) -> str:
        if not self.steps:
            return f"goal: {self.goal}" if self.goal else "no plan"
        lines = [f"plan (goal: {self.goal})"]
        for i, step in enumerate(self.steps):
            marker = "->" if i == self.current_step else ("done" if i < self.current_step else "  ")
            lines.append(f"  {marker} {i + 1}. {step}")
        return "\n".join(lines)

    def done(self) -> bool:
        return self.current_step >= len(self.steps)


PlanGenerator = Callable[[str], Awaitable[Plan] | Plan]
ReplanChecker = Callable[[str, Plan], Awaitable[bool] | bool]


class Planner:
    """Holds the current plan; delegates generation/checking to injected policies."""

    def __init__(
        self,
        generator: PlanGenerator,
        *,
        replan_checker: ReplanChecker | None = None,
    ) -> None:
        self.generator = generator
        self.replan_checker = replan_checker
        self.current_plan: Plan | None = None

    async def ensure_plan(self, context: str) -> Plan:
        if self.current_plan is None or self.current_plan.done():
            self.current_plan = await _maybe_await(self.generator(context))
        return self.current_plan

    async def maybe_replan(self, observation_summary: str) -> bool:
        """True when the checker says reality contradicts the plan."""
        if self.current_plan is None:
            return False
        if self.replan_checker is None:
            heuristic = self.current_plan.done()
            if heuristic:
                self.current_plan = None
            return heuristic
        contradicted = await _maybe_await(
            self.replan_checker(observation_summary, self.current_plan)
        )
        if contradicted:
            self.current_plan = None
        return contradicted

    def reset(self) -> None:
        self.current_plan = None


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or asyncio.isfuture(value) or inspect.isawaitable(value):
        return await value
    return value
