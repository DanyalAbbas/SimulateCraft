"""JSONL event logger for replay/analysis, plus a replay utility."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, TextIO

from ..core.events import (
    AgentActed,
    AgentAdded,
    AgentRemoved,
    AgentSpoke,
    BrainFailed,
    Event,
    EventBus,
    HumanChat,
    SimulationEnded,
    SimulationPaused,
    SimulationResumed,
    SimulationStarted,
)

_EVENT_TYPES: dict[str, type[Event]] = {
    t.model_fields["kind"].default: t
    for t in (
        SimulationStarted,
        SimulationEnded,
        SimulationPaused,
        SimulationResumed,
        AgentAdded,
        AgentRemoved,
        AgentActed,
        AgentSpoke,
        BrainFailed,
        HumanChat,
    )
}


class JsonlLogger:
    """Append every outbound event to a ``.jsonl`` file."""

    def __init__(self, path: str | Path, bus: EventBus) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: TextIO = self.path.open("a", encoding="utf-8")
        self._bus = bus
        self._unsub = bus.subscribe(self.handle_event)

    def handle_event(self, event: Event) -> None:
        self._fh.write(event.model_dump_json() + "\n")

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> None:
        try:
            self._bus.unsubscribe(self.handle_event)
        finally:
            self._fh.close()


def load_events(path: str | Path) -> list[Event]:
    """Load logged JSONL events back into typed models."""
    out: list[Event] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw: dict[str, Any] = json.loads(line)
            event_type = _EVENT_TYPES.get(raw.get("kind", ""))
            if event_type is not None:
                out.append(event_type.model_validate(raw))
    return out


class Replayer:
    """Replay logged events onto a (fresh) EventBus at controllable speed.

    ``speed`` multiplier: 1.0 = real time per recorded timestamps,
    N>1 = N times faster, 0 = as fast as possible.
    """

    def __init__(self, path: str | Path) -> None:
        self.events: list[Event] = load_events(path)

    async def replay(self, bus: EventBus, *, speed: float = 0.0) -> int:
        count = 0
        prev_ts: float | None = None
        for event in self.events:
            if speed > 0 and prev_ts is not None and event.timestamp > 0:
                delay = (event.timestamp - prev_ts) / speed
                if delay > 0:
                    await asyncio.sleep(delay)
            prev_ts = event.timestamp or prev_ts
            await bus.publish(event, restamp=False)
            count += 1
        return count
