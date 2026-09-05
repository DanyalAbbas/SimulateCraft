"""Unit tests for watcher role assignment."""

from __future__ import annotations

import pytest

from simulatecraft.minecraft.rcon import RconError
from simulatecraft.server.roles import (
    WatcherRoleRequest,
    assign_watcher_role,
    role_payload,
)


def test_assign_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "simulatecraft.server.roles.run_commands",
        lambda cmds: [f"done:{c}" for c in cmds],
    )
    result = assign_watcher_role(WatcherRoleRequest(username=" Steve ", role="op"))
    assert result.username == "Steve"
    assert result.commands == ["op Steve"]
    assert "Assigned op" in result.message
    assert role_payload(result)["ok"] is True


def test_assign_spectator_and_gamemodes(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def capture(cmds: list[str]) -> list[str]:
        seen.append(cmds)
        return ["Made Steve a server operator", "Set game mode"]

    monkeypatch.setattr("simulatecraft.server.roles.run_commands", capture)

    assign_watcher_role(WatcherRoleRequest(username="Steve", role="spectator"))
    assert seen[-1] == ["op Steve", "gamemode spectator Steve"]

    assign_watcher_role(WatcherRoleRequest(username="Steve", role="creative"))
    assert seen[-1] == ["gamemode creative Steve"]

    assign_watcher_role(WatcherRoleRequest(username="Steve", role="deop"))
    assert seen[-1] == ["deop Steve"]


def test_empty_username() -> None:
    with pytest.raises(ValueError, match="required"):
        assign_watcher_role(WatcherRoleRequest(username="   ", role="op"))


def test_rcon_error_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "simulatecraft.server.roles.run_commands",
        lambda cmds: (_ for _ in ()).throw(RconError("down")),
    )
    with pytest.raises(ValueError, match="down"):
        assign_watcher_role(WatcherRoleRequest(username="Steve", role="op"))


def test_player_missing_spectator_with_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "simulatecraft.server.roles.run_commands",
        lambda cmds: ["Opped Steve", "No player was found"],
    )
    with pytest.raises(ValueError, match="not online yet"):
        assign_watcher_role(WatcherRoleRequest(username="Steve", role="spectator"))


def test_player_missing_survival(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "simulatecraft.server.roles.run_commands",
        lambda cmds: ["That player cannot be found"],
    )
    with pytest.raises(ValueError, match="does not see player"):
        assign_watcher_role(WatcherRoleRequest(username="Steve", role="survival"))
