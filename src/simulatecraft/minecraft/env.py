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
import logging
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

log = logging.getLogger(__name__)


class AgentBotConfig:
    """Per-agent bot connection settings."""

    def __init__(
        self,
        username: str,
        password: str = "",
        ipc_port: int = 25570,
        auth: str = "offline",
        goal: str = "",
        spawn_x: float | None = None,
        spawn_y: float | None = None,
        spawn_z: float | None = None,
        gamemode: str | None = None,
        op: bool = False,
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
        self.gamemode = gamemode
        self.op = op
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
        self._map_pan_limit: int = 512

    # ------------------------------------------------------------------
    # Agent / bot registration
    # ------------------------------------------------------------------

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
        gamemode: str | None = None,
        op: bool = False,
        persona: str = "",
    ) -> None:
        """Register an agent and configure its bot.

        Call before ``connect()``, or use :meth:`spawn_bot` to add one at runtime.
        ``ipc_port`` defaults to the next free port starting at 25570.
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
            gamemode=gamemode,
            op=op,
            persona=persona,
        )
        self._chat_logs[agent_id] = []
        self._last_rewards[agent_id] = 0.0
        self.register_agent(agent_id)

    def _next_ipc_port(self) -> int:
        used = {cfg.ipc_port for cfg in self._bot_configs.values()}
        port = 25570
        while port in used:
            port += 1
        return port

    # ------------------------------------------------------------------
    # Lifecycle (async context manager)
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Spawn all bots and wait for them to join the server."""
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
        gamemode: str | None = None,
        op: bool = False,
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
            gamemode=gamemode,
            op=op,
            persona=persona,
        )
        try:
            await self._connect_one(agent_id)
            await self._fetch_all_states()
        except Exception:
            await self.despawn_bot(agent_id)
            raise

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
        """OP / teleport / gamemode via RCON (preferred) then bot-side fallback."""
        commands: list[str] = []
        if cfg.op:
            commands.append(f"op {cfg.username}")
        if cfg.spawn_x is not None and cfg.spawn_y is not None and cfg.spawn_z is not None:
            commands.append(
                f"tp {cfg.username} {cfg.spawn_x:.2f} {cfg.spawn_y:.2f} {cfg.spawn_z:.2f}"
            )
        if cfg.gamemode:
            mode = cfg.gamemode.strip().lower()
            if mode in {"survival", "creative", "adventure", "spectator"}:
                commands.append(f"gamemode {mode} {cfg.username}")

        if commands:
            try:
                from .rcon import run_commands

                run_commands(commands)
            except Exception as exc:
                log.warning(
                    "RCON presence setup for '%s' failed (%s); trying bot chat fallback",
                    agent_id,
                    exc,
                )

        try:
            await bridge.configure_presence(
                x=cfg.spawn_x,
                y=cfg.spawn_y,
                z=cfg.spawn_z,
                gamemode=cfg.gamemode,
            )
        except Exception as exc:
            log.warning("Bot presence configure for '%s' failed: %s", agent_id, exc)

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
        await self._fetch_all_states()
        await self._refresh_map()

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
            result = await bridge.perform_action(action.model_dump())
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
        return _parse_state(
            raw,
            agent_id,
            self._tick_count,
            self._chat_logs.get(agent_id, []),
            cfg.goal,
        )

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
        origin = (cx - self._map_size // 2, cz - self._map_size // 2)
        # Skip rescan if the camera hasn't moved much and we already have a map.
        if (
            self._map_cache is not None
            and self._map_origin is not None
            and abs(origin[0] - self._map_origin[0]) < 8
            and abs(origin[1] - self._map_origin[1]) < 8
            and self._tick_count % 3 != 0
        ):
            return
        try:
            await self.fetch_map(origin[0], origin[1], self._map_size)
        except Exception as exc:
            log.warning("map scan failed: %s", exc)

    async def fetch_map(
        self, origin_x: int, origin_z: int, size: int | None = None
    ) -> dict[str, Any]:
        """Scan a top-down map tile for the viewer (also used by WS pan requests)."""
        if not self._bridges:
            return {}
        tile = max(16, min(int(size or self._map_size), 128))
        ox = int(origin_x)
        oz = int(origin_z)
        if self._home_xz is not None:
            hx, hz = self._home_xz
            lim = self._map_pan_limit
            ox = max(hx - lim, min(hx + lim - tile, ox))
            oz = max(hz - lim, min(hz + lim - tile, oz))
        bridge = next(iter(self._bridges.values()))
        result = await bridge.get_map(ox, oz, tile)
        self._map_cache = result
        self._map_origin = (ox, oz)
        return result

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
                    "gamemode": cfg.gamemode if cfg else obs.stats.game_mode,
                    "op": bool(cfg.op) if cfg else False,
                }
            else:
                agents[aid] = {
                    "position": [0.0, 0.0],
                    "name": cfg.username if cfg else aid,
                    "goal": cfg.goal if cfg else "",
                    "persona": cfg.persona if cfg else "",
                    "gamemode": cfg.gamemode if cfg else None,
                    "op": bool(cfg.op) if cfg else False,
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
