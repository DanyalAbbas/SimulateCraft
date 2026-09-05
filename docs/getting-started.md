# First run

This walkthrough gets SimulateCraft running on your machine end-to-end.

## What you need

- **Python 3.11+**
- **Node.js 18+** (Mineflayer bots)
- **Docker** — optional, but easiest way to get a Minecraft **1.21.4** server
- An **LLM key** — free [Groq](https://console.groq.com/keys) is the simplest start

## Step 1 — Clone and enter the repo

```bash
git clone https://github.com/DanyalAbbas/SimulateCraft.git
cd SimulateCraft
```

## Step 2 — Add an API key

Copy the example env file and paste your key:

```bash
cp .env.example .env
```

Edit `.env` and set at least one of:

```bash
GROQ_API_KEY=gsk_...
```

Other options (OpenRouter, 9Router) are covered in [Connect an LLM](llm-providers.md).

## Step 3 — Launch

```bash
chmod +x run.sh
./run.sh
```

That script will:

1. Install Python packages (`uv`)
2. Install the Mineflayer bot (`npm`)
3. Start a local offline Minecraft server (Docker), unless you opt out
4. Wait until the world is ready
5. Start the explorer agent and the web viewer

## Step 4 — Open the viewer and join Minecraft

1. Browser → [http://127.0.0.1:8000](http://127.0.0.1:8000)
2. Minecraft Java **1.21.4** → Multiplayer → `localhost`

You should see the bot on the map and in-world.

## Using your own Minecraft server

Skip Docker and point at a server you already run:

```bash
./run.sh --no-docker --host localhost --port 25565
```

Use a version Mineflayer supports (bundled compose pins **1.21.4**). Online-mode
servers need auth; the Docker server runs offline for easy local bots.

## Useful CLI flags

```bash
./run.sh --help
# common ones:
#   --no-docker
#   --host / --port
#   --agents explorer builder
#   --model groq:openai/gpt-oss-20b
#   --viewer-port 8000
```

## If something fails

| Problem | What to try |
|---|---|
| “No LLM key” | Put `GROQ_API_KEY` (or another provider) in `.env` |
| Bot never joins | Wait for `Done (` in `docker compose logs -f`; port open ≠ world ready |
| Wrong MC version | Use 1.21.4, or set `--mc-version` to match your server |
| Viewer blank | Confirm the process is still running; open `http://127.0.0.1:8000` |

Next: [Connect an LLM](llm-providers.md) · [Use the live viewer](viewer.md)
