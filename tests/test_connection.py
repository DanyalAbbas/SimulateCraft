"""Unit tests for MinecraftBridge without a live Node process."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from simulatecraft.minecraft.connection import BridgeError, MinecraftBridge


def test_connect_hint_branches() -> None:
    b = MinecraftBridge(host="h", minecraft_port=1)
    assert "Could not connect" in b._minecraft_connect_hint("ECONNREFUSED")
    assert "World still generating" in b._minecraft_connect_hint("socketClosed before spawn")
    assert "Mineflayer cannot speak" in b._minecraft_connect_hint("PartialReadError xyz")
    assert "failed before spawn" in b._minecraft_connect_hint("mystery")


def test_dispatch_rpc_and_events() -> None:
    b = MinecraftBridge()
    loop = asyncio.new_event_loop()
    fut = loop.create_future()
    b._pending["1"] = fut
    b._dispatch({"id": "1", "result": {"ok": True}})
    assert fut.result() == {"ok": True}

    fut2 = loop.create_future()
    b._pending["2"] = fut2
    b._dispatch({"id": "2", "error": "boom"})
    with pytest.raises(BridgeError, match="boom"):
        fut2.result()

    # unknown / done future ignored
    b._dispatch({"id": "missing", "result": {}})
    done = loop.create_future()
    done.set_result(1)
    b._pending["3"] = done
    b._dispatch({"id": "3", "result": {}})

    seen: list[Any] = []
    b.on_event("chat", lambda d: seen.append(d))
    b.on_event("chat", lambda d: (_ for _ in ()).throw(RuntimeError("handler boom")))
    b._dispatch({"event": "chat", "data": {"text": "hi"}})
    assert seen == [{"text": "hi"}]
    b._dispatch({"noop": True})
    loop.close()


async def test_call_not_connected() -> None:
    b = MinecraftBridge()
    with pytest.raises(BridgeError, match="not connected"):
        await b.call("get_state")


async def test_call_success_and_timeout() -> None:
    b = MinecraftBridge(request_timeout=0.05)
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    b._writer = writer

    async def resolve_later() -> None:
        await asyncio.sleep(0.01)
        # find pending and resolve
        for req_id, fut in list(b._pending.items()):
            if not fut.done():
                fut.set_result({"ok": True})

    task = asyncio.create_task(resolve_later())
    assert await b.call("get_state") == {"ok": True}
    await task

    with pytest.raises(BridgeError, match="timed out"):
        await b.call("slow")


async def test_close_fails_pending() -> None:
    b = MinecraftBridge()
    fut = asyncio.get_running_loop().create_future()
    b._pending["x"] = fut
    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.side_effect = __import__("subprocess").TimeoutExpired(cmd="node", timeout=1)
    b._process = proc
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    b._writer = writer
    read_task = asyncio.create_task(asyncio.sleep(10))
    b._read_task = read_task
    await b.close()
    assert fut.done()
    with pytest.raises(BridgeError, match="closed"):
        fut.result()
    proc.kill.assert_called()


async def test_connect_missing_script(tmp_path: Path) -> None:
    b = MinecraftBridge(bot_script=tmp_path / "missing.js")
    with pytest.raises(FileNotFoundError):
        await b.connect()


async def test_connect_already_connected() -> None:
    b = MinecraftBridge()
    b._connected = True
    await b.connect()


async def test_connect_spawn_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "bot.js"
    script.write_text("// stub", encoding="utf-8")
    b = MinecraftBridge(bot_script=script, connect_timeout=2.0, password="x", version="1.21.4")

    proc = MagicMock()
    proc.poll.return_value = None
    monkeypatch.setattr(
        "simulatecraft.minecraft.connection.subprocess.Popen",
        lambda *a, **k: proc,
    )

    async def fake_tcp(self: MinecraftBridge) -> None:
        self._writer = MagicMock()
        self._reader = MagicMock()

        # Immediately fire spawned via handler registration race: patch on_event
        original = self.on_event

        def on_event(name: str, handler: Any) -> None:
            original(name, handler)
            if name == "bot.spawned":
                handler({"ok": True})

        self.on_event = on_event  # type: ignore[method-assign]

    monkeypatch.setattr(MinecraftBridge, "_tcp_connect", fake_tcp)
    await b.connect()
    assert b._connected is True
    await b.close()


async def test_connect_spawn_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "bot.js"
    script.write_text("// stub", encoding="utf-8")
    b = MinecraftBridge(bot_script=script, connect_timeout=1.0)
    monkeypatch.setattr(
        "simulatecraft.minecraft.connection.subprocess.Popen",
        lambda *a, **k: MagicMock(poll=lambda: None),
    )

    async def fake_tcp(self: MinecraftBridge) -> None:
        original = self.on_event

        def on_event(name: str, handler: Any) -> None:
            original(name, handler)
            if name == "bot.error":
                handler({"message": "ECONNREFUSED"})

        self.on_event = on_event  # type: ignore[method-assign]

    monkeypatch.setattr(MinecraftBridge, "_tcp_connect", fake_tcp)
    monkeypatch.setattr(MinecraftBridge, "close", AsyncMock())
    with pytest.raises(BridgeError, match="Could not connect"):
        await b.connect()


async def test_tcp_connect_process_exited(monkeypatch: pytest.MonkeyPatch) -> None:
    b = MinecraftBridge(connect_timeout=0.2)
    proc = MagicMock()
    proc.poll.return_value = 1
    proc.returncode = 1
    b._process = proc
    with pytest.raises(BridgeError, match="exited before"):
        await b._tcp_connect()


async def test_tcp_connect_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    b = MinecraftBridge(connect_timeout=0.15)
    b._process = MagicMock(poll=lambda: None)

    async def refuse(*a: Any, **k: Any) -> None:
        raise ConnectionRefusedError()

    monkeypatch.setattr(asyncio, "open_connection", refuse)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    # Force deadline immediately
    times = [0.0, 1.0]

    def fake_time() -> float:
        return times.pop(0) if times else 99.0

    monkeypatch.setattr(asyncio.get_event_loop(), "time", fake_time)
    with pytest.raises(BridgeError, match="Could not connect to the bot IPC"):
        await b._tcp_connect()


async def test_read_loop_bad_json_and_eof() -> None:
    b = MinecraftBridge()

    class Reader:
        def __init__(self) -> None:
            self.lines = [b"{not-json}\n", b"", b'{"event":"chat","data":{}}\n']

        async def readline(self) -> bytes:
            if not self.lines:
                return b""
            return self.lines.pop(0)

    b._reader = Reader()  # type: ignore[assignment]
    await b._read_loop()


async def test_high_level_wrappers() -> None:
    b = MinecraftBridge()
    b.call = AsyncMock(return_value={"ok": True})  # type: ignore[method-assign]
    assert await b.get_state() == {"ok": True}
    assert await b.perform_action({"kind": "chat"}) == {"ok": True}
    assert await b.get_map(0, 0, 32) == {"ok": True}
    assert await b.configure_presence(x=1, y=2, z=3, gamemode="survival") == {"ok": True}


async def test_context_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "bot.js"
    script.write_text("//", encoding="utf-8")
    b = MinecraftBridge(bot_script=script)
    monkeypatch.setattr(MinecraftBridge, "connect", AsyncMock())
    monkeypatch.setattr(MinecraftBridge, "close", AsyncMock())
    async with b:
        pass
    b.connect.assert_awaited()  # type: ignore[attr-defined]
    b.close.assert_awaited()  # type: ignore[attr-defined]
