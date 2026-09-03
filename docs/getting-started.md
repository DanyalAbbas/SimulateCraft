# Getting started

## Requirements

- Python ≥ 3.11
- Node.js ≥ 18
- Docker (optional — ships a local Minecraft **1.21.4** server)
- A free [Groq](https://console.groq.com/keys) or [OpenRouter](https://openrouter.ai/keys) API key

## Two-command run

```bash
echo 'GROQ_API_KEY=gsk_your_key' > .env
chmod +x run.sh && ./run.sh
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000). Join `localhost` in
Minecraft Java **1.21.4** to see the bot in-world.

Already have a server?

```bash
./run.sh --no-docker --host localhost --port 25565
```

## Development install

```bash
uv sync --extra llm --extra dev --extra docs
uv run pytest
DISABLE_MKDOCS_2_WARNING=true uv run mkdocs serve
```

## CLI

```bash
uv run simulatecraft --help
```

## Quick Python example

```python
import asyncio
from simulatecraft import Agent, Runner, RunnerConfig
from simulatecraft.brains.llm import LLMBrain, resolve_model
from simulatecraft.minecraft import MinecraftEnvironment, ALL_ACTIONS

env = MinecraftEnvironment(server_host="localhost", server_port=25565)
env.add_bot("bot1", username="MyBot", goal="collect 64 logs of wood")

brain = LLMBrain(
    action_types=ALL_ACTIONS,
    persona="A diligent Minecraft worker.",
    model=resolve_model(),
)

runner = Runner(environment=env, config=RunnerConfig(tick_rate=1.0, max_ticks=300))
runner.add_agent(Agent(id="bot1", name="MyBot", brain=brain))

async def main():
    async with env:
        await runner.start()

asyncio.run(main())
```

See [Architecture](architecture.md) for how the pieces connect, and the
[API reference](reference/) for every module.
