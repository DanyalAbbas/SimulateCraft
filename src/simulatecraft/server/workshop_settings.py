"""Persistent agent-workshop settings: prompt generator + roster column map.

Stored at ``data/agent_workshop.json``. Defaults target a university-style
roster; other simulations can remap columns and rewrite the generator
instructions from the Configure panel.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from simulatecraft.minecraft.world_settings import data_dir

log = logging.getLogger(__name__)

ColumnRole = Literal[
    "name",
    "goal",
    "persona",
    "skin_url",
    "notes",
    "attribute",
    "trait",
    "skip",
]

DEFAULT_PROMPT_GENERATOR_INSTRUCTIONS = (
    "You write structured system prompts for Minecraft simulation agents.\n"
    "Given rough notes (and optional draft text), return ONLY the finished "
    "system prompt — no preamble, no markdown fences.\n"
    "Use short markdown sections such as: Identity, Personality, Behaviour, Style.\n"
    "Keep it under 900 words. Stay second-person (\"You are…\").\n"
    "Never mention being an AI or language model. Stay useful inside Minecraft."
)

# Minimal roster: anyone can import Name + optional goal/persona/notes.
MINIMAL_ROSTER_COLUMNS: list[dict[str, Any]] = [
    {
        "key": "name",
        "label": "Name",
        "headers": ["Name", "Username", "Agent"],
        "role": "name",
        "include_in_persona": True,
        "identity": True,
    },
    {
        "key": "goal",
        "label": "Goal",
        "headers": ["Goal"],
        "role": "goal",
        "include_in_persona": False,
    },
    {
        "key": "persona",
        "label": "Persona",
        "headers": ["Persona", "System prompt"],
        "role": "persona",
        "include_in_persona": False,
    },
    {
        "key": "notes",
        "label": "Notes",
        "headers": ["Notes", "Draft"],
        "role": "notes",
        "include_in_persona": True,
    },
    {
        "key": "skin_url",
        "label": "Skin URL",
        "headers": ["Skin URL", "Skin"],
        "role": "skin_url",
        "include_in_persona": False,
    },
]

# University / org simulation (matches the user's current CSV).
UNIVERSITY_ROSTER_COLUMNS: list[dict[str, Any]] = [
    {
        "key": "timestamp",
        "label": "Timestamp",
        "headers": ["Timestamp"],
        "role": "skip",
        "include_in_persona": False,
    },
    {
        "key": "name",
        "label": "Name",
        "headers": ["Name", "Username", "Agent"],
        "role": "name",
        "include_in_persona": True,
        "identity": True,
    },
    {
        "key": "gender",
        "label": "Gender",
        "headers": ["Gender"],
        "role": "attribute",
        "include_in_persona": True,
        "identity": True,
    },
    {
        "key": "role",
        "label": "Role",
        "headers": ["Role"],
        "role": "attribute",
        "include_in_persona": True,
        "identity": True,
        "identity_format": "working as {value}",
    },
    {
        "key": "department",
        "label": "Department",
        "headers": ["Department", "Dept"],
        "role": "attribute",
        "include_in_persona": True,
        "identity": True,
        "identity_format": "in {value}",
    },
    {
        "key": "openness",
        "label": "Openness",
        "headers": ["Openness"],
        "role": "trait",
        "include_in_persona": True,
    },
    {
        "key": "conscientiousness",
        "label": "Conscientiousness",
        "headers": ["Conscientiousness"],
        "role": "trait",
        "include_in_persona": True,
    },
    {
        "key": "extraversion",
        "label": "Extraversion",
        "headers": ["Extraversion"],
        "role": "trait",
        "include_in_persona": True,
    },
    {
        "key": "agreeableness",
        "label": "Agreeableness",
        "headers": ["Agreeableness"],
        "role": "trait",
        "include_in_persona": True,
    },
    {
        "key": "neuroticism",
        "label": "Neuroticism",
        "headers": ["Neuroticism"],
        "role": "trait",
        "include_in_persona": True,
    },
    {
        "key": "skin_url",
        "label": "Skin URL",
        "headers": ["Skin URL", "Skin"],
        "role": "skin_url",
        "include_in_persona": False,
    },
    {
        "key": "fun_fact",
        "label": "Fun fact",
        "headers": ["Fun Fact", "Fun fact"],
        "role": "attribute",
        "include_in_persona": True,
    },
    {
        "key": "goal",
        "label": "Goal",
        "headers": ["Goal"],
        "role": "goal",
        "include_in_persona": False,
    },
    {
        "key": "persona",
        "label": "Persona",
        "headers": ["Persona", "System prompt"],
        "role": "persona",
        "include_in_persona": False,
    },
    {
        "key": "notes",
        "label": "Notes",
        "headers": ["Notes", "Draft"],
        "role": "notes",
        "include_in_persona": True,
    },
]


class RosterColumn(BaseModel):
    """One logical field that can be read from a CSV/Excel header."""

    key: str = Field(..., min_length=1, max_length=64)
    label: str = Field(default="", max_length=120)
    headers: list[str] = Field(default_factory=list)
    role: ColumnRole = "attribute"
    include_in_persona: bool = True
    identity: bool = False
    identity_format: str = Field(
        default="{value}",
        max_length=120,
        description="How to fold this attribute into the Identity sentence. Use {value}.",
    )

    @field_validator("key")
    @classmethod
    def _slug_key(cls, value: str) -> str:
        cleaned = value.strip().lower().replace(" ", "_")
        if not cleaned or not cleaned.replace("_", "").isalnum():
            raise ValueError("column key must be alphanumeric / underscore")
        return cleaned[:64]

    @field_validator("headers", mode="before")
    @classmethod
    def _coerce_headers(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [p.strip() for p in value.split(",") if p.strip()]
        return [str(v).strip() for v in value if str(v).strip()]

    def display_label(self) -> str:
        return (self.label or self.key.replace("_", " ").title()).strip()


class AgentWorkshopSettings(BaseModel):
    """Viewer settings for prompt generation and bulk roster import."""

    prompt_generator_instructions: str = Field(
        default=DEFAULT_PROMPT_GENERATOR_INSTRUCTIONS,
        max_length=12_000,
    )
    roster_preset: str = Field(
        default="university",
        description="Hint label: university | minimal | custom",
    )
    roster_columns: list[RosterColumn] = Field(default_factory=list)

    @field_validator("prompt_generator_instructions")
    @classmethod
    def _nonempty_instructions(cls, value: str) -> str:
        text = value.strip()
        if not text:
            return DEFAULT_PROMPT_GENERATOR_INSTRUCTIONS
        return text[:12_000]


def workshop_path() -> Path:
    return data_dir() / "agent_workshop.json"


def default_university_settings() -> AgentWorkshopSettings:
    return AgentWorkshopSettings(
        prompt_generator_instructions=DEFAULT_PROMPT_GENERATOR_INSTRUCTIONS,
        roster_preset="university",
        roster_columns=[RosterColumn.model_validate(c) for c in UNIVERSITY_ROSTER_COLUMNS],
    )


def default_minimal_settings() -> AgentWorkshopSettings:
    return AgentWorkshopSettings(
        prompt_generator_instructions=DEFAULT_PROMPT_GENERATOR_INSTRUCTIONS,
        roster_preset="minimal",
        roster_columns=[RosterColumn.model_validate(c) for c in MINIMAL_ROSTER_COLUMNS],
    )


def load_workshop_settings() -> AgentWorkshopSettings:
    path = workshop_path()
    if not path.exists():
        settings = default_university_settings()
        save_workshop_settings(settings)
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        settings = AgentWorkshopSettings.model_validate(raw)
        if not settings.roster_columns:
            settings.roster_columns = default_university_settings().roster_columns
        return settings
    except Exception:
        log.exception("failed to load %s; using defaults", path)
        return default_university_settings()


def save_workshop_settings(settings: AgentWorkshopSettings) -> AgentWorkshopSettings:
    path = workshop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        settings.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return settings


def apply_roster_preset(name: str) -> AgentWorkshopSettings:
    key = (name or "").strip().lower()
    current = load_workshop_settings()
    if key == "minimal":
        settings = default_minimal_settings()
    else:
        settings = default_university_settings()
    # Keep the user's prompt-generator instructions when switching column presets.
    settings.prompt_generator_instructions = current.prompt_generator_instructions
    return save_workshop_settings(settings)


def settings_public_dict(settings: AgentWorkshopSettings | None = None) -> dict[str, Any]:
    s = settings or load_workshop_settings()
    return s.model_dump()


def expected_headers_hint(settings: AgentWorkshopSettings | None = None) -> str:
    s = settings or load_workshop_settings()
    names: list[str] = []
    for col in s.roster_columns:
        if col.role == "skip":
            continue
        if col.headers:
            names.append(col.headers[0])
        else:
            names.append(col.display_label())
    return ", ".join(names) if names else "Name"
