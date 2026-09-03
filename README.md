# SimulateCraft

**LLM-driven AI agent simulations in Minecraft.**

Drop one or more LLM-powered bots into any Minecraft server. Each bot has a persona, long-term memory, a goal, and a full set of typed actions — movement, mining, building, crafting, navigation, and chat. Watch them think and act live in your browser.

```
┌─────────────────────────────────────────────────────────────────┐
│                        SimulateCraft                            │
│                                                                 │
│  LLMBrain ──decide()──► MinecraftEnvironment                    │
│  (pydantic-ai)            │                                     │
│  + MemoryStream           │  MinecraftBridge (TCP/JSON-RPC)     │
│  + Retriever              │       │                             │
│  + ReflectionEngine       │       ▼                             │
│  + Planner                │   bot.js (Mineflayer / Node.js)     │
│  + SkillRegistry          │       │                             │
│                           │       ▼                             │
│  Runner (async loop) ◄────┘  Minecraft Server                   │
│      │                                                          │
│      ▼ EventBus                                                 │
│  JSONL logger · FastAPI websocket viewer                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Run it (two commands)

You need **Node.js 18+** and **Docker** installed once on the machine. After that:

```bash
# 1. Free Groq key → https://console.groq.com/keys  (no credit card)
echo 'GROQ_API_KEY=gsk_your_key' > .env

# 2. Install everything, start Minecraft 1.21.4, launch the bot + viewer
chmod +x run.sh
./run.sh
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000). Join `localhost` in Minecraft Java **1.21.4** to see the bot in-world.

`./run.sh` does all of this for you:
- installs Python packages (`uv`)
- installs the Mineflayer bot (`npm`)
- starts a local offline Minecraft server (Docker)
- waits until the world is ready
- runs the explorer agent and the web viewer

Already have your own server? `./run.sh --no-docker --host localhost --port 25565`

---

## LLM access — free options

SimulateCraft auto-selects the best available free provider in this order:
**Groq** → **OpenRouter** → offline TestModel. No credit card required for either free tier.

### Option 1 — Groq ⚡ (fastest, recommended)

[Groq](https://console.groq.com) runs Llama and other open models at extremely low latency (often 500+ tokens/sec). Free tier, no credit card.

```bash
# 1. Get a free key at https://console.groq.com/keys
export GROQ_API_KEY=gsk_...

# 2. Run — auto-selects openai/gpt-oss-120b
python -m simulatecraft.examples.minecraft_explorer.main --host localhost
```

| Model string | Notes |
|---|---|
| `groq:openai/gpt-oss-120b` | GPT-OSS 120B — **free**, Groq's current default |
| `groq:openai/gpt-oss-20b` | GPT-OSS 20B — **free**, faster |
| `groq:qwen/qwen3.6-27b` | Qwen 3.6 27B — **free**, strong reasoning |

Full list: [console.groq.com/docs/models](https://console.groq.com/docs/models)

```bash
SIMULATECRAFT_MODEL="groq:openai/gpt-oss-20b" \
python -m simulatecraft.examples.minecraft_explorer.main --host localhost
```

### Option 2 — OpenRouter (many models, including free tier)

[OpenRouter](https://openrouter.ai) routes to dozens of providers through one key. Has free-tier models with rate limits.

```bash
# 1. Get a free key at https://openrouter.ai/keys
export OPENROUTER_API_KEY=sk-or-...

# 2. Run — auto-selects meta-llama/llama-3.1-8b-instruct:free
python -m simulatecraft.examples.minecraft_explorer.main --host localhost
```

| Model string | Notes |
|---|---|
| `openrouter:meta-llama/llama-3.1-8b-instruct:free` | Llama 3.1 8B — **free** (auto-selected) |
| `openrouter:google/gemma-3-27b-it:free` | Gemma 27B — **free** |
| `openrouter:mistralai/mistral-7b-instruct:free` | Mistral 7B — **free** |
| `openrouter:anthropic/claude-sonnet-4.6` | Claude Sonnet — paid, best quality |

Browse all free models: [openrouter.ai/models?q=:free](https://openrouter.ai/models?q=:free)

### Direct provider keys (if you have them)

```bash
export SIMULATECRAFT_MODEL="anthropic:claude-sonnet-4-5"   # needs ANTHROPIC_API_KEY
export SIMULATECRAFT_MODEL="openai:gpt-4o-mini"            # needs OPENAI_API_KEY
export SIMULATECRAFT_MODEL="google-gla:gemini-2.0-flash"   # needs GOOGLE_API_KEY
```

### Offline — no key at all

Omit all keys and SimulateCraft falls back to pydantic-ai's `TestModel` (canned deterministic responses, zero network calls). Good for testing the wiring.

---

## 5-minute quickstart

Start a Minecraft server (any vanilla 1.20+ server on `localhost:25565`), then:

```bash
# Single explorer bot (auto-picks free OpenRouter model if OPENROUTER_API_KEY is set)
python -m simulatecraft.examples.minecraft_explorer.main \
    --host localhost --port 25565 --agents explorer

# Four-agent team with live browser viewer
python -m simulatecraft.examples.minecraft_explorer.main \
    --host localhost --port 25565 \
    --agents explorer builder gatherer defender \
    --serve --viewer-port 8000
# open http://127.0.0.1:8000
```

Available agents: `explorer` · `builder` · `gatherer` · `defender`

---

## Architecture

### Connection layer

Python spawns a **Node.js Mineflayer process** (`minecraft/bot/bot.js`) per bot.
The two sides communicate over a local TCP socket using newline-delimited JSON-RPC:

```
Python LLMBrain
    → MinecraftEnvironment.step(action)
        → MinecraftBridge.call("perform_action", action=...)   [TCP JSON-RPC]
            → bot.js executes the action via Mineflayer API
            ← {"id": "...", "result": {"ok": true}}
```

Push events (chat, death, health changes) flow the other way without polling.

### Actions

Every action the LLM can emit is a strict Pydantic model with a `kind` discriminator.
`LLMBrain` receives the full union as its `output_type`, so the model's choice arrives
already validated — no JSON parsing, no regex.

| Category | Actions |
|---|---|
| Movement | `Move`, `Jump`, `Sneak`, `LookAt` |
| World | `MineBlock`, `PlaceBlock`, `UseItem`, `ActivateBlock` |
| Inventory | `EquipItem`, `DropItem`, `Craft` |
| Social | `Chat`, `Whisper` |
| Navigation | `NavigateTo`, `FollowEntity` |
| Meta | `Wait` |

### Observations

Each tick the environment fetches a `MinecraftObservation` from the bot:

- **Position**, yaw, pitch, biome
- **Stats**: health, food, XP, game mode, time of day, weather
- **Inventory** with item names and counts
- **Nearby blocks** within configurable radius
- **Nearby entities** (mobs, players) with distances
- **Craftable items** right now
- **Chat log** (rolling window)
- **Current goal** (injected by the environment)

`MinecraftObservation.render()` produces a compact, token-efficient text summary
that goes straight into the LLM prompt.

### Memory & cognition

Each agent brain has:

- **MemoryStream** — append-only log of observations, action results, chat, and reflections, each with an importance score (1–10).
- **Retriever** — Generative-Agents-style retrieval: scores memories by recency × importance × embedding similarity to the current observation, returns top-k.
- **ReflectionEngine** — every N ticks, distills the last 50 memories into high-level insights and stores them back with importance=9.
- **Planner** — holds the agent's current `Plan` (goal + ordered steps); can request a replan when the situation changes.
- **SkillRegistry** — Voyager-style store of verified action sequences; the brain replays a matching skill before paying for an LLM call.

---

## Build your own simulation

### Minimal single-bot setup

```python
import asyncio
from simulatecraft import Agent, Runner, RunnerConfig
from simulatecraft.brains.llm import LLMBrain, LLMBrainConfig, resolve_model
from simulatecraft.minecraft import MinecraftEnvironment, ALL_ACTIONS

env = MinecraftEnvironment(server_host="localhost", server_port=25565)
env.add_bot("bot1", username="MyBot", goal="collect 64 logs of wood")

brain = LLMBrain(
    action_types=ALL_ACTIONS,
    persona="A diligent Minecraft worker who focuses on resource gathering.",
    # Uses SIMULATECRAFT_MODEL env var, or auto-picks free OpenRouter model,
    # or falls back to TestModel if no keys are set.
    model=resolve_model(),
)

runner = Runner(
    environment=env,
    config=RunnerConfig(tick_rate=1.0, max_ticks=300),
)
runner.add_agent(Agent(id="bot1", name="MyBot", brain=brain))

async def main():
    async with env:
        await runner.start()

asyncio.run(main())
```

### Multi-agent setup

```python
env = MinecraftEnvironment(server_host="localhost", server_port=25565)

# Each bot gets its own IPC port (auto-assigned) and Mineflayer process
env.add_bot("alex", username="Alex", goal="build a house")
env.add_bot("bob",  username="Bob",  goal="mine iron ore")

runner = Runner(environment=env, config=RunnerConfig(tick_rate=1.0))
runner.add_agent(Agent(id="alex", brain=LLMBrain(action_types=ALL_ACTIONS,
    persona="A builder.", model="openai:gpt-4o-mini")))
runner.add_agent(Agent(id="bob",  brain=LLMBrain(action_types=ALL_ACTIONS,
    persona="A miner.", model="openai:gpt-4o-mini")))
```

### Custom action set

```python
from typing import Literal
from simulatecraft import Action
from simulatecraft.brains.llm import LLMBrain

class PlantCrops(Action):
    kind: Literal["plant_crops"] = "plant_crops"
    crop: str = "wheat"
    count: int = 9

brain = LLMBrain(
    action_types=[PlantCrops, ...],   # only give the LLM what it needs
    persona="A Minecraft farmer.",
    model="openai:gpt-4o-mini",
)
```

### Live browser viewer

```python
from simulatecraft.server import SimulationServer

server = SimulationServer(runner, host="127.0.0.1", port=8000)
await server.serve(run_simulation=True)
# open http://127.0.0.1:8000
```

### Event log & replay

```python
from simulatecraft.viewers.log import JsonlLogger, Replayer
from simulatecraft.core import EventBus

JsonlLogger("events.jsonl", runner.bus)   # record

# replay later at 4× speed
bus = EventBus()
bus.subscribe(lambda e: print(e.kind, e.model_dump()))
import asyncio
asyncio.run(Replayer("events.jsonl").replay(bus, speed=4.0))
```

---

## HTTP / WebSocket API (when --serve)

| Endpoint | Purpose |
|---|---|
| `GET /api/state` | Full snapshot + runner status |
| `POST /api/control/{pause,resume,step,stop,reset}` | Control the simulation |
| `POST /api/chat?text=...&target=...` | Send a message to an agent |
| `WS /ws` | Stream every event live; send `{"type":"chat",...}` / `{"type":"control",...}` |

---

## Requirements

- Python ≥ 3.11
- Node.js ≥ 18 (for the Mineflayer bot)
- A running Minecraft Java Edition server (1.18+)
- An LLM API key (optional — `model="test"` works offline)

---

## Development

```bash
uv sync --extra llm --extra dev --extra docs
uv run pytest
uv run ruff check src tests && uv run ruff format src tests
uv run mypy src/simulatecraft
```

### Documentation (auto-updates from source)

API docs for **every module** are generated on each MkDocs build from live
docstrings under `src/simulatecraft/` — edit the code, not hand-written
reference pages.

```bash
uv sync --extra docs
DISABLE_MKDOCS_2_WARNING=true uv run mkdocs serve
DISABLE_MKDOCS_2_WARNING=true uv run mkdocs build   # writes ./site
```

Guide pages live in `docs/`; the `reference/` tree is produced by
`docs/gen_ref_pages.py` via `mkdocs-gen-files`.

Published docs (from `main`): [https://danyalabbas.github.io/SimulateAI/](https://danyalabbas.github.io/SimulateAI/)

### CI / CD

| Workflow | Trigger | What it does |
|---|---|---|
| **CI** | push/PR → `main`, `staging` | Ruff, pytest (3.11–3.13), mypy, MkDocs build |
| **Deploy docs** | push → `main` | Builds docs and deploys to **GitHub Pages** |
| **Staging** | push → `staging` | Full validate + uploads a docs site artifact (14 days) |

One-time GitHub setup for public docs:

1. Repo **Settings → Pages → Build and deployment → Source: GitHub Actions**
2. Merge/push to `main` so **Deploy docs** can run
3. Open [https://danyalabbas.github.io/SimulateAI/](https://danyalabbas.github.io/SimulateAI/)

Use `staging` for integration; promote to `main` when ready to publish.

---

## License

MIT
