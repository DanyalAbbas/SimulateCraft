"""Minimal Minecraft RCON client (stdlib only).

Used to grant OP and set gamemode / teleport when the server exposes RCON
(itzg image: ENABLE_RCON=true, RCON_PASSWORD=..., RCON_PORT=25575).
"""

from __future__ import annotations

import contextlib
import logging
import os
import socket
import struct
from typing import Any

log = logging.getLogger(__name__)

_SERVERDATA_AUTH = 3
_SERVERDATA_EXECCOMMAND = 2


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
        resp_id, _ = self._send(self.password, _SERVERDATA_AUTH)
        if resp_id == -1:
            self.close()
            raise RconError("RCON authentication failed (check RCON_PASSWORD)")

    def close(self) -> None:
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None

    def command(self, cmd: str) -> str:
        if self._sock is None:
            raise RconError("RCON not connected")
        _, body = self._send(cmd, _SERVERDATA_EXECCOMMAND)
        return body

    def _send(self, payload: str, req_type: int) -> tuple[int, str]:
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
        _ = resp_type
        text = data[8:-2].decode("utf-8", errors="replace")
        return resp_id, text

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
    host = os.getenv("RCON_HOST", os.getenv("MC_RCON_HOST", "localhost")).strip()
    port = int(os.getenv("RCON_PORT", os.getenv("MC_RCON_PORT", "25575")))
    password = os.getenv("RCON_PASSWORD", os.getenv("MC_RCON_PASSWORD", "simulatecraft")).strip()
    return host, port, password


def run_commands(
    commands: list[str],
    *,
    host: str | None = None,
    port: int | None = None,
    password: str | None = None,
) -> list[str]:
    """Run a batch of console commands; returns response bodies."""
    if not commands:
        return []
    dh, dp, dw = default_rcon_settings()
    with MinecraftRcon(host or dh, port if port is not None else dp, password or dw) as rcon:
        return [rcon.command(cmd) for cmd in commands]
