"""Shared test helpers (not fixtures)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from simulatecraft.brains import Brain
from simulatecraft.core import (
    Action,
    Agent,
    Environment,
    Observation,
    Runner,
    RunnerConfig,
    Snapshot,
    StepResult,
)


class FixedAction(Action):
    kind: str = "fixed"


class SayAction(Action):
    kind: str = "say"
    text: str = ""


class ScriptedBrain(Brain[Observation]):
    """Deterministic brain for tests: decide via a callable."""

    def __init__(self, policy: Callable[[Observation], Action]) -> None:
        self.policy = policy

    def decide(self, observation: Observation) -> Action:
        return self.policy(observation)


class StubEnvironment(Environment):
    """Minimal in-memory env for runner/server tests (no Minecraft)."""

    def __init__(self) -> None:
        super().__init__()
        self.positions: dict[str, list[float]] = {}
        self.last_actions: dict[str, Action] = {}
        self.exit_on_say: bool = False

    def register_agent(self, agent_id: str) -> None:
        super().register_agent(agent_id)
        self.positions.setdefault(agent_id, [0.0, 0.0, 0.0])

    def observe(self, agent_id: str) -> Observation:
        return Observation(
            agent_id=agent_id,
            tick=self._tick_count,
            data={"position": self.positions.get(agent_id, [0.0, 0.0, 0.0])},
        )

    def step(self, agent_id: str, action: Action) -> StepResult:
        self.last_actions[agent_id] = action
        if self.exit_on_say and action.kind == "say":
            self.unregister_agent(agent_id)
            return StepResult(
                reward=1.0,
                terminated=True,
                info={"said": getattr(action, "text", "")},
            )
        reward = 0.1 if action.kind == "say" else 0.0
        info = {"said": getattr(action, "text", "")} if action.kind == "say" else {}
        return StepResult(reward=reward, info=info)

    def snapshot(self) -> Snapshot:
        return Snapshot(
            tick=self._tick_count,
            agents={
                aid: {"position": self.positions.get(aid, [0.0, 0.0, 0.0]), "name": aid}
                for aid in self.agent_ids
            },
            world={"stub": True},
        )


class RunnerFactory:
    def __init__(self) -> None:
        self.created: list[Runner] = []

    def __call__(
        self,
        env: StubEnvironment | None = None,
        agents: list[Agent] | None = None,
        **config_kwargs: Any,
    ) -> tuple[Runner, StubEnvironment]:
        environment = env or StubEnvironment()
        config_kwargs.setdefault("max_ticks", 50)
        runner = Runner(environment=environment, config=RunnerConfig(**config_kwargs))
        for agent in agents or []:
            runner.add_agent(agent)
        environment.reset()
        for agent in agents or []:
            environment.register_agent(agent.id)
        self.created.append(runner)
        return runner, environment
