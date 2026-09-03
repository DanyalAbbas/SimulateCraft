"""Typed Minecraft observation models.

``MinecraftObservation`` is what the environment hands to an agent's brain each
tick. It extends the base ``Observation`` with rich Minecraft-specific fields so
the LLM prompt gets structured, token-efficient context instead of a raw JSON
blob.

The data is populated by ``MinecraftEnvironment.observe()`` which queries the
Mineflayer bot over the IPC bridge.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..core.schemas import Observation

# ---------------------------------------------------------------------------
# Sub-models (nested inside MinecraftObservation)
# ---------------------------------------------------------------------------


class Vec3(BaseModel):
    """3-D float coordinate."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __str__(self) -> str:
        return f"({self.x:.1f}, {self.y:.1f}, {self.z:.1f})"


class InventoryItem(BaseModel):
    """One stack in the bot's inventory."""

    name: str
    count: int
    slot: int = -1
    nbt: dict[str, Any] = {}


class NearbyBlock(BaseModel):
    """A block within the scan radius."""

    name: str
    x: int
    y: int
    z: int
    hardness: float | None = None


class NearbyEntity(BaseModel):
    """A mob or player the bot can see."""

    name: str  # entity type e.g. "creeper", or player username
    entity_type: str  # "mob", "player", "item", "other"
    x: float
    y: float
    z: float
    distance: float
    health: float | None = None


class ChatMessage(BaseModel):
    """One line from the Minecraft chat log."""

    sender: str  # username or "" for server messages
    text: str
    tick: int = -1


class BotStats(BaseModel):
    """Vital statistics of the bot."""

    health: float = 20.0
    food: float = 20.0
    saturation: float = 5.0
    experience_level: int = 0
    game_mode: str = "survival"
    is_raining: bool = False
    time_of_day: int = 0  # 0-24000, 6000=noon, 18000=midnight
    biome: str = "unknown"


class RecipeInfo(BaseModel):
    """A craftable item the bot currently has materials for."""

    item_name: str
    count: int = 1
    needs_table: bool = False


# ---------------------------------------------------------------------------
# Main observation
# ---------------------------------------------------------------------------


class MinecraftObservation(Observation):
    """Full structured state snapshot handed to the agent brain each tick.

    All fields have sensible defaults so partial observations work: the bridge
    can omit fields it hasn't queried yet and the brain still gets a valid model.
    """

    # ---- position & orientation ----
    position: Vec3 = Field(default_factory=Vec3)
    yaw: float = 0.0  # horizontal look angle in degrees
    pitch: float = 0.0  # vertical look angle in degrees
    on_ground: bool = True
    biome: str = "unknown"

    # ---- vital stats ----
    stats: BotStats = Field(default_factory=BotStats)

    # ---- world context ----
    nearby_blocks: list[NearbyBlock] = Field(default_factory=list)
    """Blocks within the configured scan radius, sorted by distance."""

    nearby_entities: list[NearbyEntity] = Field(default_factory=list)
    """Mobs and players the bot can detect."""

    # ---- inventory ----
    inventory: list[InventoryItem] = Field(default_factory=list)
    equipped_item: str | None = None  # name of item in main hand

    # ---- craftable right now ----
    craftable: list[RecipeInfo] = Field(default_factory=list)

    # ---- social ----
    chat_log: list[ChatMessage] = Field(default_factory=list)
    """Last N chat messages (configurable in MinecraftEnvironment)."""

    # ---- agent's own goal (injected by the environment or runner) ----
    current_goal: str = ""

    def render(self) -> str:
        """Compact text summary injected into the LLM prompt."""
        lines: list[str] = [
            f"Tick {self.tick} | Pos {self.position} | Biome: {self.biome}",
            f"Health {self.stats.health}/20 | Food {self.stats.food}/20 "
            f"| Time {self.stats.time_of_day} | Rain: {self.stats.is_raining}",
        ]

        if self.equipped_item:
            lines.append(f"Holding: {self.equipped_item}")

        if self.inventory:
            inv_summary = ", ".join(f"{item.count}x {item.name}" for item in self.inventory[:12])
            if len(self.inventory) > 12:
                inv_summary += f" ... (+{len(self.inventory) - 12} more)"
            lines.append(f"Inventory: {inv_summary}")

        if self.nearby_blocks:
            block_summary = ", ".join(
                f"{b.name}@({b.x},{b.y},{b.z})" for b in self.nearby_blocks[:8]
            )
            lines.append(f"Nearby blocks: {block_summary}")

        if self.nearby_entities:
            ent_summary = ", ".join(
                f"{e.name}({e.entity_type}) ~{e.distance:.1f}m" for e in self.nearby_entities[:6]
            )
            lines.append(f"Nearby entities: {ent_summary}")

        if self.craftable:
            craft_summary = ", ".join(r.item_name for r in self.craftable[:6])
            lines.append(f"Craftable: {craft_summary}")

        if self.chat_log:
            lines.append("Recent chat:")
            for msg in self.chat_log[-4:]:
                prefix = f"<{msg.sender}> " if msg.sender else "[server] "
                lines.append(f"  {prefix}{msg.text}")

        if self.current_goal:
            lines.append(f"Current goal: {self.current_goal}")

        return "\n".join(lines)
