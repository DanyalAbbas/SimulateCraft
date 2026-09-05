"""Unit tests for CLI helpers (no Docker / Node required)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from simulatecraft import cli


def test_repo_root_finds_pyproject() -> None:
    root = cli.repo_root()
    assert (root / "pyproject.toml").exists()
    assert (root / "docker-compose.yml").exists()


def test_require_llm_key_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    cli.require_llm_key()


def test_require_llm_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "SIMULATECRAFT_MODEL",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="No LLM key"):
        cli.require_llm_key()


def test_setup_node(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(cli, "_which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(cli, "BOT_DIR", tmp_path)
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(cli, "_run", lambda cmd, cwd=None: calls.append(cmd))
    cli.setup_node()
    assert calls and calls[0][0].endswith("npm")

    monkeypatch.setattr(cli, "_which", lambda name: None)
    with pytest.raises(SystemExit, match="Missing"):
        cli.setup_node()


def test_ensure_minecraft_skip(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    cli.ensure_minecraft(skip=True, host="localhost", port=25565)
    assert "Skipping Docker" in capsys.readouterr().out


def test_ensure_minecraft_already_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_need", lambda name, hint: "/usr/bin/docker")
    monkeypatch.setattr(cli, "_port_open", lambda h, p: True)
    monkeypatch.setattr(cli, "_docker_container_health", lambda *a, **k: "healthy")
    monkeypatch.setattr(cli, "_minecraft_logs_ready", lambda *a, **k: False)
    monkeypatch.setattr(cli.time, "sleep", lambda *_: None)
    cli.ensure_minecraft(skip=False, host="localhost", port=25565)


def test_ensure_minecraft_compose_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_need", lambda name, hint: "/usr/bin/docker")
    monkeypatch.setattr(cli, "_port_open", lambda h, p: False)
    monkeypatch.setattr(cli, "_run", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_docker_container_health", lambda *a, **k: "starting")
    monkeypatch.setattr(cli, "_minecraft_logs_ready", lambda *a, **k: False)
    # Force immediate timeout
    t0 = [1000.0]

    def fake_time() -> float:
        t0[0] += 300
        return t0[0]

    monkeypatch.setattr(cli.time, "time", fake_time)
    monkeypatch.setattr(cli.time, "sleep", lambda *_: None)
    with pytest.raises(SystemExit, match="did not become ready"):
        cli.ensure_minecraft(skip=False, host="localhost", port=25565)


def test_minecraft_logs_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="Done (12.3s)! For help", stderr="", returncode=0),
    )
    assert cli._minecraft_logs_ready("/usr/bin/docker") is True

    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(OSError("no")),
    )
    assert cli._minecraft_logs_ready("/usr/bin/docker") is False


def test_docker_container_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="healthy\n", stderr="", returncode=0),
    )
    assert cli._docker_container_health("/usr/bin/docker") == "healthy"

    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="", stderr="", returncode=1),
    )
    assert cli._docker_container_health("/usr/bin/docker") is None


def test_port_open(monkeypatch: pytest.MonkeyPatch) -> None:
    class Conn:
        def __enter__(self) -> Conn:
            return self

        def __exit__(self, *a: Any) -> None:
            return None

    monkeypatch.setattr(cli.socket, "create_connection", lambda *a, **k: Conn())
    assert cli._port_open("localhost", 1) is True

    monkeypatch.setattr(
        cli.socket,
        "create_connection",
        lambda *a, **k: (_ for _ in ()).throw(OSError()),
    )
    assert cli._port_open("localhost", 1) is False


def test_main_setup_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "setup_node", lambda: None)
    cli.main(["--setup-only"])


def test_main_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "setup_node", lambda: None)
    monkeypatch.setattr(cli, "require_llm_key", lambda: None)
    monkeypatch.setattr(cli, "ensure_minecraft", lambda **k: None)
    launched: list[Any] = []
    monkeypatch.setattr(cli, "launch_example", lambda args: launched.append(args))
    cli.main(["--no-docker", "--agents", "explorer"])
    assert launched and launched[0].no_docker is True


def test_launch_example(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio as aio

    called: dict[str, Any] = {}

    async def fake_run(*a: Any, **k: Any) -> None:
        called["ok"] = True

    monkeypatch.setattr(
        "simulatecraft.examples.minecraft_explorer.main.run_with_server",
        fake_run,
    )
    monkeypatch.setattr("simulatecraft.brains.llm.resolve_model", lambda: "test")

    def fake_asyncio_run(coro: Any) -> None:
        called["ran"] = True
        # Close the coroutine to avoid "never awaited" warnings.
        if hasattr(coro, "close"):
            coro.close()

    monkeypatch.setattr(aio, "run", fake_asyncio_run)

    args = SimpleNamespace(
        model="test",
        host="localhost",
        port=25565,
        agents=["explorer"],
        tick_rate=1.0,
        ticks=10,
        viewer_host="127.0.0.1",
        viewer_port=8000,
        log="events.jsonl",
        mc_version=None,
    )
    cli.launch_example(args)
    assert called.get("ran") is True
