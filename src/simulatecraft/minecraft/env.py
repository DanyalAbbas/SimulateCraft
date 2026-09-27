"""MinecraftEnvironment — bridges SimulateCraft's Environment interface to Mineflayer.

One ``MinecraftEnvironment`` manages one or more bots (one per registered agent).
Each agent gets its own ``MinecraftBridge`` connection to its own bot process,
so agents can be physically separate bots in the same Minecraft server.

Usage
-----
    env = MinecraftEnvironment(
        server_host="localhost",
        server_port=25565,
    )
    async with env:
        env.register_agent("alex", username="Alex")
        env.register_agent("bob",  username="Bob")
        runner = Runner(environment=env, config=RunnerConfig(tick_rate=1.0))
        runner.add_agent(Agent(id="alex", brain=LLMBrain(...)))
        runner.add_agent(Agent(id="bob",  brain=LLMBrain(...)))
        await runner.start()
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import math
import secrets
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ..core.environment import Environment, Snapshot
from ..core.schemas import Action, StepResult
from .actions import Chat, NavigateTo
from .connection import MinecraftBridge
from .observations import (
    BotStats,
    ChatMessage,
    InventoryItem,
    MinecraftObservation,
    NearbyBlock,
    NearbyEntity,
    Vec3,
)
from .world_settings import (
    WorldSettings,
    apply_rules_via_rcon,
    load_settings,
    ticks_to_add_per_second,
)

log = logging.getLogger(__name__)

# Bot IPC (Python↔Node) — keep clear of Minecraft game (25565) and RCON (25575).
_IPC_PORT_BASE = 35670
_RESERVED_IPC_PORTS = frozenset({25565, 25575})


def _ipc_port_available(port: int) -> bool:
    """True if nothing is listening / bound on 127.0.0.1:port."""
    if port in _RESERVED_IPC_PORTS:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


class AgentBotConfig:
    """Per-agent bot connection settings."""

    def __init__(
        self,
        username: str,
        password: str = "",
        ipc_port: int = _IPC_PORT_BASE,
        auth: str = "offline",
        goal: str = "",
        spawn_x: float | None = None,
        spawn_y: float | None = None,
        spawn_z: float | None = None,
        persona: str = "",
    ) -> None:
        self.username = username
        self.password = password
        self.ipc_port = ipc_port
        self.auth = auth
        self.goal = goal
        self.spawn_x = spawn_x
        self.spawn_y = spawn_y
        self.spawn_z = spawn_z
        self.persona = persona


class MinecraftEnvironment(Environment):
    """Multi-agent Minecraft environment backed by Mineflayer bots.

    Each registered agent maps to one bot subprocess. The environment
    queries each bot's state for ``observe()`` and dispatches actions
    back through the bridge in ``step()``.
    """

    def __init__(
        self,
        *,
        server_host: str = "localhost",
        server_port: int = 25565,
        version: str | None = None,
        bot_script: str | Path | None = None,
        node_executable: str = "node",
        block_scan_radius: int = 6,
        entity_scan_radius: int = 16,
        chat_log_size: int = 20,
        connect_timeout: float = 30.0,
        request_timeout: float = 45.0,
        map_pan_limit: int = 512,
    ) -> None:
        super().__init__()
        self.server_host = server_host
        self.server_port = server_port
        self.version = version
        self.bot_script = bot_script
        self.node_executable = node_executable
        self.block_scan_radius = block_scan_radius
        self.entity_scan_radius = entity_scan_radius
        self.chat_log_size = chat_log_size
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout

        # agent_id → bridge
        self._bridges: dict[str, MinecraftBridge] = {}
        # agent_id → config
        self._bot_configs: dict[str, AgentBotConfig] = {}
        # per-agent rolling chat log
        self._chat_logs: dict[str, list[ChatMessage]] = {}
        # per-agent last reward (set by step() for observe() to return)
        self._last_rewards: dict[str, float] = {}
        self._map_cache: dict[str, Any] | None = None
        self._map_size: int = 128
        self._map_origin: tuple[int, int] | None = None
        self._home_xz: tuple[int, int] | None = None
        # Viewer pan/scan radius in blocks around home (half-side of square).
        self._map_pan_limit: int = max(128, min(int(map_pan_limit), 8192))
        self._world_settings: WorldSettings = load_settings()
        self._day_accum_ticks: float = 0.0
        self._last_day_advance: float | None = None
        self._map_preload_lock = asyncio.Lock()
        self._scout_ports: set[int] = set()

    @property
    def map_pan_limit(self) -> int:
        return self._map_pan_limit

    def reload_world_settings(self) -> WorldSettings:
        self._world_settings = load_settings()
        return self._world_settings

    @property
    def world_settings(self) -> WorldSettings:
        return self._world_settings

    def apply_world_rules(self) -> list[str]:
        """Push gamerules / time to the live Minecraft server."""
        self.reload_world_settings()
        try:
            return apply_rules_via_rcon(self._world_settings.rules)
        except Exception as exc:
            log.warning("Applying world rules failed: %s", exc)
            return []

    def add_bot(
        self,
        agent_id: str,
        *,
        username: str | None = None,
        password: str = "",
        ipc_port: int | None = None,
        auth: str = "offline",
        goal: str = "",
        spawn_x: float | None = None,
        spawn_y: float | None = None,
        spawn_z: float | None = None,
        persona: str = "",
    ) -> None:
        """Register an agent and configure its bot.

        Call before ``connect()``, or use :meth:`spawn_bot` to add one at runtime.
        ``ipc_port`` defaults to the next free port starting at 35670
        (avoids Minecraft 25565 / RCON 25575).
        """
        if agent_id in self._bot_configs:
            raise ValueError(f"agent {agent_id!r} already registered")
        if ipc_port is None:
            ipc_port = self._next_ipc_port()
        self._bot_configs[agent_id] = AgentBotConfig(
            username=username or agent_id,
            password=password,
            ipc_port=ipc_port,
            auth=auth,
            goal=goal,
            spawn_x=spawn_x,
            spawn_y=spawn_y,
            spawn_z=spawn_z,
            persona=persona,
        )
        self._chat_logs[agent_id] = []
        self._last_rewards[agent_id] = 0.0
        self.register_agent(agent_id)

    def _next_ipc_port(self) -> int:
        used = {cfg.ipc_port for cfg in self._bot_configs.values()} | self._scout_ports
        port = _IPC_PORT_BASE
        while port in used or not _ipc_port_available(port):
            port += 1
            if port > _IPC_PORT_BASE + 10_000:
                raise RuntimeError("No free bot IPC port found")
        return port

    # ------------------------------------------------------------------
    # Lifecycle (async context manager)
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Spawn all bots and wait for them to join the server."""
        self.apply_world_rules()
        tasks = [self._connect_one(aid) for aid in self._bot_configs]
        await asyncio.gather(*tasks)
        # Warm observation cache so the viewer and first decide() see real state.
        await self._fetch_all_states()
        await self._refresh_map()

    async def _connect_one(self, agent_id: str) -> None:
        cfg = self._bot_configs[agent_id]
        bridge = MinecraftBridge(
            host=self.server_host,
            minecraft_port=self.server_port,
            username=cfg.username,
            password=cfg.password,
            version=self.version,
            ipc_port=cfg.ipc_port,
            bot_script=self.bot_script,
            node_executable=self.node_executable,
            auth=cfg.auth,
            connect_timeout=self.connect_timeout,
            request_timeout=self.request_timeout,
        )

        # Subscribe to chat events and append to rolling log
        def _on_chat(data: dict[str, Any]) -> None:
            msg = ChatMessage(
                sender=data.get("sender", ""),
                text=data.get("text", ""),
                tick=self._tick_count,
            )
            log_list = self._chat_logs.setdefault(agent_id, [])
            log_list.append(msg)
            if len(log_list) > self.chat_log_size:
                log_list.pop(0)

        bridge.on_event("chat", _on_chat)

        def _on_death(data: dict[str, Any]) -> None:
            log.info("Bot '%s' died at %s", agent_id, data.get("position"))

        def _on_respawn(data: dict[str, Any]) -> None:
            # New joins / chunk unload can kill bots; snap them back to last
            # known position instead of leaving them at their spawn pin.
            asyncio.create_task(self._recover_bot_after_respawn(agent_id))

        bridge.on_event("bot.death", _on_death)
        bridge.on_event("bot.respawn", _on_respawn)
        await bridge.connect()
        self._bridges[agent_id] = bridge
        await self._apply_presence(agent_id, bridge, cfg)
        log.info("Bot for agent '%s' (%s) connected.", agent_id, cfg.username)

    async def spawn_bot(
        self,
        agent_id: str,
        *,
        username: str | None = None,
        password: str = "",
        auth: str = "offline",
        goal: str = "",
        spawn_x: float | None = None,
        spawn_y: float | None = None,
        spawn_z: float | None = None,
        persona: str = "",
    ) -> None:
        """Register and connect a bot while the environment is already running."""
        self.add_bot(
            agent_id,
            username=username,
            password=password,
            auth=auth,
            goal=goal,
            spawn_x=spawn_x,
            spawn_y=spawn_y,
            spawn_z=spawn_z,
            persona=persona,
        )
        try:
            # Soften join lag so existing agents don't fall through unloaded chunks.
            await self._protect_agents_for_join()
            await self._connect_one(agent_id)
            # Only refresh the new bot — fetching everyone spikes the server and
            # is a common trigger for mass deaths when many agents are online.
            if hasattr(self, "_obs_cache"):
                try:
                    self._obs_cache[agent_id] = await self._fetch_state(agent_id)
                except Exception as exc:
                    log.warning("State fetch for new agent '%s' failed: %s", agent_id, exc)
            else:
                await self._fetch_all_states()
        except Exception:
            await self.despawn_bot(agent_id)
            raise

    async def _protect_agents_for_join(self) -> None:
        """Brief resistance / no-fall so a new join doesn't kill nearby bots."""
        try:
            from .rcon import run_commands

            run_commands(
                [
                    "effect give @a resistance 20 255 true",
                    "effect give @a slow_falling 20 0 true",
                ]
            )
        except Exception as exc:
            log.debug("Join protection effects failed: %s", exc)

    async def _recover_bot_after_respawn(self, agent_id: str) -> None:
        """Teleport a respawned bot back to its last known position."""
        await asyncio.sleep(0.4)
        bridge = self._bridges.get(agent_id)
        cfg = self._bot_configs.get(agent_id)
        if bridge is None or cfg is None:
            return
        cache = getattr(self, "_obs_cache", {}) or {}
        obs = cache.get(agent_id)
        if obs is not None:
            x, y, z = obs.position.x, obs.position.y, obs.position.z
        elif cfg.spawn_x is not None and cfg.spawn_y is not None and cfg.spawn_z is not None:
            x, y, z = cfg.spawn_x, cfg.spawn_y, cfg.spawn_z
        else:
            return
        log.info(
            "Recovering bot '%s' after respawn → (%.1f, %.1f, %.1f)",
            agent_id,
            x,
            y,
            z,
        )
        with contextlib.suppress(Exception):
            await self._teleport_bot(cfg.username, bridge, x, y, z)
            await bridge.perform_action({"kind": "cancel_path"})

    async def despawn_bot(self, agent_id: str) -> None:
        """Disconnect one bot and forget its registration."""
        bridge = self._bridges.pop(agent_id, None)
        if bridge is not None:
            with contextlib.suppress(Exception):
                await bridge.close()
        self._bot_configs.pop(agent_id, None)
        self._chat_logs.pop(agent_id, None)
        self._last_rewards.pop(agent_id, None)
        cache = getattr(self, "_obs_cache", None)
        if isinstance(cache, dict):
            cache.pop(agent_id, None)
        self.unregister_agent(agent_id)

    async def _apply_presence(
        self, agent_id: str, bridge: MinecraftBridge, cfg: AgentBotConfig
    ) -> None:
        """Teleport only this agent to its pinned spawn (never other players)."""
        if cfg.spawn_x is None or cfg.spawn_y is None or cfg.spawn_z is None:
            return
        x, y, z = float(cfg.spawn_x), float(cfg.spawn_y), float(cfg.spawn_z)
        # Use execute-as so RCON cannot accidentally target the wrong entity.
        # Avoid permanent spawnpoint-at-pin: if they die later from join lag,
        # respawn recovery uses last known position instead.
        commands = [
            f"execute as {cfg.username} run teleport @s {x:.2f} {y:.2f} {z:.2f}",
        ]
        try:
            from .rcon import run_commands

            run_commands(commands)
        except Exception as exc:
            log.warning(
                "RCON teleport for '%s' failed (%s); trying bot chat fallback",
                agent_id,
                exc,
            )
            try:
                await bridge.configure_presence(x=x, y=y, z=z)
            except Exception as bot_exc:
                log.warning("Bot teleport for '%s' failed: %s", agent_id, bot_exc)

    async def close(self) -> None:
        """Disconnect all bots gracefully."""
        await asyncio.gather(*(b.close() for b in self._bridges.values()))
        self._bridges.clear()

    async def __aenter__(self) -> MinecraftEnvironment:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Environment interface
    # ------------------------------------------------------------------

    async def prepare_tick(self) -> None:
        """Refresh bot observations before the runner asks each agent to decide."""
        self._advance_custom_daylight()
        self._enforce_boundaries()
        await self._fetch_all_states()
        await self._refresh_map()

    def _advance_custom_daylight(self) -> None:
        """When day_length_minutes is set, manually advance world time."""
        rules = self._world_settings.rules
        if not rules.allow_night or rules.day_length_minutes is None:
            return
        import time

        now = time.monotonic()
        if self._last_day_advance is None:
            self._last_day_advance = now
            return
        elapsed = now - self._last_day_advance
        self._last_day_advance = now
        self._day_accum_ticks += ticks_to_add_per_second(rules.day_length_minutes) * elapsed
        add = int(self._day_accum_ticks)
        if add < 1:
            return
        self._day_accum_ticks -= add
        try:
            from .rcon import run_commands

            run_commands([f"time add {add}"])
        except Exception as exc:
            log.debug("Custom day advance failed: %s", exc)

    def _enforce_boundaries(self) -> None:
        bounds = self._world_settings.boundaries
        if not bounds.enabled or bounds.enforce == "off":
            return
        cache = getattr(self, "_obs_cache", {}) or {}
        commands: list[str] = []
        for aid, obs in cache.items():
            cfg = self._bot_configs.get(aid)
            if cfg is None or obs is None:
                continue
            x, y, z = obs.position.x, obs.position.y, obs.position.z
            if bounds.contains(x, z):
                continue
            if bounds.enforce == "soft":
                cx, cz = bounds.clamp(x, z)
                commands.append(f"tp {cfg.username} {cx:.2f} {y:.2f} {cz:.2f}")
        if not commands:
            return
        try:
            from .rcon import run_commands

            run_commands(commands)
        except Exception as exc:
            log.debug("Boundary teleport failed: %s", exc)

    def observe(self, agent_id: str) -> MinecraftObservation:
        """Return the latest cached observation for this agent."""
        cached = getattr(self, "_obs_cache", {}).get(agent_id)
        if cached is not None:
            return cached
        cfg = self._bot_configs.get(agent_id, AgentBotConfig(username=agent_id))
        return MinecraftObservation(
            agent_id=agent_id,
            tick=self._tick_count,
            current_goal=cfg.goal,
        )

    async def step(self, agent_id: str, action: Action) -> StepResult:
        """Dispatch the action to the bot and wait for Mineflayer to finish it."""
        bridge = self._bridges.get(agent_id)
        if bridge is None:
            return StepResult(info={"error": f"no bridge for agent {agent_id}"})
        result = await self._execute_action(agent_id, bridge, action)
        reward = self._last_rewards.get(agent_id, 0.0)
        info = {"action": action.kind, **(result if isinstance(result, dict) else {})}
        return StepResult(reward=reward, info=info)

    async def _execute_action(
        self, agent_id: str, bridge: MinecraftBridge, action: Action
    ) -> dict[str, Any]:
        try:
            payload = action.model_dump()
            bounds = self._world_settings.boundaries
            if (
                isinstance(action, NavigateTo)
                and bounds.enabled
                and bounds.enforce in {"soft", "hard"}
            ):
                tx, tz = float(payload.get("x", 0)), float(payload.get("z", 0))
                if not bounds.contains(tx, tz):
                    if bounds.enforce == "hard":
                        return {
                            "ok": False,
                            "error": (
                                f"target ({tx:.0f},{tz:.0f}) is outside the play square "
                                f"(AABB "
                                f"X[{bounds.min_x:.0f}..{bounds.max_x:.0f}] "
                                f"Z[{bounds.min_z:.0f}..{bounds.max_z:.0f}])"
                            ),
                        }
                    cx, cz = bounds.clamp(tx, tz)
                    payload["x"], payload["z"] = cx, cz
            result = await bridge.perform_action(payload)
            reward = 0.0
            if isinstance(action, Chat):
                reward = 0.05
            elif isinstance(action, NavigateTo):
                reward = 0.1 if result.get("ok") else -0.05
            elif result.get("ok"):
                reward = 0.02
            self._last_rewards[agent_id] = reward
            return result
        except Exception as exc:
            log.warning("Action '%s' for agent '%s' failed: %s", action.kind, agent_id, exc)
            self._last_rewards[agent_id] = -0.1
            return {"ok": False, "error": str(exc)}

    def tick(self) -> None:
        """Advance the environment clock. Observations refresh in prepare_tick()."""
        self._tick_count += 1

    async def _fetch_all_states(self) -> None:
        if not hasattr(self, "_obs_cache"):
            self._obs_cache: dict[str, MinecraftObservation] = {}
        if not self._bridges:
            return
        tasks = {aid: self._fetch_state(aid) for aid in self._bridges}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for agent_id, result in zip(tasks.keys(), results, strict=True):
            if isinstance(result, Exception):
                log.warning("State fetch for '%s' failed: %s", agent_id, result)
            else:
                self._obs_cache[agent_id] = result  # type: ignore[assignment]

    async def _fetch_state(self, agent_id: str) -> MinecraftObservation:
        bridge = self._bridges[agent_id]
        cfg = self._bot_configs[agent_id]
        raw = await bridge.get_state()
        obs = _parse_state(
            raw,
            agent_id,
            self._tick_count,
            self._chat_logs.get(agent_id, []),
            cfg.goal,
        )
        notes = [self._world_settings.boundaries.describe()]
        rules = self._world_settings.rules
        if not rules.allow_night:
            notes.append("World rule: night is disabled (always daytime).")
        elif rules.day_length_minutes is not None:
            notes.append(
                f"World rule: custom day length ~{rules.day_length_minutes:g} real minutes."
            )
        elif not rules.daylight_cycle:
            notes.append("World rule: daylight cycle paused.")
        obs.world_notes = " | ".join(notes)
        return obs

    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        if hasattr(self, "_obs_cache"):
            self._obs_cache.clear()
        self._map_cache = None
        self._map_origin = None
        self._home_xz = None
        for k in self._last_rewards:
            self._last_rewards[k] = 0.0

    async def _refresh_map(self) -> None:
        """Top-down surface map around the agents, for the web viewer."""
        if not self._bridges:
            return
        cache = getattr(self, "_obs_cache", {})
        xs = [obs.position.x for obs in cache.values()]
        zs = [obs.position.z for obs in cache.values()]
        if not xs:
            return
        cx = int(sum(xs) / len(xs))
        cz = int(sum(zs) / len(zs))
        if self._home_xz is None:
            self._home_xz = (cx, cz)
        origin = (
            (cx - self._map_size // 2) // self._map_size * self._map_size,
            (cz - self._map_size // 2) // self._map_size * self._map_size,
        )
        # Only rescan when the agent moved into a different tile (avoid shimmer).
        if (
            self._map_cache is not None
            and self._map_origin is not None
            and origin[0] == self._map_origin[0]
            and origin[1] == self._map_origin[1]
        ):
            return
        try:
            await self.fetch_map(origin[0], origin[1], self._map_size)
        except Exception as exc:
            log.warning("map scan failed: %s", exc)

    async def fetch_map(
        self, origin_x: int, origin_z: int, size: int | None = None, *, clamp: bool = True
    ) -> dict[str, Any]:
        """Scan a top-down map tile for the viewer (also used by WS pan requests)."""
        tile = max(16, min(int(size or self._map_size), 128))
        ox = int(origin_x)
        oz = int(origin_z)
        if clamp and self._home_xz is not None:
            hx, hz = self._home_xz
            lim = self._map_pan_limit
            ox = max(hx - lim, min(hx + lim - tile, ox))
            oz = max(hz - lim, min(hz + lim - tile, oz))
        empty = {
            "origin_x": ox,
            "origin_z": oz,
            "width": tile,
            "height": tile,
            "pixels": "",
            "coverage": 0.0,
        }
        if not self._bridges:
            return empty
        bridge = next(iter(self._bridges.values()))
        try:
            result = await bridge.get_map(ox, oz, tile)
        except Exception as exc:
            log.warning("get_map failed at %s,%s: %s", ox, oz, exc)
            return empty
        if not isinstance(result, dict):
            return empty
        result.setdefault("origin_x", ox)
        result.setdefault("origin_z", oz)
        result.setdefault("width", tile)
        result.setdefault("height", tile)
        self._map_cache = result
        self._map_origin = (ox, oz)
        return result

    @staticmethod
    def map_tile_origins(
        min_x: float,
        max_x: float,
        min_z: float,
        max_z: float,
        *,
        tile: int = 128,
    ) -> list[tuple[int, int]]:
        """Grid of tile origins covering an XZ AABB (inclusive)."""
        tile = max(16, int(tile))
        x0 = math.floor(min(min_x, max_x) / tile) * tile
        x1 = math.floor(max(min_x, max_x) / tile) * tile
        z0 = math.floor(min(min_z, max_z) / tile) * tile
        z1 = math.floor(max(min_z, max_z) / tile) * tile
        return [(ox, oz) for ox in range(x0, x1 + 1, tile) for oz in range(z0, z1 + 1, tile)]

    async def preload_map_region(
        self,
        min_x: float,
        max_x: float,
        min_z: float,
        max_z: float,
        *,
        y: float | None = None,
        settle_seconds: float = 2.0,
        max_tiles: int = 512,
        workers: int = 8,
        use_agents: bool = False,
        on_tile: Callable[[dict[str, Any], int, int], Awaitable[None] | None] | None = None,
    ) -> dict[str, Any]:
        """Scan an XZ box with temporary scout bots (parallel), stream via ``on_tile``.

        By default only scout clients are teleported — your simulation agents stay
        put. Pass ``use_agents=True`` to also draft connected agents as workers.
        Caps at ``max_tiles`` (default 512 ≈ 2896×2896 blocks at tile 128).
        """
        if not self._bridges:
            raise RuntimeError("No bots connected — spawn an agent before preloading the map")
        if self._map_preload_lock.locked():
            raise RuntimeError("Map preload already in progress")

        async with self._map_preload_lock:
            return await self._preload_map_region_locked(
                min_x,
                max_x,
                min_z,
                max_z,
                y=y,
                settle_seconds=settle_seconds,
                max_tiles=max_tiles,
                workers=workers,
                use_agents=use_agents,
                on_tile=on_tile,
            )

    async def _preload_map_region_locked(
        self,
        min_x: float,
        max_x: float,
        min_z: float,
        max_z: float,
        *,
        y: float | None,
        settle_seconds: float,
        max_tiles: int,
        workers: int,
        use_agents: bool,
        on_tile: Callable[[dict[str, Any], int, int], Awaitable[None] | None] | None,
    ) -> dict[str, Any]:
        tile = self._map_size
        origins = self.map_tile_origins(min_x, max_x, min_z, max_z, tile=tile)
        if not origins:
            return {"ok": True, "tiles": 0, "scanned": 0, "pan_limit": self._map_pan_limit}
        # Hard ceiling so a mis-click can't scan for hours.
        hard_cap = 1024
        limit = max(1, min(int(max_tiles), hard_cap))
        if len(origins) > limit:
            side = int(math.sqrt(limit)) * tile
            raise ValueError(
                f"Region needs {len(origins)} tiles (max {limit}). "
                f"Draw a smaller square (≤ ~{side}×{side} blocks) or raise max_tiles."
            )

        # Expand pan so the UI can show the preloaded area.
        if self._home_xz is None:
            self._home_xz = (
                int((min(min_x, max_x) + max(min_x, max_x)) / 2),
                int((min(min_z, max_z) + max(min_z, max_z)) / 2),
            )
        hx, hz = self._home_xz
        reach = max(
            abs(min(min_x, max_x) - hx),
            abs(max(min_x, max_x) - hx),
            abs(min(min_z, max_z) - hz),
            abs(max(min_z, max_z) - hz),
            tile,
        )
        self._map_pan_limit = max(self._map_pan_limit, int(math.ceil(reach)) + tile)

        cache = getattr(self, "_obs_cache", {}) or {}
        crew: list[dict[str, Any]] = []
        # Prefer temporary scouts so simulation agents are not yanked around.
        if use_agents:
            for agent_id, bridge in list(self._bridges.items()):
                cfg = self._bot_configs.get(agent_id)
                username = cfg.username if cfg else agent_id
                obs = cache.get(agent_id)
                if obs is not None:
                    ret = (obs.position.x, obs.position.y, obs.position.z)
                else:
                    ret = (float(hx), 80.0, float(hz))
                crew.append(
                    {
                        "username": username,
                        "bridge": bridge,
                        "return": ret,
                        "scout": False,
                    }
                )

        target = max(1, min(int(workers) or 8, 8, len(origins)))
        scouts: list[dict[str, Any]] = []
        need = max(0, target - len(crew))
        if need > 0:
            try:
                scouts = await self._spawn_map_scouts(need)
                crew.extend(scouts)
            except Exception as exc:
                log.warning("Could only spawn partial scout pool (%s); continuing", exc)

        if not crew:
            raise RuntimeError(
                "Could not start map scouts — spawn an agent and check the Minecraft server"
            )

        # Prefer a live agent Y; fall back to a mid-world height for scouts-only.
        agent_y = next(
            (
                float(obs.position.y)
                for obs in cache.values()
                if obs is not None and getattr(obs, "position", None) is not None
            ),
            80.0,
        )
        scan_y = float(y) if y is not None else agent_y
        settle = max(0.6, float(settle_seconds))
        total = len(origins)
        scanned = 0
        progress_lock = asyncio.Lock()
        weak: list[tuple[int, int]] = []
        weak_lock = asyncio.Lock()
        # Round-robin shard so workers stay spatially spread.
        shards: list[list[tuple[int, int]]] = [[] for _ in crew]
        for i, origin in enumerate(origins):
            shards[i % len(crew)].append(origin)

        async def emit(
            tile_data: dict[str, Any], *, cur: int | None = None, tot: int | None = None
        ) -> None:
            nonlocal scanned
            async with progress_lock:
                scanned += 1
                progress_cur = cur if cur is not None else scanned
            progress_tot = tot if tot is not None else total
            if on_tile is not None:
                maybe = on_tile(tile_data, progress_cur, progress_tot)
                if inspect.isawaitable(maybe):
                    await maybe

        async def scan_one(
            member: dict[str, Any],
            ox: int,
            oz: int,
            *,
            settle_s: float,
            retries: int,
        ) -> dict[str, Any]:
            bridge: MinecraftBridge = member["bridge"]
            username: str = member["username"]
            cx = ox + tile / 2.0
            cz = oz + tile / 2.0
            await self._teleport_bot(username, bridge, cx, scan_y, cz)
            tile_data: dict[str, Any] = {
                "origin_x": ox,
                "origin_z": oz,
                "width": tile,
                "height": tile,
                "pixels": "",
                "coverage": 0.0,
            }
            for attempt in range(max(1, retries)):
                await asyncio.sleep(settle_s if attempt == 0 else max(1.0, settle_s))
                tile_data = await self._scan_map_with_bridge(bridge, ox, oz, tile)
                if float(tile_data.get("coverage") or 0.0) >= 0.35:
                    break
            return tile_data

        async def worker(member: dict[str, Any], jobs: list[tuple[int, int]]) -> None:
            for ox, oz in jobs:
                tile_data = await scan_one(member, ox, oz, settle_s=settle, retries=2)
                if float(tile_data.get("coverage") or 0.0) < 0.35:
                    async with weak_lock:
                        weak.append((ox, oz))
                await emit(tile_data)

        try:
            await asyncio.gather(
                *(worker(member, shard) for member, shard in zip(crew, shards, strict=True))
            )

            # Second pass: re-visit parchment / sparse tiles with a longer settle.
            if weak and crew:
                gaps = list(weak)
                weak.clear()
                log.info("Map preload mop-up: retrying %s low-coverage tiles", len(gaps))
                mop_shards: list[list[tuple[int, int]]] = [[] for _ in crew]
                for i, origin in enumerate(gaps):
                    mop_shards[i % len(crew)].append(origin)
                mop_settle = max(settle * 1.75, 2.5)
                mop_total = total + len(gaps)
                mop_done = 0
                mop_lock = asyncio.Lock()

                async def mop_worker(member: dict[str, Any], jobs: list[tuple[int, int]]) -> None:
                    nonlocal mop_done
                    for ox, oz in jobs:
                        tile_data = await scan_one(member, ox, oz, settle_s=mop_settle, retries=3)
                        async with mop_lock:
                            mop_done += 1
                            cur = total + mop_done
                        await emit(tile_data, cur=cur, tot=mop_total)

                await asyncio.gather(
                    *(
                        mop_worker(member, shard)
                        for member, shard in zip(crew, mop_shards, strict=True)
                        if shard
                    )
                )
        finally:
            for member in crew:
                if member["scout"]:
                    continue
                rx, ry, rz = member["return"]
                with contextlib.suppress(Exception):
                    await self._teleport_bot(member["username"], member["bridge"], rx, ry, rz)
            await self._despawn_map_scouts(scouts)

        return {
            "ok": True,
            "tiles": total,
            "scanned": scanned,
            "workers": len(crew),
            "scouts": len(scouts),
            "gaps_retried": max(0, scanned - total),
            "pan_limit": self._map_pan_limit,
            "min_x": min(min_x, max_x),
            "max_x": max(min_x, max_x),
            "min_z": min(min_z, max_z),
            "max_z": max(min_z, max_z),
        }

    async def _scan_map_with_bridge(
        self, bridge: MinecraftBridge, origin_x: int, origin_z: int, size: int
    ) -> dict[str, Any]:
        """Scan one tile via a specific bot (used by parallel preload workers)."""
        empty = {
            "origin_x": origin_x,
            "origin_z": origin_z,
            "width": size,
            "height": size,
            "pixels": "",
            "coverage": 0.0,
        }
        try:
            result = await bridge.get_map(origin_x, origin_z, size)
        except Exception as exc:
            log.warning("get_map failed at %s,%s: %s", origin_x, origin_z, exc)
            return empty
        if not isinstance(result, dict):
            return empty
        result.setdefault("origin_x", origin_x)
        result.setdefault("origin_z", origin_z)
        result.setdefault("width", size)
        result.setdefault("height", size)
        self._map_cache = result
        self._map_origin = (origin_x, origin_z)
        return result

    async def _spawn_map_scouts(self, count: int) -> list[dict[str, Any]]:
        """Spawn temporary Mineflayer clients (not simulation agents) for chunk loading."""
        scouts: list[dict[str, Any]] = []
        for i in range(max(0, count)):
            username = f"MS{i}{secrets.token_hex(2)}"[:16]
            port = self._next_ipc_port()
            self._scout_ports.add(port)
            bridge = MinecraftBridge(
                host=self.server_host,
                minecraft_port=self.server_port,
                username=username,
                password="",
                version=self.version,
                ipc_port=port,
                bot_script=self.bot_script,
                node_executable=self.node_executable,
                auth="offline",
                connect_timeout=self.connect_timeout,
                request_timeout=self.request_timeout,
            )
            try:
                await bridge.connect()
            except Exception:
                self._scout_ports.discard(port)
                with contextlib.suppress(Exception):
                    await bridge.close()
                log.warning(
                    "Map scout %s failed to connect; using %s workers",
                    username,
                    len(scouts),
                )
                break
            scouts.append(
                {
                    "username": username,
                    "bridge": bridge,
                    "return": (0.0, 80.0, 0.0),
                    "scout": True,
                    "port": port,
                }
            )
            log.info("Map scout '%s' connected (ipc %s)", username, port)
        return scouts

    async def _despawn_map_scouts(self, scouts: list[dict[str, Any]]) -> None:
        for scout in scouts:
            bridge = scout.get("bridge")
            if bridge is not None:
                with contextlib.suppress(Exception):
                    await bridge.close()
            port = scout.get("port")
            if port is not None:
                self._scout_ports.discard(int(port))

    async def _teleport_bot(
        self,
        username: str,
        bridge: MinecraftBridge,
        x: float,
        y: float,
        z: float,
    ) -> None:
        try:
            from .rcon import run_commands

            run_commands([f"tp {username} {x:.2f} {y:.2f} {z:.2f}"])
            return
        except Exception as exc:
            log.debug("RCON tp failed (%s); trying bot chat", exc)
        await bridge.configure_presence(x=x, y=y, z=z)

    def snapshot(self) -> Snapshot:
        """Top-down Minecraft map (surface blocks) plus agent markers in world XZ."""
        cache = getattr(self, "_obs_cache", {})
        agents: dict[str, dict[str, Any]] = {}
        for aid in self.agent_ids:
            cfg = self._bot_configs.get(aid)
            obs = cache.get(aid)
            if obs is not None:
                x, y, z = obs.position.x, obs.position.y, obs.position.z
                agents[aid] = {
                    "position": [x, z],
                    "position_3d": [x, y, z],
                    "name": cfg.username if cfg else aid,
                    "health": obs.stats.health,
                    "food": obs.stats.food,
                    "holding": obs.equipped_item,
                    "goal": obs.current_goal,
                    "biome": obs.biome,
                    "yaw": obs.yaw,
                    "persona": cfg.persona if cfg else "",
                }
            else:
                agents[aid] = {
                    "position": [0.0, 0.0],
                    "name": cfg.username if cfg else aid,
                    "goal": cfg.goal if cfg else "",
                    "persona": cfg.persona if cfg else "",
                }

        world_map = self._map_cache or {}
        width = int(world_map.get("width") or self._map_size)
        height = int(world_map.get("height") or self._map_size)
        origin_x = world_map.get("origin_x", 0)
        origin_z = world_map.get("origin_z", 0)
        if self._home_xz is not None:
            home = list(self._home_xz)
        else:
            home = [origin_x + width // 2, origin_z + height // 2]

        return Snapshot(
            tick=self._tick_count,
            agents=agents,
            world={
                "kind": "minecraft",
                "server": self.server_host,
                "view": "top-down-xz",
                "width": width,
                "height": height,
                "origin_xz": [origin_x, origin_z],
                "home_xz": home,
                "pan_limit": self._map_pan_limit,
                "tile_size": self._map_size,
                "map": world_map,
                "boundaries": self._world_settings.boundaries.model_dump(mode="json"),
                "rules": self._world_settings.rules.model_dump(mode="json"),
                "world_info": self._world_settings.world.model_dump(mode="json"),
            },
        )


# ---------------------------------------------------------------------------
# State parsing helper
# ---------------------------------------------------------------------------


def _parse_state(
    raw: dict[str, Any],
    agent_id: str,
    tick: int,
    chat_log: list[ChatMessage],
    goal: str,
) -> MinecraftObservation:
    pos_raw = raw.get("position", {})
    pos = Vec3(x=pos_raw.get("x", 0), y=pos_raw.get("y", 0), z=pos_raw.get("z", 0))

    stats_raw = raw.get("stats", {})
    stats = BotStats(
        health=stats_raw.get("health", 20),
        food=stats_raw.get("food", 20),
        saturation=stats_raw.get("saturation", 5),
        experience_level=stats_raw.get("experience_level", 0),
        game_mode=stats_raw.get("game_mode", "survival"),
        is_raining=stats_raw.get("is_raining", False),
        time_of_day=stats_raw.get("time_of_day", 0),
        biome=raw.get("biome", "unknown"),
    )

    inventory = [
        InventoryItem(name=i["name"], count=i["count"], slot=i.get("slot", -1))
        for i in raw.get("inventory", [])
    ]

    nearby_blocks = [
        NearbyBlock(
            name=b["name"],
            x=b["x"],
            y=b["y"],
            z=b["z"],
            hardness=b.get("hardness"),
        )
        for b in raw.get("nearby_blocks", [])
    ]

    nearby_entities = [
        NearbyEntity(
            name=e["name"],
            entity_type=e.get("entity_type", "mob"),
            x=e["x"],
            y=e["y"],
            z=e["z"],
            distance=e["distance"],
            health=e.get("health"),
        )
        for e in raw.get("nearby_entities", [])
    ]

    from .observations import RecipeInfo

    craftable = [
        RecipeInfo(
            item_name=r["item_name"],
            count=r.get("count", 1),
            needs_table=r.get("needs_table", False),
        )
        for r in raw.get("craftable", [])
    ]

    return MinecraftObservation(
        agent_id=agent_id,
        tick=tick,
        position=pos,
        yaw=raw.get("yaw", 0.0),
        pitch=raw.get("pitch", 0.0),
        on_ground=raw.get("on_ground", True),
        biome=raw.get("biome", "unknown"),
        stats=stats,
        inventory=inventory,
        equipped_item=raw.get("equipped_item"),
        nearby_blocks=nearby_blocks,
        nearby_entities=nearby_entities,
        craftable=craftable,
        chat_log=chat_log[-20:],
        current_goal=goal,
        data=raw,
    )
