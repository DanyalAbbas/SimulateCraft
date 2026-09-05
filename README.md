# SimulateCraft

[![CI](https://github.com/DanyalAbbas/SimulateCraft/actions/workflows/ci.yml/badge.svg)](https://github.com/DanyalAbbas/SimulateCraft/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://danyalabbas.github.io/SimulateCraft/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**LLM-driven AI agents that live in Minecraft.**

Drop bots into a Java Edition server. Each agent has a persona, memory, a goal,
and typed actions (move, mine, craft, chat…). Watch them think and act in a live
browser map — or drive everything from Python.

**Docs:** [danyalabbas.github.io/SimulateCraft](https://danyalabbas.github.io/SimulateCraft/)  
**LLM setup:** [OpenRouter & 9Router guide](https://danyalabbas.github.io/SimulateCraft/llm-providers/)

---

## Features

- **Mineflayer bots** — one Node process per agent, JSON-RPC bridge from Python
- **Typed actions** — pydantic models the LLM must emit (no fragile JSON scraping)
- **Memory & planning** — stream, retrieval, reflection, skills (Voyager-style)
- **Live viewer** — map, spawn agents, chat, pause / step / tick-speed controls
- **Provider flexibility** — Groq, OpenRouter, 9Router, Anthropic, OpenAI, offline test

```
LLMBrain ──decide()──► MinecraftEnvironment
(pydantic-ai)            │
+ Memory / Planner       │  TCP JSON-RPC
+ Skills                 ▼
Runner ◄──────────── bot.js (Mineflayer)
   │
   ▼ EventBus → JSONL log · FastAPI viewer
```

---

## Quick start

**Needs:** Python ≥ 3.11, Node.js ≥ 18, Docker (optional local MC 1.21.4), and an
LLM key ([Groq](https://console.groq.com/keys), [OpenRouter](https://openrouter.ai/keys),
or [9Router](https://9router.com/)).

```bash
# Free Groq key (fast) — or see docs for OpenRouter / 9Router
echo 'GROQ_API_KEY=gsk_your_key' > .env

chmod +x run.sh
./run.sh
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Join `localhost` in Minecraft
Java **1.21.4**.

Own server already running?

```bash
./run.sh --no-docker --host localhost --port 25565
```

---

## LLM providers

| Provider | Env | Notes |
|---|---|---|
| **Groq** | `GROQ_API_KEY` | Fast free tier — default when set |
| **OpenRouter** | `OPENROUTER_API_KEY` | Many models, free `:free` ids |
| **9Router** | `OPENAI_BASE_URL` + `OPENAI_API_KEY` + `SIMULATECRAFT_MODEL` | Local OpenAI-compatible gateway |
| **Offline** | `SIMULATECRAFT_MODEL=test` | No network (CI / wiring) |

```bash
# OpenRouter
OPENROUTER_API_KEY=sk-or-...
SIMULATECRAFT_MODEL=openrouter:meta-llama/llama-3.1-8b-instruct:free

# 9Router (local)
OPENAI_BASE_URL=http://localhost:20128/v1
OPENAI_API_KEY=<dashboard-key>
SIMULATECRAFT_MODEL=oc/mimo-v2.5-free
```

Full walkthrough: **[LLM providers](docs/llm-providers.md)** (OpenRouter + 9Router).

---

## Install (library)

```bash
uv sync --extra llm --extra dev
# or: pip install -e '.[llm]'
```

```python
import asyncio
from simulatecraft import Agent, Runner, RunnerConfig
from simulatecraft.brains.llm import LLMBrain, resolve_model
from simulatecraft.minecraft import MinecraftEnvironment, ALL_ACTIONS

env = MinecraftEnvironment(server_host="localhost", server_port=25565)
env.add_bot("bot1", username="MyBot", goal="collect 64 logs")

brain = LLMBrain(
    action_types=ALL_ACTIONS,
    persona="A careful gatherer who narrates in chat.",
    model=resolve_model(),
)
runner = Runner(environment=env, config=RunnerConfig(tick_rate=1.0, max_ticks=300))
runner.add_agent(Agent(id="bot1", name="MyBot", brain=brain))

async def main():
    async with env:
        await runner.start()

asyncio.run(main())
```

Multi-agent example and CLI: `python -m simulatecraft.examples.minecraft_explorer.main --help`

---

## Live viewer

With `--serve` (or `./run.sh`), the UI exposes:

- Full-bleed map (pan / zoom / follow)
- Spawn agents (persona, spawn pin)
- Watcher roles for **human** Minecraft accounts (OP / spectator via RCON)
- Chat & events, tick speed, step ×1 / ×10

API sketch:

| Endpoint | Purpose |
|---|---|
| `GET /api/state` | Snapshot + status (`tick`, `tick_rate`, `max_ticks`) |
| `POST /api/control/{command}` | `pause` / `resume` / `step` / `faster` / `slower` / … |
| `POST /api/agents` | Spawn a bot at runtime |
| `WS /ws` | Live events + control / chat / map tiles |

Details: [Live viewer docs](docs/viewer.md).

---

## Documentation

| Guide | |
|---|---|
| [Getting started](docs/getting-started.md) | Install & first run |
| [LLM providers](docs/llm-providers.md) | Groq, OpenRouter, 9Router |
| [Architecture](docs/architecture.md) | Runner, bridge, cognition |
| [Live viewer](docs/viewer.md) | UI & WebSocket protocol |
| [Contributing](docs/contributing.md) | Dev setup & PR tips |
| [API reference](https://danyalabbas.github.io/SimulateCraft/reference/) | Auto-generated from source |

```bash
uv sync --extra docs
DISABLE_MKDOCS_2_WARNING=true uv run mkdocs serve
```

---

## Development

```bash
uv sync --extra llm --extra dev --extra docs
uv run ruff check src tests && uv run ruff format src tests
uv run pytest
uv run mypy src/simulatecraft
```

| Workflow | Branch | Role |
|---|---|---|
| **CI** | `main`, `staging` | Ruff, pytest, mypy, docs build |
| **Deploy docs** | `main` | GitHub Pages |
| **Staging** | `staging` | Validate + docs artifact |

---

## Project layout

```
src/simulatecraft/
  core/          Runner, EventBus, schemas
  brains/        LLMBrain (pydantic-ai)
  minecraft/     Environment, bridge, bot.js
  memory/        Stream, retrieval, reflection
  server/        FastAPI viewer + static UI
  examples/      Ready-made explorer team
```

---

## Contributing

See [CONTRIBUTING](docs/contributing.md). Issues and PRs welcome.

## License

[MIT](LICENSE)
