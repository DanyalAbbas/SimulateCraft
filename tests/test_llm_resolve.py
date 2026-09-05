"""Additional LLMBrain / resolve_model coverage."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from simulatecraft.brains import llm as llm_mod
from simulatecraft.brains.llm import (
    BrainDeps,
    _action_from_step,
    _build_pydantic_ai_model,
    _decision_prompt,
    _make_openai_compatible_model,
    resolve_model,
)
from simulatecraft.core.schemas import Action, NoOpAction, StepResult
from simulatecraft.memory.stream import MemoryStream


class MoveAction(Action):
    kind: str = "move"


def test_resolve_model_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_mod, "load_dotenv", lambda *a, **k: None, raising=False)
    from dotenv import load_dotenv

    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)

    monkeypatch.setenv("SIMULATECRAFT_MODEL", "groq:custom")
    assert resolve_model() == "groq:custom"

    monkeypatch.delenv("SIMULATECRAFT_MODEL", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert resolve_model().startswith("groq:")

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    assert resolve_model().startswith("openrouter:")

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert resolve_model() == "test"


def test_openai_compatible_requires_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    with pytest.raises(OSError, match="OPENAI_BASE_URL"):
        _make_openai_compatible_model("oc/x")


def test_openrouter_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(OSError, match="OPENROUTER_API_KEY"):
        llm_mod._make_openrouter_model("meta-llama/x")


def test_openrouter_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    fake_model = object()
    fake_provider = object()

    class FakeProvider:
        def __init__(self, **kwargs: Any) -> None:
            pass

    class FakeModel:
        def __init__(self, name: str, provider: Any = None) -> None:
            self.name = name

    monkeypatch.setattr(
        "pydantic_ai.providers.openrouter.OpenRouterProvider",
        FakeProvider,
    )
    monkeypatch.setattr(
        "pydantic_ai.models.openrouter.OpenRouterModel",
        FakeModel,
    )
    model = llm_mod._make_openrouter_model("meta-llama/x")
    assert isinstance(model, FakeModel)
    built = _build_pydantic_ai_model("openrouter:meta-llama/x")
    assert isinstance(built, FakeModel)


def test_build_passthrough_object() -> None:
    sentinel = object()
    assert _build_pydantic_ai_model(sentinel) is sentinel


def test_action_from_step_and_prompt() -> None:
    action = _action_from_step({"kind": "move"}, [MoveAction])
    assert isinstance(action, MoveAction)
    fallback = _action_from_step({"not": "an action"}, [MoveAction])
    assert isinstance(fallback, NoOpAction)

    deps = BrainDeps(
        persona="p",
        observation_text="obs",
        memories=["m1"],
        plan="do stuff",
        inbox=["hello"],
        tick=1,
    )
    prompt = _decision_prompt(deps)
    assert "Pending messages" in prompt
    assert "do stuff" in prompt
    assert "m1" in prompt


async def test_update_failure_and_reflection(monkeypatch: pytest.MonkeyPatch) -> None:
    from simulatecraft.brains.llm import LLMBrain, LLMBrainConfig

    class FakeReflection:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def reflect(self, memory: Any) -> list[str]:
            return ["insight"]

    brain = LLMBrain(
        [MoveAction],
        persona="p",
        model="test",
        config=LLMBrainConfig(model="test", reflect_every=1),
        memory=MemoryStream(),
        summarizer=lambda texts: "sum",
    )
    brain.reflection = FakeReflection()  # type: ignore[assignment]
    brain._observations_since_reflect = 1
    await brain.update(StepResult(info={"ok": False, "action": "move", "reason": "blocked"}))
    await brain.update(StepResult(info={"said": "hi"}))

    async def boom(memory: Any) -> list[str]:
        raise RuntimeError("reflect fail")

    brain.reflection.reflect = boom  # type: ignore[method-assign]
    brain._observations_since_reflect = 1
    await brain.update(StepResult(info={"error": "x"}))
