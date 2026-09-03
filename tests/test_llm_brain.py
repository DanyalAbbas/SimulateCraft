"""LLM brain logic against pydantic-ai's offline TestModel/FunctionModel.

No real API calls: FunctionModel mocks the model client, exercising output
validation, retries, memory logging, and dependency injection.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import pytest

pytest.importorskip("pydantic_ai", reason="LLM extra not installed")

from simulatecraft.brains.llm import BrainDeps, LLMBrain, LLMBrainConfig
from simulatecraft.core import Action, Observation, StepResult
from simulatecraft.memory import HashingEmbedding, MemoryStream, Retriever


class MoveAction(Action):
    kind: Literal["move"] = "move"
    direction: Literal["up", "down", "left", "right", "stay"] = "stay"


class SayAction(Action):
    kind: Literal["say"] = "say"
    text: str = ""


def make_obs() -> Observation:
    return Observation(
        agent_id="maya",
        tick=1,
        data={"position": [2, 2], "goals_visible": [[4, 4]], "neighbors": {"leo": [3, 3]}},
    )


def function_model_from(responses: list[dict[str, Any]]):
    """Build a pydantic-ai FunctionModel emitting typed output-tool calls."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    state = {"call": 0}

    def pick_tool(info: Any, payload: dict[str, Any]) -> str:
        tools = list(info.output_tools)
        if len(tools) == 1:
            return tools[0].name
        kind = payload.get("kind")
        for tool in tools:
            props = getattr(tool, "parameters_json_schema", {}).get("properties", {})
            kind_spec = props.get("kind", {})
            if kind_spec.get("const") == kind or kind_spec.get("enum") == [kind]:
                return tool.name
        raise ValueError(f"no output tool matches kind {kind!r}")

    def handler(messages: Any, info: Any) -> Any:
        index = min(state["call"], len(responses) - 1)
        payload = responses[index]
        state["call"] += 1
        try:
            tool_name = pick_tool(info, payload)
            args = json.dumps(payload)
        except ValueError:
            tool_name = info.output_tools[0].name
            args = json.dumps(payload)
        return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=args)])

    return FunctionModel(handler), state


def monkeypatch_agent_run(brain: LLMBrain, output: Any) -> dict[str, Any]:
    """Replace brain.agent.run to capture prompts/deps without any model."""
    captured: dict[str, Any] = {}

    class FakeResult:
        pass

    async def fake_run(prompt: str, **kwargs: Any) -> FakeResult:
        captured["prompt"] = prompt
        captured["deps"] = kwargs.get("deps")
        result = FakeResult()
        result.output = output
        return result

    brain.agent.run = fake_run  # type: ignore[method-assign]
    return captured


async def test_valid_output_arrives_as_typed_action() -> None:
    model, _ = function_model_from([{"kind": "say", "text": "hello town"}])
    brain = LLMBrain(
        [MoveAction, SayAction], persona="p", model=model, config=LLMBrainConfig(retries=0)
    )
    action = await brain.decide(make_obs())
    assert isinstance(action, SayAction)
    assert action.text == "hello town"


async def test_discriminated_union_dispatches_by_kind() -> None:
    model, _ = function_model_from([{"kind": "move", "direction": "left"}])
    brain = LLMBrain(
        [MoveAction, SayAction], persona="p", model=model, config=LLMBrainConfig(retries=0)
    )
    action = await brain.decide(make_obs())
    assert isinstance(action, MoveAction)
    assert action.direction == "left"


async def test_schema_failure_recovers_on_retry() -> None:
    model, state = function_model_from(
        [
            {"kind": "teleport", "to": "the moon"},
            {"kind": "move", "direction": "up"},
        ]
    )
    brain = LLMBrain(
        [MoveAction, SayAction], persona="p", model=model, config=LLMBrainConfig(retries=2)
    )
    action = await brain.decide(make_obs())
    assert isinstance(action, MoveAction)
    assert state["call"] == 2


async def test_exhausted_retries_raise() -> None:
    from pydantic_core import ValidationError

    model, _ = function_model_from([{"kind": "teleport"}])
    brain = LLMBrain(
        [MoveAction, SayAction], persona="p", model=model, config=LLMBrainConfig(retries=0)
    )
    with pytest.raises((ValidationError, Exception)):
        await brain.decide(make_obs())


async def test_decide_and_update_log_to_memory() -> None:
    model, _ = function_model_from([{"kind": "say", "text": "hi"}])
    stream = MemoryStream()
    brain = LLMBrain(
        [MoveAction, SayAction],
        persona="p",
        model=model,
        config=LLMBrainConfig(),
        memory=stream,
    )
    await brain.decide(make_obs())
    await brain.update(StepResult(reward=0.05, info={"said": "hi"}))
    kinds = [r.kind for r in stream.all()]
    assert "observation" in kinds
    assert "action_result" in kinds


async def test_memories_injected_into_deps() -> None:
    stream = MemoryStream()
    for i in range(5):
        await stream.add(f"memory item {i}", kind="chat")
    retriever = Retriever(stream, HashingEmbedding())
    brain = LLMBrain(
        [MoveAction, SayAction],
        persona="I am Maya.",
        model="test",
        config=LLMBrainConfig(memory_top_k=3),
        memory=stream,
        retriever=retriever,
    )
    captured = monkeypatch_agent_run(brain, MoveAction())
    await brain.decide(make_obs())

    deps: BrainDeps = captured["deps"]
    assert isinstance(deps, BrainDeps)
    assert deps.persona == "I am Maya."
    assert 1 <= len(deps.memories) <= 3
    assert deps.observation_text
    assert "Persona:" in captured["prompt"]
    assert "I am Maya." in captured["prompt"]
    assert "Current observation" in captured["prompt"]


async def test_human_message_enters_inbox_then_deps() -> None:
    brain = LLMBrain(
        [MoveAction, SayAction],
        persona="p",
        model="test",
        config=LLMBrainConfig(),
    )
    captured = monkeypatch_agent_run(brain, SayAction(text="oh no!"))
    brain.on_human_message("visitor", "the fountain is haunted")

    await brain.decide(make_obs())
    deps = captured["deps"]
    assert any("haunted" in m for m in deps.inbox)
    assert "Pending messages" in captured["prompt"]
    assert "haunted" in captured["prompt"]

    await brain.decide(make_obs())
    second_deps = captured["deps"]
    assert second_deps.inbox == []


async def test_testmodel_default_produces_action() -> None:
    brain = LLMBrain([MoveAction, SayAction], persona="p", model="test")
    action = await brain.decide(make_obs())
    assert isinstance(action, (MoveAction, SayAction))


async def test_skill_queue_short_circuits_llm() -> None:
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    from simulatecraft.skills.registry import SkillRegistry

    calls = {"n": 0}

    def counting_handler(messages: Any, info: Any) -> Any:
        calls["n"] += 1
        tool = "final_result_MoveAction"
        return ModelResponse(
            parts=[
                ToolCallPart(tool_name=tool, args=json.dumps({"kind": "move", "direction": "stay"}))
            ]
        )

    registry = SkillRegistry(HashingEmbedding(), similarity_threshold=-1.0)
    registry.register(
        "go_east",
        "walk toward the fountain by heading east",
        [{"kind": "move", "direction": "right"}, {"kind": "move", "direction": "right"}],
    )
    registry.skills[0].verified = True

    obs_renderer = "reach the fountain"
    brain = LLMBrain(
        [MoveAction, SayAction],
        persona="p",
        model=FunctionModel(counting_handler),
        config=LLMBrainConfig(),
        skills=registry,
    )

    class FixedObs(Observation):
        def render(self) -> str:
            return obs_renderer

    obs = FixedObs(agent_id="maya", tick=1, data={})
    a1 = await brain.decide(obs)
    a2 = await brain.decide(obs)
    assert isinstance(a1, MoveAction) and a1.direction == "right"
    assert isinstance(a2, MoveAction) and a2.direction == "right"
    assert calls["n"] == 0


async def test_retriever_none_falls_back_to_recent_memory() -> None:
    model, _ = function_model_from([{"kind": "say", "text": "ok"}])
    stream = MemoryStream()
    for i in range(8):
        await stream.add(f"note {i}")
    brain = LLMBrain(
        [MoveAction, SayAction],
        persona="p",
        model=model,
        config=LLMBrainConfig(memory_top_k=4),
        memory=stream,
        retriever=None,
    )
    memories = brain._retrieve_memories(make_obs())
    assert len(memories) == 4
    assert memories[-1] == "note 7"


def test_openai_compatible_gateway_builds_chat_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic_ai.models.openai import OpenAIChatModel

    from simulatecraft.brains.llm import _build_pydantic_ai_model

    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:20128/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    bare = _build_pydantic_ai_model("oc/mimo-v2.5-free")
    assert isinstance(bare, OpenAIChatModel)
    assert bare.model_name == "oc/mimo-v2.5-free"

    prefixed = _build_pydantic_ai_model("openai:oc/mimo-v2.5-free")
    assert isinstance(prefixed, OpenAIChatModel)

    explicit = _build_pydantic_ai_model("openai-compatible:kr/claude-sonnet-4.5")
    assert isinstance(explicit, OpenAIChatModel)
    assert explicit.model_name == "kr/claude-sonnet-4.5"

    # Native providers must not be rewritten when a gateway URL is present.
    assert _build_pydantic_ai_model("groq:openai/gpt-oss-120b") == "groq:openai/gpt-oss-120b"
    assert _build_pydantic_ai_model("test") == "test"
