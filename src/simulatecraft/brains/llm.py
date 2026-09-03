"""LLMBrain: pydantic-ai-driven reasoning behind the standard Brain interface.

This is the ONLY module in the package that imports ``pydantic_ai``. Its API
moves fast, so every pydantic-ai-specific call lives here; pin the exact
version in pyproject.toml and upgrade in this single file.

Model string formats accepted by LLMBrain / resolve_model()
------------------------------------------------------------
- ``"groq:openai/gpt-oss-120b"``                           ← Groq free tier, default ⚡
- ``"groq:openai/gpt-oss-20b"``                            ← Groq free tier, faster/smaller
- ``"groq:qwen/qwen3.6-27b"``                              ← Groq free tier, strong reasoning
- ``"openrouter:meta-llama/llama-3.1-8b-instruct:free"``   ← OpenRouter free tier
- ``"openrouter:anthropic/claude-sonnet-4.6"``             ← OpenRouter paid
- ``"anthropic:claude-sonnet-4-5"``                        ← direct Anthropic key
- ``"openai:gpt-4o-mini"``                                  ← direct OpenAI key
- ``"google-gla:gemini-2.0-flash"``                         ← direct Google key
- ``"test"``                                                ← offline TestModel, no key needed

Auto-selection order (resolve_model):  GROQ_API_KEY → OPENROUTER_API_KEY → "test"
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any, Union

from pydantic import BaseModel, Field

from ..core.schemas import Action, NoOpAction, Observation, StepResult
from ..memory.reflection import ReflectionEngine
from ..memory.retrieval import Retriever
from ..memory.stream import MemoryStream
from ..planning.planner import Plan, Planner
from ..skills.registry import SkillRegistry
from .base import Brain

log = logging.getLogger(__name__)

try:
    from pydantic_ai import Agent as PydanticAgent
except ImportError as exc:  # pragma: no cover - exercised only without [llm] extra
    raise ImportError(
        "brains.llm requires the [llm] extra: pip install simulatecraft[llm]"
    ) from exc


# ---------------------------------------------------------------------------
# Model resolution helpers
# ---------------------------------------------------------------------------


def _build_pydantic_ai_model(model: str | Any) -> Any:
    """Convert a SimulateCraft model string to a pydantic-ai model object.

    Handles the ``openrouter:<model-name>`` prefix specially; everything else
    is passed through as-is (pydantic-ai resolves ``anthropic:``, ``openai:``,
    ``google-gla:`` etc. natively).
    """
    if not isinstance(model, str):
        return model  # already a pydantic-ai model/object

    if model.startswith("openrouter:"):
        model_name = model[len("openrouter:") :]
        return _make_openrouter_model(model_name)

    return model  # pydantic-ai handles everything else by string prefix


def _make_openrouter_model(model_name: str) -> Any:
    """Build an OpenRouterModel. Reads OPENROUTER_API_KEY from the environment."""
    try:
        from pydantic_ai.models.openrouter import OpenRouterModel
        from pydantic_ai.providers.openrouter import OpenRouterProvider
    except ImportError as exc:
        raise ImportError(
            "OpenRouter support requires pydantic-ai[openrouter]. "
            "Run: pip install 'pydantic-ai[openrouter]'"
        ) from exc

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise OSError(
            "OPENROUTER_API_KEY is not set.\n"
            "Get a free key at https://openrouter.ai/keys then:\n"
            "  export OPENROUTER_API_KEY=sk-or-..."
        )
    provider = OpenRouterProvider(
        api_key=api_key,
        app_title="SimulateCraft",
        app_url="https://github.com/example/simulatecraft",
    )
    return OpenRouterModel(model_name, provider=provider)


def resolve_model(env_var: str = "SIMULATECRAFT_MODEL") -> str:
    """Read the model string from the environment, auto-selecting a free provider.

    Priority
    --------
    1. ``SIMULATECRAFT_MODEL`` env var  — any format accepted:
         openrouter:meta-llama/llama-3.1-8b-instruct:free
         groq:openai/gpt-oss-120b
         anthropic:claude-sonnet-4-5
         openai:gpt-4o-mini
         test
    2. ``GROQ_API_KEY`` present  →  ``groq:openai/gpt-oss-120b``
       (Groq is free-tier, very fast — best default for agent tick loops)
    3. ``OPENROUTER_API_KEY`` present  →  ``openrouter:meta-llama/llama-3.1-8b-instruct:free``
    4. No keys at all  →  ``"test"`` (offline TestModel, zero network calls)
    """
    from dotenv import load_dotenv

    load_dotenv()

    model = os.getenv(env_var, "").strip()
    if model:
        return model

    if os.getenv("GROQ_API_KEY", "").strip():
        groq_model = "groq:openai/gpt-oss-120b"
        log.info("No %s set; using Groq free-tier model: %s", env_var, groq_model)
        return groq_model

    if os.getenv("OPENROUTER_API_KEY", "").strip():
        free_model = "openrouter:meta-llama/llama-3.1-8b-instruct:free"
        log.info("No %s set; using free OpenRouter model: %s", env_var, free_model)
        return free_model

    log.warning(
        "No %s, GROQ_API_KEY, or OPENROUTER_API_KEY set. Using offline TestModel — "
        "agents will produce canned responses.\n"
        "  Free options:\n"
        "    Groq (fast):       export GROQ_API_KEY=gsk_...   (console.groq.com/keys)\n"
        "    OpenRouter (many): export OPENROUTER_API_KEY=sk-or-... (openrouter.ai/keys)",
        env_var,
    )
    return "test"


class BrainDeps(BaseModel):
    """Dependency-injected context handed to the pydantic-ai agent each run."""

    persona: str = ""
    observation: dict[str, Any] = {}
    observation_text: str = ""
    memories: list[str] = []
    plan: str | None = None
    inbox: list[str] = []
    tick: int = 0


class LLMBrainConfig(BaseModel):
    model: str = "test"
    reflect_every: int = 15
    memory_top_k: int = 5
    retries: int = 2


class LLMBrain(Brain[Observation]):
    """Decides via an LLM with validated structured output (no manual parsing).

    - Available actions are exposed through pydantic-ai's ``output_type`` as a
      discriminated union of your Action subclasses, so the model's choice
      arrives as an already-validated Action instance.
    - Schema failures are handled by pydantic-ai's native retry mechanism.
    - Provider switching is just the ``model`` string ("anthropic:...",
      "openai:...", "google-gla:...", "google-gla:gemini-...").
    """

    def __init__(
        self,
        action_types: list[type[Action]],
        *,
        persona: str,
        model: str | Any = "test",
        config: LLMBrainConfig | None = None,
        instructions: str | None = None,
        memory: MemoryStream | None = None,
        retriever: Retriever | None = None,
        planner: Planner | None = None,
        skills: SkillRegistry | None = None,
        summarizer: Any = None,
    ) -> None:
        self.config = config or LLMBrainConfig(model=model if isinstance(model, str) else "test")
        self.action_types = action_types
        self.persona = persona
        self.memory = memory if memory is not None else MemoryStream()
        self.retriever = retriever
        self.planner = planner
        self.skills = skills
        self._inbox: list[str] = []

        # Resolve model string → pydantic-ai model object.
        # "openrouter:<name>" builds an OpenRouterModel; everything else passes through.
        resolved_model = _build_pydantic_ai_model(model)

        output_type = _discriminated_union(action_types)
        self.agent: PydanticAgent[BrainDeps, Any] = PydanticAgent(
            resolved_model,
            output_type=output_type,
            deps_type=BrainDeps,
            instructions=instructions or DEFAULT_INSTRUCTIONS,
            retries=self.config.retries,
        )

        self.reflection: ReflectionEngine | None = None
        if summarizer is not None:
            self.reflection = ReflectionEngine(
                summarizer, every_n_records=max(5, self.config.reflect_every // 2)
            )
        self._observations_since_reflect = 0
        self._skill_queue: list[Action] = []

    async def decide(self, observation: Observation) -> Action:
        if not self._skill_queue and self.skills is not None:
            skill = self.skills.find(
                observation.render(),
                require_verified=True,
            )
            if skill is not None:
                self._skill_queue = [
                    _action_from_step(step, self.action_types) for step in skill.steps if step
                ][:8]
                await self.memory.add(f"Reusing skill '{skill.name}'", kind="plan")

        if self._skill_queue:
            return self._skill_queue.pop(0)

        for message in self._inbox:
            await self.memory.add(
                f"[human] {message}", kind="human_chat", sim_tick=observation.tick
            )

        await self.memory.add(
            f"Observed: {observation.render()}",
            kind="observation",
            sim_tick=observation.tick,
        )
        self._observations_since_reflect += 1

        memories = self._retrieve_memories(observation)
        plan_text = self._plan_text()
        deps = BrainDeps(
            persona=self.persona,
            observation=observation.model_dump(),
            observation_text=observation.render(),
            memories=memories,
            plan=plan_text,
            inbox=list(self._inbox),
            tick=observation.tick,
        )
        self._inbox.clear()

        result = await self.agent.run(
            f"Current observation:\n{observation.render()}\n\nChoose your next action.",
            deps=deps,
        )
        action = result.output
        if not isinstance(action, Action):
            raise TypeError(f"LLM produced non-Action output: {type(action).__name__}")
        return action

    async def update(self, step_result: StepResult) -> None:
        summary = "ok" if "error" not in step_result.info else str(step_result.info["error"])
        if "said" in step_result.info:
            summary = f"you said: {step_result.info['said']}"
        await self.memory.add(f"Last action result: {summary}", kind="action_result")
        if self.reflection and self._observations_since_reflect >= self.config.reflect_every:
            self._observations_since_reflect = 0
            try:
                insights = await self.reflection.reflect(self.memory)
                for insight in insights:
                    log.info("reflection insight: %s", insight)
            except Exception:
                log.exception("reflection failed")

    def on_human_message(self, sender: str, text: str) -> None:
        self._inbox.append(f"{sender} says to you: {text}")

    def _retrieve_memories(self, observation: Observation) -> list[str]:
        if self.retriever is None:
            return [r.content for r in self.memory.recent(self.config.memory_top_k)]
        hits = self.retriever.retrieve(observation.render(), top_k=self.config.memory_top_k)
        return [h.record.content for h in hits]

    def _plan_text(self) -> str | None:
        plan: Plan | None = getattr(self.planner, "current_plan", None) if self.planner else None
        return plan.render() if plan is not None else None


DEFAULT_INSTRUCTIONS = (
    "You are an agent inside a simulation. Given your persona, relevant "
    "memories, current plan, pending messages and the latest observation, "
    "choose exactly one next action. Stay in character."
)


def _discriminated_union(action_types: list[type[Action]]) -> Any:
    if len(action_types) == 1:
        return action_types[0]
    union = Union[tuple(action_types)]  # type: ignore[valid-type]  # noqa: UP007
    return Annotated[union, Field(discriminator="kind")]


def _action_from_step(step: dict[str, Any], action_types: list[type[Action]]) -> Action:
    for action_type in action_types:
        try:
            return action_type.model_validate(step)
        except Exception:
            continue
    return NoOpAction()
