# How it works

A short mental model — enough to navigate the codebase without reading every module.

## One tick

Each simulation tick roughly does this:

1. **Observe** — Python asks each bot for world state (position, inventory, nearby blocks…).
2. **Decide** — the LLM brain picks one typed action (move, mine, chat, …).
3. **Act** — the action is sent to the Mineflayer process, which executes it in Minecraft.
4. **Emit** — results go onto an event bus (viewer log, JSONL logger, etc.).

Then the clock advances and the loop repeats (paced by tick rate).

## Main pieces

| Piece | Job |
|---|---|
| **Runner** | Owns the async tick loop: pause, step, speed, max ticks |
| **MinecraftEnvironment** | One or more bots; observe / step / map tiles |
| **MinecraftBridge** | Local TCP JSON-RPC to a Node `bot.js` process |
| **LLMBrain** | Persona + memory + LLM → validated action |
| **EventBus** | Outbound events for the UI; inbound chat/control from you |
| **SimulationServer** | FastAPI app + static viewer at port 8000 |

## Why Node?

Mineflayer is the mature Minecraft bot library. Python stays the brain and
orchestrator; Node only talks to the game. One Node process per agent.

## Memory (optional depth)

Each brain can keep a memory stream, retrieve relevant bits, occasionally
reflect, and reuse verified “skills” (short action sequences). You can ignore
this until you customize agents.

## Where to look in the repo

```text
src/simulatecraft/
  cli.py              ./run.sh entry (setup + launch)
  core/               Runner, EventBus, schemas
  brains/             LLMBrain
  minecraft/          env, bridge, bot.js, RCON
  server/             viewer API + static UI
  examples/           ready-made explorer team
```

For function-level detail, use the [API reference](reference/index.md).
