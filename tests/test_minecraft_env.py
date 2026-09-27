"""Unit tests for MinecraftEnvironment with a mocked bridge."""

from __future__ import annotations

import asyncio
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
    assert env._bot_configs["a"].ipc_port == 35670
    assert env._bot_configs["b"].ipc_port == 35671
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
    # Isolate from any local data/world_settings.json boundaries.
    env._world_settings.boundaries.enabled = False
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
    empty = await env2.fetch_map(0, 0)
    assert empty["pixels"] == ""
    assert empty["origin_x"] == 0


def test_map_pan_limit_constructor() -> None:
    env = MinecraftEnvironment(map_pan_limit=2048)
    assert env.map_pan_limit == 2048
    env_small = MinecraftEnvironment(map_pan_limit=10)
    assert env_small.map_pan_limit == 128  # floor
    env_huge = MinecraftEnvironment(map_pan_limit=1_500_000)
    assert env_huge.map_pan_limit == 8192  # cap


def test_map_tile_origins() -> None:
    origins = MinecraftEnvironment.map_tile_origins(-10, 130, -10, 130, tile=128)
    assert origins == [
        (-128, -128),
        (-128, 0),
        (-128, 128),
        (0, -128),
        (0, 0),
        (0, 128),
        (128, -128),
        (128, 0),
        (128, 128),
    ]
    assert MinecraftEnvironment.map_tile_origins(0, 0, 0, 0, tile=128) == [(0, 0)]


async def test_preload_map_region(monkeypatch: pytest.MonkeyPatch) -> None:
    env = MinecraftEnvironment(map_pan_limit=128)
    env.add_bot("a", username="Alex")
    bridge = AsyncMock()
    bridge.configure_presence = AsyncMock(return_value={"ok": True})
    bridge.get_map = AsyncMock(
        side_effect=lambda ox, oz, size: {
            "origin_x": ox,
            "origin_z": oz,
            "width": size,
            "height": size,
            "pixels": "AAAA",
            "coverage": 0.9,
        }
    )
    env._bridges["a"] = bridge
    env._home_xz = (0, 0)
    env._obs_cache = {
        "a": MinecraftObservation(
            agent_id="a",
            tick=0,
            position=Vec3(x=1, y=70, z=2),
            current_goal="g",
        )
    }

    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    # Don't spawn real Mineflayer scouts in unit tests.
    env._spawn_map_scouts = AsyncMock(return_value=[])  # type: ignore[method-assign]

    async def fake_tp(username: str, br: Any, x: float, y: float, z: float) -> None:
        await br.configure_presence(x=x, y=y, z=z)

    env._teleport_bot = fake_tp  # type: ignore[method-assign]

    progress: list[tuple[int, int]] = []

    async def on_tile(_tile: dict, cur: int, tot: int) -> None:
        progress.append((cur, tot))

    result = await env.preload_map_region(
        0, 200, 0, 200, settle_seconds=0.01, workers=1, use_agents=True, on_tile=on_tile
    )
    assert result["ok"] is True
    assert result["scanned"] == 4  # 0 and 128 in each axis
    assert result["workers"] == 1
    assert result["pan_limit"] >= 200
    assert progress[-1] == (4, 4)
    assert bridge.configure_presence.await_count >= 5  # 4 tiles + restore
    assert bridge.get_map.await_count >= 4

    with pytest.raises(ValueError, match="tiles"):
        await env.preload_map_region(0, 5000, 0, 5000, max_tiles=4, workers=1, use_agents=True)

    empty = MinecraftEnvironment()
    with pytest.raises(RuntimeError, match="No bots"):
        await empty.preload_map_region(0, 10, 0, 10)


async def test_preload_map_region_parallel_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    env = MinecraftEnvironment(map_pan_limit=128)
    env.add_bot("a", username="Alex")
    env.add_bot("b", username="Bob")
    bridges = []
    for aid in ("a", "b"):
        bridge = AsyncMock()
        bridge.configure_presence = AsyncMock(return_value={"ok": True})
        bridge.get_map = AsyncMock(
            side_effect=lambda ox, oz, size: {
                "origin_x": ox,
                "origin_z": oz,
                "width": size,
                "height": size,
                "pixels": "AAAA",
                "coverage": 0.9,
            }
        )
        env._bridges[aid] = bridge
        bridges.append(bridge)
    env._home_xz = (0, 0)
    env._obs_cache = {
        "a": MinecraftObservation(agent_id="a", tick=0, position=Vec3(x=0, y=70, z=0)),
        "b": MinecraftObservation(agent_id="b", tick=0, position=Vec3(x=1, y=70, z=1)),
    }
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    env._spawn_map_scouts = AsyncMock(return_value=[])  # type: ignore[method-assign]
    env._teleport_bot = AsyncMock()  # type: ignore[method-assign]

    result = await env.preload_map_region(
        0, 200, 0, 200, settle_seconds=0.01, workers=8, use_agents=True
    )
    assert result["ok"] is True
    assert result["scanned"] == 4
    assert result["workers"] == 2
    assert result["scouts"] == 0
    assert bridges[0].get_map.await_count + bridges[1].get_map.await_count >= 4


async def test_refresh_map_skip_and_fail() -> None:
    env = MinecraftEnvironment()
    await env._refresh_map()  # no bridges
    env.add_bot("a")
    bridge = AsyncMock()
    env._bridges["a"] = bridge
    env._obs_cache = {
        "a": MinecraftObservation(agent_id="a", tick=0, position=Vec3(x=0, y=64, z=0))
    }
    # Agent at (0,0) with tile size 128 → origin (-128, -128). Same origin → skip.
    env._map_cache = {"width": 128}
    env._map_origin = (-128, -128)
    env._home_xz = (0, 0)
    await env._refresh_map()
    bridge.get_map.assert_not_called()

    # Different cached origin → scan; failures are logged, not raised.
    env._map_origin = (0, 0)
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
    monkeypatch.setattr(MinecraftEnvironment, "_protect_agents_for_join", AsyncMock())
    with pytest.raises(RuntimeError):
        await env2.spawn_bot("z", username="Zed")


async def test_recover_bot_after_respawn() -> None:
    env = MinecraftEnvironment()
    env.add_bot("a", username="Alex", spawn_x=0, spawn_y=64, spawn_z=0)
    bridge = AsyncMock()
    bridge.perform_action = AsyncMock(return_value={"ok": True})
    env._bridges["a"] = bridge
    env._obs_cache = {
        "a": MinecraftObservation(
            agent_id="a",
            tick=0,
            position=Vec3(x=50, y=70, z=60),
        )
    }
    env._teleport_bot = AsyncMock()  # type: ignore[method-assign]
    await env._recover_bot_after_respawn("a")
    env._teleport_bot.assert_awaited()
    args = env._teleport_bot.await_args
    assert args.args[0] == "Alex"
    assert args.args[2:] == (50, 70, 60)
    bridge.perform_action.assert_awaited()


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
