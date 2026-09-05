"""Unit tests for observations rendering and action summaries."""

from __future__ import annotations

from simulatecraft.minecraft.actions import (
    ActivateBlock,
    Chat,
    Craft,
    DropItem,
    EquipItem,
    FollowEntity,
    Jump,
    LookAt,
    MineBlock,
    Move,
    NavigateTo,
    PlaceBlock,
    Sneak,
    UseItem,
    Wait,
    Whisper,
)
from simulatecraft.minecraft.observations import (
    BotStats,
    ChatMessage,
    InventoryItem,
    MinecraftObservation,
    NearbyBlock,
    NearbyEntity,
    RecipeInfo,
    Vec3,
)


def test_vec3_str() -> None:
    assert "1" in str(Vec3(x=1, y=2, z=3))


def test_observation_render_full() -> None:
    obs = MinecraftObservation(
        agent_id="a",
        tick=3,
        position=Vec3(x=1, y=64, z=-2),
        biome="plains",
        stats=BotStats(health=18, food=15, time_of_day=1000, is_raining=True),
        equipped_item="wooden_pickaxe",
        inventory=[InventoryItem(name=f"item{i}", count=i + 1) for i in range(14)],
        nearby_blocks=[NearbyBlock(name="oak_log", x=0, y=64, z=0) for _ in range(10)],
        nearby_entities=[
            NearbyEntity(name="zombie", entity_type="mob", x=1, y=64, z=1, distance=3.2)
            for _ in range(8)
        ],
        craftable=[RecipeInfo(item_name=f"stick{i}") for i in range(8)],
        chat_log=[
            ChatMessage(sender="Steve", text="hi"),
            ChatMessage(sender="", text="server note"),
        ],
        current_goal="build a hut",
    )
    text = obs.render()
    assert "Tick 3" in text
    assert "Holding: wooden_pickaxe" in text
    assert "+2 more" in text
    assert "Nearby blocks" in text
    assert "Nearby entities" in text
    assert "Craftable" in text
    assert "<Steve>" in text
    assert "[server]" in text
    assert "Current goal" in text


def test_action_summaries() -> None:
    assert Move(direction="forward").render()
    assert Jump().render()
    assert Sneak(enable=True).render()
    assert LookAt(x=1, y=2, z=3).render()
    assert LookAt(entity="Steve").render()
    assert MineBlock(x=0, y=64, z=0).render()
    assert PlaceBlock(x=0, y=64, z=0, block_name="dirt").render()
    assert UseItem().render()
    assert UseItem(x=1, y=2, z=3).render()
    assert ActivateBlock(x=0, y=64, z=0).render()
    assert EquipItem(item_name="sword").render()
    assert DropItem(item_name="dirt", count=2).render()
    assert Craft(item_name="stick", count=4, use_crafting_table=True).render()
    assert Chat(text="hello").render()
    assert Whisper(target="Steve", text="psst").render()
    assert NavigateTo(x=10, y=64, z=10).render()
    assert FollowEntity(target="Steve").render()
    assert Wait(ticks=3).render()
