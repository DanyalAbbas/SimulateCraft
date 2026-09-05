# Getting started

## Requirements

- Python ≥ 3.11
- Node.js ≥ 18
- Docker (optional — ships a local Minecraft **1.21.4** server)
- An LLM path: [Groq](https://console.groq.com/keys), [OpenRouter](https://openrouter.ai/keys),
  or a local [9Router](https://9router.com/) gateway — see [LLM providers](llm-providers.md)

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

### Other providers (quick)

```bash
# OpenRouter
cat > .env <<'EOF'
OPENROUTER_API_KEY=sk-or-v1-...
EOF

# 9Router (gateway must already be running)
cat > .env <<'EOF'
OPENAI_BASE_URL=http://localhost:20128/v1
OPENAI_API_KEY=your-9router-dashboard-key
SIMULATECRAFT_MODEL=oc/mimo-v2.5-free
EOF
```

Details and troubleshooting: **[LLM providers](llm-providers.md)**.

## Development install

```bash
uv sync --extra llm --extra dev --extra docs
uv run pytest
DISABLE_MKDOCS_2_WARNING=true uv run mkdocs serve
```

Prefer not to pull the embeddings/Torch stack — use `--extra llm` rather than
`--all-extras`.

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

Next: [Architecture](architecture.md) · [Live viewer](viewer.md) · [API reference](reference/)
