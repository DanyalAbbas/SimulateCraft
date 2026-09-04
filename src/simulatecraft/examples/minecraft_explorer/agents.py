"""Pre-built LLM agent personas for the Minecraft explorer example.

Each persona is an LLMBrain configured with a personality, a long-term goal,
and the full Minecraft action set.

Model string examples
---------------------
- ``"openrouter:meta-llama/llama-3.1-8b-instruct:free"``  ← free, just needs OPENROUTER_API_KEY
- ``"openrouter:google/gemma-3-27b-it:free"``              ← another free option
- ``"openrouter:anthropic/claude-sonnet-4.6"``             ← paid via OpenRouter
- ``"anthropic:claude-sonnet-4-5"``                        ← direct Anthropic key
- ``"openai:gpt-4o-mini"``                                 ← direct OpenAI key
- ``"test"``                                               ← offline, no key needed
"""

from __future__ import annotations

from simulatecraft.brains.llm import LLMBrain, LLMBrainConfig
from simulatecraft.memory.retrieval import Retriever, default_backend
from simulatecraft.memory.stream import MemoryStream
from simulatecraft.minecraft.actions import ALL_ACTIONS
from simulatecraft.planning.planner import Plan, Planner
from simulatecraft.skills.registry import SkillRegistry


def _make_brain(persona: str, goal: str, model: str) -> LLMBrain:
    memory = MemoryStream()
    retriever = Retriever(memory, default_backend())
    skills = SkillRegistry(persistence_path=".simulatecraft_skills.json")

    planner = Planner(
        generator=lambda _ctx: Plan(
            goal=goal,
            steps=[
                "Look around and assess the environment",
                "Gather basic resources (wood, stone)",
                "Craft essential tools",
                "Explore and achieve the main goal",
            ],
        )
    )

    brain = LLMBrain(
        action_types=ALL_ACTIONS,
        persona=persona,
        model=model,
        config=LLMBrainConfig(
            model=model,
            reflect_every=20,
            memory_top_k=6,
            retries=2,
        ),
        memory=memory,
        retriever=retriever,
        planner=planner,
        skills=skills,
    )
    return brain


# ---------------------------------------------------------------------------
# Persona definitions
# ---------------------------------------------------------------------------

EXPLORER_PERSONA = (
    "Alex, an adventurous Minecraft explorer. You love discovering new biomes, "
    "structures, and resources. You are methodical — you always craft tools before "
    "venturing far. When you find something interesting you narrate it in chat."
)

BUILDER_PERSONA = (
    "Bea, a master builder. Your primary drive is construction: you gather materials "
    "efficiently and build shelter and structures with purpose. You are patient and "
    "detail-oriented. You announce what you are building in chat."
)

GATHERER_PERSONA = (
    "Cole, a resourceful gatherer. You focus on efficiently collecting food, wood, "
    "stone and ores. You share surplus resources with other players. You are pragmatic "
    "and cheerful, often commenting on what you find."
)

DEFENDER_PERSONA = (
    "Dana, a vigilant defender. You protect the group from hostile mobs, warn others "
    "of danger in chat, and craft armour and weapons first. You are alert and decisive."
)


def custom(
    *,
    persona: str,
    goal: str,
    model: str = "test",
    instructions: str | None = None,
) -> LLMBrain:
    """Build an LLM brain from free-form frontend fields."""
    memory = MemoryStream()
    retriever = Retriever(memory, default_backend())
    skills = SkillRegistry(persistence_path=".simulatecraft_skills.json")
    planner = Planner(
        generator=lambda _ctx: Plan(
            goal=goal or "survive and explore",
            steps=[
                "Look around and assess the environment",
                "Gather basic resources (wood, stone)",
                "Craft essential tools",
                "Explore and achieve the main goal",
            ],
        )
    )
    return LLMBrain(
        action_types=ALL_ACTIONS,
        persona=persona or "A Minecraft adventurer.",
        model=model,
        instructions=instructions,
        config=LLMBrainConfig(
            model=model if isinstance(model, str) else "test",
            reflect_every=20,
            memory_top_k=6,
            retries=2,
        ),
        memory=memory,
        retriever=retriever,
        planner=planner,
        skills=skills,
    )


def explorer(model: str = "test") -> LLMBrain:
    return _make_brain(EXPLORER_PERSONA, "explore as much of the world as possible", model)


def builder(model: str = "test") -> LLMBrain:
    return _make_brain(BUILDER_PERSONA, "build a comfortable shelter before nightfall", model)


def gatherer(model: str = "test") -> LLMBrain:
    return _make_brain(GATHERER_PERSONA, "collect a full stack of wood, stone, and food", model)


def defender(model: str = "test") -> LLMBrain:
    return _make_brain(DEFENDER_PERSONA, "craft armour and weapons, protect teammates", model)
