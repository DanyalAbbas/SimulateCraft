"""Runtime agent create/remove helpers used by the live viewer API."""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from simulatecraft.brains.llm import resolve_model
from simulatecraft.core import Agent, AgentState, Runner
from simulatecraft.examples.minecraft_explorer.agents import custom
from simulatecraft.server.persona import build_structured_persona, parse_roster_file
from simulatecraft.server.workshop_settings import load_workshop_settings

log = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{1,31}$")


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
    skin_url: str | None = Field(default=None, max_length=500)


class AgentCreateResponse(BaseModel):
    ok: bool = True
    agent_id: str
    username: str


class BulkAgentCreateResponse(BaseModel):
    ok: bool = True
    created: list[AgentCreateResponse] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    total_rows: int = 0


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

    model = (req.model or resolve_model()).strip()
    brain = custom(
        persona=req.persona,
        goal=req.goal,
        model=model,
        instructions=req.instructions,
    )
    state_data: dict[str, Any] = {
        "role": "custom",
        "persona": req.persona,
        "goal": req.goal,
    }
    if req.skin_url:
        state_data["skin_url"] = req.skin_url.strip()
    # Register on the runner *before* awaiting Minecraft spawn so a concurrent
    # tick cannot see an env agent_id with no Brain (that used to crash the loop).
    runner.add_agent(
        Agent(
            id=agent_id,
            name=req.username.strip()[:16],
            brain=brain,
            state=AgentState(data=state_data),
        )
    )
    try:
        await spawn(
            agent_id,
            username=req.username.strip()[:16],
            goal=req.goal,
            spawn_x=req.spawn_x,
            spawn_y=req.spawn_y,
            spawn_z=req.spawn_z,
            persona=req.persona,
        )
    except Exception:
        runner.remove_agent(agent_id)
        despawn = getattr(env, "despawn_bot", None)
        if callable(despawn):
            await despawn(agent_id)
        else:
            env.unregister_agent(agent_id)
        raise

    return AgentCreateResponse(agent_id=agent_id, username=req.username.strip()[:16])


def _unique_username(runner: Runner, base: str) -> str:
    """Avoid Minecraft username collisions among already-spawned bots."""
    existing = {(getattr(a, "name", None) or a.id).lower() for a in runner.agents}
    for cfg in getattr(runner.environment, "_bot_configs", {}).values():
        uname = getattr(cfg, "username", None)
        if uname:
            existing.add(str(uname).lower())
    candidate = base[:16]
    if candidate.lower() not in existing:
        return candidate
    for n in range(2, 100):
        suffix = str(n)
        trimmed = f"{base[: max(1, 16 - len(suffix))]}{suffix}"
        if trimmed.lower() not in existing:
            return trimmed
    return f"A{abs(hash(base)) % 10_000_000}"[:16]


async def create_agents_from_roster(
    runner: Runner,
    *,
    filename: str,
    data: bytes,
    spawn_x: float | None = None,
    spawn_y: float | None = None,
    spawn_z: float | None = None,
    model: str | None = None,
) -> BulkAgentCreateResponse:
    workshop = load_workshop_settings()
    profiles = parse_roster_file(filename, data, settings=workshop)
    created: list[AgentCreateResponse] = []
    errors: list[dict[str, str]] = []
    for idx, profile in enumerate(profiles, start=1):
        try:
            username = _unique_username(runner, profile.minecraft_username())
            persona = (
                profile.persona.strip() or build_structured_persona(profile, settings=workshop)
            )[:4000]
            req = AgentCreateRequest(
                username=username,
                persona=persona,
                goal=profile.default_goal(),
                model=model,
                spawn_x=spawn_x,
                spawn_y=spawn_y,
                spawn_z=spawn_z,
                skin_url=profile.skin_url or None,
            )
            created.append(await create_agent(runner, req))
        except Exception as exc:
            log.exception("bulk agent create failed for row %s (%s)", idx, profile.name)
            errors.append({"row": str(idx), "name": profile.name, "error": str(exc)})
    return BulkAgentCreateResponse(
        created=created,
        errors=errors,
        total_rows=len(profiles),
    )


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
