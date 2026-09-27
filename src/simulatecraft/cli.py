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


def _docker_container_health(docker: str, container: str = "simulatecraft-mc") -> str | None:
    fmt = "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}"
    try:
        result = subprocess.run(
            [docker, "inspect", "--format", fmt, container],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None


def _minecraft_logs_ready(docker: str, container: str = "simulatecraft-mc") -> bool:
    """True once the vanilla server prints Done (port open is not enough)."""
    try:
        result = subprocess.run(
            [docker, "logs", container],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    text = f"{result.stdout}\n{result.stderr}"
    return "Done (" in text or "RCON running on" in text


def _existing_world_dir() -> Path | None:
    world = REPO_ROOT / "data" / "minecraft" / "world"
    if (world / "level.dat").is_file():
        return world
    return None


def _prompt_line(message: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        raw = input(f"{message}{suffix}: ").strip()
    except EOFError:
        return default
    return raw or default


def _configure_world(
    *,
    world_mode: str | None = None,
    import_path: str | None = None,
    seed: int | None = None,
) -> None:
    """Ask (or use flags) whether to import a world or generate a random one.

    ``world_mode``: ``import`` | ``random`` | ``keep`` | None (interactive).
    """
    from simulatecraft.minecraft.world_settings import (
        import_world_folder,
        import_world_zip,
        prepare_random_world,
    )

    existing = _existing_world_dir()
    mode = (world_mode or "").strip().lower() or None

    if mode is None:
        if not sys.stdin.isatty():
            mode = "keep" if existing else "random"
        else:
            print("\n=== World setup ===")
            if existing:
                print(f"Found existing world at {existing}")
                print("  [1] Keep existing world")
                print("  [2] Import a Minecraft world (.zip or folder)")
                print("  [3] Generate a new random world")
                choice = _prompt_line("Choice", "1")
                mode = {"1": "keep", "2": "import", "3": "random"}.get(choice, "keep")
            else:
                print("No world yet. Import a custom world, or generate a random one.")
                print("  [1] Import a Minecraft world (.zip or folder)")
                print("  [2] Generate a new random world")
                choice = _prompt_line("Choice", "2")
                mode = {"1": "import", "2": "random"}.get(choice, "random")

    if mode == "keep":
        if not existing:
            print("No existing world to keep — generating a random one.")
            mode = "random"
        else:
            print(f"Keeping world at {existing}")
            return

    if mode == "import":
        path_str = (import_path or "").strip()
        if not path_str:
            if not sys.stdin.isatty():
                sys.exit("`--world import` requires `--import-world /path/to/world.zip`")
            path_str = _prompt_line("Path to world .zip or folder")
        if not path_str:
            sys.exit("No import path given.")
        path = Path(path_str).expanduser().resolve()
        if path.is_file() and path.suffix.lower() == ".zip":
            settings = import_world_zip(path, label=path.stem)
        elif path.is_dir():
            settings = import_world_folder(path, label=path.name)
        else:
            sys.exit(f"Not a .zip or world folder: {path}")
        print(f"Imported world: {settings.world.label}")
        os.environ.pop("SEED", None)
        return

    # random
    settings, chosen = prepare_random_world(seed=seed)
    os.environ["SEED"] = str(chosen)
    print(f"Random world ready (seed {chosen}). Minecraft will generate it on first boot.")
    _ = settings


def ensure_minecraft(
    *,
    skip: bool,
    host: str,
    port: int,
    world_mode: str | None = None,
    import_path: str | None = None,
    seed: int | None = None,
) -> None:
    if skip:
        print(f"Skipping Docker; expecting a server at {host}:{port}")
        _try_apply_world_rules()
        return
    docker = _need(
        "docker",
        "Install Docker Desktop / Docker Engine, or start your own Minecraft Java 1.21.4 server\n"
        "and re-run with: ./run.sh --no-docker   (Windows: .\\run.ps1 --no-docker)",
    )
    if _port_open(host, port):
        print(f"Minecraft already listening on {host}:{port}")
        print("(World setup skipped — stop the server to import or regenerate a world.)")
    else:
        if not COMPOSE_FILE.exists():
            sys.exit(f"Missing {COMPOSE_FILE}")
        _configure_world(world_mode=world_mode, import_path=import_path, seed=seed)
        print("Starting Minecraft 1.21.4 (offline mode) via Docker…")
        _run([docker, "compose", "-f", str(COMPOSE_FILE), "up", "-d"])

    print("Waiting for the server to finish generating the world (first boot can take 1–2 min)…")
    deadline = time.time() + 240
    while time.time() < deadline:
        health = _docker_container_health(docker)
        ready = health == "healthy" or _minecraft_logs_ready(docker)
        if ready:
            time.sleep(2)
            print("Minecraft is up.")
            _try_apply_world_rules()
            return
        time.sleep(2)
    sys.exit(
        f"Minecraft did not become ready at {host}:{port} in time.\n"
        "Check: docker compose logs -f\n"
        'Look for a line like: Done (…)! For help, type "help"'
    )


def _try_apply_world_rules() -> None:
    try:
        from simulatecraft.minecraft.world_settings import apply_rules_via_rcon

        apply_rules_via_rcon()
        print("Applied world rules from data/world_settings.json (if any).")
    except Exception as exc:
        print(f"Note: could not apply world rules yet ({exc})")


def _env_set(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def require_llm_key() -> None:
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv()
    if (
        _env_set("OPENROUTER_API_KEY")
        or _env_set("GROQ_API_KEY")
        or _env_set("SIMULATECRAFT_MODEL")
    ):
        return
    if _env_set("OPENAI_BASE_URL"):
        sys.exit(
            "OPENAI_BASE_URL is set, but SIMULATECRAFT_MODEL is missing.\n\n"
            "For 9Router / your own API, set all three in `.env`:\n"
            "  OPENAI_BASE_URL=http://localhost:20128/v1\n"
            "  OPENAI_API_KEY=<key>\n"
            "  SIMULATECRAFT_MODEL=oc/space-bunny-free\n\n"
            "Docs: https://danyalabbas.github.io/SimulateCraft/llm-providers/\n"
        )
    sys.exit(
        "No LLM provider configured.\n\n"
        "Edit `.env` in this folder (copy from `.env.example` if needed).\n\n"
        "Preferred options:\n"
        "  OpenRouter:\n"
        "    OPENROUTER_API_KEY=sk-or-...\n"
        "    https://openrouter.ai/keys\n\n"
        "  9Router / your own OpenAI-compatible API:\n"
        "    OPENAI_BASE_URL=http://localhost:20128/v1\n"
        "    OPENAI_API_KEY=<key>\n"
        "    SIMULATECRAFT_MODEL=oc/space-bunny-free\n\n"
        "  Groq (quick try only — rate-limits fast under agent load):\n"
        "    GROQ_API_KEY=gsk_...\n\n"
        "Then run again:\n"
        "  ./run.sh          # macOS / Linux\n"
        "  .\\run.ps1        # Windows PowerShell\n"
        "  run.cmd          # Windows double-click / cmd\n\n"
        "Docs: https://danyalabbas.github.io/SimulateCraft/llm-providers/\n"
    )


def launch_example(args: argparse.Namespace) -> None:
    import asyncio

    from simulatecraft.brains.llm import resolve_model
    from simulatecraft.examples.minecraft_explorer.main import run_with_server

    model = args.model or resolve_model()
    print(f"Starting agents  [model: {model}]")
    radius = int(getattr(args, "map_radius", 512) or 512)
    if radius > 8192:
        print(f"Note: --map-radius {radius} capped to 8192 (viewer scan limit).")
        args.map_radius = 8192
    elif radius > 2048:
        print(
            f"Note: --map-radius {radius} only widens how far you can pan; "
            "it does not zoom out or preload the whole area. Prefer ≤2048."
        )
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
            map_radius=args.map_radius,
        )
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="simulatecraft",
        description="Install deps, start a local Minecraft server, and run LLM agents.",
    )
    parser.add_argument("--setup-only", action="store_true", help="Install Node bot deps and exit")
    parser.add_argument("--no-docker", action="store_true", help="Do not start Docker Minecraft")
    parser.add_argument(
        "--world",
        choices=("import", "random", "keep"),
        default=None,
        help="World setup without a prompt: import | random | keep existing",
    )
    parser.add_argument(
        "--import-world",
        default=None,
        metavar="PATH",
        help="Path to a .zip or Java world folder (implies --world import)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed for --world random (default: random)",
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=25565)
    parser.add_argument("--agents", nargs="+", default=["explorer"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--ticks", type=int, default=10_000)
    parser.add_argument("--tick-rate", type=float, default=1.0)
    parser.add_argument(
        "--map-radius",
        type=int,
        default=512,
        metavar="BLOCKS",
        help="Live viewer map half-side in blocks around spawn (default 512)",
    )
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
    world_mode = args.world
    if args.import_world and not world_mode:
        world_mode = "import"
    ensure_minecraft(
        skip=args.no_docker,
        host=args.host,
        port=args.port,
        world_mode=world_mode,
        import_path=args.import_world,
        seed=args.seed,
    )
    print(f"\nViewer will be at http://{args.viewer_host}:{args.viewer_port}\n")
    launch_example(args)


if __name__ == "__main__":
    main()
