# First run

Get SimulateCraft running end-to-end. Most users are on **Windows** — use `run.ps1` / `run.cmd`. macOS and Linux use `run.sh`.

## What you need

- **Python 3.11+**
- **Node.js 18+** (Mineflayer bots)
- **Docker Desktop** — optional, but easiest way to get Minecraft **1.21.4**
- An **LLM key** — free [Groq](https://console.groq.com/keys) is the simplest start

## Step 1 — Clone the repo

```text
git clone https://github.com/DanyalAbbas/SimulateCraft.git
cd SimulateCraft
```

## Step 2 — Add an API key

Copy `.env.example` to `.env` and set:

```text
GROQ_API_KEY=gsk_...
```

| OS | How |
|---|---|
| Windows | Copy `.env.example` → `.env` in File Explorer, then edit in Notepad |
| macOS / Linux | `cp .env.example .env` then edit |

Other providers: [Connect an LLM](llm-providers.md).

## Step 3 — Launch

**Windows (PowerShell):**

```powershell
.\run.ps1
```

Or double-click **`run.cmd`** in File Explorer (same thing; avoids execution-policy prompts).

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

## Step 4 — Open the viewer and join Minecraft

1. Browser → [http://127.0.0.1:8000](http://127.0.0.1:8000)  
2. Minecraft Java **1.21.4** → Multiplayer → `localhost`  

You should see the bot on the map and in-world.

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

Same flags on Windows and Unix:

```text
--no-docker
--host / --port
--agents explorer builder
--model groq:openai/gpt-oss-20b
--viewer-port 8000
--help
```

Examples:

```powershell
.\run.ps1 --agents explorer builder
.\run.ps1 --help
```

## If something fails

| Problem | What to try |
|---|---|
| “No LLM key” | Put `GROQ_API_KEY` in `.env` (same folder as `run.ps1`) |
| PowerShell “cannot be loaded” | Use `run.cmd`, or `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Bot never joins | Wait for world ready: `docker compose logs -f` → look for `Done (` |
| Docker missing | Install [Docker Desktop](https://www.docker.com/products/docker-desktop/), or use `--no-docker` with your own server |
| Wrong MC version | Use 1.21.4, or pass `--mc-version` to match your server |
| Viewer blank | Keep the terminal open; open `http://127.0.0.1:8000` |

Next: [Connect an LLM](llm-providers.md) · [Use the live viewer](viewer.md)
