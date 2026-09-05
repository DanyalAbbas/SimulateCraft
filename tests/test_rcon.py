"""Unit tests for Minecraft RCON client and docker fallback."""

from __future__ import annotations

import struct
from typing import Any
from unittest.mock import MagicMock

import pytest

from simulatecraft.minecraft import rcon as rcon_mod
from simulatecraft.minecraft.rcon import (
    MinecraftRcon,
    RconError,
    _docker_rcon_cli,
    default_rcon_settings,
    run_commands,
)


def _packet(req_id: int, req_type: int, payload: str = "") -> bytes:
    body = struct.pack("<ii", req_id, req_type) + payload.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(body)) + body


class FakeSock:
    def __init__(self, responses: list[bytes]) -> None:
        self._buf = b"".join(responses)
        self.sent: list[bytes] = []
        self.timeout: float | None = None
        self.closed = False

    def settimeout(self, t: float) -> None:
        self.timeout = t

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, n: int) -> bytes:
        if self.timeout == 0.15 and not self._buf:
            raise TimeoutError()
        if not self._buf:
            return b""
        chunk, self._buf = self._buf[:n], self._buf[n:]
        return chunk

    def close(self) -> None:
        self.closed = True


def test_default_rcon_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RCON_HOST", raising=False)
    monkeypatch.delenv("MC_RCON_HOST", raising=False)
    monkeypatch.delenv("RCON_PORT", raising=False)
    monkeypatch.delenv("MC_RCON_PORT", raising=False)
    monkeypatch.delenv("RCON_PASSWORD", raising=False)
    monkeypatch.delenv("MC_RCON_PASSWORD", raising=False)
    assert default_rcon_settings() == ("127.0.0.1", 25575, "simulatecraft")

    monkeypatch.setenv("RCON_HOST", "mc")
    monkeypatch.setenv("RCON_PORT", "25570")
    monkeypatch.setenv("RCON_PASSWORD", "  ")
    assert default_rcon_settings() == ("mc", 25570, "simulatecraft")


def test_rcon_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = FakeSock([_packet(-1, 2, "")])
    monkeypatch.setattr(rcon_mod.socket, "create_connection", lambda *a, **k: sock)
    client = MinecraftRcon("h", 1, "bad")
    with pytest.raises(RconError, match="authentication"):
        client.connect()
    assert sock.closed


def test_rcon_command_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # auth ok (id=1, type=2), drain empty timeout, then command reply
    responses = [
        _packet(1, 2, ""),  # auth
        _packet(2, 0, "hello"),  # command body
    ]
    sock = FakeSock(responses)
    monkeypatch.setattr(rcon_mod.socket, "create_connection", lambda *a, **k: sock)

    with MinecraftRcon("h", 1, "pw") as client:
        # After auth, drain may timeout — inject more response for command
        sock._buf += _packet(2, 0, " world")
        out = client.command("say hi")
        assert "hello" in out or "world" in out or out == "hello"


def test_rcon_command_not_connected() -> None:
    with pytest.raises(RconError, match="not connected"):
        MinecraftRcon("h", 1, "pw").command("list")


def test_rcon_recv_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = FakeSock([])
    monkeypatch.setattr(rcon_mod.socket, "create_connection", lambda *a, **k: sock)
    client = MinecraftRcon("h", 1, "pw")
    client._sock = sock
    with pytest.raises(RconError, match="closed"):
        client._recv_exact(4)


def test_run_commands_empty() -> None:
    assert run_commands([]) == []


def test_run_commands_tcp_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class Ctx:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *a: Any) -> None:
            return None

        def command(self, cmd: str) -> str:
            return f"ok:{cmd}"

    monkeypatch.setattr(rcon_mod, "MinecraftRcon", lambda *a, **k: Ctx())
    assert run_commands(["list", "op Steve"]) == ["ok:list", "ok:op Steve"]


def test_run_commands_falls_back_to_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rcon_mod,
        "MinecraftRcon",
        lambda *a, **k: (_ for _ in ()).throw(OSError("down")),
    )
    monkeypatch.setattr(rcon_mod, "_docker_rcon_cli", lambda cmds, **k: [f"d:{c}" for c in cmds])
    assert run_commands(["list"]) == ["d:list"]


def test_run_commands_both_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rcon_mod,
        "MinecraftRcon",
        lambda *a, **k: (_ for _ in ()).throw(OSError("down")),
    )
    monkeypatch.setattr(
        rcon_mod,
        "_docker_rcon_cli",
        lambda cmds, **k: (_ for _ in ()).throw(RconError("no docker")),
    )
    with pytest.raises(RconError, match="Could not reach"):
        run_commands(["list"])


def test_docker_rcon_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rcon_mod.shutil, "which", lambda _: None)
    with pytest.raises(RconError, match="docker not found"):
        _docker_rcon_cli(["list"])

    monkeypatch.setattr(rcon_mod.shutil, "which", lambda _: "/usr/bin/docker")

    good = MagicMock(returncode=0, stdout="ok\n", stderr="")
    monkeypatch.setattr(rcon_mod.subprocess, "run", lambda *a, **k: good)
    assert _docker_rcon_cli(["list"]) == ["ok"]

    bad = MagicMock(returncode=1, stdout="", stderr="")
    monkeypatch.setattr(rcon_mod.subprocess, "run", lambda *a, **k: bad)
    with pytest.raises(RconError, match="rcon-cli failed"):
        _docker_rcon_cli(["list"])
