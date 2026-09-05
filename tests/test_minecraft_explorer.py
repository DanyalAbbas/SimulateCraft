"""Tests for explorer example builders and CLI dispatch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from simulatecraft.core.events import AgentActed, BrainFailed, EventBus
from simulatecraft.examples.minecraft_explorer import agents as agent_mod
from simulatecraft.examples.minecraft_explorer import main as explorer_main


def test_agent_factories(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for factory in (
        agent_mod.explorer,
        agent_mod.builder,
        agent_mod.gatherer,
        agent_mod.defender,
    ):
        brain = factory("test")
        assert brain.persona
    custom = agent_mod.custom(persona="P", goal="G", model="test", instructions="extra")
    assert custom.persona == "P"


def test_build_and_unknown_agent() -> None:
    env, runner = explorer_main.build("localhost", 25565, ["explorer", "builder"], "test", 1.0, 10)
    assert set(env._bot_configs) == {"explorer", "builder"}
    assert {a.id for a in runner.agents} == {"explorer", "builder"}
    with pytest.raises(ValueError, match="Unknown agent"):
        explorer_main.build("localhost", 25565, ["nope"], "test", 1.0, 10)


def test_attach_progress(capsys: pytest.CaptureFixture) -> None:
    bus = EventBus()
    explorer_main._attach_progress(bus)
    import asyncio

    async def pub() -> None:
        await bus.publish(AgentActed(agent_id="a", action_kind="chat", decision_ms=12))
        await bus.publish(BrainFailed(agent_id="a", error="boom"))

    asyncio.run(pub())
    out = capsys.readouterr().out
    assert "chat" in out
    assert "FAILED" in out


async def test_run_headless(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    env = MagicMock()
    env.tick_count = 3
    env.__aenter__ = AsyncMock(return_value=env)
    env.__aexit__ = AsyncMock(return_value=None)
    runner = MagicMock()
    runner.bus = EventBus()
    runner.start = AsyncMock()
    monkeypatch.setattr(explorer_main, "build", lambda *a, **k: (env, runner))
    monkeypatch.setattr(explorer_main, "JsonlLogger", MagicMock())
    await explorer_main.run_headless(
        "localhost", 25565, ["explorer"], "test", 1.0, 5, str(tmp_path / "e.jsonl")
    )
    runner.start.assert_awaited()


async def test_run_with_server(monkeypatch: pytest.MonkeyPatch) -> None:
    env = MagicMock()
    env.__aenter__ = AsyncMock(return_value=env)
    env.__aexit__ = AsyncMock(return_value=None)
    runner = MagicMock()
    runner.bus = EventBus()
    monkeypatch.setattr(explorer_main, "build", lambda *a, **k: (env, runner))

    server = MagicMock()
    server.serve = AsyncMock()
    monkeypatch.setattr(
        "simulatecraft.server.SimulationServer",
        lambda *a, **k: server,
    )
    await explorer_main.run_with_server(
        "localhost", 25565, ["explorer"], "test", 1.0, 5, "127.0.0.1", 8000, None
    )
    server.serve.assert_awaited()


def test_main_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def headless(*a: Any, **k: Any) -> None:
        calls.append("headless")

    async def served(*a: Any, **k: Any) -> None:
        calls.append("serve")

    monkeypatch.setattr(explorer_main, "run_headless", headless)
    monkeypatch.setattr(explorer_main, "run_with_server", served)
    monkeypatch.setattr(explorer_main, "resolve_model", lambda: "test")
    monkeypatch.setattr(explorer_main.asyncio, "run", lambda coro: asyncio_run(coro))

    import asyncio as aio

    def asyncio_run(coro: Any) -> None:
        aio.get_event_loop_policy().new_event_loop().run_until_complete(coro)

    monkeypatch.setattr(
        "sys.argv",
        ["prog", "--agents", "explorer", "--model", "test"],
    )
    explorer_main.main()
    assert calls == ["headless"]

    calls.clear()
    monkeypatch.setattr(
        "sys.argv",
        ["prog", "--serve", "--agents", "explorer", "--model", "test"],
    )
    explorer_main.main()
    assert calls == ["serve"]
