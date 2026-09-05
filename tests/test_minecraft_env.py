"""Unit tests for MinecraftEnvironment with a mocked bridge."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from simulatecraft.minecraft.actions import Chat, MineBlock, NavigateTo
from simulatecraft.minecraft.env import MinecraftEnvironment, _parse_state
from simulatecraft.minecraft.observations import ChatMessage, MinecraftObservation, Vec3


def _raw_state(**overrides: Any) -> dict[str, Any]:
    base = {
        "position": {"x": 10, "y": 64, "z": -4},
        "yaw": 90.0,
        "pitch": 0.0,
        "on_ground": True,
        "biome": "plains",
        "equipped_item": "stick",
        "stats": {
            "health": 18,
            "food": 16,
            "saturation": 5,
            "experience_level": 1,
            "game_mode": "survival",
            "is_raining": False,
            "time_of_day": 1000,
        },
        "inventory": [{"name": "oak_log", "count": 3, "slot": 0}],
        "nearby_blocks": [{"name": "dirt", "x": 1, "y": 63, "z": 1, "hardness": 0.5}],
        "nearby_entities": [
            {
                "name": "cow",
                "entity_type": "mob",
                "x": 2,
                "y": 64,
                "z": 2,
                "distance": 3.0,
                "health": 10,
            }
        ],
        "craftable": [{"item_name": "stick", "count": 4, "needs_table": False}],
    }
    base.update(overrides)
    return base


def test_add_bot_and_ports() -> None:
    env = MinecraftEnvironment()
    env.add_bot("a", username="Alex", goal="explore")
    env.add_bot("b", username="Bea")
    assert env._bot_configs["a"].ipc_port == 25570
    assert env._bot_configs["b"].ipc_port == 25571
    with pytest.raises(ValueError, match="already"):
        env.add_bot("a")


def test_parse_state_and_observe() -> None:
    obs = _parse_state(_raw_state(), "a", 5, [ChatMessage(sender="x", text="hi")], "goal")
    assert obs.position.x == 10
    assert obs.inventory[0].name == "oak_log"
    assert obs.current_goal == "goal"

    env = MinecraftEnvironment()
    env.add_bot("a", goal="mine")
    empty = env.observe("a")
    assert empty.current_goal == "mine"
    env._obs_cache = {"a": obs}
    assert env.observe("a") is obs


async def test_step_rewards() -> None:
    env = MinecraftEnvironment()
    env.add_bot("a")
    bridge = AsyncMock()
    env._bridges["a"] = bridge

    bridge.perform_action = AsyncMock(return_value={"ok": True, "said": "hi"})
    result = await env.step("a", Chat(text="hi"))
    assert result.reward == 0.05

    bridge.perform_action = AsyncMock(return_value={"ok": True})
    result = await env.step("a", NavigateTo(x=1, y=64, z=1))
    assert result.reward == 0.1

    bridge.perform_action = AsyncMock(return_value={"ok": False})
    result = await env.step("a", NavigateTo(x=1, y=64, z=1))
    assert result.reward == -0.05

    bridge.perform_action = AsyncMock(return_value={"ok": True})
    result = await env.step("a", MineBlock(x=0, y=64, z=0))
    assert result.reward == 0.02

    bridge.perform_action = AsyncMock(side_effect=RuntimeError("fail"))
    result = await env.step("a", MineBlock(x=0, y=64, z=0))
    assert result.reward == -0.1
    assert result.info["ok"] is False

    missing = await env.step("missing", Chat(text="x"))
    assert "no bridge" in missing.info["error"]


async def test_fetch_map_and_snapshot() -> None:
    env = MinecraftEnvironment()
    env.add_bot("a", username="Alex", goal="g", persona="p")
    bridge = AsyncMock()
    bridge.get_map = AsyncMock(
        return_value={"width": 32, "height": 32, "origin_x": 0, "origin_z": 0, "pixels": []}
    )
    env._bridges["a"] = bridge
    env._home_xz = (0, 0)
    env._obs_cache = {
        "a": MinecraftObservation(
            agent_id="a",
            tick=0,
            position=Vec3(x=5, y=64, z=5),
            current_goal="g",
        )
    }
    tile = await env.fetch_map(1000, 1000, 32)
    assert tile["width"] == 32
    snap = env.snapshot()
    assert "a" in snap.agents
    assert snap.world["kind"] == "minecraft"

    env._obs_cache = {}
    snap2 = env.snapshot()
    assert snap2.agents["a"]["position"] == [0.0, 0.0]

    env2 = MinecraftEnvironment()
    assert await env2.fetch_map(0, 0) == {}


async def test_refresh_map_skip_and_fail() -> None:
    env = MinecraftEnvironment()
    await env._refresh_map()  # no bridges
    env.add_bot("a")
    bridge = AsyncMock()
    env._bridges["a"] = bridge
    env._obs_cache = {
        "a": MinecraftObservation(agent_id="a", tick=0, position=Vec3(x=0, y=64, z=0))
    }
    env._map_cache = {"width": 128}
    env._map_origin = (-64, -64)
    env._home_xz = (0, 0)
    env._tick_count = 1  # not divisible by 3 → skip
    await env._refresh_map()
    bridge.get_map.assert_not_called()

    env._tick_count = 3
    env.fetch_map = AsyncMock(side_effect=RuntimeError("scan fail"))  # type: ignore[method-assign]
    await env._refresh_map()


async def test_despawn_and_presence(monkeypatch: pytest.MonkeyPatch) -> None:
    env = MinecraftEnvironment()
    env.add_bot("a", spawn_x=1, spawn_y=64, spawn_z=2)
    bridge = AsyncMock()
    bridge.close = AsyncMock()
    env._bridges["a"] = bridge
    env._obs_cache = {"a": MinecraftObservation(agent_id="a", tick=0)}
    await env.despawn_bot("a")
    assert "a" not in env._bridges

    env.add_bot("b", spawn_x=1, spawn_y=64, spawn_z=2)
    bridge2 = AsyncMock()
    monkeypatch.setattr(
        "simulatecraft.minecraft.rcon.run_commands",
        lambda cmds: (_ for _ in ()).throw(RuntimeError("rcon down")),
    )
    bridge2.configure_presence = AsyncMock(side_effect=RuntimeError("bot fail"))
    await env._apply_presence("b", bridge2, env._bot_configs["b"])

    monkeypatch.setattr("simulatecraft.minecraft.rcon.run_commands", lambda cmds: ["ok"])
    await env._apply_presence("b", bridge2, env._bot_configs["b"])

    env.add_bot("c")  # no spawn
    await env._apply_presence("c", bridge2, env._bot_configs["c"])


async def test_fetch_all_states_and_tick() -> None:
    env = MinecraftEnvironment()
    env.add_bot("a", goal="g")
    bridge = AsyncMock()
    bridge.get_state = AsyncMock(return_value=_raw_state())
    env._bridges["a"] = bridge
    await env._fetch_all_states()
    assert "a" in env._obs_cache

    bridge.get_state = AsyncMock(side_effect=RuntimeError("boom"))
    await env._fetch_all_states()

    env.tick()
    assert env.tick_count == 1
    env.reset()
    assert env._map_cache is None


async def test_connect_one_and_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    env = MinecraftEnvironment()
    env.add_bot("a", username="Alex")

    class FakeBridge:
        def __init__(self, **kwargs: Any) -> None:
            self.handlers: dict[str, Any] = {}

        def on_event(self, name: str, handler: Any) -> None:
            self.handlers[name] = handler

        async def connect(self) -> None:
            return None

    monkeypatch.setattr("simulatecraft.minecraft.env.MinecraftBridge", FakeBridge)
    monkeypatch.setattr(MinecraftEnvironment, "_apply_presence", AsyncMock())
    await env._connect_one("a")
    assert "a" in env._bridges
    env._bridges["a"].handlers["chat"]({"sender": "x", "text": "hi"})
    assert env._chat_logs["a"][-1].text == "hi"

    # spawn_bot failure path
    env2 = MinecraftEnvironment()

    async def boom(self: MinecraftEnvironment, agent_id: str) -> None:
        raise RuntimeError("fail connect")

    monkeypatch.setattr(MinecraftEnvironment, "_connect_one", boom)
    monkeypatch.setattr(MinecraftEnvironment, "despawn_bot", AsyncMock())
    with pytest.raises(RuntimeError):
        await env2.spawn_bot("z", username="Zed")


async def test_prepare_tick_and_close() -> None:
    env = MinecraftEnvironment()
    env._fetch_all_states = AsyncMock()  # type: ignore[method-assign]
    env._refresh_map = AsyncMock()  # type: ignore[method-assign]
    await env.prepare_tick()
    env._fetch_all_states.assert_awaited()

    bridge = AsyncMock()
    env._bridges["a"] = bridge
    await env.close()
    assert env._bridges == {}


async def test_context_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    env = MinecraftEnvironment()
    monkeypatch.setattr(MinecraftEnvironment, "connect", AsyncMock())
    monkeypatch.setattr(MinecraftEnvironment, "close", AsyncMock())
    async with env:
        pass
