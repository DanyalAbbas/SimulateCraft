"""Minecraft console commands via RCON, with docker rcon-cli fallback.

Used for watcher role assignment (OP / spectator) and agent teleport.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import socket
import struct
import subprocess
from typing import Any

log = logging.getLogger(__name__)

_SERVERDATA_AUTH = 3
_SERVERDATA_AUTH_RESPONSE = 2
_SERVERDATA_EXECCOMMAND = 2
_SERVERDATA_RESPONSE_VALUE = 0


class RconError(RuntimeError):
    """RCON authentication or command failure."""


class MinecraftRcon:
    """Blocking RCON session. Prefer short-lived use per command batch."""

    def __init__(self, host: str, port: int, password: str, *, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._req_id = 0

    def __enter__(self) -> MinecraftRcon:
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        self._sock = sock
        resp_id, resp_type, _ = self._send(self.password, _SERVERDATA_AUTH)
        if resp_id == -1:
            self.close()
            raise RconError("RCON authentication failed (check RCON_PASSWORD)")
        # Some servers send a trailing empty RESPONSE_VALUE after auth — drain it.
        if resp_type == _SERVERDATA_AUTH_RESPONSE:
            self._drain_pending()

    def close(self) -> None:
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None

    def command(self, cmd: str) -> str:
        if self._sock is None:
            raise RconError("RCON not connected")
        _, _, body = self._send(cmd, _SERVERDATA_EXECCOMMAND)
        # Command replies can span multiple RESPONSE_VALUE packets; read until idle.
        extra = self._drain_pending(max_packets=4)
        if extra:
            body = f"{body}{extra}"
        return body

    def _drain_pending(self, *, max_packets: int = 1) -> str:
        assert self._sock is not None
        chunks: list[str] = []
        self._sock.settimeout(0.15)
        try:
            for _ in range(max_packets):
                try:
                    data = self._recv_exact(4)
                except (TimeoutError, OSError):
                    break
                (length,) = struct.unpack("<i", data)
                if length <= 0 or length > 65536:
                    break
                try:
                    payload = self._recv_exact(length)
                except (TimeoutError, OSError):
                    break
                if len(payload) < 8:
                    break
                text = payload[8:-2].decode("utf-8", errors="replace")
                if text:
                    chunks.append(text)
        finally:
            self._sock.settimeout(self.timeout)
        return "".join(chunks)

    def _send(self, payload: str, req_type: int) -> tuple[int, int, str]:
        assert self._sock is not None
        self._req_id += 1
        req_id = self._req_id
        body = payload.encode("utf-8") + b"\x00\x00"
        packet = struct.pack("<ii", req_id, req_type) + body
        self._sock.sendall(struct.pack("<i", len(packet)) + packet)

        data = self._recv_exact(4)
        (length,) = struct.unpack("<i", data)
        data = self._recv_exact(length)
        resp_id, resp_type = struct.unpack("<ii", data[:8])
        text = data[8:-2].decode("utf-8", errors="replace")
        return resp_id, resp_type, text

    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise RconError("RCON connection closed")
            buf += chunk
        return buf


def default_rcon_settings() -> tuple[str, int, str]:
    """Host/port/password from env, with SimulateCraft defaults."""
    host = os.getenv("RCON_HOST", os.getenv("MC_RCON_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    port = int(os.getenv("RCON_PORT", os.getenv("MC_RCON_PORT", "25575")))
    password = os.getenv("RCON_PASSWORD", os.getenv("MC_RCON_PASSWORD", "simulatecraft")).strip()
    if not password:
        password = "simulatecraft"
    return host, port, password


def _docker_rcon_cli(commands: list[str], *, container: str = "simulatecraft-mc") -> list[str]:
    docker = shutil.which("docker")
    if not docker:
        raise RconError("docker not found for rcon-cli fallback")
    responses: list[str] = []
    for cmd in commands:
        result = subprocess.run(
            [docker, "exec", container, "rcon-cli", cmd],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        text = (result.stdout or result.stderr or "").strip()
        if result.returncode != 0 and not text:
            raise RconError(f"rcon-cli failed for {cmd!r} (exit {result.returncode})")
        responses.append(text)
    return responses


def run_commands(
    commands: list[str],
    *,
    host: str | None = None,
    port: int | None = None,
    password: str | None = None,
) -> list[str]:
    """Run console commands via TCP RCON, falling back to docker rcon-cli."""
    if not commands:
        return []
    dh, dp, dw = default_rcon_settings()
    try:
        with MinecraftRcon(host or dh, port if port is not None else dp, password or dw) as rcon:
            return [rcon.command(cmd) for cmd in commands]
    except Exception as exc:
        log.warning("TCP RCON failed (%s); trying docker rcon-cli", exc)
        try:
            return _docker_rcon_cli(commands)
        except Exception as fallback_exc:
            raise RconError(
                f"Could not reach Minecraft RCON ({exc}). "
                f"Docker fallback also failed ({fallback_exc}). "
                "Is the server up with ENABLE_RCON=true on port 25575?"
            ) from fallback_exc
