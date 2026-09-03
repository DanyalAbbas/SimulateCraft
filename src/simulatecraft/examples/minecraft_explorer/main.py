"""SimulateCraft — Minecraft LLM Explorer example.

Launches one or more LLM-driven bots into a Minecraft server. Each bot has a
distinct persona and long-term goal. All bots share the same server; they can
see and chat with each other in-game.

Quickest start — free LLM via OpenRouter
-----------------------------------------
    # 1. Get a free key at https://openrouter.ai/keys  (takes 30 seconds)
    export OPENROUTER_API_KEY=sk-or-...

    # 2. Run — auto-selects a free model (Llama 3.1 8B)
    python -m simulatecraft.examples.minecraft_explorer.main \\
        --host localhost --port 25565 --agents explorer builder

Pick a specific OpenRouter model (free or paid)
------------------------------------------------
    SIMULATECRAFT_MODEL="openrouter:meta-llama/llama-3.1-8b-instruct:free" ...
    SIMULATECRAFT_MODEL="openrouter:google/gemma-3-27b-it:free" ...
    SIMULATECRAFT_MODEL="openrouter:anthropic/claude-sonnet-4.6" ...
    # See full list at https://openrouter.ai/models?q=:free

Direct provider keys (if you have them)
-----------------------------------------
    SIMULATECRAFT_MODEL="anthropic:claude-sonnet-4-5" ...
    SIMULATECRAFT_MODEL="openai:gpt-4o-mini" ...

Offline — no key needed
------------------------
    python -m simulatecraft.examples.minecraft_explorer.main --host localhost
    # Uses pydantic-ai TestModel — canned responses, no network calls.

Live browser viewer
-------------------
    python -m simulatecraft.examples.minecraft_explorer.main \\
        --host localhost --agents explorer builder gatherer defender \\
        --serve --viewer-port 8000
    # open http://127.0.0.1:8000

Each bot uses a separate Mineflayer process and IPC port (25570, 25571, ...).
Prerequisites:
    Node.js >= 18   →  https://nodejs.org
    npm install     →  cd src/simulatecraft/minecraft/bot && npm install
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from simulatecraft.brains.llm import resolve_model
from simulatecraft.core import Agent, AgentActed, AgentState, BrainFailed, Runner, RunnerConfig
from simulatecraft.core.events import Event
from simulatecraft.minecraft import MinecraftEnvironment
from simulatecraft.viewers.log import JsonlLogger

from .agents import builder, defender, explorer, gatherer

log = logging.getLogger(__name__)


def _attach_progress(bus) -> None:
    """Print live tick/action lines so the terminal isn't silent."""

    def on_event(event: Event) -> None:
        if isinstance(event, AgentActed):
            print(
                f"[t{event.tick}] {event.agent_id} → {event.action_kind} "
                f"({event.decision_ms:.0f}ms)",
                flush=True,
            )
        elif isinstance(event, BrainFailed):
            print(f"[t{event.tick}] {event.agent_id} FAILED: {event.error}", flush=True)

    bus.subscribe(on_event)

# Map CLI name → (brain factory, in-game username, goal text)
AGENT_REGISTRY: dict[str, tuple] = {
    "explorer": (explorer, "Alex",  "explore as much of the world as possible"),
    "builder":  (builder,  "Bea",   "build a shelter before nightfall"),
    "gatherer": (gatherer, "Cole",  "collect wood, stone, and food"),
    "defender": (defender, "Dana",  "craft armour and keep teammates safe"),
}


def build(
    host: str,
    port: int,
    agent_names: list[str],
    model: str,
    tick_rate: float,
    max_ticks: int,
    mc_version: str | None = None,
) -> tuple[MinecraftEnvironment, Runner]:
    env = MinecraftEnvironment(
        server_host=host,
        server_port=port,
        version=mc_version,
        block_scan_radius=6,
        entity_scan_radius=16,
        chat_log_size=20,
    )
    runner = Runner(
        environment=env,
        config=RunnerConfig(
            tick_rate=tick_rate,
            max_ticks=max_ticks,
            decision_timeout=60.0,
            stop_when_env_empty=False,
        ),
    )

    for i, name in enumerate(agent_names):
        if name not in AGENT_REGISTRY:
            raise ValueError(
                f"Unknown agent '{name}'. Choose from: {', '.join(AGENT_REGISTRY)}"
            )
        factory, username, goal = AGENT_REGISTRY[name]
        ipc_port = 25570 + i
        env.add_bot(name, username=username, ipc_port=ipc_port, goal=goal)
        brain = factory(model)
        runner.add_agent(
            Agent(
                id=name,
                name=username,
                brain=brain,
                state=AgentState(data={"role": name}),
            )
        )
    return env, runner


async def run_headless(
    host: str,
    port: int,
    agent_names: list[str],
    model: str,
    tick_rate: float,
    max_ticks: int,
    log_file: str | None,
    mc_version: str | None = None,
) -> None:
    env, runner = build(
        host, port, agent_names, model, tick_rate, max_ticks, mc_version=mc_version
    )
    _attach_progress(runner.bus)
    if log_file:
        JsonlLogger(log_file, runner.bus)
        print(f"Event log → {log_file}")

    print(f"Connecting {len(agent_names)} bot(s) to {host}:{port}  [model: {model}]")
    async with env:
        print("All bots spawned. Starting simulation.")
        await runner.start()
    print(f"Simulation finished after {env.tick_count} tick(s).")


async def run_with_server(
    host: str,
    port: int,
    agent_names: list[str],
    model: str,
    tick_rate: float,
    max_ticks: int,
    viewer_host: str,
    viewer_port: int,
    log_file: str | None,
    mc_version: str | None = None,
) -> None:
    from simulatecraft.server import SimulationServer

    env, runner = build(
        host, port, agent_names, model, tick_rate, max_ticks, mc_version=mc_version
    )
    _attach_progress(runner.bus)
    if log_file:
        JsonlLogger(log_file, runner.bus)

    print(f"Connecting {len(agent_names)} bot(s) to {host}:{port}  [model: {model}]")
    async with env:
        server = SimulationServer(runner, host=viewer_host, port=viewer_port)
        print(
            f"Live viewer → http://{viewer_host}:{viewer_port}  "
            "(Ctrl-C to stop)"
        )
        await server.serve(run_simulation=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SimulateCraft — LLM agents in Minecraft",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Model string examples:\n"
            "  openrouter:meta-llama/llama-3.1-8b-instruct:free  (free, needs OPENROUTER_API_KEY)\n"
            "  openrouter:google/gemma-3-27b-it:free              (free, needs OPENROUTER_API_KEY)\n"
            "  openrouter:anthropic/claude-sonnet-4.6             (paid, needs OPENROUTER_API_KEY)\n"
            "  anthropic:claude-sonnet-4-5                        (needs ANTHROPIC_API_KEY)\n"
            "  openai:gpt-4o-mini                                 (needs OPENAI_API_KEY)\n"
            "  test                                               (offline, no key needed)\n"
            "\nFree OpenRouter models: https://openrouter.ai/models?q=:free"
        ),
    )
    parser.add_argument("--host", default="localhost", help="Minecraft server host")
    parser.add_argument("--port", type=int, default=25565, help="Minecraft server port")
    parser.add_argument(
        "--mc-version",
        default=None,
        help="Minecraft protocol version for Mineflayer (e.g. 1.21.4). "
        "Leave unset to auto-detect. Latest 26.x servers are not supported yet.",
    )
    parser.add_argument(
        "--agents",
        nargs="+",
        default=["explorer"],
        choices=list(AGENT_REGISTRY),
        metavar="AGENT",
        help=f"Agents to spawn: {', '.join(AGENT_REGISTRY)}",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "LLM model string. Overrides SIMULATECRAFT_MODEL env var. "
            "If unset, auto-selects a free OpenRouter model when OPENROUTER_API_KEY is set."
        ),
    )
    parser.add_argument("--ticks", type=int, default=200, help="Max simulation ticks")
    parser.add_argument("--tick-rate", type=float, default=1.0, help="Ticks per second")
    parser.add_argument("--serve", action="store_true", help="Launch browser viewer")
    parser.add_argument("--viewer-host", default="127.0.0.1")
    parser.add_argument("--viewer-port", type=int, default=8000)
    parser.add_argument("--log", default="events.jsonl", help="JSONL event log path")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    # --model flag wins; otherwise auto-resolve from env vars
    model = args.model or resolve_model()

    if args.serve:
        asyncio.run(
            run_with_server(
                args.host, args.port, args.agents, model,
                args.tick_rate, args.ticks,
                args.viewer_host, args.viewer_port,
                args.log,
                args.mc_version,
            )
        )
    else:
        asyncio.run(
            run_headless(
                args.host, args.port, args.agents, model,
                args.tick_rate, args.ticks,
                args.log,
                args.mc_version,
            )
        )


if __name__ == "__main__":
    main()
