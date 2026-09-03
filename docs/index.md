# SimulateCraft

**LLM agents that play Minecraft.**

Drop one or more LLM-powered bots into a Java Edition server. Each bot gets a
persona, long-term memory, a goal, typed actions, and a live map in your browser.

## Browse the docs

| Section | What’s inside |
|---|---|
| **[Guides](guides/index.md)** | Installation, quickstart, architecture, actions, memory, viewer |
| **[API reference](reference/)** | Auto-generated docs for every Python module |

```bash
echo 'GROQ_API_KEY=gsk_your_key' > .env
./run.sh
# viewer → http://127.0.0.1:8000
# docs  → https://danyalabbas.github.io/SimulateCraft/
```

!!! tip "Docs auto-update"
    The **API reference** tab is rebuilt from live docstrings on every
    `mkdocs build`. Change docstrings under `src/simulatecraft/` — do not
    hand-edit generated pages under `reference/`.
