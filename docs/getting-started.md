# First run

Get SimulateCraft running end-to-end. Most users are on **Windows** — use the PowerShell one-liner or `run.ps1` / `run.cmd`. macOS and Linux use the curl one-liner or `run.sh`.

## What you need (before the one-liner)

Install these yourself first — the installer will not install them for you:

| Tool | Why | Where |
|---|---|---|
| **Git** | Clones the repo | [git-scm.com](https://git-scm.com/) |
| **Node.js 18+** | Mineflayer bots | [nodejs.org](https://nodejs.org) |
| **Docker Desktop** | Bundled Minecraft **1.21.4** (optional if you pass `--no-docker`) | [docker.com](https://www.docker.com/products/docker-desktop/) |
| **LLM provider** | Agent brains | [OpenRouter](https://openrouter.ai/keys), [9Router](https://9router.com/), or your own OpenAI-compatible API |

`uv` (Python runner) is installed automatically if missing.

Prefer **OpenRouter**, **9Router**, or your own API. Groq works for a smoke test but rate-limits quickly under agent load.

## Fastest path — one command

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/DanyalAbbas/SimulateCraft/main/install.ps1 | iex
```

If that URL fails (occasional raw.githubusercontent.com 503):

```powershell
irm https://cdn.jsdelivr.net/gh/DanyalAbbas/SimulateCraft@main/install.ps1 | iex
```

If PowerShell blocks scripts later, use `run.cmd`, or once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/DanyalAbbas/SimulateCraft/main/install.sh | bash
```

### What the installer does

1. Checks for Git + Node 18+
2. Installs `uv` if needed
3. Clones into `~/SimulateCraft` (or `%USERPROFILE%\SimulateCraft` on Windows)
4. Creates `.env` from `.env.example`
5. **Stops with next steps** if no LLM key is set yet (blank `OPENROUTER_API_KEY=` does not count)
6. Otherwise launches `run.ps1` / `run.sh`

Optional: set a key in the same shell before installing:

```powershell
# Windows
$env:OPENROUTER_API_KEY = "sk-or-..."
irm https://raw.githubusercontent.com/DanyalAbbas/SimulateCraft/main/install.ps1 | iex
```

```bash
# macOS / Linux
OPENROUTER_API_KEY=sk-or-... curl -fsSL https://raw.githubusercontent.com/DanyalAbbas/SimulateCraft/main/install.sh | bash
```

Clone only (no launch): `SIMULATECRAFT_SKIP_RUN=1` (Unix) or `$env:SIMULATECRAFT_SKIP_RUN = "1"` (Windows).

## Manual install

### 1. Clone

```text
git clone https://github.com/DanyalAbbas/SimulateCraft.git
cd SimulateCraft
```

### 2. Add an LLM provider

Copy `.env.example` to `.env` and set one of:

```text
OPENROUTER_API_KEY=sk-or-...
```

or for 9Router / your own API:

```text
OPENAI_BASE_URL=http://localhost:20128/v1
OPENAI_API_KEY=...
SIMULATECRAFT_MODEL=oc/mimo-v2.5-free
```

| OS | How |
|---|---|
| Windows | Copy `.env.example` → `.env` in File Explorer, then edit in Notepad |
| macOS / Linux | `cp .env.example .env` then edit |

More detail: [Connect an LLM](llm-providers.md).

### 3. Launch

**Windows (PowerShell):**

```powershell
.\run.ps1
```

Or double-click **`run.cmd`** in File Explorer.

**macOS / Linux:**

```bash
chmod +x run.sh
./run.sh
```

The launcher will:

1. Install `uv` if needed, then Python packages  
2. Install the Mineflayer bot (`npm`)  
3. Start a local offline Minecraft server (Docker), unless you pass `--no-docker`  
4. Wait until the world is ready  
5. Start the explorer agent and the web viewer  

### 4. Open the viewer and join Minecraft

1. Browser → [http://127.0.0.1:8000](http://127.0.0.1:8000)  
2. Minecraft Java **1.21.4** → Multiplayer → `localhost`  

## Using your own Minecraft server

```powershell
# Windows
.\run.ps1 --no-docker --host localhost --port 25565
```

```bash
# macOS / Linux
./run.sh --no-docker --host localhost --port 25565
```

Bundled Docker pins **1.21.4** and offline mode (easy for bots). Online-mode servers need proper auth.

## Useful flags

```text
--no-docker
--host / --port
--agents explorer builder
--model openrouter:meta-llama/llama-3.1-8b-instruct:free
--viewer-port 8000
--help
```

## If something fails

| Problem | What to try |
|---|---|
| “No LLM provider” | Set `OPENROUTER_API_KEY` (or 9Router vars) in `.env` — blank values do not count |
| Missing `git` / `node` | Install Git and Node 18+ before the one-liner |
| PowerShell “cannot be loaded” | Use `run.cmd`, or `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `install.ps1` download 503 | Use the jsDelivr one-liner above |
| Bot never joins | Wait for world ready: `docker compose logs -f` → look for `Done (` |
| Docker missing | Install Docker Desktop, or use `--no-docker` with your own server |
| Wrong MC version | Use 1.21.4, or pass `--mc-version` to match your server |
| Viewer blank | Keep the terminal open; open `http://127.0.0.1:8000` |

Next: [Connect an LLM](llm-providers.md) · [Use the live viewer](viewer.md)
