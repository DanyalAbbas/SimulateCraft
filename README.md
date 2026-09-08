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

Install these **before** the one-liner:

- **Git**
- **Node.js 18+**
- **Docker Desktop** (optional — starts a local Minecraft **1.21.4** server)
- An LLM provider: [OpenRouter](https://openrouter.ai/keys), [9Router](https://9router.com/), or your own OpenAI-compatible API

`uv` is installed automatically. Prefer OpenRouter / 9Router / your own API — Groq rate-limits quickly under agent load.

---

## Quick start

### One-line install

**Windows** (PowerShell) — needs Git + Node 18+ already installed:

```powershell
irm https://raw.githubusercontent.com/DanyalAbbas/SimulateCraft/main/install.ps1 | iex
```

If raw.githubusercontent.com returns 503:

```powershell
irm https://cdn.jsdelivr.net/gh/DanyalAbbas/SimulateCraft@main/install.ps1 | iex
```

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/DanyalAbbas/SimulateCraft/main/install.sh | bash
```

The installer clones into `~/SimulateCraft`, creates `.env`, and **stops with next steps** until you set a non-empty LLM key. Then:

```powershell
# Windows
cd ~/SimulateCraft
# edit .env — set OPENROUTER_API_KEY=...
.\run.ps1
```

```bash
# macOS / Linux
cd ~/SimulateCraft
# edit .env — set OPENROUTER_API_KEY=...
./run.sh
```

Optional: pass a key in the same shell so install can launch immediately:

```powershell
$env:OPENROUTER_API_KEY = "sk-or-..."
irm https://raw.githubusercontent.com/DanyalAbbas/SimulateCraft/main/install.ps1 | iex
```

```bash
OPENROUTER_API_KEY=sk-or-... curl -fsSL https://raw.githubusercontent.com/DanyalAbbas/SimulateCraft/main/install.sh | bash
```

### Manual install

```text
git clone https://github.com/DanyalAbbas/SimulateCraft.git
cd SimulateCraft
cp .env.example .env   # Windows: copy in File Explorer
```

Set in `.env`:

```text
OPENROUTER_API_KEY=sk-or-your_key
```

Or 9Router / your own API via `OPENAI_BASE_URL` + `OPENAI_API_KEY` + `SIMULATECRAFT_MODEL`. See [Connect an LLM](docs/llm-providers.md).

**Windows** (PowerShell or double-click `run.cmd`):

```powershell
.\run.ps1
```

**macOS / Linux:**

```bash
chmod +x run.sh
./run.sh
```

### Open and play

1. Viewer → [http://127.0.0.1:8000](http://127.0.0.1:8000)
2. Minecraft Java **1.21.4** → Multiplayer → `localhost`

Already have a Minecraft server?

```powershell
# Windows
.\run.ps1 --no-docker --host localhost --port 25565

# macOS / Linux
./run.sh --no-docker --host localhost --port 25565
```

If PowerShell blocks scripts, double-click **`run.cmd`**, or run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

---

## LLM setup

| Provider | What to set |
|---|---|
| **OpenRouter** | `OPENROUTER_API_KEY=sk-or-...` |
| **9Router** (local) | `OPENAI_BASE_URL=http://localhost:20128/v1`<br>`OPENAI_API_KEY=<dashboard-key>`<br>`SIMULATECRAFT_MODEL=oc/mimo-v2.5-free` |
| **Own API** | `OPENAI_BASE_URL=...`<br>`OPENAI_API_KEY=...`<br>`SIMULATECRAFT_MODEL=...` |
| **Groq** (rate-limited) | `GROQ_API_KEY=gsk_...` |

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
