"""Server: REST control/state + websocket broadcast with inbound messages."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from simulatecraft.core import Agent, AgentState, Runner, RunnerConfig
from simulatecraft.server.app import create_app
from helpers import FixedAction, ScriptedBrain, StubEnvironment


@pytest.fixture()
def client() -> TestClient:
    runner = _build_runner()
    app = create_app(runner)
    with TestClient(app) as test_client:
        yield test_client


def _build_runner() -> Runner:
    env = StubEnvironment()
    runner = Runner(environment=env, config=RunnerConfig(max_ticks=500, tick_rate=50))
    runner.add_agent(
        Agent(
            id="alice",
            name="Alice",
            brain=ScriptedBrain(lambda obs: FixedAction()),
            state=AgentState(),
        )
    )
    env.reset()
    env.register_agent("alice")
    return runner


def test_state_endpoint(client: TestClient) -> None:
    response = client.get("/api/state")
    assert response.status_code == 200
    payload = response.json()
    assert "alice" in payload["snapshot"]["agents"]
    assert payload["snapshot"]["world"]["stub"] is True
    assert set(payload["status"]) == {"running", "paused", "tick"}


def test_index_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert b"SimulateCraft" in response.content


def test_control_endpoint_pause_resume(client: TestClient) -> None:
    assert client.post("/api/control/pause").status_code == 200
    state = client.get("/api/state").json()["status"]
    assert state["paused"] is True
    assert client.post("/api/control/resume").status_code == 200


def test_chat_endpoint_queues_inbound(client: TestClient) -> None:
    response = client.post("/api/chat", params={"text": "hi", "target": "alice"})
    assert response.status_code == 200


def test_websocket_receives_events_and_accepts_chat(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "state"

        ws.send_json({"type": "chat", "text": "hello alice", "target": "alice"})

        got_chat = False
        for _ in range(30):
            message = ws.receive_json()
            if message["type"] == "event" and message["event"]["kind"] == "human.chat":
                got_chat = True
                break
        assert got_chat
