"""Typed event schemas and the central pub/sub EventBus.

Every observability concern (terminal viewer, JSONL logger, websocket
broadcaster) subscribes here. Environments and agents never know they are
being watched: with zero subscribers everything still works.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

_seq_counter = itertools.count(1)


def _stamp(event: Event, tick: int) -> Event:
    updates: dict[str, Any] = {"seq": next(_seq_counter), "timestamp": time.time()}
    if tick >= 0:
        updates["tick"] = tick
    return event.model_copy(update=updates)


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = 0
    tick: int = -1
    timestamp: float = 0.0
    kind: str


class SimulationStarted(Event):
    kind: Literal["simulation.started"] = "simulation.started"
    agent_ids: list[str] = Field(default_factory=list)


class SimulationEnded(Event):
    kind: Literal["simulation.ended"] = "simulation.ended"
    reason: str = "max_ticks"


class SimulationPaused(Event):
    kind: Literal["simulation.paused"] = "simulation.paused"


class SimulationResumed(Event):
    kind: Literal["simulation.resumed"] = "simulation.resumed"


class TickCompleted(Event):
    kind: Literal["env.ticked"] = "env.ticked"


class AgentAdded(Event):
    kind: Literal["agent.added"] = "agent.added"
    agent_id: str
    name: str = ""
    position: list[float] | None = None


class AgentRemoved(Event):
    kind: Literal["agent.removed"] = "agent.removed"
    agent_id: str
    reason: str = ""


class ObservationTaken(Event):
    kind: Literal["agent.observed"] = "agent.observed"
    agent_id: str
    observation_summary: str = ""


class AgentActed(Event):
    kind: Literal["agent.acted"] = "agent.acted"
    agent_id: str
    action_kind: str = ""
    action: dict[str, Any] = Field(default_factory=dict)
    reward: float = 0.0
    terminated: bool = False
    decision_ms: float = 0.0


class AgentSpoke(Event):
    kind: Literal["agent.spoke"] = "agent.spoke"
    agent_id: str
    text: str


class BrainFailed(Event):
    kind: Literal["brain.failed"] = "brain.failed"
    agent_id: str
    error: str


class HumanChat(Event):
    """Inbound: a human sent a message, optionally targeting one agent."""

    kind: Literal["human.chat"] = "human.chat"
    sender: str = "human"
    target_agent_id: str | None = None
    text: str


class HumanControl(Event):
    """Inbound: viewer control commands (pause/resume/step/stop/reset)."""

    kind: Literal["human.control"] = "human.control"
    command: Literal["pause", "resume", "step", "stop", "reset"]
    sender: str = "human"


InboundEvent = HumanChat | HumanControl

EventHandler = Callable[[Event], None | Awaitable[None]]


class EventBus:
    """Ordered pub/sub with isolated subscriber errors and an inbound queue."""

    def __init__(self) -> None:
        self._handlers: list[tuple[EventHandler, bool]] = []
        self._inbound: asyncio.Queue[InboundEvent] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, handler: EventHandler, *, once: bool = False) -> Callable[[], None]:
        self._handlers.append((handler, once))
        return lambda: self.unsubscribe(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        self._handlers = [(h, once) for h, once in self._handlers if h is not handler]

    async def publish(self, event: Event, *, tick: int = -1, restamp: bool = True) -> Event:
        stamped = _stamp(event, tick) if restamp else event
        for handler, once in list(self._handlers):
            if once:
                self.unsubscribe(handler)
            try:
                result = handler(stamped)
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                    await result
            except Exception:
                log.exception("event handler %r failed for %s", handler, stamped.kind)
        return stamped

    # ---- inbound channel -------------------------------------------------

    def publish_inbound(self, event: InboundEvent) -> None:
        """Queue an inbound event AND mirror it onto the outbound bus for viewers."""
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is not None:
            if self._loop is None:
                self.bind_loop(current)
            if current is self._loop:
                self._inbound.put_nowait(event)
                current.create_task(self.publish(event))
                return
        if self._loop is not None and self._loop.is_running():

            def _queue_and_broadcast() -> None:
                self._inbound.put_nowait(event)
                asyncio.ensure_future(self.publish(event), loop=self._loop)

            self._loop.call_soon_threadsafe(_queue_and_broadcast)
        else:
            self._inbound.put_nowait(event)

    async def drain_inbound(self) -> list[InboundEvent]:
        events: list[InboundEvent] = []
        while not self._inbound.empty():
            events.append(self._inbound.get_nowait())
        return events
