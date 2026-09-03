# Quickstart

## Single explorer bot

```bash
python -m simulatecraft.examples.minecraft_explorer.main \
    --host localhost --port 25565 --agents explorer
```

## Multi-agent team + viewer

```bash
python -m simulatecraft.examples.minecraft_explorer.main \
    --host localhost --port 25565 \
    --agents explorer builder gatherer defender \
    --serve --viewer-port 8000
```

Available agents: `explorer` · `builder` · `gatherer` · `defender`

## Minimal Python script

```python
import asyncio
from simulatecraft import Agent, Runner, RunnerConfig
from simulatecraft.brains.llm import LLMBrain, resolve_model
from simulatecraft.minecraft import MinecraftEnvironment, ALL_ACTIONS

env = MinecraftEnvironment(server_host="localhost", server_port=25565)
env.add_bot("bot1", username="MyBot", goal="collect 64 logs of wood")

brain = LLMBrain(
    action_types=ALL_ACTIONS,
    persona="A diligent Minecraft worker who focuses on resource gathering.",
    model=resolve_model(),
)

runner = Runner(
    environment=env,
    config=RunnerConfig(tick_rate=1.0, max_ticks=300),
)
runner.add_agent(Agent(id="bot1", name="MyBot", brain=brain))

async def main():
    async with env:
        await runner.start()

asyncio.run(main())
```

See [Actions & observations](actions.md) to trim the action set, and
[Memory & planning](cognition.md) to wire cognition modules.
