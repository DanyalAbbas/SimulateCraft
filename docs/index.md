# SimulateCraft

**LLM agents that play Minecraft.**

Drop bots into a Java Edition server. Each agent gets a persona, memory, a goal,
typed actions, and a live map in your browser.

## Guides

| Page | What it covers |
|---|---|
| [Getting started](getting-started.md) | Install, `.env`, `./run.sh` |
| [LLM providers](llm-providers.md) | **Groq, OpenRouter, 9Router**, and more |
| [Architecture](architecture.md) | Runner, Mineflayer bridge, EventBus |
| [Live viewer](viewer.md) | Map UI, controls, WebSocket protocol |
| [Contributing](contributing.md) | Dev setup, tests, PRs |
| [API reference](reference/) | Every Python module (auto-generated) |

```bash
echo 'GROQ_API_KEY=gsk_your_key' > .env
./run.sh
# viewer → http://127.0.0.1:8000
```

!!! tip "OpenRouter or 9Router?"
    Prefer **[LLM providers](llm-providers.md)** for copy-paste `.env` setups —
    OpenRouter free models, or a local 9Router gateway at `localhost:20128/v1`.

!!! tip "Live viewer"
    Use **Add agent** to spawn bots with a custom persona and map spawn pin.
    **Watcher roles** apply OP / spectator to *your* Minecraft username (not agents).

!!! tip "API docs stay in sync"
    The **API reference** is rebuilt from live docstrings on every `mkdocs build`.
    Edit code under `src/simulatecraft/` — don’t hand-edit generated pages.
