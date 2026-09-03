"""One-command setup and run: install deps, start Minecraft, launch agents."""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for path in [here.parent, *here.parents]:
        if (path / "pyproject.toml").exists() and (path / "docker-compose.yml").exists():
            return path
    return Path.cwd()


REPO_ROOT = repo_root()
BOT_DIR = Path(__file__).resolve().parent / "minecraft" / "bot"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"


def _which(name: str) -> str | None:
    return shutil.which(name)


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def _need(name: str, hint: str) -> str:
    path = _which(name)
    if not path:
        sys.exit(f"Missing `{name}`.\n{hint}")
    return path


def setup_node() -> None:
    _need("node", "Install Node.js 18+ from https://nodejs.org")
    npm = _need("npm", "npm comes with Node.js: https://nodejs.org")
    if not BOT_DIR.joinpath("package.json").exists():
        sys.exit(f"Bot package.json not found at {BOT_DIR}")
    print("Installing Mineflayer (Node)…")
    _run([npm, "install"], cwd=BOT_DIR)


def ensure_minecraft(*, skip: bool, host: str, port: int) -> None:
    if skip:
        print(f"Skipping Docker; expecting a server at {host}:{port}")
        return
    if _port_open(host, port):
        print(f"Minecraft already listening on {host}:{port}")
        return
    docker = _need(
        "docker",
        "Install Docker Desktop / Docker Engine, or start your own Minecraft Java 1.21.4 server\n"
        "and re-run with: ./run.sh --no-docker",
    )
    compose = [docker, "compose", "-f", str(COMPOSE_FILE), "up", "-d"]
    if not COMPOSE_FILE.exists():
        sys.exit(f"Missing {COMPOSE_FILE}")
    print("Starting Minecraft 1.21.4 (offline mode) via Docker…")
    _run(compose)
    print("Waiting for the server to finish generating the world (first boot can take 1–2 min)…")
    deadline = time.time() + 180
    while time.time() < deadline:
        if _port_open(host, port):
            # Give the process a few extra seconds after the port opens.
            time.sleep(4)
            print("Minecraft is up.")
            return
        time.sleep(2)
    sys.exit(f"Minecraft did not open {host}:{port} in time.\nCheck: docker compose logs -f")


def require_llm_key() -> None:
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv()
    if (
        os.getenv("GROQ_API_KEY")
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("SIMULATECRAFT_MODEL")
    ):
        return
    sys.exit(
        "No LLM key found.\n\n"
        "1. Get a free Groq key (30 seconds, no credit card):\n"
        "     https://console.groq.com/keys\n"
        "2. Put it in a .env file in this folder:\n"
        "     echo 'GROQ_API_KEY=gsk_your_key' > .env\n"
        "3. Run ./run.sh again.\n"
    )


def launch_example(args: argparse.Namespace) -> None:
    import asyncio

    from simulatecraft.brains.llm import resolve_model
    from simulatecraft.examples.minecraft_explorer.main import run_with_server

    model = args.model or resolve_model()
    print(f"Starting agents  [model: {model}]")
    asyncio.run(
        run_with_server(
            args.host,
            args.port,
            args.agents,
            model,
            args.tick_rate,
            args.ticks,
            args.viewer_host,
            args.viewer_port,
            args.log,
            args.mc_version,
        )
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="simulatecraft",
        description="Install deps, start a local Minecraft server, and run LLM agents.",
    )
    parser.add_argument("--setup-only", action="store_true", help="Install Node bot deps and exit")
    parser.add_argument("--no-docker", action="store_true", help="Do not start Docker Minecraft")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=25565)
    parser.add_argument("--agents", nargs="+", default=["explorer"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--ticks", type=int, default=10_000)
    parser.add_argument("--tick-rate", type=float, default=1.0)
    parser.add_argument("--viewer-host", default="127.0.0.1")
    parser.add_argument("--viewer-port", type=int, default=8000)
    parser.add_argument("--log", default="events.jsonl")
    parser.add_argument("--mc-version", default=None)
    args = parser.parse_args(argv)

    setup_node()
    if args.setup_only:
        print("Setup complete.")
        return
    require_llm_key()
    ensure_minecraft(skip=args.no_docker, host=args.host, port=args.port)
    print(f"\nViewer will be at http://{args.viewer_host}:{args.viewer_port}\n")
    launch_example(args)


if __name__ == "__main__":
    main()
