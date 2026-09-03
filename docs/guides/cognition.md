# Memory & planning

Each agent brain can plug in the same cognition stack used by Generative Agents
and Voyager-style skill libraries.

## MemoryStream

Append-only log of observations, action results, chat, and reflections. Each
record has an importance score (1–10).

See [`MemoryStream`](../reference/memory/stream.md).

## Retriever

Scores memories by **recency × importance × embedding similarity** to the
current observation and returns top-k.

Default embeddings are a local hashing backend (no HuggingFace download). Set
`SIMULATECRAFT_EMBEDDINGS=transformer` to prefer `sentence-transformers`.

See [`Retriever`](../reference/memory/retrieval.md).

## ReflectionEngine

Every N new records, distills recent memories into higher-level insights and
stores them back with importance 9.

See [`ReflectionEngine`](../reference/memory/reflection.md).

## Planner

Holds the agent’s current `Plan` (goal + ordered steps) and can request a
replan when the situation changes.

See [`Planner`](../reference/planning/planner.md).

## SkillRegistry

Voyager-style store of verified action sequences. When a skill matches the
current situation, `LLMBrain` replays it before paying for another LLM call.

See [`SkillRegistry`](../reference/skills/registry.md).
