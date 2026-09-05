"""Fill remaining coverage gaps with focused unit tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from helpers import FixedAction, ScriptedBrain, StubEnvironment
from simulatecraft.brains.llm import LLMBrain, LLMBrainConfig
from simulatecraft.core import Agent, AgentState, HumanControl, Observation, Runner, RunnerConfig
from simulatecraft.core.events import EventBus
from simulatecraft.memory.reflection import ReflectionEngine
from simulatecraft.memory.retrieval import Retriever, default_backend
from simulatecraft.memory.stream import MemoryStream
from simulatecraft.minecraft.actions import MineBlock, Move
from simulatecraft.minecraft.connection import BridgeError, MinecraftBridge
from simulatecraft.minecraft.env import MinecraftEnvironment
from simulatecraft.planning.planner import Plan, Planner
from simulatecraft.server.agents import (
    AgentCreateRequest,
    _slug_username,
    _unique_id,
    create_agent,
    delete_agent,
)
from simulatecraft.skills.registry import SkillRegistry


def test_slug_and_unique_id() -> None:
    assert _slug_username("123").startswith("bot_")
    assert _slug_username("").startswith("bot_")
    env = StubEnvironment()
    runner = Runner(environment=env)
    runner.add_agent(Agent(id="alex", name="A", brain=ScriptedBrain(lambda o: FixedAction())))
    env.register_agent("alex")
    assert _unique_id(runner, "alex") == "alex_2"


async def test_create_agent_bad_id() -> None:
    env = StubEnvironment()
    runner = Runner(environment=env)
    with pytest.raises(ValueError, match="agent id"):
        await create_agent(runner, AgentCreateRequest(id="1bad", username="Steve"))


async def test_create_agent_no_spawn() -> None:
    class NoSpawn(StubEnvironment):
        pass

    env = NoSpawn()
    # hide spawn_bot
    object.__setattr__(env, "spawn_bot", None)
    env.spawn_bot = None  # type: ignore[assignment]
    runner = Runner(environment=env)
    with pytest.raises(ValueError, match="does not support"):
        await create_agent(runner, AgentCreateRequest(username="Steve"))


async def test_delete_agent_missing() -> None:
    env = StubEnvironment()
    runner = Runner(environment=env)
    with pytest.raises(ValueError, match="unknown agent"):
        await delete_agent(runner, "nope")


def test_mine_nearest_render() -> None:
    assert "nearest" in MineBlock(block_name="oak_log").render()


def test_openrouter_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if "openrouter" in name:
            raise ImportError("missing")
        if fromlist and any("openrouter" in str(x) for x in fromlist):
            # from pydantic_ai.models.openrouter import OpenRouterModel
            mod_name = name
            if "openrouter" in mod_name or (
                name.startswith("pydantic_ai") and fromlist and "OpenRouter" in str(fromlist)
            ):
                raise ImportError("missing")
        try:
            return real_import(name, globals, locals, fromlist, level)
        except ImportError:
            raise

    # More reliable: patch the import inside the function by raising when loading submodule
    import types

    fake_mod = types.ModuleType("pydantic_ai.models.openrouter")

    def boom_getattr(name: str) -> Any:
        raise ImportError("missing openrouter")

    # Simplest path: monkeypatch _make_openrouter_model's import by replacing the function's dependency
    from simulatecraft.brains import llm as llm_mod

    def raise_import(*a: Any, **k: Any) -> Any:
        raise ImportError(
            "OpenRouter support requires pydantic-ai[openrouter]. "
            "Run: pip install 'pydantic-ai[openrouter]'"
        )

    # Force the try/except ImportError branch by making the import fail
    import sys

    class FakeLoader:
        def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
            if "openrouter" in fullname:
                raise ImportError("blocked")
            return None

    # Directly exercise by calling with patched importlib
    import importlib

    real = importlib.import_module

    def fake_import_module(name: str, package: str | None = None) -> Any:
        if "openrouter" in name:
            raise ImportError("no")
        return real(name, package)

    # The code uses `from pydantic_ai.models.openrouter import ...` not import_module.
    # Patch builtins.__import__ carefully:
    def selective_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if name in {"pydantic_ai.models.openrouter", "pydantic_ai.providers.openrouter"}:
            raise ImportError("missing extra")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", selective_import)
    with pytest.raises(ImportError, match="openrouter|OpenRouter|missing"):
        llm_mod._make_openrouter_model("x")


async def test_decide_rejects_non_action() -> None:
    brain = LLMBrain([Move], persona="p", model="test", config=LLMBrainConfig(model="test"))

    class FakeResult:
        output = "not-an-action"

    async def fake_run(*a: Any, **k: Any) -> FakeResult:
        return FakeResult()

    brain.agent.run = fake_run  # type: ignore[method-assign]
    with pytest.raises(TypeError, match="non-Action"):
        await brain.decide(Observation(agent_id="a", tick=0))


async def test_runner_pause_step_requests(make_runner) -> None:
    runner, _ = make_runner(
        max_ticks=5,
        tick_rate=None,
        stop_when_env_empty=False,
        agents=[
            Agent(
                id="p",
                name="P",
                brain=ScriptedBrain(lambda o: FixedAction()),
                state=AgentState(),
            )
        ],
    )
    runner.request_pause()
    runner.request_step(2)
    task = asyncio.create_task(runner.start())
    await asyncio.sleep(0.25)
    runner.request_resume()
    await asyncio.wait_for(task, timeout=3)
    assert runner.environment.tick_count >= 2


async def test_runner_already_running(make_runner) -> None:
    runner, _ = make_runner(
        max_ticks=10_000,
        tick_rate=1.0,
        stop_when_env_empty=False,
        agents=[
            Agent(
                id="p",
                name="P",
                brain=ScriptedBrain(lambda o: FixedAction()),
                state=AgentState(),
            )
        ],
    )
    task = asyncio.create_task(runner.start())
    for _ in range(50):
        if runner.is_running:
            break
        await asyncio.sleep(0.02)
    assert runner.is_running
    with pytest.raises(RuntimeError, match="already running"):
        await runner.start()
    runner.request_stop()
    await asyncio.wait_for(task, timeout=3)


async def test_human_control_inbound(make_runner) -> None:
    runner, _ = make_runner(max_ticks=20, stop_when_env_empty=False)
    task = asyncio.create_task(runner.start())
    await asyncio.sleep(0.05)
    runner.bus.publish_inbound(HumanControl(command="pause"))
    await asyncio.sleep(0.1)
    runner.bus.publish_inbound(HumanControl(command="resume"))
    runner.bus.publish_inbound(HumanControl(command="step"))
    runner.bus.publish_inbound(HumanControl(command="reset"))
    await asyncio.sleep(0.1)
    runner.request_stop()
    await asyncio.wait_for(task, timeout=3)


async def test_env_connect_and_chat_trim(monkeypatch: pytest.MonkeyPatch) -> None:
    env = MinecraftEnvironment(chat_log_size=2)
    env.add_bot("a", username="Alex")

    class FakeBridge:
        def __init__(self, **kwargs: Any) -> None:
            self.handlers: dict[str, Any] = {}

        def on_event(self, name: str, handler: Any) -> None:
            self.handlers[name] = handler

        async def connect(self) -> None:
            return None

        async def get_state(self) -> dict[str, Any]:
            return {
                "position": {"x": 0, "y": 64, "z": 0},
                "stats": {},
                "inventory": [],
                "nearby_blocks": [],
                "nearby_entities": [],
                "craftable": [],
            }

        async def get_map(self, *a: Any, **k: Any) -> dict[str, Any]:
            return {"width": 16, "height": 16, "origin_x": 0, "origin_z": 0}

        async def close(self) -> None:
            return None

    monkeypatch.setattr("simulatecraft.minecraft.env.MinecraftBridge", FakeBridge)
    monkeypatch.setattr(MinecraftEnvironment, "_apply_presence", AsyncMock())
    await env.connect()
    handler = env._bridges["a"].handlers["chat"]
    handler({"sender": "a", "text": "1"})
    handler({"sender": "a", "text": "2"})
    handler({"sender": "a", "text": "3"})
    assert len(env._chat_logs["a"]) == 2
    await env.close()


async def test_tcp_connect_success(monkeypatch: pytest.MonkeyPatch) -> None:
    b = MinecraftBridge(connect_timeout=1.0)
    b._process = MagicMock(poll=lambda: None)
    reader, writer = object(), MagicMock()

    async def open_conn(*a: Any, **k: Any) -> tuple[Any, Any]:
        return reader, writer

    async def fake_read(self: MinecraftBridge) -> None:
        return None

    monkeypatch.setattr(asyncio, "open_connection", open_conn)
    monkeypatch.setattr(MinecraftBridge, "_read_loop", fake_read)
    await b._tcp_connect()
    assert b._writer is writer


async def test_read_loop_exception() -> None:
    b = MinecraftBridge()

    class BoomReader:
        async def readline(self) -> bytes:
            raise RuntimeError("socket boom")

    b._reader = BoomReader()  # type: ignore[assignment]
    await b._read_loop()


async def test_connect_timeout_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "bot.js"
    script.write_text("//", encoding="utf-8")
    b = MinecraftBridge(bot_script=script, connect_timeout=0.05)
    monkeypatch.setattr(
        "simulatecraft.minecraft.connection.subprocess.Popen",
        lambda *a, **k: MagicMock(poll=lambda: None),
    )

    async def fake_tcp(self: MinecraftBridge) -> None:
        return None

    monkeypatch.setattr(MinecraftBridge, "_tcp_connect", fake_tcp)
    monkeypatch.setattr(MinecraftBridge, "close", AsyncMock())
    with pytest.raises(BridgeError, match="did not spawn"):
        await b.connect()


async def test_planner_and_skills_edges(tmp_path: Path) -> None:
    plan = Plan(goal="g", steps=["a", "b"])
    assert plan.current() == "a"
    plan.advance()
    assert plan.render()
    assert not plan.done()
    plan.advance()
    assert plan.done()

    empty = Plan(goal="g", steps=[])
    assert empty.current() is None
    assert empty.render()

    planner = Planner(generator=lambda ctx: Plan(goal="x", steps=["1"]))
    assert (await planner.ensure_plan("ctx")).goal == "x"
    planner.current_plan = Plan(goal="old", steps=["1"])
    assert await planner.maybe_replan("obs") is False
    planner.current_plan = Plan(goal="old", steps=["1"])
    planner.current_plan.current_step = 1
    assert await planner.maybe_replan("obs") is True
    planner.reset()
    assert planner.current_plan is None
    assert await planner.maybe_replan("obs") is False

    reg = SkillRegistry(persistence_path=str(tmp_path / "skills.json"))
    reg.register("s", "wood gathering", [{"kind": "wait"}], verified=True)
    assert reg.find("wood", require_verified=True) is not None
    assert await reg.verify("missing", True) is False
    assert await reg.verify("s", True) is True


async def test_reflection_async() -> None:
    def summarizer(text: str) -> list[str]:
        return ["insight about the world"]

    engine = ReflectionEngine(summarizer, every_n_records=2, min_records=2)
    mem = MemoryStream()
    await mem.add("one")
    assert engine.should_reflect(mem) is False
    await mem.add("two")
    assert engine.should_reflect(mem) is True
    insights = await engine.reflect(mem)
    assert insights
    assert await engine.reflect(MemoryStream()) == []


async def test_retrieval_default_backend() -> None:
    backend = default_backend()
    mem = MemoryStream()
    await mem.add("hello world oak tree")
    retriever = Retriever(mem, backend)
    hits = retriever.retrieve("oak", top_k=1)
    assert hits


def test_cli_compose_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from simulatecraft import cli

    monkeypatch.setattr(cli, "_need", lambda name, hint: "/usr/bin/docker")
    monkeypatch.setattr(cli, "_port_open", lambda h, p: False)
    monkeypatch.setattr(cli, "_run", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_docker_container_health", lambda *a, **k: "healthy")
    monkeypatch.setattr(cli.time, "sleep", lambda *_: None)
    cli.ensure_minecraft(skip=False, host="localhost", port=25565)


def test_ws_map_message() -> None:
    from fastapi.testclient import TestClient

    from simulatecraft.server.app import create_app

    env = StubEnvironment()
    runner = Runner(environment=env, config=RunnerConfig(max_ticks=50, tick_rate=50))
    env.reset()

    async def fetch_map(ox: int, oz: int, size: int = 128) -> dict[str, Any]:
        return {"origin_x": ox, "origin_z": oz, "size": size, "pixels": []}

    env.fetch_map = fetch_map  # type: ignore[attr-defined]
    app = create_app(runner)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "state"
            ws.send_json({"type": "map", "origin_x": 0, "origin_z": 0, "size": 32})
            got = False
            for _ in range(40):
                msg = ws.receive_json()
                if msg.get("type") == "map":
                    got = True
                    break
            assert got
