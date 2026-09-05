# SimulateCraft

<p align="center">
  <img src="assets/cover.png" alt="SimulateCraft — LLM agents in Minecraft" width="100%" />
</p>

[![CI](https://github.com/DanyalAbbas/SimulateCraft/actions/workflows/ci.yml/badge.svg)](https://github.com/DanyalAbbas/SimulateCraft/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://danyalabbas.github.io/SimulateCraft/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

LLM-powered agents that play Minecraft. Spawn bots with goals and personas, watch them on a live map, and chat with them from your browser.

---

## Requirements

- Python **3.11+**
- Node.js **18+**
- Docker (optional — starts a local Minecraft **1.21.4** server)
- An LLM key: [Groq](https://console.groq.com/keys), [OpenRouter](https://openrouter.ai/keys), or [9Router](https://9router.com/)

---

## Quick start

1. Clone the repo and create a `.env` file (see [`.env.example`](.env.example)):

```bash
# Fast free tier — https://console.groq.com/keys
echo 'GROQ_API_KEY=gsk_your_key' > .env
```

2. Run:

```bash
chmod +x run.sh
./run.sh
```

3. Open the viewer at [http://127.0.0.1:8000](http://127.0.0.1:8000) and join `localhost` in Minecraft Java **1.21.4**.

Already have a Minecraft server?

```bash
./run.sh --no-docker --host localhost --port 25565
```

`./run.sh` installs Python/Node deps, starts Minecraft (unless `--no-docker`), and launches the agents + viewer.

---

## LLM setup

Put one of these in `.env`:

| Provider | What to set |
|---|---|
| **Groq** (recommended) | `GROQ_API_KEY=gsk_...` |
| **OpenRouter** | `OPENROUTER_API_KEY=sk-or-...` |
| **9Router** (local) | `OPENAI_BASE_URL=http://localhost:20128/v1`<br>`OPENAI_API_KEY=<dashboard-key>`<br>`SIMULATECRAFT_MODEL=oc/mimo-v2.5-free` |

Optional model override: `SIMULATECRAFT_MODEL=...`

Full details: [LLM providers](docs/llm-providers.md) · [Docs site](https://danyalabbas.github.io/SimulateCraft/)

---

## Docs & contributing

Tutorials (readable how-tos):

- [First run](docs/getting-started.md)
- [Connect an LLM](docs/llm-providers.md)
- [Use the live viewer](docs/viewer.md)
- [How it works](docs/how-it-works.md)
- [Contributing](docs/contributing.md)

Published site: [danyalabbas.github.io/SimulateCraft](https://danyalabbas.github.io/SimulateCraft/)

```bash
uv sync --extra llm --extra dev
uv run pytest
```

## License

[MIT](LICENSE)
