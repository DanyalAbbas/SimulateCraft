# Actions & observations

## Actions

Every action the LLM can emit is a strict Pydantic model with a `kind`
discriminator. `LLMBrain` receives the full union as its `output_type`, so the
model’s choice arrives already validated.

| Category | Actions |
|---|---|
| Movement | `Move`, `Jump`, `Sneak`, `LookAt` |
| World | `MineBlock`, `PlaceBlock`, `UseItem`, `ActivateBlock` |
| Inventory | `EquipItem`, `DropItem`, `Craft` |
| Social | `Chat`, `Whisper` |
| Navigation | `NavigateTo`, `FollowEntity` |
| Meta | `Wait` |

Pass [`ALL_ACTIONS`](../reference/minecraft/actions.md) for the full set, or a
smaller list when you want a narrower policy.

```python
from simulatecraft.minecraft import Move, Chat, NavigateTo
from simulatecraft.brains.llm import LLMBrain

brain = LLMBrain(
    action_types=[Move, Chat, NavigateTo],
    persona="A careful scout.",
    model="groq:openai/gpt-oss-120b",
)
```

## Observations

Each tick the environment builds a [`MinecraftObservation`](../reference/minecraft/observations.md):

- Position, yaw, pitch, biome
- Stats: health, food, XP, game mode, time of day, weather
- Inventory with item names and counts
- Nearby blocks and entities
- Craftable items right now
- Chat log (rolling window)
- Current goal (injected by the environment)

`MinecraftObservation.render()` produces a compact text summary for the LLM prompt.
