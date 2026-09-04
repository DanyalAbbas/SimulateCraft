# SimulateCraft

**LLM agents that play Minecraft.**

Drop one or more LLM-powered bots into a Java Edition server. Each bot gets a
persona, long-term memory, a goal, typed actions, and a live map in your browser.

## In this docs site

| Page | What it covers |
|---|---|
| [Getting started](getting-started.md) | Install, `.env`, `./run.sh` |
| [Architecture](architecture.md) | Runner, Mineflayer bridge, EventBus |
| [Live viewer](viewer.md) | Map UI and WebSocket controls |
| [API reference](reference/) | Every Python module (auto-generated) |

```bash
echo 'GROQ_API_KEY=gsk_your_key' > .env
./run.sh
# viewer → http://127.0.0.1:8000
```

!!! tip "Live viewer workshop"
    Open the viewer and use **Add agent** to spawn bots with a custom system
    prompt, map spawn pin, OP, and spectator mode — no CLI restart needed.

!!! tip "API docs stay in sync"
    The **API reference** section is rebuilt from live docstrings on every
    `mkdocs build`. Edit code under `src/simulatecraft/` — don’t hand-edit
    generated pages.
