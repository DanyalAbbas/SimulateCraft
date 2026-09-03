# Installation

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

The console script wires Docker (optional), the Mineflayer bot, the explorer
agent, and the FastAPI viewer.
