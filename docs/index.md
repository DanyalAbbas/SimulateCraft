# SimulateCraft

![SimulateCraft cover](assets/cover.png)

**LLM agents that play Minecraft.**

You run a Minecraft server, SimulateCraft joins with one or more bots, an LLM
decides what each bot does each tick, and a browser UI lets you watch and steer
the simulation.

## Start here

| Tutorial | What you’ll do |
|---|---|
| [First run](getting-started.md) | One-line install, set a provider, launch with `run.ps1` / `run.sh` |
| [Connect an LLM](llm-providers.md) | OpenRouter, 9Router, own API, or Groq |
| [Use the live viewer](viewer.md) | Map, spawn agents, chat, pause / speed |
| [How it works](how-it-works.md) | Big picture of the tick loop (no API dump) |
| [Contributing](contributing.md) | Dev setup if you want to change the code |

Need a function signature later? See the [API reference](reference/index.md) at the end of the sidebar.

!!! tip "Fastest path"
    1. Install **Git**, **Node.js 18+**, and **Docker Desktop**.
    2. Run the one-liner from [First run](getting-started.md).
    3. Put an **OpenRouter** key (or 9Router / your API) in `.env`.
    4. `.\run.ps1` (Windows) or `./run.sh` (macOS / Linux).
    5. Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and join `localhost` in Minecraft **1.21.4**.
