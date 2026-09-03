"""SimulateCraft — LLM-driven AI agent simulations in Minecraft.

Core public API
---------------
    from simulatecraft import Agent, Runner, RunnerConfig
    from simulatecraft.minecraft import (
        MinecraftEnvironment,
        ALL_ACTIONS,
        Move, MineBlock, Chat, NavigateTo, ...
    )
    from simulatecraft.brains.llm import LLMBrain, LLMBrainConfig
    from simulatecraft.memory import MemoryStream, Retriever
    from simulatecraft.planning import Planner, Plan
    from simulatecraft.skills import SkillRegistry
"""

from .brains import Brain
from .core import (
    Action,
    Agent,
    AgentActed,
    AgentAdded,
    AgentRemoved,
    AgentSpoke,
    AgentState,
    BrainFailed,
    Environment,
    Event,
    EventBus,
    HumanChat,
    HumanControl,
    InboundEvent,
    NoOpAction,
    Observation,
    Runner,
    RunnerConfig,
    Snapshot,
    StepResult,
)

__version__ = "0.1.0"

__all__ = [
    # core loop
    "Action",
    "Agent",
    "AgentState",
    "Brain",
    "Environment",
    "Runner",
    "RunnerConfig",
    "Snapshot",
    "StepResult",
    "Observation",
    "NoOpAction",
    # events
    "AgentActed",
    "AgentAdded",
    "AgentRemoved",
    "AgentSpoke",
    "BrainFailed",
    "Event",
    "EventBus",
    "HumanChat",
    "HumanControl",
    "InboundEvent",
]
