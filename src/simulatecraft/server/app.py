"""FastAPI app: REST control + live websocket broadcast + inbound human input."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..core.events import (
    Event,
    EventBus,
    HumanChat,
    SimulationPaused,
    SimulationResumed,
    TickCompleted,
)
from ..core.runner import Runner
from .agents import (
    AgentCreateRequest,
    AgentCreateResponse,
    BulkAgentCreateResponse,
    create_agent,
    create_agents_from_roster,
    delete_agent,
)
from .persona import GeneratePromptRequest, GeneratePromptResponse, generate_persona
from .roles import WatcherRoleRequest, WatcherRoleResponse, assign_watcher_role
from .workshop_settings import (
    AgentWorkshopSettings,
    apply_roster_preset,
    expected_headers_hint,
    load_workshop_settings,
    save_workshop_settings,
)
from .workshop_settings import settings_public_dict as workshop_public_dict

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class RunnerStatus(BaseModel):
    running: bool
    paused: bool
    tick: int
    tick_rate: float | None = None
    max_ticks: int = 0


class ControlBody(BaseModel):
    """Optional extras for control commands (step count, rates, etc.)."""

    n: int | None = None
    value: float | None = None


class StateResponse(BaseModel):
    snapshot: dict[str, Any]
    status: RunnerStatus


class WebsocketBroadcaster:
    """Fans every outbound EventBus event out to connected websockets."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.clients: set[WebSocket] = set()
        bus.subscribe(self._on_event)

    async def _on_event(self, event: Event) -> None:
        if not self.clients:
            return
        payload = json.dumps({"type": "event", "event": json.loads(event.model_dump_json())})
        dead: list[WebSocket] = []
        for ws in list(self.clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


def create_app(runner: Runner, *, state_push_interval: float = 0.5) -> FastAPI:
    app = FastAPI(title="SimulateCraft", version="0.1.0")
    broadcaster = WebsocketBroadcaster(runner.bus)
    with contextlib.suppress(RuntimeError):
        runner.bus.bind_loop(asyncio.get_running_loop())
    app.state.broadcaster = broadcaster
    app.state.runner = runner
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def status() -> RunnerStatus:
        return RunnerStatus(
            running=runner.is_running,
            paused=runner.is_paused,
            tick=runner.environment.tick_count,
            tick_rate=runner.config.tick_rate,
            max_ticks=runner.config.max_ticks,
        )

    def full_state() -> StateResponse:
        return StateResponse(
            snapshot=json.loads(runner.environment.snapshot().model_dump_json()),
            status=status(),
        )

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/state")
    async def get_state() -> StateResponse:
        return full_state()

    @app.post("/api/control/{command}")
    async def control(
        command: Literal[
            "pause",
            "resume",
            "step",
            "stop",
            "reset",
            "faster",
            "slower",
            "set_tick_rate",
            "set_max_ticks",
            "extend_ticks",
        ],
        body: ControlBody | None = None,
    ) -> dict[str, Any]:
        extras = body or ControlBody()
        result = await _apply_control(
            runner,
            command,
            n=extras.n,
            value=extras.value,
        )
        return {"ok": command, **result}

    @app.post("/api/chat")
    async def chat(text: str, target: str | None = None, sender: str = "human") -> dict[str, str]:
        runner.bus.publish_inbound(HumanChat(sender=sender, target_agent_id=target, text=text))
        return {"ok": "sent"}

    @app.get("/api/agents")
    async def list_agents() -> dict[str, Any]:
        snap = full_state().snapshot
        return {"agents": snap.get("agents") or {}}

    @app.post("/api/agents")
    async def post_agent(body: AgentCreateRequest) -> AgentCreateResponse:
        try:
            return await create_agent(runner, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            log.exception("agent create failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/agents/generate-prompt")
    async def post_generate_prompt(body: GeneratePromptRequest) -> GeneratePromptResponse:
        """Expand rough notes into a structured system prompt / persona.

        Uses the configurable generator instructions from
        ``GET/PUT /api/agents/workshop`` unless ``instructions`` is provided.
        """
        try:
            return await generate_persona(
                text=body.text,
                name=body.name,
                use_llm=body.use_llm,
                model=body.model,
                instructions=body.instructions,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            log.exception("generate-prompt failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/agents/workshop")
    async def get_agent_workshop() -> dict[str, Any]:
        settings = load_workshop_settings()
        return {
            **workshop_public_dict(settings),
            "expected_headers": expected_headers_hint(settings),
        }

    @app.put("/api/agents/workshop")
    async def put_agent_workshop(body: AgentWorkshopSettings) -> dict[str, Any]:
        settings = save_workshop_settings(body)
        return {
            **workshop_public_dict(settings),
            "expected_headers": expected_headers_hint(settings),
        }

    @app.post("/api/agents/workshop/preset/{name}")
    async def post_agent_workshop_preset(name: str) -> dict[str, Any]:
        """Load a built-in roster column preset (``university`` or ``minimal``)."""
        if name.strip().lower() not in {"university", "minimal"}:
            raise HTTPException(status_code=400, detail="Unknown preset (use university|minimal)")
        settings = apply_roster_preset(name)
        return {
            **workshop_public_dict(settings),
            "expected_headers": expected_headers_hint(settings),
        }

    @app.post("/api/agents/bulk")
    async def post_agents_bulk(
        file: Annotated[UploadFile, File()],
        spawn_x: float | None = None,
        spawn_y: float | None = None,
        spawn_z: float | None = None,
    ) -> BulkAgentCreateResponse:
        """Spawn many agents from a CSV or Excel roster.

        Column mapping is configurable via ``/api/agents/workshop`` (defaults
        to a university-style Name / Role / Department / Big Five roster).
        """
        name = file.filename or "agents.csv"
        content = await file.read()
        if len(content) > 8 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Roster file too large (max 8MB)")
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")
        try:
            return await create_agents_from_roster(
                runner,
                filename=name,
                data=content,
                spawn_x=spawn_x,
                spawn_y=spawn_y,
                spawn_z=spawn_z,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            log.exception("bulk agent create failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.delete("/api/agents/{agent_id}")
    async def remove_agent(agent_id: str) -> dict[str, Any]:
        try:
            return await delete_agent(runner, agent_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            log.exception("agent delete failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/watchers/role")
    async def post_watcher_role(body: WatcherRoleRequest) -> WatcherRoleResponse:
        """Assign OP / spectator / gamemode to a human Minecraft player (not an agent)."""
        try:
            return assign_watcher_role(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            log.exception("watcher role assign failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/world/settings")
    async def get_world_settings() -> dict[str, Any]:
        from simulatecraft.minecraft.world_settings import load_settings, settings_public_dict

        return settings_public_dict(load_settings())

    @app.put("/api/world/settings")
    async def put_world_settings(body: dict[str, Any]) -> dict[str, Any]:
        from simulatecraft.minecraft.world_settings import (
            WorldSettings,
            apply_boundaries_via_rcon,
            apply_rules_via_rcon,
            load_settings,
            save_settings,
            settings_public_dict,
        )

        try:
            settings = WorldSettings.model_validate(body)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        previous = load_settings()
        applied: list[str] = []
        barrier_cmds = 0
        apply_error: str | None = None

        try:
            applied = apply_rules_via_rcon(settings.rules)
        except Exception as exc:
            apply_error = str(exc)
            log.warning("world rules apply failed: %s", exc)

        try:
            results, updated_bounds = apply_boundaries_via_rcon(
                settings.boundaries,
                previous=previous.boundaries,
            )
            barrier_cmds = len(results)
            settings.boundaries = updated_bounds
        except Exception as exc:
            msg = f"barriers: {exc}"
            apply_error = f"{apply_error}; {msg}" if apply_error else msg
            log.warning("world barriers apply failed: %s", exc)

        save_settings(settings)
        env = runner.environment
        if hasattr(env, "reload_world_settings"):
            env.reload_world_settings()

        return {
            "ok": True,
            "settings": settings_public_dict(settings),
            "applied_commands": applied,
            "barrier_commands": barrier_cmds,
            "apply_error": apply_error,
        }

    @app.post("/api/map/preload")
    async def post_map_preload(body: dict[str, Any]) -> dict[str, Any]:
        """Teleport a bot across an XZ box and scan map tiles (no live stream)."""
        try:
            return await _handle_map_preload(runner, body, ws=None)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            log.exception("map preload failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/world/import")
    async def post_world_import(
        file: Annotated[UploadFile, File()],
    ) -> dict[str, Any]:
        """Upload a .zip of a Minecraft Java world (must contain level.dat).

        After import, restart the Minecraft container so ``/data/world`` is loaded.
        """
        from simulatecraft.minecraft.world_settings import (
            data_dir,
            import_world_zip,
            settings_public_dict,
        )

        name = file.filename or "world.zip"
        if not name.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Upload a .zip of a Java world folder")
        uploads = data_dir() / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        dest = uploads / name
        content = await file.read()
        if len(content) > 512 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="World zip too large (max 512MB)")
        dest.write_bytes(content)
        try:
            settings = import_world_zip(dest, label=Path(name).stem)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            log.exception("world import failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        env = runner.environment
        if hasattr(env, "reload_world_settings"):
            env.reload_world_settings()
        return {
            "ok": True,
            "settings": settings_public_dict(settings),
            "restart_required": True,
            "hint": (
                "Run: docker compose down && docker compose up -d (or POST /api/world/restart)"
            ),
        }

    @app.post("/api/world/restart")
    async def post_world_restart() -> dict[str, Any]:
        """Restart the bundled Docker Minecraft server to pick up an imported world."""
        import shutil
        import subprocess

        docker = shutil.which("docker")
        if not docker:
            raise HTTPException(status_code=500, detail="docker not found on PATH")
        from simulatecraft.minecraft.world_settings import repo_root

        compose = repo_root() / "docker-compose.yml"
        if not compose.exists():
            raise HTTPException(
                status_code=500,
                detail=f"docker-compose.yml not found at {compose}",
            )
        try:
            subprocess.run(
                [docker, "compose", "-f", str(compose), "down"],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [docker, "compose", "-f", str(compose), "up", "-d"],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise HTTPException(
                status_code=500,
                detail=exc.stderr or exc.stdout or str(exc),
            ) from exc
        return {
            "ok": True,
            "message": (
                "Minecraft container restarted. Wait until the world finishes "
                "loading, then refresh agents."
            ),
        }

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        broadcaster.clients.add(ws)
        try:
            await ws.send_text(
                json.dumps({"type": "state", "state": json.loads(full_state().model_dump_json())})
            )
            push_states = asyncio.create_task(
                _push_states(ws, broadcaster, full_state, state_push_interval)
            )
            while True:
                raw = await ws.receive_text()
                try:
                    message = json.loads(raw)
                    await _handle_client_message(runner, message, ws, broadcaster=broadcaster)
                except (json.JSONDecodeError, KeyError, ValueError) as exc:
                    log.warning("bad inbound ws message: %s (%s)", raw[:120], exc)
        except WebSocketDisconnect:
            pass
        finally:
            push_states.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await push_states
            broadcaster.clients.discard(ws)

    return app


async def _push_states(
    ws: WebSocket, broadcaster: WebsocketBroadcaster, provider: Any, interval: float
) -> None:
    try:
        while True:
            payload = json.dumps(
                {"type": "state", "state": json.loads(provider().model_dump_json())}
            )
            await ws.send_text(payload)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        raise
    except Exception:
        broadcaster.clients.discard(ws)


async def _apply_control(
    runner: Runner,
    command: str,
    *,
    n: int | None = None,
    value: float | None = None,
) -> dict[str, Any]:
    """Apply a control command immediately (works even when not running)."""
    if command == "pause":
        runner.request_pause()
        await runner.bus.publish(SimulationPaused())
        return {"paused": True}
    if command == "resume":
        runner.request_resume()
        await runner.bus.publish(SimulationResumed())
        return {"paused": False}
    if command == "step":
        count = max(1, min(100, int(n or 1)))
        if runner.is_running and runner.is_paused:
            runner.request_step(count)
        else:
            for _ in range(count):
                await runner.step_once()
        return {"steps": count, "tick": runner.environment.tick_count}
    if command == "stop":
        runner.request_stop("server_control")
        return {"running": False}
    if command == "reset":
        runner.environment.reset()
        await runner.bus.publish(TickCompleted(), tick=runner.environment.tick_count)
        return {"tick": runner.environment.tick_count}
    if command == "faster":
        rate = runner.adjust_tick_rate(2.0)
        return {"tick_rate": rate}
    if command == "slower":
        rate = runner.adjust_tick_rate(0.5)
        return {"tick_rate": rate}
    if command == "set_tick_rate":
        if value is None:
            raise ValueError("set_tick_rate requires value")
        # value <= 0 means unlimited
        rate = runner.set_tick_rate(None if float(value) <= 0 else float(value))
        return {"tick_rate": rate}
    if command == "set_max_ticks":
        if value is None:
            raise ValueError("set_max_ticks requires value")
        max_ticks = runner.set_max_ticks(int(value))
        return {"max_ticks": max_ticks}
    if command == "extend_ticks":
        amount = max(1, int(n or value or 1000))
        max_ticks = runner.extend_max_ticks(amount)
        return {"max_ticks": max_ticks, "extended_by": amount}
    raise ValueError(f"unknown control command {command!r}")


async def _handle_client_message(
    runner: Runner,
    message: dict[str, Any],
    ws: WebSocket | None = None,
    *,
    broadcaster: WebsocketBroadcaster | None = None,
) -> None:
    msg_type = message.get("type")
    if msg_type == "chat":
        runner.bus.publish_inbound(
            HumanChat(
                sender=str(message.get("sender") or "human"),
                target_agent_id=message.get("target"),
                text=str(message["text"]),
            )
        )
    elif msg_type == "control":
        await _apply_control(
            runner,
            str(message["command"]),
            n=message.get("n"),
            value=message.get("value"),
        )
    elif msg_type == "map":
        env = runner.environment
        fetch = getattr(env, "fetch_map", None)
        if not callable(fetch):
            raise ValueError("environment does not support map tiles")
        origin_x = int(message["origin_x"])
        origin_z = int(message["origin_z"])
        size = int(message.get("size") or 128)
        try:
            map_data = await fetch(origin_x, origin_z, size)
        except Exception as exc:
            log.warning("map tile fetch failed: %s", exc)
            map_data = {
                "origin_x": origin_x,
                "origin_z": origin_z,
                "width": size,
                "height": size,
                "pixels": "",
            }
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.send_text(json.dumps({"type": "map", "map": map_data or {}}))
    elif msg_type == "map_preload":
        # Run in the background so the WS receive loop stays alive (preload can
        # take minutes). Tiles are broadcast to every connected viewer.
        asyncio.create_task(
            _handle_map_preload(runner, message, ws, broadcaster=broadcaster),
            name="map-preload",
        )
    elif msg_type == "agent_create":
        req = AgentCreateRequest.model_validate(message.get("agent") or message)
        created = await create_agent(runner, req)
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.send_text(json.dumps({"type": "agent_created", **created.model_dump()}))
    elif msg_type == "agent_delete":
        agent_id = str(message["agent_id"])
        deleted = await delete_agent(runner, agent_id)
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.send_text(json.dumps({"type": "agent_deleted", **deleted}))
    elif msg_type == "watcher_role":
        role_req = WatcherRoleRequest.model_validate(message.get("watcher") or message)
        assigned = assign_watcher_role(role_req)
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.send_text(json.dumps({"type": "watcher_role", **assigned.model_dump()}))
    else:
        raise ValueError(f"unknown inbound type {msg_type!r}")


async def _ws_broadcast(
    payload: dict[str, Any],
    *,
    ws: WebSocket | None = None,
    broadcaster: WebsocketBroadcaster | None = None,
) -> None:
    """Send JSON to all live viewers (or a single socket). Never raises on closed sockets."""
    text = json.dumps(payload)
    targets: list[WebSocket] = []
    if broadcaster is not None:
        targets.extend(list(broadcaster.clients))
    elif ws is not None:
        targets.append(ws)
    dead: list[WebSocket] = []
    for client in targets:
        try:
            await client.send_text(text)
        except Exception:
            dead.append(client)
    if broadcaster is not None:
        for d in dead:
            broadcaster.clients.discard(d)


async def _handle_map_preload(
    runner: Runner,
    message: dict[str, Any],
    ws: WebSocket | None = None,
    *,
    broadcaster: WebsocketBroadcaster | None = None,
) -> dict[str, Any]:
    """Teleport a bot across a region and stream map tiles back to viewers."""
    env = runner.environment
    preload = getattr(env, "preload_map_region", None)
    if not callable(preload):
        err = "environment does not support map preload"
        await _ws_broadcast(
            {"type": "map_preload_error", "error": err},
            ws=ws,
            broadcaster=broadcaster,
        )
        return {"ok": False, "error": err}

    try:
        min_x = float(message["min_x"])
        max_x = float(message["max_x"])
        min_z = float(message["min_z"])
        max_z = float(message["max_z"])
    except (KeyError, TypeError, ValueError):
        err = "map_preload requires min_x, max_x, min_z, max_z"
        await _ws_broadcast(
            {"type": "map_preload_error", "error": err},
            ws=ws,
            broadcaster=broadcaster,
        )
        return {"ok": False, "error": err}

    y = message.get("y")
    settle = message.get("settle_seconds")
    max_tiles = message.get("max_tiles")
    workers = message.get("workers")

    async def on_tile(tile_data: dict[str, Any], current: int, total: int) -> None:
        await _ws_broadcast({"type": "map", "map": tile_data or {}}, ws=ws, broadcaster=broadcaster)
        await _ws_broadcast(
            {"type": "map_preload_progress", "current": current, "total": total},
            ws=ws,
            broadcaster=broadcaster,
        )

    kwargs: dict[str, Any] = {"on_tile": on_tile}
    if y is not None:
        kwargs["y"] = float(y)
    if settle is not None:
        kwargs["settle_seconds"] = float(settle)
    if max_tiles is not None:
        kwargs["max_tiles"] = int(max_tiles)
    if workers is not None:
        kwargs["workers"] = int(workers)

    try:
        result = await preload(min_x, max_x, min_z, max_z, **kwargs)
    except (ValueError, RuntimeError) as exc:
        await _ws_broadcast(
            {"type": "map_preload_error", "error": str(exc)},
            ws=ws,
            broadcaster=broadcaster,
        )
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        log.exception("map preload failed")
        await _ws_broadcast(
            {"type": "map_preload_error", "error": str(exc)},
            ws=ws,
            broadcaster=broadcaster,
        )
        return {"ok": False, "error": str(exc)}

    await _ws_broadcast(
        {"type": "map_preload_done", **(result or {})},
        ws=ws,
        broadcaster=broadcaster,
    )
    return result or {}


class SimulationServer:
    """Owns the uvicorn server + a background simulation task.

    Usage::

        runner = Runner(environment=env, agents=[...])
        async with SimulationServer(runner) as server:
            await server.serve()
    """

    def __init__(self, runner: Runner, host: str = "127.0.0.1", port: int = 8000) -> None:
        self.runner = runner
        self.host = host
        self.port = port
        self.app = create_app(runner)
        self._server: Any = None
        self._sim_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> SimulationServer:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop()

    def start_simulation(self) -> None:
        if self._sim_task is None or self._sim_task.done():
            self._sim_task = asyncio.create_task(self._run_simulation_forever())

    async def _run_simulation_forever(self) -> None:
        """Keep the viewer loop alive across crashes (e.g. mid-spawn races)."""
        while True:
            try:
                await self.runner.start()
            except Exception:
                log.exception("Simulation crashed; restarting in 0.5s")
                await asyncio.sleep(0.5)
                continue
            reason = self.runner._stop_reason
            if reason in {"server_shutdown", "server_control", "human_stop"}:
                return
            if reason == "max_ticks":
                # Live viewer: extend and keep going instead of freezing the UI.
                self.runner.extend_max_ticks(10_000)
                log.info(
                    "Hit max_ticks; extended to %s and continuing",
                    self.runner.config.max_ticks,
                )
                continue
            if reason == "no_agents_left":
                await asyncio.sleep(1.0)
                continue
            # Unexpected clean stop — brief pause then resume.
            await asyncio.sleep(0.5)

    async def serve(self, *, run_simulation: bool = True) -> None:
        import uvicorn

        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
        self._server = uvicorn.Server(config)
        if run_simulation:
            self.start_simulation()
        try:
            await self._server.serve()
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.runner.request_stop("server_shutdown")
        if self._sim_task is not None and not self._sim_task.done():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(self._sim_task, timeout=5.0)
