<p align="center">
  <img src="assets/cover.png" alt="SimulateCraft — LLM agents in Minecraft" width="100%" />
</p>

<p align="center">
  <a href="https://github.com/DanyalAbbas/SimulateCraft/actions/workflows/ci.yml">
    <img src="https://github.com/DanyalAbbas/SimulateCraft/actions/workflows/ci.yml/badge.svg" alt="CI" />
  </a>
  <a href="https://danyalabbas.github.io/SimulateCraft/">
    <img src="https://img.shields.io/badge/docs-GitHub%20Pages-blue" alt="Docs" />
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" />
  </a>
</p>

LLM-powered agents that play Minecraft. Spawn bots with goals and personas, watch them on a live map, and chat with them from your browser.

---

## Requirements

- Python **3.11+**
- Node.js **18+**
- Docker Desktop (optional — starts a local Minecraft **1.21.4** server)
- An LLM key: [Groq](https://console.groq.com/keys), [OpenRouter](https://openrouter.ai/keys), or [9Router](https://9router.com/)

---

## Quick start

### 1. Clone and add a key

```text
git clone https://github.com/DanyalAbbas/SimulateCraft.git
cd SimulateCraft
```

Copy `.env.example` to `.env` and set a key:

```text
GROQ_API_KEY=gsk_your_key
```

Get a free key at [console.groq.com/keys](https://console.groq.com/keys).

### 2. Run (one command)

**Windows** (PowerShell or double-click `run.cmd`):

```powershell
.\run.ps1
```

**macOS / Linux:**

```bash
chmod +x run.sh
./run.sh
```

### 3. Open and play

1. Viewer → [http://127.0.0.1:8000](http://127.0.0.1:8000)
2. Minecraft Java **1.21.4** → Multiplayer → `localhost`

Already have a Minecraft server?

```powershell
# Windows
.\run.ps1 --no-docker --host localhost --port 25565

# macOS / Linux
./run.sh --no-docker --host localhost --port 25565
```

The launcher installs Python packages (`uv`), Mineflayer (`npm`), starts Minecraft via Docker (unless `--no-docker`), then opens the agents + viewer.

If PowerShell blocks scripts, double-click **`run.cmd`** instead, or run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

---

## LLM setup

Put one of these in `.env`:

| Provider | What to set |
|---|---|
| **Groq** (recommended) | `GROQ_API_KEY=gsk_...` |
| **OpenRouter** | `OPENROUTER_API_KEY=sk-or-...` |
| **9Router** (local) | `OPENAI_BASE_URL=http://localhost:20128/v1`<br>`OPENAI_API_KEY=<dashboard-key>`<br>`SIMULATECRAFT_MODEL=oc/mimo-v2.5-free` |

Optional: `SIMULATECRAFT_MODEL=...`

More detail: [Connect an LLM](docs/llm-providers.md) · [Docs site](https://danyalabbas.github.io/SimulateCraft/)

---

## Docs

- [First run](docs/getting-started.md)
- [Connect an LLM](docs/llm-providers.md)
- [Use the live viewer](docs/viewer.md)
- [How it works](docs/how-it-works.md)
- [Contributing](docs/contributing.md)

## License

[MIT](LICENSE)


<p align="center">
  Created and Managed by:
<p align="center">
	<a href="https://github.com/DanyalAbbas"><img src="https://img.shields.io/badge/-Danyal%20Abbas-black%20?style=flat&logo=github&logoColor=white"/></a>
