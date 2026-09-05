"""FastAPI app: REST control + live websocket broadcast + inbound human input."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
from .agents import AgentCreateRequest, AgentCreateResponse, create_agent, delete_agent
from .roles import WatcherRoleRequest, WatcherRoleResponse, assign_watcher_role

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
                    await _handle_client_message(runner, message, ws)
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
    runner: Runner, message: dict[str, Any], ws: WebSocket | None = None
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
        map_data = await fetch(origin_x, origin_z, size)
        if ws is not None:
            await ws.send_text(json.dumps({"type": "map", "map": map_data}))
    elif msg_type == "agent_create":
        req = AgentCreateRequest.model_validate(message.get("agent") or message)
        created = await create_agent(runner, req)
        if ws is not None:
            await ws.send_text(json.dumps({"type": "agent_created", **created.model_dump()}))
    elif msg_type == "agent_delete":
        agent_id = str(message["agent_id"])
        deleted = await delete_agent(runner, agent_id)
        if ws is not None:
            await ws.send_text(json.dumps({"type": "agent_deleted", **deleted}))
    elif msg_type == "watcher_role":
        role_req = WatcherRoleRequest.model_validate(message.get("watcher") or message)
        assigned = assign_watcher_role(role_req)
        if ws is not None:
            await ws.send_text(json.dumps({"type": "watcher_role", **assigned.model_dump()}))
    else:
        raise ValueError(f"unknown inbound type {msg_type!r}")


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
            self._sim_task = asyncio.create_task(self.runner.start())

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
