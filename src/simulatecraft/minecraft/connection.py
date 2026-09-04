"""Mineflayer IPC bridge — Python side.

Architecture
------------
A Node.js process runs ``bot/bot.js`` which connects to Minecraft via Mineflayer.
This module spawns that process and communicates with it over a local TCP socket
using newline-delimited JSON (one JSON object per line).

Python sends  → {"id": "<uuid>", "method": "<name>", "params": {...}}
Node responds ← {"id": "<uuid>", "result": {...}}  or  {"id": "<uuid>", "error": "..."}
Node also pushes unsolicited events:
              ← {"event": "<name>", "data": {...}}

Usage
-----
    bridge = MinecraftBridge(host="localhost", minecraft_port=25565,
                             username="SimBot", bot_script=None)
    await bridge.connect()
    state = await bridge.get_state()
    await bridge.perform_action({"kind": "chat", "text": "hello!"})
    await bridge.close()

``bot_script`` defaults to the bundled ``bot/bot.js``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_BOT_SCRIPT = Path(__file__).parent / "bot" / "bot.js"
_DEFAULT_IPC_PORT = 25570  # local TCP port for Python↔Node JSON RPC


class BridgeError(Exception):
    """Raised when the bot process crashes or returns an error response."""


class MinecraftBridge:
    """Manages the Node.js Mineflayer subprocess and the JSON-RPC socket."""

    def __init__(
        self,
        *,
        host: str = "localhost",
        minecraft_port: int = 25565,
        username: str = "SimBot",
        password: str = "",
        version: str | None = None,
        ipc_port: int = _DEFAULT_IPC_PORT,
        bot_script: str | Path | None = None,
        node_executable: str = "node",
        connect_timeout: float = 30.0,
        request_timeout: float = 45.0,
        auth: str = "offline",
    ) -> None:
        self.host = host
        self.minecraft_port = minecraft_port
        self.username = username
        self.password = password
        self.version = version
        self.ipc_port = ipc_port
        self.bot_script = Path(bot_script) if bot_script else _DEFAULT_BOT_SCRIPT
        self.node_executable = node_executable
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout
        self.auth = auth

        self._process: subprocess.Popen | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._event_handlers: dict[str, list[Any]] = {}
        self._read_task: asyncio.Task | None = None
        self._connected = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Spawn the Node bot and wait until it signals it has joined the server."""
        if self._connected:
            return

        if not self.bot_script.exists():
            raise FileNotFoundError(
                f"Bot script not found: {self.bot_script}\n"
                "Run: cd src/simulatecraft/minecraft/bot && npm install"
            )

        env = {**os.environ, "IPC_PORT": str(self.ipc_port)}
        cmd = [
            self.node_executable,
            str(self.bot_script),
            "--host",
            self.host,
            "--port",
            str(self.minecraft_port),
            "--username",
            self.username,
            "--ipc-port",
            str(self.ipc_port),
            "--auth",
            self.auth,
        ]
        if self.password:
            cmd += ["--password", self.password]
        if self.version:
            cmd += ["--version", self.version]

        log.info("Spawning bot process: %s", " ".join(cmd))
        self._process = subprocess.Popen(  # noqa: S603
            cmd,
            env=env,
            cwd=str(self.bot_script.parent),
            stdout=None,
            stderr=None,
        )

        await self._tcp_connect()

        spawned: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

        def _on_spawned(data: dict[str, Any]) -> None:
            if not spawned.done():
                spawned.set_result(data)

        def _on_failed(data: dict[str, Any]) -> None:
            if spawned.done():
                return
            reason = data.get("message") or data.get("reason") or "disconnected"
            spawned.set_exception(BridgeError(self._minecraft_connect_hint(str(reason))))

        self.on_event("bot.spawned", _on_spawned)
        self.on_event("bot.error", _on_failed)
        self.on_event("bot.disconnected", _on_failed)
        try:
            await asyncio.wait_for(spawned, timeout=self.connect_timeout)
        except TimeoutError as exc:
            await self.close()
            raise BridgeError(
                f"Bot did not spawn within {self.connect_timeout}s. "
                f"Is a Minecraft Java server running at {self.host}:{self.minecraft_port}?"
            ) from exc
        except BridgeError:
            await self.close()
            raise

        self._connected = True
        log.info("Bot '%s' spawned in Minecraft.", self.username)

    def _minecraft_connect_hint(self, reason: str) -> str:
        target = f"{self.host}:{self.minecraft_port}"
        if "ECONNREFUSED" in reason or "connect" in reason.lower():
            return (
                f"Could not connect to Minecraft at {target}.\n"
                "Start a Java Edition server on that host/port, then retry.\n"
                "Example (Docker): docker run -d --name mc -p 25565:25565 "
                "-e EULA=TRUE -e VERSION=1.21.4 itzg/minecraft-server"
            )
        if "socketClosed" in reason or "Failed to verify" in reason or "EPIPE" in reason:
            return (
                f"Minecraft closed the connection before spawn ({target}): {reason}.\n"
                "Common causes:\n"
                "  • World still generating (port open ≠ ready). Wait for "
                "'Done (…)!' in `docker compose logs -f`, then retry.\n"
                "  • online-mode kicks offline bots — use ONLINE_MODE=FALSE "
                "(bundled docker-compose already does).\n"
                "  • Unsupported protocol version — pin VERSION=1.21.4."
            )
        if "PartialReadError" in reason or "unsupported" in reason.lower():
            return (
                f"Mineflayer cannot speak this Minecraft version ({reason}).\n"
                "Pin the server to a supported release, e.g. 1.21.4:\n"
                "  docker compose down && docker compose up -d"
            )
        return f"Minecraft bot failed before spawn ({target}): {reason}"

    async def _tcp_connect(self) -> None:
        """Open the TCP socket to the Node IPC server."""
        deadline = asyncio.get_event_loop().time() + self.connect_timeout
        while asyncio.get_event_loop().time() < deadline:
            if self._process is not None and self._process.poll() is not None:
                raise BridgeError(
                    "The Mineflayer bot process exited before the IPC server was ready.\n"
                    f"Exit code: {self._process.returncode}\n"
                    "Run: cd src/simulatecraft/minecraft/bot && npm install"
                )
            try:
                self._reader, self._writer = await asyncio.open_connection(
                    "127.0.0.1",
                    self.ipc_port,
                    # Map payloads are ~64KB+; asyncio's default readline limit is 64KB.
                    limit=8 * 1024 * 1024,
                )
                self._read_task = asyncio.create_task(self._read_loop())
                log.debug("IPC socket connected on port %d", self.ipc_port)
                return
            except (ConnectionRefusedError, OSError):
                await asyncio.sleep(0.25)
        raise BridgeError(
            f"Could not connect to the bot IPC server on port {self.ipc_port}.\n"
            "Make sure Node.js is installed and: cd src/simulatecraft/minecraft/bot && npm install"
        )

    async def close(self) -> None:
        """Gracefully shut down the bot and the subprocess."""
        self._connected = False
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        # Fail any pending requests
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(BridgeError("bridge closed"))
        self._pending.clear()

    # ------------------------------------------------------------------
    # RPC helpers
    # ------------------------------------------------------------------

    async def call(self, method: str, **params: Any) -> Any:
        """Send an RPC request and await its response."""
        if self._writer is None:
            raise BridgeError("Bridge not connected. Call connect() first.")
        req_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[req_id] = future
        msg = json.dumps({"id": req_id, "method": method, "params": params}) + "\n"
        self._writer.write(msg.encode())
        await self._writer.drain()
        try:
            return await asyncio.wait_for(future, timeout=self.request_timeout)
        except TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise BridgeError(f"RPC '{method}' timed out after {self.request_timeout}s") from exc

    # ------------------------------------------------------------------
    # High-level API used by MinecraftEnvironment
    # ------------------------------------------------------------------

    async def get_state(self) -> dict[str, Any]:
        """Return a full world-state snapshot from the bot."""
        return await self.call("get_state")

    async def perform_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Execute one action dict (matches Action.model_dump()) on the bot."""
        return await self.call("perform_action", action=action)

    async def get_map(self, origin_x: int, origin_z: int, size: int = 128) -> dict[str, Any]:
        return await self.call("get_map", origin_x=origin_x, origin_z=origin_z, size=size)

    async def configure_presence(
        self,
        *,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        gamemode: str | None = None,
    ) -> dict[str, Any]:
        """Teleport / set gamemode after spawn (bot must be OP for chat commands)."""
        return await self.call(
            "configure_presence",
            x=x,
            y=y,
            z=z,
            gamemode=gamemode,
        )

    # ------------------------------------------------------------------
    # Event subscription (push events from Node → Python)
    # ------------------------------------------------------------------

    def on_event(self, event_name: str, handler: Any) -> None:
        self._event_handlers.setdefault(event_name, []).append(handler)

    # ------------------------------------------------------------------
    # Internal: read loop
    # ------------------------------------------------------------------

    async def _read_loop(self) -> None:
        """Continuously read newline-delimited JSON from the IPC socket."""
        assert self._reader is not None
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    log.warning("IPC socket closed by bot process.")
                    break
                try:
                    msg = json.loads(line.decode().strip())
                except json.JSONDecodeError as exc:
                    log.warning("Bad JSON from bot: %s | %s", exc, line[:120])
                    continue
                self._dispatch(msg)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("IPC read loop error")

    def _dispatch(self, msg: dict[str, Any]) -> None:
        # RPC response
        if "id" in msg:
            req_id = msg["id"]
            future = self._pending.pop(req_id, None)
            if future is None or future.done():
                return
            if "error" in msg:
                future.set_exception(BridgeError(msg["error"]))
            else:
                future.set_result(msg.get("result", {}))
            return
        # Push event
        if "event" in msg:
            event_name = msg["event"]
            data = msg.get("data", {})
            for handler in list(self._event_handlers.get(event_name, [])):
                try:
                    handler(data)
                except Exception:
                    log.exception("Event handler for '%s' raised", event_name)
            return
        log.debug("Unknown IPC message: %s", msg)

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> MinecraftBridge:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
