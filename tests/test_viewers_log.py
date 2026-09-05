"""Unit tests for JSONL logger / replay and viewers package exports."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from simulatecraft.core.events import (
    AgentActed,
    EventBus,
    HumanChat,
    SimulationPaused,
    SimulationStarted,
)
from simulatecraft.viewers import JsonlLogger, Replayer, load_events
from simulatecraft.viewers import log as log_mod


async def test_jsonl_logger_writes_and_closes(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    bus = EventBus()
    logger = JsonlLogger(path, bus)
    await bus.publish(SimulationStarted(agent_ids=["a"]))
    await bus.publish(HumanChat(sender="h", text="hi", target_agent_id="a"))
    logger.flush()
    logger.close()

    events = load_events(path)
    assert len(events) == 2
    assert events[0].kind == "simulation.started"
    assert events[1].kind == "human.chat"


def test_load_events_skips_blank_and_unknown(tmp_path: Path) -> None:
    path = tmp_path / "mixed.jsonl"
    path.write_text(
        "\n"
        + SimulationPaused().model_dump_json()
        + "\n"
        + '{"kind":"not.a.real.event","tick":1}\n'
        + "\n",
        encoding="utf-8",
    )
    events = load_events(path)
    assert len(events) == 1
    assert isinstance(events[0], SimulationPaused)


async def test_replayer_speed_zero(tmp_path: Path) -> None:
    path = tmp_path / "replay.jsonl"
    bus = EventBus()
    logger = JsonlLogger(path, bus)
    e1 = SimulationStarted(agent_ids=["x"])
    e1.timestamp = 1.0
    e2 = AgentActed(agent_id="x", action_kind="chat", decision_ms=10)
    e2.timestamp = 3.0
    await bus.publish(e1, restamp=False)
    await bus.publish(e2, restamp=False)
    logger.close()

    out_bus = EventBus()
    received: list[str] = []
    out_bus.subscribe(lambda e: received.append(e.kind))
    count = await Replayer(path).replay(out_bus, speed=0.0)
    assert count == 2
    assert received == ["simulation.started", "agent.acted"]


async def test_replayer_speed_sleeps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "timed.jsonl"
    bus = EventBus()
    logger = JsonlLogger(path, bus)
    e1 = SimulationStarted(agent_ids=["x"])
    e1.timestamp = 10.0
    e2 = SimulationPaused()
    e2.timestamp = 12.0
    await bus.publish(e1, restamp=False)
    await bus.publish(e2, restamp=False)
    logger.close()

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    out = EventBus()
    await Replayer(path).replay(out, speed=2.0)
    assert sleeps == [1.0]  # (12-10)/2


def test_viewers_package_exports() -> None:
    assert log_mod.JsonlLogger is JsonlLogger
    assert log_mod.Replayer is Replayer
    assert log_mod.load_events is load_events
