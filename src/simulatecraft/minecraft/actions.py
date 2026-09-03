"""Typed Minecraft actions for LLM agents.

Every action the LLM can emit is a pydantic model with a ``kind`` discriminator.
The full union (``MinecraftAction``) is passed to LLMBrain as ``action_types`` so
the model's choice arrives already validated — no JSON parsing, no regex.

Categories
----------
- Movement  : Move, Jump, Sneak, Sprint, LookAt
- World     : MineBlock, PlaceBlock, UseItem, ActivateBlock
- Inventory : EquipItem, DropItem, Craft
- Social    : Chat, Whisper
- Navigation: NavigateTo  (Mineflayer pathfinder handles the pathfinding)
- Meta      : Wait, NoOp
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from ..core.schemas import Action

# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------


class Move(Action):
    """Walk one step in a cardinal direction."""

    kind: Literal["move"] = "move"
    direction: Literal["forward", "back", "left", "right"] = "forward"
    sprint: bool = False

    def render(self) -> str:
        prefix = "sprint" if self.sprint else "walk"
        return f"{prefix} {self.direction}"


class Jump(Action):
    """Jump (optionally while moving)."""

    kind: Literal["jump"] = "jump"

    def render(self) -> str:
        return "jump"


class Sneak(Action):
    """Toggle sneaking on or off."""

    kind: Literal["sneak"] = "sneak"
    enable: bool = True

    def render(self) -> str:
        return f"sneak {'on' if self.enable else 'off'}"


class LookAt(Action):
    """Turn to face a target — block coordinates or entity name."""

    kind: Literal["look_at"] = "look_at"
    # Either block coords OR an entity name (resolved on bot side)
    x: float | None = None
    y: float | None = None
    z: float | None = None
    entity: str | None = None  # e.g. "creeper", "Steve"

    def render(self) -> str:
        if self.entity:
            return f"look at {self.entity}"
        return f"look at ({self.x}, {self.y}, {self.z})"


# ---------------------------------------------------------------------------
# World interaction
# ---------------------------------------------------------------------------


class MineBlock(Action):
    """Dig/break a block at a given position (or the block the bot is looking at)."""

    kind: Literal["mine_block"] = "mine_block"
    x: int | None = None
    y: int | None = None
    z: int | None = None
    block_name: str | None = None  # resolve nearest matching block when coords absent

    def render(self) -> str:
        if self.block_name and self.x is None:
            return f"mine nearest {self.block_name}"
        return f"mine block at ({self.x}, {self.y}, {self.z})"


class PlaceBlock(Action):
    """Place a block from inventory at a given position."""

    kind: Literal["place_block"] = "place_block"
    block_name: str
    x: int
    y: int
    z: int
    face: Literal["top", "bottom", "north", "south", "east", "west"] = "top"

    def render(self) -> str:
        return f"place {self.block_name} at ({self.x}, {self.y}, {self.z}) on {self.face}"


class UseItem(Action):
    """Right-click / use the currently equipped item (optionally on a target block)."""

    kind: Literal["use_item"] = "use_item"
    x: int | None = None
    y: int | None = None
    z: int | None = None

    def render(self) -> str:
        if self.x is not None:
            return f"use item on ({self.x}, {self.y}, {self.z})"
        return "use item"


class ActivateBlock(Action):
    """Right-click a block to open/use it (chest, furnace, door, lever, etc.)."""

    kind: Literal["activate_block"] = "activate_block"
    x: int
    y: int
    z: int

    def render(self) -> str:
        return f"activate block at ({self.x}, {self.y}, {self.z})"


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


class EquipItem(Action):
    """Move an item to the bot's hand or armour slot."""

    kind: Literal["equip"] = "equip"
    item_name: str
    destination: Literal["hand", "head", "torso", "legs", "feet", "off-hand"] = "hand"

    def render(self) -> str:
        return f"equip {self.item_name} in {self.destination}"


class DropItem(Action):
    """Drop one or more of an item from inventory."""

    kind: Literal["drop_item"] = "drop_item"
    item_name: str
    count: int = 1

    def render(self) -> str:
        return f"drop {self.count}x {self.item_name}"


class Craft(Action):
    """Craft an item by name (recipe looked up on the bot side)."""

    kind: Literal["craft"] = "craft"
    item_name: str
    count: int = 1
    use_crafting_table: bool = False

    def render(self) -> str:
        suffix = " (crafting table)" if self.use_crafting_table else ""
        return f"craft {self.count}x {self.item_name}{suffix}"


# ---------------------------------------------------------------------------
# Social
# ---------------------------------------------------------------------------


class Chat(Action):
    """Send a public message in Minecraft chat."""

    kind: Literal["chat"] = "chat"
    text: str

    def render(self) -> str:
        return f'say "{self.text}"'


class Whisper(Action):
    """Send a private /msg to another player."""

    kind: Literal["whisper"] = "whisper"
    target: str
    text: str

    def render(self) -> str:
        return f'/msg {self.target} "{self.text}"'


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


class NavigateTo(Action):
    """High-level pathfind to a position. Mineflayer pathfinder handles obstacles."""

    kind: Literal["navigate_to"] = "navigate_to"
    x: float
    y: float
    z: float
    timeout_seconds: float = 8.0

    def render(self) -> str:
        return f"navigate to ({self.x:.1f}, {self.y:.1f}, {self.z:.1f})"


class FollowEntity(Action):
    """Follow a named player or mob until the next action."""

    kind: Literal["follow"] = "follow"
    target: str  # player username or mob type
    min_distance: float = 2.0
    timeout_seconds: float = 8.0

    def render(self) -> str:
        return f"follow {self.target}"


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


class Wait(Action):
    """Do nothing for a number of ticks. Useful when waiting for events."""

    kind: Literal["wait"] = "wait"
    ticks: int = 1

    def render(self) -> str:
        return f"wait {self.ticks} tick(s)"


# ---------------------------------------------------------------------------
# Discriminated union exposed to LLMBrain
# ---------------------------------------------------------------------------

MinecraftAction = Annotated[
    Move
    | Jump
    | Sneak
    | LookAt
    | MineBlock
    | PlaceBlock
    | UseItem
    | ActivateBlock
    | EquipItem
    | DropItem
    | Craft
    | Chat
    | Whisper
    | NavigateTo
    | FollowEntity
    | Wait,
    Field(discriminator="kind"),
]

# Flat list for passing to LLMBrain(action_types=...)
ALL_ACTIONS: list[type[Action]] = [
    Move,
    Jump,
    Sneak,
    LookAt,
    MineBlock,
    PlaceBlock,
    UseItem,
    ActivateBlock,
    EquipItem,
    DropItem,
    Craft,
    Chat,
    Whisper,
    NavigateTo,
    FollowEntity,
    Wait,
]
