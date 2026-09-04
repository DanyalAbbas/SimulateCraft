"""Runtime agent create/remove helpers used by the live viewer API."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from simulatecraft.brains.llm import resolve_model
from simulatecraft.core import Agent, AgentState, Runner
from simulatecraft.examples.minecraft_explorer.agents import custom

_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{1,31}$")
_Gamemode = Literal["survival", "creative", "adventure", "spectator"]


class AgentCreateRequest(BaseModel):
    """Payload for POST /api/agents and WS type=agent_create."""

    id: str | None = Field(default=None, description="Stable agent id; auto-generated if omitted")
    username: str = Field(..., min_length=1, max_length=16)
    persona: str = Field(default="A Minecraft adventurer.", max_length=4000)
    instructions: str | None = Field(
        default=None,
        max_length=8000,
        description="Optional system-prompt override for the LLM brain",
    )
    goal: str = Field(default="survive and explore", max_length=500)
    model: str | None = None
    spawn_x: float | None = None
    spawn_y: float | None = None
    spawn_z: float | None = None
    gamemode: _Gamemode | None = None
    op: bool = False
    spectator: bool = False


class AgentCreateResponse(BaseModel):
    ok: bool = True
    agent_id: str
    username: str


def _slug_username(username: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", username.strip())[:24]
    if not slug or not slug[0].isalpha():
        slug = f"bot_{slug or 'agent'}"
    return slug.lower()


def _unique_id(runner: Runner, base: str) -> str:
    candidate = base
    n = 2
    existing = {a.id for a in runner.agents} | set(runner.environment.agent_ids)
    while candidate in existing:
        candidate = f"{base}_{n}"
        n += 1
    return candidate


async def create_agent(runner: Runner, req: AgentCreateRequest) -> AgentCreateResponse:
    env = runner.environment
    spawn = getattr(env, "spawn_bot", None)
    if not callable(spawn):
        raise ValueError("environment does not support runtime agent spawn")

    agent_id = req.id.strip() if req.id else _slug_username(req.username)
    if not _ID_RE.match(agent_id):
        raise ValueError("agent id must be 2–32 chars, start with a letter, [A-Za-z0-9_-]")
    agent_id = _unique_id(runner, agent_id)

    gamemode = req.gamemode
    if req.spectator:
        gamemode = "spectator"

    model = (req.model or resolve_model()).strip()
    await spawn(
        agent_id,
        username=req.username.strip()[:16],
        goal=req.goal,
        spawn_x=req.spawn_x,
        spawn_y=req.spawn_y,
        spawn_z=req.spawn_z,
        gamemode=gamemode,
        op=req.op or req.spectator,
        persona=req.persona,
    )

    try:
        brain = custom(
            persona=req.persona,
            goal=req.goal,
            model=model,
            instructions=req.instructions,
        )
        runner.add_agent(
            Agent(
                id=agent_id,
                name=req.username.strip()[:16],
                brain=brain,
                state=AgentState(
                    data={
                        "role": "custom",
                        "persona": req.persona,
                        "goal": req.goal,
                        "gamemode": gamemode,
                        "op": req.op or req.spectator,
                    }
                ),
            )
        )
    except Exception:
        despawn = getattr(env, "despawn_bot", None)
        if callable(despawn):
            await despawn(agent_id)
        raise

    return AgentCreateResponse(agent_id=agent_id, username=req.username.strip()[:16])


async def delete_agent(runner: Runner, agent_id: str) -> dict[str, Any]:
    env = runner.environment
    despawn = getattr(env, "despawn_bot", None)
    removed = runner.remove_agent(agent_id)
    if callable(despawn):
        await despawn(agent_id)
    elif agent_id in env.agent_ids:
        env.unregister_agent(agent_id)
    if not removed and agent_id not in env.agent_ids:
        raise ValueError(f"unknown agent {agent_id!r}")
    return {"ok": True, "agent_id": agent_id}
