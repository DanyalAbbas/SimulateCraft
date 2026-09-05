"""Server: REST control/state + websocket broadcast with inbound messages."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from helpers import FixedAction, ScriptedBrain, StubEnvironment
from simulatecraft.core import Agent, AgentState, Runner, RunnerConfig
from simulatecraft.server.app import create_app


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
    assert set(payload["status"]) == {"running", "paused", "tick", "tick_rate", "max_ticks"}
    assert payload["status"]["tick_rate"] == 50
    assert payload["status"]["max_ticks"] == 500


def test_index_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert b"SimulateCraft" in response.content


def test_control_endpoint_pause_resume(client: TestClient) -> None:
    assert client.post("/api/control/pause").status_code == 200
    state = client.get("/api/state").json()["status"]
    assert state["paused"] is True
    assert client.post("/api/control/resume").status_code == 200


def test_control_tick_rate_and_extend(client: TestClient) -> None:
    # Fixture starts at tick_rate=50; doubling exceeds the 50 tps cap → unlimited.
    faster = client.post("/api/control/faster")
    assert faster.status_code == 200
    assert faster.json()["tick_rate"] is None

    set_rate = client.post("/api/control/set_tick_rate", json={"value": 2})
    assert set_rate.status_code == 200
    assert set_rate.json()["tick_rate"] == 2.0
    assert client.get("/api/state").json()["status"]["tick_rate"] == 2.0

    slower = client.post("/api/control/slower")
    assert slower.status_code == 200
    assert slower.json()["tick_rate"] == 1.0

    extended = client.post("/api/control/extend_ticks", json={"n": 250})
    assert extended.status_code == 200
    assert extended.json()["max_ticks"] == 750
    assert client.get("/api/state").json()["status"]["max_ticks"] == 750


def test_control_step_n(client: TestClient) -> None:
    before = client.get("/api/state").json()["status"]["tick"]
    stepped = client.post("/api/control/step", json={"n": 3})
    assert stepped.status_code == 200
    assert stepped.json()["steps"] == 3
    after = client.get("/api/state").json()["status"]["tick"]
    assert after == before + 3


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


def test_control_stop_reset_set_max(client: TestClient) -> None:
    assert client.post("/api/control/set_max_ticks", json={"value": 900}).status_code == 200
    assert client.get("/api/state").json()["status"]["max_ticks"] == 900
    assert client.post("/api/control/reset").status_code == 200
    assert client.post("/api/control/stop").status_code == 200


def test_list_agents(client: TestClient) -> None:
    body = client.get("/api/agents").json()
    assert "alice" in body["agents"]


def test_watcher_role_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from simulatecraft.server.roles import WatcherRoleResponse

    monkeypatch.setattr(
        "simulatecraft.server.app.assign_watcher_role",
        lambda req: WatcherRoleResponse(
            username=req.username,
            role=req.role,
            commands=[f"op {req.username}"],
            responses=["ok"],
            message="done",
        ),
    )
    ok = client.post("/api/watchers/role", json={"username": "Steve", "role": "op"})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    monkeypatch.setattr(
        "simulatecraft.server.app.assign_watcher_role",
        lambda req: (_ for _ in ()).throw(ValueError("bad")),
    )
    bad = client.post("/api/watchers/role", json={"username": "Steve", "role": "op"})
    assert bad.status_code == 400


def test_websocket_control_and_watcher(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from simulatecraft.server.roles import WatcherRoleResponse

    monkeypatch.setattr(
        "simulatecraft.server.app.assign_watcher_role",
        lambda req: WatcherRoleResponse(
            username=req.username,
            role=req.role,
            commands=[],
            message="ok",
        ),
    )
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "state"
        ws.send_json({"type": "control", "command": "pause"})
        ws.send_json({"type": "watcher_role", "username": "Steve", "role": "op"})
        got = False
        for _ in range(40):
            msg = ws.receive_json()
            if msg.get("type") == "watcher_role":
                got = True
                break
        assert got


def test_websocket_agent_lifecycle(client: TestClient) -> None:
    pytest.importorskip("pydantic_ai", reason="LLM extra not installed")
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "state"
        ws.send_json(
            {
                "type": "agent_create",
                "username": "Carl",
                "persona": "p",
                "goal": "g",
                "model": "test",
            }
        )
        created = None
        for _ in range(40):
            msg = ws.receive_json()
            if msg.get("type") == "agent_created":
                created = msg
                break
        assert created is not None
        agent_id = created["agent_id"]
        ws.send_json({"type": "agent_delete", "agent_id": agent_id})
        deleted = False
        for _ in range(40):
            msg = ws.receive_json()
            if msg.get("type") == "agent_deleted":
                deleted = True
                break
        assert deleted


async def test_simulation_server_stop() -> None:
    from simulatecraft.server.app import SimulationServer

    runner = _build_runner()
    server = SimulationServer(runner, host="127.0.0.1", port=8765)
    async with server:
        # Don't start the real loop (would run until max_ticks); just stop cleanly.
        await server.stop()
    assert not runner.is_running


def test_create_and_delete_agent_via_rest(client: TestClient) -> None:
    pytest.importorskip("pydantic_ai", reason="LLM extra not installed")
    response = client.post(
        "/api/agents",
        json={
            "username": "Bea",
            "persona": "A careful builder.",
            "goal": "build a hut",
            "model": "test",
            "spawn_x": 10,
            "spawn_y": 64,
            "spawn_z": -4,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["username"] == "Bea"
    agent_id = body["agent_id"]

    state = client.get("/api/state").json()
    assert agent_id in state["snapshot"]["agents"]

    deleted = client.delete(f"/api/agents/{agent_id}")
    assert deleted.status_code == 200
    state = client.get("/api/state").json()
    assert agent_id not in state["snapshot"]["agents"]
