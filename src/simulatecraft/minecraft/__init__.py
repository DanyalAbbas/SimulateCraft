"""SimulateCraft Minecraft module.

Public API
----------
    from simulatecraft.minecraft import (
        MinecraftEnvironment,
        MinecraftBridge,
        MinecraftObservation,
        ALL_ACTIONS,
        # individual actions:
        Move, Jump, Sneak, LookAt,
        MineBlock, PlaceBlock, UseItem, ActivateBlock,
        AttackEntity, Eat, CollectItem,
        EquipItem, DropItem, GiveItem, Craft,
        Chat, Whisper,
        NavigateTo, FollowEntity, CancelPath,
        Wait,
    )
"""

from .actions import (
    ALL_ACTIONS,
    ActivateBlock,
    AttackEntity,
    CancelPath,
    Chat,
    CollectItem,
    Craft,
    DropItem,
    Eat,
    EquipItem,
    FollowEntity,
    GiveItem,
    Jump,
    LookAt,
    MineBlock,
    MinecraftAction,
    Move,
    NavigateTo,
    PlaceBlock,
    Sneak,
    UseItem,
    Wait,
    Whisper,
)
from .connection import BridgeError, MinecraftBridge
from .env import AgentBotConfig, MinecraftEnvironment
from .observations import (
    BotStats,
    ChatMessage,
    InventoryItem,
    MinecraftObservation,
    NearbyBlock,
    NearbyEntity,
    Vec3,
)

__all__ = [
    # environment
    "MinecraftEnvironment",
    "AgentBotConfig",
    # bridge
    "MinecraftBridge",
    "BridgeError",
    # observations
    "MinecraftObservation",
    "Vec3",
    "BotStats",
    "InventoryItem",
    "NearbyBlock",
    "NearbyEntity",
    "ChatMessage",
    # actions
    "MinecraftAction",
    "ALL_ACTIONS",
    "Move",
    "Jump",
    "Sneak",
    "LookAt",
    "MineBlock",
    "PlaceBlock",
    "UseItem",
    "ActivateBlock",
    "AttackEntity",
    "Eat",
    "CollectItem",
    "EquipItem",
    "DropItem",
    "GiveItem",
    "Craft",
    "Chat",
    "Whisper",
    "NavigateTo",
    "FollowEntity",
    "CancelPath",
    "Wait",
]
