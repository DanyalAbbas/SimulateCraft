"""Async simulation loop: Environment + Agents + EventBus.

The Runner never inspects what kind of Brain an agent uses. All observability
flows through the EventBus; with zero subscribers everything still runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .agent import Agent
from .environment import Environment
from .events import (
    AgentActed,
    AgentAdded,
    AgentRemoved,
    AgentSpoke,
    BrainFailed,
    EventBus,
    HumanChat,
    HumanControl,
    InboundEvent,
    ObservationTaken,
    SimulationEnded,
    SimulationPaused,
    SimulationResumed,
    SimulationStarted,
    TickCompleted,
)
from .schemas import Action, NoOpAction, Observation, StepResult

log = logging.getLogger(__name__)


class RunnerConfig(BaseModel):
    """``tick_rate=None`` runs as fast as possible (batch mode); a number paces realtime."""

    tick_rate: float | None = None
    max_ticks: int = 10_000
    decision_timeout: float = 30.0
    emit_observations: bool = False
    stop_when_env_empty: bool = True


@dataclass
class Runner:
    environment: Environment
    agents: list[Agent] = field(default_factory=list)
    bus: EventBus = field(default_factory=EventBus)
    config: RunnerConfig = field(default_factory=RunnerConfig)

    _running: bool = False
    _paused: bool = False
    _step_requests: int = 0
    _stop_reason: str = ""
    _control_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        with contextlib.suppress(RuntimeError):
            self.bus.bind_loop(asyncio.get_running_loop())
        self._known_ids: set[str] = set()

    # ---- agent management --------------------------------------------------

    def add_agent(self, agent: Agent) -> None:
        self.agents.append(agent)
        self.environment.register_agent(agent.id)

    def remove_agent(self, agent_id: str) -> bool:
        """Remove an agent from the runner (does not disconnect Minecraft)."""
        before = len(self.agents)
        self.agents = [a for a in self.agents if a.id != agent_id]
        self._known_ids.discard(agent_id)
        return len(self.agents) < before

    def get_agent(self, agent_id: str) -> Agent | None:
        return next((a for a in self.agents if a.id == agent_id), None)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ---- control surface (used by CLI, tests, and the web server) -----------

    async def start(self) -> None:
        """Run until max_ticks / empty env / stop(). Returns when finished."""
        if self._running:
            raise RuntimeError("Runner already running")
        await self._emit(SimulationStarted(agent_ids=[a.id for a in self.agents]))
        self._running = True
        self._stop_reason = "max_ticks"
        await self._sync_membership()
        try:
            while self._running and self.environment.tick_count < self.config.max_ticks:
                await self._process_inbound()
                if not self._running:
                    break
                if self._paused:
                    if self._step_requests > 0:
                        self._step_requests -= 1
                    else:
                        await asyncio.sleep(0.05)
                        continue
                await self.run_tick()
                if not self._running:
                    break
                if self.config.stop_when_env_empty and not self.environment.agent_ids:
                    self._stop_reason = "no_agents_left"
                    break
                await self._pace()
        finally:
            self._running = False
            await self._emit(SimulationEnded(reason=self._stop_reason))

    def request_pause(self) -> None:
        self._paused = True

    def request_resume(self) -> None:
        self._paused = False

    def request_stop(self, reason: str = "requested") -> None:
        self._running = False
        self._stop_reason = reason

    def request_step(self, n: int = 1) -> None:
        self._step_requests += n

    async def step_once(self) -> None:
        """Execute exactly one tick regardless of pause state."""
        was_paused = self._paused
        self._paused = False
        try:
            await self.run_tick()
        finally:
            self._paused = was_paused

    # ---- main tick -----------------------------------------------------------

    async def run_tick(self) -> None:
        tick = self.environment.tick_count
        active_ids = self.environment.agent_ids

        # Environments may implement async prepare_tick() to refresh observations first.
        prepare = getattr(self.environment, "prepare_tick", None)
        if callable(prepare):
            prepared = prepare()
            if inspect.isawaitable(prepared):
                await prepared

        observations: dict[str, Observation] = {}
        for aid in active_ids:
            obs = self.environment.observe(aid)
            if inspect.isawaitable(obs):
                obs = await obs
            observations[aid] = obs
            if self.config.emit_observations:
                await self._emit(
                    ObservationTaken(agent_id=aid, observation_summary=obs.render()), tick=tick
                )

        decisions = await self._gather_decisions(observations, tick)

        for aid in active_ids:
            action, decision_ms = decisions.get(aid, (NoOpAction(), 0.0))
            result = await self._safe_step(aid, action)
            agent = self.get_agent(aid)
            if agent is not None:
                try:
                    await agent.update(result)
                except Exception as exc:
                    msg = f"update failed: {type(exc).__name__}: {exc}"
                    await self._emit(BrainFailed(agent_id=aid, error=msg), tick=tick)
            await self._emit(
                AgentActed(
                    agent_id=aid,
                    action_kind=action.kind,
                    action=action.model_dump(),
                    reward=result.reward,
                    terminated=(
                        result.terminated
                        or result.truncated
                        or aid not in self.environment.agent_ids
                    ),
                    decision_ms=decision_ms,
                ),
                tick=tick,
            )
            said = getattr(action, "text", None) or getattr(action, "say", None)
            if isinstance(said, str) and said.strip():
                await self._emit(AgentSpoke(agent_id=aid, text=said), tick=tick)

        tick_result = self.environment.tick()
        if inspect.isawaitable(tick_result):
            await tick_result
        tick += 1
        await self._emit(TickCompleted(), tick=tick)
        await self._sync_membership()

    async def _gather_decisions(
        self, observations: dict[str, Observation], tick: int
    ) -> dict[str, tuple[Action, float]]:
        """Decide concurrently (LLM I/O overlaps), then apply sequentially for determinism."""
        order = list(observations.keys())

        async def _one(aid: str) -> tuple[str, Action, float]:
            agent = self.get_agent(aid)
            assert agent is not None
            start = time.monotonic()
            try:
                action = await asyncio.wait_for(
                    agent.decide(observations[aid]), timeout=self.config.decision_timeout
                )
                return aid, action, (time.monotonic() - start) * 1000.0
            except TimeoutError:
                await self._emit(
                    BrainFailed(
                        agent_id=aid,
                        error=f"decision timed out after {self.config.decision_timeout}s",
                    ),
                    tick=tick,
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                await self._emit(BrainFailed(agent_id=aid, error=error), tick=tick)
            return aid, NoOpAction(), (time.monotonic() - start) * 1000.0

        results = await asyncio.gather(*(_one(aid) for aid in order))
        return {aid: (action, ms) for aid, action, ms in results}

    async def _safe_step(self, agent_id: str, action: Action) -> StepResult:
        try:
            result = self.environment.step(agent_id, action)
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception as exc:
            log.exception("env.step failed for %s", agent_id)
            return StepResult(info={"error": f"{type(exc).__name__}: {exc}"})

    async def _sync_membership(self) -> None:
        current = set(self.environment.agent_ids)
        for new_id in sorted(current - self._known_ids):
            agent = self.get_agent(new_id)
            pos = _position_of(agent, self.environment)
            await self._emit(
                AgentAdded(agent_id=new_id, name=agent.name if agent else new_id, position=pos)
            )
            self._known_ids.add(new_id)
        for gone_id in sorted(self._known_ids - current):
            await self._emit(AgentRemoved(agent_id=gone_id, reason="left_environment"))
            self._known_ids.discard(gone_id)

    # ---- inbound events -------------------------------------------------------

    async def _process_inbound(self) -> None:
        events: list[InboundEvent] = await self.bus.drain_inbound()
        for event in events:
            await self._handle_inbound(event)

    async def _handle_inbound(self, event: InboundEvent) -> None:
        if isinstance(event, HumanControl):
            command = event.command
            if command == "pause":
                self.request_pause()
                await self._emit(SimulationPaused())
            elif command == "resume":
                self.request_resume()
                await self._emit(SimulationResumed())
            elif command == "step":
                self.request_step(1)
            elif command == "stop":
                self.request_stop("human_stop")
            elif command == "reset":
                self.environment.reset()
        elif isinstance(event, HumanChat):
            if event.target_agent_id:
                agent = self.get_agent(event.target_agent_id)
                if agent is not None:
                    agent.on_human_message(event.sender, event.text)

    # ---- pacing -----------------------------------------------------------------

    async def _pace(self) -> None:
        rate = self.config.tick_rate
        if rate and rate > 0:
            await asyncio.sleep(1.0 / rate)

    async def _emit(self, event: Any, *, tick: int = -1) -> Any:
        return await self.bus.publish(event, tick=tick)


def _position_of(agent: Agent | None, env: Environment) -> list[float] | None:
    lookup = getattr(env, "position_of", None)
    if agent is not None and callable(lookup):
        try:
            pos = lookup(agent.id)
        except Exception:
            pos = None
        if isinstance(pos, (tuple, list)) and len(pos) == 2:
            return [float(pos[0]), float(pos[1])]
    if agent is None:
        return None
    pos = agent.state.get("position")
    if isinstance(pos, (tuple, list)) and len(pos) == 2:
        return [float(pos[0]), float(pos[1])]
    return None
