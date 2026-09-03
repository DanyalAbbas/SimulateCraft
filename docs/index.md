# SimulateCraft documentation

**LLM-driven AI agent simulations in Minecraft.**

SimulateCraft drops LLM-powered bots into a Minecraft server. Each bot gets a persona, long-term memory, planning, typed actions, and a live browser map so you can watch them think and act.

## What you can do here

- [Getting started](getting-started.md) — install, `.env`, `./run.sh`
- [Architecture](architecture.md) — runner, bridge, Mineflayer, EventBus
- [Live viewer](viewer.md) — the cartography UI at `:8000`
- [API reference](reference/) — **auto-generated** from every Python module

!!! tip "Docs stay in sync"
    The API reference is rebuilt from live source on every `mkdocs build` /
    `mkdocs serve`. Edit module docstrings under `src/simulatecraft/` — do not
    hand-edit pages under `reference/`.

```bash
uv sync --extra docs
DISABLE_MKDOCS_2_WARNING=true uv run mkdocs serve
# docs usually open at http://127.0.0.1:8000 (next free port if the viewer is up)
```
