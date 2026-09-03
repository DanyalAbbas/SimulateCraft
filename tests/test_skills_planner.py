"""Planner + SkillRegistry behavior."""

from __future__ import annotations

from simulatecraft.memory import HashingEmbedding
from simulatecraft.planning import Plan, Planner
from simulatecraft.skills.registry import SkillRegistry


async def test_plan_render_and_advance() -> None:
    plan = Plan(goal="greet", steps=["walk over", "say hi"])
    text = plan.render()
    assert "1. walk over" in text
    assert plan.current() == "walk over"
    assert plan.advance() == "walk over"
    assert plan.current() == "say hi"
    assert not plan.done()
    plan.advance()
    plan.advance()
    assert plan.advance() is None
    assert plan.done()


async def test_planner_generates_when_done() -> None:
    generations = {"n": 0}

    def generator(context: str) -> Plan:
        generations["n"] += 1
        return Plan(goal="g", steps=["only step"])

    planner = Planner(generator)
    first = await planner.ensure_plan("ctx")
    again = await planner.ensure_plan("ctx")
    first.advance()
    await planner.ensure_plan("ctx")
    assert generations["n"] == 2
    assert first is again


async def test_replan_checker_triggers_reset() -> None:
    async def checker(observation: str, plan: Plan) -> bool:
        return "fire" in observation

    planner = Planner(lambda ctx: Plan(goal="g", steps=["s"]), replan_checker=checker)
    await planner.ensure_plan("ctx")
    assert not await planner.maybe_replan("all calm")
    assert planner.current_plan is not None
    assert await planner.maybe_replan("fire in the bakery")
    assert planner.current_plan is None


def test_skill_register_verify_find() -> None:
    registry = SkillRegistry(HashingEmbedding())
    skill = registry.register(
        "goto_fountain",
        "head east twice to reach the fountain",
        [{"kind": "move", "direction": "east"}, {"kind": "move", "direction": "east"}],
    )
    assert not skill.verified
    assert registry.find("anything else", require_verified=True) is None

    import asyncio

    asyncio.run(registry.verify("goto_fountain", True))
    hit = registry.find("how to reach the fountain from here")
    assert hit is not None and hit.name == "goto_fountain"
    assert hit.verified


def test_skill_similarity_threshold_blocks_weak_match() -> None:
    registry = SkillRegistry(HashingEmbedding(), similarity_threshold=0.99)
    registry.register(
        "x", "walk east twice to reach the fountain", [{"kind": "move", "direction": "east"}]
    )
    import asyncio

    asyncio.run(registry.verify("x", True))
    assert registry.find("completely unrelated query about hats") is None


def test_skill_persistence_roundtrip(tmp_path) -> None:
    path = tmp_path / "skills.json"
    registry = SkillRegistry(persistence_path=path)
    registry.register("skill-a", "description a", [{"kind": "noop"}])
    reloaded = SkillRegistry(persistence_path=path)
    assert [s.name for s in reloaded.skills] == ["skill-a"]


async def test_skill_usage_stats() -> None:
    registry = SkillRegistry(HashingEmbedding())
    registry.register("s", "desc", [])
    await registry.verify("s", True)
    await registry.verify("s", False)
    skill = registry.get("s")
    assert skill.times_used == 2
    assert skill.success_count == 1
