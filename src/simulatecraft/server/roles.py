"""Assign OP / spectator (and related) roles to human Minecraft watchers via RCON.

These roles are for people observing agent behaviour in-world — never for AI agents.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from simulatecraft.minecraft.rcon import RconError, run_commands

WatcherRole = Literal["op", "deop", "spectator", "survival", "creative", "adventure"]


class WatcherRoleRequest(BaseModel):
    """Grant a role to a human Minecraft username."""

    username: str = Field(..., min_length=1, max_length=16)
    role: WatcherRole


class WatcherRoleResponse(BaseModel):
    ok: bool = True
    username: str
    role: WatcherRole
    commands: list[str]
    responses: list[str] = Field(default_factory=list)
    message: str = ""


def _player_missing(text: str) -> bool:
    lowered = text.lower()
    return any(
        needle in lowered
        for needle in (
            "no player was found",
            "that player cannot be found",
            "no entity was found",
            "player not found",
        )
    )


def assign_watcher_role(req: WatcherRoleRequest) -> WatcherRoleResponse:
    name = req.username.strip()[:16]
    if not name:
        raise ValueError("username is required")

    commands: list[str]
    if req.role == "op":
        commands = [f"op {name}"]
    elif req.role == "deop":
        commands = [f"deop {name}"]
    elif req.role == "spectator":
        # OP first so they can use commands; gamemode needs them online.
        commands = [f"op {name}", f"gamemode spectator {name}"]
    else:
        commands = [f"gamemode {req.role} {name}"]

    try:
        responses = run_commands(commands)
    except RconError as exc:
        raise ValueError(str(exc)) from exc

    joined = "\n".join(responses)
    if req.role in {"spectator", "survival", "creative", "adventure"} and _player_missing(joined):
        hint = (
            f"Minecraft does not see player {name!r} online. "
            "Join the server with that exact username, then click Assign role again."
        )
        if req.role == "spectator":
            opped = any(("operator" in r.lower()) or ("opped" in r.lower()) for r in responses)
            if opped:
                hint = (
                    f"Made {name} an operator, but they are not online yet so spectator "
                    "mode could not be applied. Join the Minecraft server, then Assign role again."
                )
        raise ValueError(hint)

    message = f"Assigned {req.role} to {name}."
    if responses:
        message = f"{message} Server: {' | '.join(r for r in responses if r)}"

    return WatcherRoleResponse(
        username=name,
        role=req.role,
        commands=commands,
        responses=[str(r) for r in responses],
        message=message,
    )


def role_payload(result: WatcherRoleResponse) -> dict[str, Any]:
    return result.model_dump()
