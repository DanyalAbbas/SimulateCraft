"""Tests for world rules, boundaries, and zip import helpers."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from simulatecraft.minecraft import world_settings as ws


def test_boundaries_clamp_and_contains_square() -> None:
    b = ws.WorldBoundaries(enabled=True, min_x=-10, max_x=10, min_z=-5, max_z=5)
    # Forced square: shorter Z side expands to match X.
    assert b.side_length == 20
    assert b.min_z == -10
    assert b.max_z == 10
    assert b.contains(0, 0)
    assert not b.contains(20, 0)
    assert b.clamp(20, 9) == (10.0, 9.0)
    assert len(b.corners) == 4


def test_boundaries_from_legacy_vertices() -> None:
    b = ws.WorldBoundaries(
        enabled=True,
        vertices=[
            ws.CornerPin(x=-20, z=-10),
            ws.CornerPin(x=30, z=-8),
            ws.CornerPin(x=25, z=40),
            ws.CornerPin(x=-15, z=35),
        ],
    )
    assert b.side_length == 50
    assert b.min_x == -20
    assert b.max_x == 30
    assert b.min_z == -10
    assert b.max_z == 40
    assert len(b.corners) == 4
    assert b.contains(0, 0)
    assert not b.contains(100, 100)


def test_migrate_corners_to_square() -> None:
    b = ws.WorldBoundaries(
        enabled=True,
        corners=[
            ws.CornerPin(x=0, z=0),
            ws.CornerPin(x=10, z=0),
            ws.CornerPin(x=10, z=10),
        ],
    )
    assert len(b.corners) == 4
    assert b.side_length == 10
    assert b.contains(5, 5)
    assert not b.contains(20, 20)


def test_worldborder_commands() -> None:
    cmds = ws.worldborder_commands_for_aabb(min_x=-10, max_x=10, min_z=-5, max_z=5)
    assert any(c.startswith("worldborder center") for c in cmds)
    assert any(c.startswith("worldborder set") for c in cmds)
    assert len(cmds) <= 6


def test_barrier_wall_commands_legacy() -> None:
    cmds = ws.barrier_wall_commands(
        min_x=0, max_x=10, min_z=0, max_z=10, y_min=60, y_max=65, block="barrier"
    )
    assert len(cmds) >= 4
    assert all(c.startswith("fill ") and c.endswith(" barrier") for c in cmds)


def test_rcon_commands_for_boundaries_uses_worldborder() -> None:
    prev = ws.WorldBoundaries(
        enabled=True,
        place_barriers=True,
        barriers_built=True,
        last_barrier_min_x=0,
        last_barrier_max_x=5,
        last_barrier_min_z=0,
        last_barrier_max_z=5,
        last_barrier_y_min=60,
        last_barrier_y_max=70,
    )
    nxt = ws.WorldBoundaries(
        enabled=True,
        place_barriers=True,
        min_x=-10,
        max_x=10,
        min_z=-10,
        max_z=10,
    )
    cmds = ws.rcon_commands_for_boundaries(nxt, previous=prev)
    assert any(c.startswith("worldborder") for c in cmds)
    assert sum(1 for c in cmds if c.startswith("worldborder")) <= 5
    # Must not spam hundreds of per-cell fills for the new border.
    assert sum(1 for c in cmds if c.endswith(" barrier")) == 0


def test_boundaries_swap_unordered() -> None:
    b = ws.WorldBoundaries(enabled=True, min_x=10, max_x=-10, min_z=5, max_z=-5)
    assert b.min_x == -10
    assert b.max_x == 10
    assert b.min_z == -10
    assert b.max_z == 10


def test_rcon_commands_no_night() -> None:
    rules = ws.WorldRules(allow_night=False, daylight_cycle=True, time_of_day="keep")
    cmds = ws.rcon_commands_for_rules(rules)
    assert "gamerule doDaylightCycle false" in cmds
    assert "time set day" in cmds
    assert "difficulty easy" in cmds


def test_rcon_commands_no_hostile_mobs() -> None:
    rules = ws.WorldRules(hostile_mobs=False)
    cmds = ws.rcon_commands_for_rules(rules)
    assert "difficulty peaceful" in cmds
    rules_on = ws.WorldRules(hostile_mobs=True)
    assert "difficulty easy" in ws.rcon_commands_for_rules(rules_on)


def test_rcon_commands_custom_day_length() -> None:
    rules = ws.WorldRules(allow_night=True, day_length_minutes=10, time_of_day="noon")
    cmds = ws.rcon_commands_for_rules(rules)
    assert "gamerule doDaylightCycle false" in cmds
    assert any(c.startswith("time set") for c in cmds)


def test_ticks_to_add() -> None:
    rate = ws.ticks_to_add_per_second(20)
    assert 19 < rate < 21


def test_save_load_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws, "data_dir", lambda: tmp_path)
    settings = ws.WorldSettings(
        rules=ws.WorldRules(allow_night=False, keep_inventory=True),
        boundaries=ws.WorldBoundaries(enabled=True, min_x=-32, max_x=32, min_z=-32, max_z=32),
    )
    ws.save_settings(settings)
    loaded = ws.load_settings()
    assert loaded.rules.allow_night is False
    assert loaded.boundaries.enabled is True
    assert loaded.boundaries.max_x == 32
    assert loaded.boundaries.side_length == 64


def test_import_world_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(ws, "minecraft_data_dir", lambda: tmp_path / "minecraft")

    world = tmp_path / "src_world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"fake")
    (world / "region").mkdir()

    zpath = tmp_path / "world.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(world / "level.dat", arcname="MySave/level.dat")
        zf.writestr("MySave/region/.keep", "")

    settings = ws.import_world_zip(zpath, label="MySave")
    assert settings.world.source == "imported"
    assert settings.world.label == "MySave"
    assert (tmp_path / "minecraft" / "world" / "level.dat").is_file()


def test_import_rejects_bad_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(ws, "minecraft_data_dir", lambda: tmp_path / "minecraft")
    zpath = tmp_path / "bad.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("readme.txt", "no level")
    with pytest.raises(ValueError, match="level.dat"):
        ws.import_world_zip(zpath)


def test_prepare_random_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(ws, "minecraft_data_dir", lambda: tmp_path / "minecraft")
    old = tmp_path / "minecraft" / "world"
    old.mkdir(parents=True)
    (old / "level.dat").write_bytes(b"x")
    settings, seed = ws.prepare_random_world(seed=42)
    assert seed == 42
    assert not old.exists()
    assert settings.world.source == "default"
    assert "42" in settings.world.label
