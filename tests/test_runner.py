"""Runner loop behavior: pacing, pause/step, timeouts, membership events."""

from __future__ import annotations

import asyncio
import contextlib

from simulatecraft.core import (
    Agent,
    AgentRemoved,
    AgentState,
    BrainFailed,
    HumanChat,
    HumanControl,
    Observation,
)
from helpers import FixedAction, SayAction, ScriptedBrain, StubEnvironment


async def test_runner_emits_tick_events(make_runner) -> None:
    runner, _ = make_runner(
        max_ticks=3,
        stop_when_env_empty=False,
        agents=[
            Agent(
                id="fx2",
                name="F",
                brain=ScriptedBrain(lambda obs: FixedAction()),
                state=AgentState(),
            )
        ],
    )
    seen: list[str] = []
    runner.bus.subscribe(lambda e: seen.append(e.kind))
    await runner.start()
    assert seen.count("env.ticked") == 3
    assert seen[0] == "simulation.started"
    assert seen[-1] == "simulation.ended"


async def test_agent_acted_event_carries_action_and_reward(make_runner) -> None:
    runner, _ = make_runner(
        agents=[
            Agent(
                id="sayer",
                name="S",
                brain=ScriptedBrain(lambda obs: SayAction(text="hi there")),
                state=AgentState(),
            )
        ],
        max_ticks=2,
        stop_when_env_empty=False,
    )
    acted: list[object] = []
    spoke: list[object] = []
    runner.bus.subscribe(lambda e: acted.append(e) if e.kind == "agent.acted" else None)
    runner.bus.subscribe(lambda e: spoke.append(e) if e.kind == "agent.spoke" else None)
    await runner.start()
    assert len(acted) == 2
    assert len(spoke) == 2


async def test_pause_resume_and_step_once(make_runner) -> None:
    runner, _ = make_runner(max_ticks=100)
    run_task = asyncio.create_task(runner.start())
    await asyncio.sleep(0.15)
    runner.request_pause()
    await asyncio.sleep(0.1)
    ticks_paused = runner.environment.tick_count

    await runner.step_once()
    assert runner.environment.tick_count == ticks_paused + 1

    runner.request_resume()
    await asyncio.sleep(0.2)
    runner.request_stop("test")
    with contextlib.suppress(Exception):
        await asyncio.wait_for(run_task, timeout=5)
    assert not runner.is_running


async def test_brain_failure_is_isolated_not_fatal(make_runner) -> None:
    class ExplodingBrain(ScriptedBrain):
        def decide(self, observation: Observation) -> FixedAction:  # type: ignore[override]
            raise RuntimeError("llm exploded")

    runner, _ = make_runner(
        agents=[
            Agent(
                id="bad",
                name="B",
                brain=ExplodingBrain(lambda o: FixedAction()),
                state=AgentState(),
            )
        ],
        max_ticks=3,
        stop_when_env_empty=False,
    )
    failures: list[BrainFailed] = []
    runner.bus.subscribe(lambda e: failures.append(e) if isinstance(e, BrainFailed) else None)
    await runner.start()
    assert len(failures) >= 1
    assert "exploded" in failures[0].error


async def test_decision_timeout_produces_noop_and_failure_event(make_runner) -> None:
    class SlowBrain(ScriptedBrain):
        async def decide(self, observation: Observation) -> FixedAction:
            await asyncio.sleep(10)
            return FixedAction()

    runner, _ = make_runner(
        agents=[
            Agent(
                id="slow",
                name="S",
                brain=SlowBrain(lambda o: FixedAction()),
                state=AgentState(),
            )
        ],
        max_ticks=1,
        decision_timeout=0.05,
        stop_when_env_empty=False,
    )
    failures: list[BrainFailed] = []
    runner.bus.subscribe(lambda e: failures.append(e) if isinstance(e, BrainFailed) else None)
    await runner.start()
    assert any("timed out" in f.error for f in failures)


async def test_membership_events_on_agent_exit() -> None:
    from simulatecraft.core import Runner, RunnerConfig

    env = StubEnvironment()
    env.exit_on_say = True
    runner = Runner(environment=env, config=RunnerConfig(max_ticks=40))
    runner.add_agent(
        Agent(
            id="runner",
            name="R",
            brain=ScriptedBrain(lambda obs: SayAction(text="bye")),
            state=AgentState(),
        )
    )
    removed: list[str] = []
    runner.bus.subscribe(
        lambda e: removed.append(e.agent_id) if isinstance(e, AgentRemoved) else None
    )
    await runner.start()
    assert "runner" in removed


async def test_human_chat_reaches_target_agent_hook(make_runner) -> None:
    received: list[tuple[str, str]] = []

    class ReceivingBrain(ScriptedBrain):
        def on_human_message(self, sender: str, text: str) -> None:
            received.append((sender, text))

    runner, _ = make_runner(
        agents=[
            Agent(
                id="maya",
                name="M",
                brain=ReceivingBrain(lambda o: FixedAction()),
                state=AgentState(),
            )
        ],
        max_ticks=10_000,
        stop_when_env_empty=False,
    )
    run_task = asyncio.create_task(runner.start())
    runner.bus.publish_inbound(
        HumanChat(sender="visitor", target_agent_id="maya", text="hello maya")
    )
    for _ in range(100):
        if received:
            break
        await asyncio.sleep(0.02)
    runner.request_stop()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(run_task, timeout=3)
    assert received == [("visitor", "hello maya")]


async def test_control_commands_pause_and_stop(make_runner) -> None:
    runner, _ = make_runner(max_ticks=10_000)
    run_task = asyncio.create_task(runner.start())
    runner.bus.publish_inbound(HumanControl(command="stop"))
    await asyncio.wait_for(run_task, timeout=3)
    assert not runner.is_running
