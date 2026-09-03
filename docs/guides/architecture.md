# Architecture

```
LLMBrain ──decide()──► MinecraftEnvironment
(pydantic-ai)            │
+ Memory / Planner       │  MinecraftBridge (TCP JSON-RPC)
+ Skills                 ▼
Runner ◄──────────── bot.js (Mineflayer)
   │
   ▼ EventBus
JSONL logger · FastAPI websocket viewer
```

## Core loop

| Piece | Role |
|---|---|
| [`Runner`](../reference/core/runner.md) | Async tick loop, pause/step, decision timeouts |
| [`Environment`](../reference/core/environment.md) | Domain state; Minecraft implements observe/step |
| [`Agent`](../reference/core/agent.md) + [`Brain`](../reference/brains/base.md) | Identity + policy |
| [`EventBus`](../reference/core/events.md) | Typed outbound events + inbound human chat/control |

## Minecraft bridge

Python spawns one Node Mineflayer process per bot. Traffic is newline-delimited
JSON-RPC on a local TCP port (default `25570`).

- `get_state` / `get_map` / `perform_action` are the live RPC surface
- Push events (`chat`, `bot.spawned`, …) flow Node → Python without polling

See [`simulatecraft.minecraft`](../reference/minecraft/index.md).

## Cognition stack

- [`MemoryStream`](../reference/memory/stream.md) — append-only memories with importance
- [`Retriever`](../reference/memory/retrieval.md) — recency × importance × similarity
- [`ReflectionEngine`](../reference/memory/reflection.md) — periodic insights
- [`Planner`](../reference/planning/planner.md) — goal + ordered steps
- [`SkillRegistry`](../reference/skills/registry.md) — verified action sequences

## Viewer & logging

- [`SimulationServer`](../reference/server/app.md) — REST + WebSocket UI
- [`JsonlLogger` / `Replayer`](../reference/viewers/log.md) — record and replay events
