"""Persistent world settings: rules, boundaries, and imported Minecraft worlds.

Stored at ``data/world_settings.json`` (repo root). Applied to the live server
via RCON gamerules / time commands. World folders live under ``data/minecraft/``.
"""

from __future__ import annotations

import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

log = logging.getLogger(__name__)

TimePreset = Literal["keep", "day", "noon", "night", "midnight", "sunrise", "sunset"]

TIME_PRESET_COMMANDS: dict[str, str] = {
    "day": "time set day",
    "noon": "time set noon",
    "night": "time set night",
    "midnight": "time set midnight",
    "sunrise": "time set 0",
    "sunset": "time set 12000",
}


def repo_root() -> Path:
    """Locate the SimulateCraft repo root (has docker-compose.yml)."""
    here = Path(__file__).resolve()
    for path in [here, *here.parents]:
        if (path / "docker-compose.yml").exists() and (path / "pyproject.toml").exists():
            return path
    return Path.cwd()


def data_dir() -> Path:
    path = repo_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def minecraft_data_dir() -> Path:
    path = data_dir() / "minecraft"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return data_dir() / "world_settings.json"


class CornerPin(BaseModel):
    """One world XZ corner of a square play border."""

    x: float
    z: float


class WorldBoundaries(BaseModel):
    """Square play area on the map (axis-aligned).

    Drawn as a square on the viewer; physical border is vanilla ``worldborder``.
    Soft/hard enforce uses the same box.
    """

    enabled: bool = False
    # Legacy polygon field — folded into min/max on load.
    vertices: list[CornerPin] = Field(default_factory=list)
    corners: list[CornerPin] = Field(default_factory=list)
    min_x: float = -64
    max_x: float = 64
    min_z: float = -64
    max_z: float = 64
    enforce: Literal["off", "soft", "hard"] = "soft"
    # Kept for older saves; worldborder is always applied when enabled.
    place_barriers: bool = True
    wall_y_min: int = 60
    wall_height: int = Field(default=16, ge=1, le=64)
    barriers_built: bool = False
    last_barrier_vertices: list[CornerPin] = Field(default_factory=list)
    last_barrier_y_min: int | None = None
    last_barrier_y_max: int | None = None
    last_barrier_min_x: float | None = None
    last_barrier_max_x: float | None = None
    last_barrier_min_z: float | None = None
    last_barrier_max_z: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _migrate_polygon_to_box(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        verts = data.get("vertices") or data.get("corners") or []
        if len(verts) >= 2:
            xs = [float(v["x"] if isinstance(v, dict) else v.x) for v in verts]
            zs = [float(v["z"] if isinstance(v, dict) else v.z) for v in verts]
            data = {
                **data,
                "min_x": min(xs),
                "max_x": max(xs),
                "min_z": min(zs),
                "max_z": max(zs),
            }
        return data

    @model_validator(mode="after")
    def _normalize_square(self) -> WorldBoundaries:
        if self.min_x > self.max_x:
            self.min_x, self.max_x = self.max_x, self.min_x
        if self.min_z > self.max_z:
            self.min_z, self.max_z = self.max_z, self.min_z
        # Force square: expand shorter side around center.
        w = self.max_x - self.min_x
        d = self.max_z - self.min_z
        side = max(w, d, 1.0)
        cx = (self.min_x + self.max_x) / 2.0
        cz = (self.min_z + self.max_z) / 2.0
        half = side / 2.0
        self.min_x, self.max_x = cx - half, cx + half
        self.min_z, self.max_z = cz - half, cz + half
        self.corners = [
            CornerPin(x=self.min_x, z=self.min_z),
            CornerPin(x=self.max_x, z=self.min_z),
            CornerPin(x=self.max_x, z=self.max_z),
            CornerPin(x=self.min_x, z=self.max_z),
        ]
        self.vertices = list(self.corners)
        return self

    @property
    def wall_y_max(self) -> int:
        return self.wall_y_min + self.wall_height - 1

    @property
    def side_length(self) -> float:
        return max(self.max_x - self.min_x, self.max_z - self.min_z)

    def contains(self, x: float, z: float) -> bool:
        if not self.enabled:
            return True
        return self.min_x <= x <= self.max_x and self.min_z <= z <= self.max_z

    def clamp(self, x: float, z: float) -> tuple[float, float]:
        if not self.enabled:
            return x, z
        return (
            max(self.min_x, min(self.max_x, x)),
            max(self.min_z, min(self.max_z, z)),
        )

    def describe(self) -> str:
        if not self.enabled:
            return "Boundaries: none (full world)"
        return (
            f"Boundaries: square side={self.side_length:.0f} "
            f"X[{self.min_x:.0f}..{self.max_x:.0f}] "
            f"Z[{self.min_z:.0f}..{self.max_z:.0f}] "
            f"enforce={self.enforce} (worldborder ON)"
        )


def _fill_cmd(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, block: str) -> str:
    return f"fill {x1} {y1} {z1} {x2} {y2} {z2} {block}"


def _chunked_wall_fills(
    *,
    x1: int,
    z1: int,
    x2: int,
    z2: int,
    y_min: int,
    y_max: int,
    block: str,
    max_blocks: int = 30000,
) -> list[str]:
    """Split a thin wall fill so each command stays under Minecraft's fill limit."""
    height = y_max - y_min + 1
    dx = abs(x2 - x1) + 1
    dz = abs(z2 - z1) + 1
    length = max(dx, dz)
    per_slice = max(1, max_blocks // max(1, height))
    cmds: list[str] = []
    if dx >= dz:
        step = 1 if x2 >= x1 else -1
        start = x1
        remaining = length
        while remaining > 0:
            take = min(per_slice, remaining)
            end = start + (take - 1) * step
            cmds.append(_fill_cmd(start, y_min, z1, end, y_max, z2, block))
            start = end + step
            remaining -= take
    else:
        step = 1 if z2 >= z1 else -1
        start = z1
        remaining = length
        while remaining > 0:
            take = min(per_slice, remaining)
            end = start + (take - 1) * step
            cmds.append(_fill_cmd(x1, y_min, start, x2, y_max, end, block))
            start = end + step
            remaining -= take
    return cmds


def barrier_wall_commands(
    *,
    min_x: int,
    max_x: int,
    min_z: int,
    max_z: int,
    y_min: int,
    y_max: int,
    block: str = "barrier",
) -> list[str]:
    """Four vertical walls around an AABB (legacy fill clear only)."""
    if min_x > max_x:
        min_x, max_x = max_x, min_x
    if min_z > max_z:
        min_z, max_z = max_z, min_z
    if y_min > y_max:
        y_min, y_max = y_max, y_min
    cmds: list[str] = []
    cmds.extend(
        _chunked_wall_fills(
            x1=min_x, z1=min_z, x2=max_x, z2=min_z, y_min=y_min, y_max=y_max, block=block
        )
    )
    cmds.extend(
        _chunked_wall_fills(
            x1=min_x, z1=max_z, x2=max_x, z2=max_z, y_min=y_min, y_max=y_max, block=block
        )
    )
    cmds.extend(
        _chunked_wall_fills(
            x1=min_x, z1=min_z, x2=min_x, z2=max_z, y_min=y_min, y_max=y_max, block=block
        )
    )
    cmds.extend(
        _chunked_wall_fills(
            x1=max_x, z1=min_z, x2=max_x, z2=max_z, y_min=y_min, y_max=y_max, block=block
        )
    )
    return cmds


def barrier_clear_commands(bounds: WorldBoundaries) -> list[str]:
    """Best-effort clear of *legacy* fill-based barrier walls (pre-worldborder).

    Per-cell air fills are intentionally NOT used — they are hundreds of RCON
    commands and extremely slow. We only clear old AABB rectangle walls (≤4
    chunked fills). Leftover diagonal fill barriers from an older build may
    remain until removed manually or the world is reset.
    """
    cmds: list[str] = []
    if (
        bounds.last_barrier_min_x is not None
        and bounds.last_barrier_max_x is not None
        and bounds.last_barrier_min_z is not None
        and bounds.last_barrier_max_z is not None
        and bounds.last_barrier_y_min is not None
        and bounds.last_barrier_y_max is not None
    ):
        cmds.extend(
            barrier_wall_commands(
                min_x=int(bounds.last_barrier_min_x),
                max_x=int(bounds.last_barrier_max_x),
                min_z=int(bounds.last_barrier_min_z),
                max_z=int(bounds.last_barrier_max_z),
                y_min=bounds.last_barrier_y_min,
                y_max=bounds.last_barrier_y_max,
                block="air",
            )
        )
    elif bounds.last_barrier_vertices and bounds.last_barrier_y_min is not None:
        # Approximate clear: AABB of the old polygon edges only (4 walls).
        xs = [v.x for v in bounds.last_barrier_vertices]
        zs = [v.z for v in bounds.last_barrier_vertices]
        y_max = bounds.last_barrier_y_max
        if y_max is None:
            y_max = bounds.last_barrier_y_min
        cmds.extend(
            barrier_wall_commands(
                min_x=int(round(min(xs))),
                max_x=int(round(max(xs))),
                min_z=int(round(min(zs))),
                max_z=int(round(max(zs))),
                y_min=bounds.last_barrier_y_min,
                y_max=y_max,
                block="air",
            )
        )
    return cmds


def worldborder_commands_for_aabb(
    *,
    min_x: float,
    max_x: float,
    min_z: float,
    max_z: float,
) -> list[str]:
    """Vanilla worldborder covering the AABB (square; diameter = longer side)."""
    if min_x > max_x:
        min_x, max_x = max_x, min_x
    if min_z > max_z:
        min_z, max_z = max_z, min_z
    cx = (min_x + max_x) / 2.0
    cz = (min_z + max_z) / 2.0
    # Inclusive block span; worldborder size is the full width of the square.
    size = max(max_x - min_x, max_z - min_z) + 1.0
    size = max(1.0, size)
    return [
        f"worldborder center {cx:.3f} {cz:.3f}",
        f"worldborder set {size:.0f}",
        "worldborder damage amount 0.2",
        "worldborder damage buffer 2",
        "worldborder warning distance 5",
    ]


def worldborder_disable_commands() -> list[str]:
    """Reset to an effectively infinite border (vanilla default scale)."""
    return ["worldborder set 59999968"]


def rcon_commands_for_boundaries(
    bounds: WorldBoundaries,
    *,
    previous: WorldBoundaries | None = None,
) -> list[str]:
    """Apply play area via ``worldborder`` (few cmds) — not per-block fills.

    Optionally clears legacy fill-based walls from older SimulateCraft builds.
    """
    cmds: list[str] = []
    prev = previous or bounds
    if prev.barriers_built and (prev.last_barrier_vertices or prev.last_barrier_min_x is not None):
        # Only cheap AABB air clears — never hundreds of per-cell fills.
        cmds.extend(barrier_clear_commands(prev))

    if bounds.enabled:
        cmds.extend(
            worldborder_commands_for_aabb(
                min_x=bounds.min_x,
                max_x=bounds.max_x,
                min_z=bounds.min_z,
                max_z=bounds.max_z,
            )
        )
    else:
        cmds.extend(worldborder_disable_commands())
    return cmds


def apply_boundaries_via_rcon(
    bounds: WorldBoundaries | None = None,
    *,
    previous: WorldBoundaries | None = None,
) -> tuple[list[str], WorldBoundaries]:
    """Apply worldborder (and optional legacy clear); return results + metadata."""
    from .rcon import run_commands

    settings = load_settings()
    bounds = bounds or settings.boundaries
    previous = previous or settings.boundaries
    cmds = rcon_commands_for_boundaries(bounds, previous=previous)
    results: list[str] = []
    if cmds:
        results = run_commands(cmds)
    if bounds.enabled:
        bounds.barriers_built = True
        bounds.place_barriers = True
        # Track AABB used for worldborder (and for cheap legacy clear next time).
        bounds.last_barrier_vertices = []
        bounds.last_barrier_min_x = float(int(round(bounds.min_x)))
        bounds.last_barrier_max_x = float(int(round(bounds.max_x)))
        bounds.last_barrier_min_z = float(int(round(bounds.min_z)))
        bounds.last_barrier_max_z = float(int(round(bounds.max_z)))
        bounds.last_barrier_y_min = None
        bounds.last_barrier_y_max = None
    else:
        bounds.barriers_built = False
        bounds.place_barriers = True
        bounds.last_barrier_vertices = []
        bounds.last_barrier_y_min = None
        bounds.last_barrier_y_max = None
        bounds.last_barrier_min_x = None
        bounds.last_barrier_max_x = None
        bounds.last_barrier_min_z = None
        bounds.last_barrier_max_z = None
    return results, bounds


class WorldRules(BaseModel):
    """Server gamerules / time behaviour for simulations."""

    # If false: lock time to daytime (no night).
    allow_night: bool = True
    # Vanilla daylight cycle. Forced off when allow_night is false or day_length_minutes is set.
    daylight_cycle: bool = True
    # Optional custom day length in real minutes (full 24000-tick day). None = vanilla (~20 min).
    day_length_minutes: float | None = Field(default=None, ge=0.5, le=240.0)
    # Snap time once when rules are applied.
    time_of_day: TimePreset = "keep"
    weather_cycle: bool = True
    clear_weather: bool = True
    mob_griefing: bool = False
    keep_inventory: bool = True
    do_mob_spawning: bool = True
    # When false: set difficulty peaceful (no hostile mobs; animals still spawn if do_mob_spawning).
    hostile_mobs: bool = True
    fire_spreads: bool = False

    def effective_daylight_cycle(self) -> bool:
        if not self.allow_night:
            return False
        if self.day_length_minutes is not None:
            return False  # we advance time manually
        return self.daylight_cycle


class WorldImportInfo(BaseModel):
    """Metadata about the active imported / mounted world."""

    source: Literal["default", "imported", "external"] = "default"
    label: str = "Default (fresh world)"
    # Relative to data/minecraft/ — usually "world"
    level_name: str = "world"
    notes: str = ""


class WorldSettings(BaseModel):
    rules: WorldRules = Field(default_factory=WorldRules)
    boundaries: WorldBoundaries = Field(default_factory=WorldBoundaries)
    world: WorldImportInfo = Field(default_factory=WorldImportInfo)


def load_settings() -> WorldSettings:
    path = settings_path()
    if not path.exists():
        return WorldSettings()
    try:
        return WorldSettings.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Failed to load %s (%s); using defaults", path, exc)
        return WorldSettings()


def save_settings(settings: WorldSettings) -> Path:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    return path


def rcon_commands_for_rules(rules: WorldRules) -> list[str]:
    """Build RCON commands that apply WorldRules to a live server."""
    cmds: list[str] = []
    cycle = "true" if rules.effective_daylight_cycle() else "false"
    cmds.append(f"gamerule doDaylightCycle {cycle}")
    cmds.append(f"gamerule doWeatherCycle {'true' if rules.weather_cycle else 'false'}")
    cmds.append(f"gamerule mobGriefing {'true' if rules.mob_griefing else 'false'}")
    cmds.append(f"gamerule keepInventory {'true' if rules.keep_inventory else 'false'}")
    cmds.append(f"gamerule doMobSpawning {'true' if rules.do_mob_spawning else 'false'}")
    cmds.append(f"gamerule doFireTick {'true' if rules.fire_spreads else 'false'}")
    # Peaceful removes / prevents hostile mobs while still allowing passive animals.
    cmds.append(f"difficulty {'easy' if rules.hostile_mobs else 'peaceful'}")

    if not rules.allow_night:
        cmds.append("time set day")
    elif rules.time_of_day != "keep":
        cmds.append(TIME_PRESET_COMMANDS[rules.time_of_day])

    if rules.clear_weather:
        cmds.append("weather clear 999999")

    if rules.day_length_minutes is not None and rules.allow_night:
        # Manual cycle: start at day; advancement happens in tick loop.
        cmds.append("time set day")

    return cmds


def apply_rules_via_rcon(rules: WorldRules | None = None) -> list[str]:
    """Push current (or given) rules to Minecraft over RCON."""
    from .rcon import run_commands

    rules = rules or load_settings().rules
    cmds = rcon_commands_for_rules(rules)
    return run_commands(cmds)


def ticks_to_add_per_second(day_length_minutes: float) -> float:
    """How many Minecraft time ticks to add each real second for a custom day length."""
    # Full day = 24000 ticks. Vanilla ≈ 20 real minutes.
    seconds = max(30.0, day_length_minutes * 60.0)
    return 24000.0 / seconds


def find_level_dat(root: Path) -> Path | None:
    """Return path to level.dat under root (supports nested single folder)."""
    direct = root / "level.dat"
    if direct.is_file():
        return direct
    world_sub = root / "world" / "level.dat"
    if world_sub.is_file():
        return world_sub
    # One nested directory that contains level.dat
    if root.is_dir():
        children = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if len(children) == 1 and (children[0] / "level.dat").is_file():
            return children[0] / "level.dat"
        for child in children:
            if (child / "level.dat").is_file():
                return child / "level.dat"
    return None


def import_world_zip(zip_path: Path, *, label: str | None = None) -> WorldSettings:
    """Extract a Minecraft world zip into ``data/minecraft/world`` and update settings.

    The server must be restarted (docker compose down/up) for the new world to load.
    """
    if not zip_path.is_file():
        raise FileNotFoundError(f"World zip not found: {zip_path}")

    staging = data_dir() / "_import_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(staging)

    level = find_level_dat(staging)
    if level is None:
        shutil.rmtree(staging, ignore_errors=True)
        raise ValueError(
            "No level.dat found in zip. Export a Minecraft Java world folder "
            "(the folder that contains level.dat, region/, data/, …)."
        )

    world_src = level.parent
    dest = minecraft_data_dir() / "world"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(world_src, dest)
    shutil.rmtree(staging, ignore_errors=True)

    settings = load_settings()
    settings.world = WorldImportInfo(
        source="imported",
        label=label or zip_path.stem,
        level_name="world",
        notes="Restart Minecraft (docker compose down && docker compose up -d) to load this world.",
    )
    save_settings(settings)
    return settings


def import_world_folder(folder: Path, *, label: str | None = None) -> WorldSettings:
    """Copy an existing Java world folder into ``data/minecraft/world``."""
    level = find_level_dat(folder)
    if level is None:
        raise ValueError(f"No level.dat under {folder}")
    world_src = level.parent
    dest = minecraft_data_dir() / "world"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(world_src, dest)

    settings = load_settings()
    settings.world = WorldImportInfo(
        source="imported",
        label=label or folder.name,
        level_name="world",
        notes="Restart Minecraft to load this world.",
    )
    save_settings(settings)
    return settings


def prepare_random_world(*, seed: int | None = None) -> tuple[WorldSettings, int]:
    """Wipe ``data/minecraft/world`` so Docker generates a new world with ``seed``."""
    import random

    chosen = int(seed) if seed is not None else random.randint(0, 2_147_483_647)
    dest = minecraft_data_dir() / "world"
    if dest.exists():
        shutil.rmtree(dest)
    settings = load_settings()
    settings.world = WorldImportInfo(
        source="default",
        label=f"Random world (seed {chosen})",
        level_name="world",
        notes=f"Generated with SEED={chosen}",
    )
    save_settings(settings)
    return settings, chosen


def settings_public_dict(settings: WorldSettings | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    return settings.model_dump(mode="json")
