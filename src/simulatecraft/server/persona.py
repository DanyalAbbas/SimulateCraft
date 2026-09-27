"""Build structured agent personas from free text or roster CSV/Excel rows."""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from simulatecraft.server.workshop_settings import (
    AgentWorkshopSettings,
    RosterColumn,
    load_workshop_settings,
)

log = logging.getLogger(__name__)

_TRAIT_BEHAVIOUR = {
    "openness": {
        "low": "prefer familiar routines; stick to known biomes and recipes",
        "moderate": "curious enough to explore, but not reckless",
        "high": "seek novelty — new biomes, builds, and experiments",
    },
    "conscientiousness": {
        "low": "improvise; leave unfinished projects; act on impulse",
        "moderate": "balance planning with flexibility",
        "high": "plan carefully, craft tools first, keep inventory tidy",
    },
    "extraversion": {
        "low": "quiet; chat sparingly; prefer solo work",
        "moderate": "chat when useful; collaborate when asked",
        "high": "talkative; narrate actions; seek teammates often",
    },
    "agreeableness": {
        "low": "competitive; protect own resources; blunt in chat",
        "moderate": "cooperative when it helps the group",
        "high": "helpful; share loot; avoid conflict; support others",
    },
    "neuroticism": {
        "low": "calm under pressure; ignore minor setbacks",
        "moderate": "react to real danger but recover quickly",
        "high": "anxious about night, mobs, and hunger; warn others early",
    },
}


class AgentProfile(BaseModel):
    """One roster row ready to become an agent (schema-agnostic)."""

    name: str = Field(..., min_length=1, max_length=64)
    goal: str = ""
    persona: str = ""
    skin_url: str = ""
    notes: str = ""
    # Free-form text attributes from configured columns (role=attribute)
    attributes: dict[str, str] = Field(default_factory=dict)
    # Numeric traits (role=trait)
    traits: dict[str, float] = Field(default_factory=dict)
    # Ordered identity fragments already formatted ("working as Explorer", …)
    identity_parts: list[str] = Field(default_factory=list)
    # Keys already folded into identity (avoid duplicating in Behaviour)
    identity_keys: list[str] = Field(default_factory=list)
    # Column metadata used when rendering (key → label)
    attribute_labels: dict[str, str] = Field(default_factory=dict)
    trait_labels: dict[str, str] = Field(default_factory=dict)

    def minecraft_username(self) -> str:
        """Minecraft usernames: 1–16 chars, [A-Za-z0-9_]."""
        raw = re.sub(r"[^A-Za-z0-9_]+", "", self.name.strip().replace(" ", "_"))
        if not raw:
            raw = "Agent"
        if not raw[0].isalpha():
            raw = f"A{raw}"
        return raw[:16]

    def default_goal(self) -> str:
        if self.goal.strip():
            return self.goal.strip()[:500]
        if self.identity_parts:
            return f"act as {', '.join(self.identity_parts[:2])}"[:500]
        return "survive, explore, and stay in character"


class GeneratePromptRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    name: str | None = Field(default=None, max_length=64)
    use_llm: bool = True
    model: str | None = None
    # Optional one-shot override; otherwise uses saved workshop settings.
    instructions: str | None = Field(default=None, max_length=12_000)


class GeneratePromptResponse(BaseModel):
    persona: str
    source: str  # "llm" | "template"


def _norm_header(cell: Any) -> str:
    return re.sub(r"\s+", " ", str(cell or "").strip().lower())


def _parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _trait_band(score: float | None) -> str:
    """Map a numeric trait to low / moderate / high (supports 1–5 or 0–100 scales)."""
    if score is None:
        return "unspecified"
    if score > 10:
        if score < 35:
            return "low"
        if score < 65:
            return "moderate"
        return "high"
    if score <= 1.0 and score >= 0:
        if score < 0.35:
            return "low"
        if score < 0.65:
            return "moderate"
        return "high"
    if score < 2.5:
        return "low"
    if score < 3.5:
        return "moderate"
    return "high"


def _trait_behaviour(key: str, band: str) -> str:
    specific = _TRAIT_BEHAVIOUR.get(key, {}).get(band)
    if specific:
        return specific
    return f"express a {band} level of {key.replace('_', ' ')}"


def _column_alias_map(columns: list[RosterColumn]) -> dict[str, str]:
    """Normalized header text → column key."""
    mapping: dict[str, str] = {}
    for col in columns:
        candidates = list(col.headers) + [col.key, col.label]
        for raw in candidates:
            norm = _norm_header(raw)
            if norm:
                mapping[norm] = col.key
    return mapping


def build_structured_persona(
    profile: AgentProfile | None = None,
    *,
    draft: str = "",
    settings: AgentWorkshopSettings | None = None,
) -> str:
    """Deterministic structured system prompt from profile fields and/or draft notes."""
    _ = settings  # reserved for future template overrides
    name = (profile.name if profile else None) or "Agent"
    draft_text = (
        draft
        or (profile.notes if profile else "")
        or (profile.persona if profile else "")
        or ""
    ).strip()

    identity_bits: list[str] = [f"You are {name}"]
    if profile:
        identity_bits.extend(p for p in profile.identity_parts if p.strip())
    identity = ", ".join(identity_bits) + "."

    sections: list[str] = [
        "## Identity",
        identity,
        "You live inside a Minecraft world. Stay in character at all times.",
    ]

    if profile and profile.traits:
        sections.append("")
        sections.append("## Personality")
        for key, score in profile.traits.items():
            band = _trait_band(score)
            label = profile.trait_labels.get(key) or key.replace("_", " ").title()
            sections.append(
                f"- {label}: {score:g} ({band}) — {_trait_behaviour(key, band)}"
            )

    attr_lines: list[str] = []
    if profile:
        skip = set(profile.identity_keys)
        for key, value in profile.attributes.items():
            if key in skip or not value.strip():
                continue
            label = profile.attribute_labels.get(key) or key.replace("_", " ").title()
            attr_lines.append(f"- {label}: {value.strip()}")

    sections.append("")
    sections.append("## Behaviour")
    sections.append("- Choose exactly one Minecraft action each tick.")
    sections.append("- Prefer short in-character chat when something noteworthy happens.")
    sections.extend(attr_lines)
    if profile and profile.identity_parts:
        sections.append(
            "- Let your identity ("
            + "; ".join(profile.identity_parts)
            + ") shape goals, priorities, and chat tone."
        )

    if draft_text:
        sections.append("")
        sections.append("## Author notes")
        sections.append(draft_text)

    sections.append("")
    sections.append("## Style")
    sections.append("- Speak in first person.")
    sections.append("- Keep chat under ~120 characters when possible.")
    sections.append("- Never break character or mention being an AI / language model.")

    return "\n".join(sections).strip()


async def generate_persona(
    *,
    text: str,
    name: str | None = None,
    use_llm: bool = True,
    model: str | None = None,
    instructions: str | None = None,
    settings: AgentWorkshopSettings | None = None,
) -> GeneratePromptResponse:
    """Expand rough notes into a structured persona; optionally polish with the LLM."""
    workshop = settings or load_workshop_settings()
    profile = AgentProfile(name=(name or "Agent").strip() or "Agent", notes=text.strip())
    template = build_structured_persona(profile, draft=text.strip(), settings=workshop)

    if not use_llm:
        return GeneratePromptResponse(persona=template, source="template")

    try:
        from pydantic_ai import Agent as PydanticAgent

        from simulatecraft.brains.llm import _build_pydantic_ai_model, resolve_model
    except ImportError:
        return GeneratePromptResponse(persona=template, source="template")

    resolved = (model or resolve_model()).strip()
    if resolved == "test":
        return GeneratePromptResponse(persona=template, source="template")

    system = (instructions or workshop.prompt_generator_instructions or "").strip()
    try:
        agent = PydanticAgent(
            _build_pydantic_ai_model(resolved),
            output_type=str,
            instructions=system,
            retries=1,
        )
        result = await agent.run(
            f"Agent name: {profile.name}\n\nRough notes:\n{text.strip()}\n\n"
            f"Draft to refine (optional):\n{template}"
        )
        persona = str(result.output).strip()
        if not persona:
            return GeneratePromptResponse(persona=template, source="template")
        return GeneratePromptResponse(persona=persona[:4000], source="llm")
    except Exception:
        log.exception("persona LLM generate failed; falling back to template")
        return GeneratePromptResponse(persona=template, source="template")


def _row_to_profile(
    row: dict[str, Any],
    columns: list[RosterColumn],
) -> AgentProfile | None:
    name_col = next((c for c in columns if c.role == "name"), None)
    name_key = name_col.key if name_col else "name"
    name = str(row.get(name_key) or "").strip()
    if not name:
        return None

    attributes: dict[str, str] = {}
    traits: dict[str, float] = {}
    identity_parts: list[str] = []
    identity_keys: list[str] = []
    attribute_labels: dict[str, str] = {}
    trait_labels: dict[str, str] = {}
    goal = ""
    persona = ""
    skin_url = ""
    notes = ""

    for col in columns:
        if col.role == "skip":
            continue
        raw = row.get(col.key)
        if raw is None or str(raw).strip() == "":
            continue
        text = str(raw).strip()

        if col.role == "name":
            continue
        if col.role == "goal":
            goal = text[:500]
        elif col.role == "persona":
            persona = text[:4000]
        elif col.role == "skin_url":
            skin_url = text[:500]
        elif col.role == "notes":
            notes = text[:2000]
        elif col.role == "trait":
            num = _parse_float(raw)
            if num is not None:
                traits[col.key] = num
                trait_labels[col.key] = col.display_label()
        elif col.role == "attribute":
            attributes[col.key] = text[:500]
            attribute_labels[col.key] = col.display_label()
            if col.identity and col.include_in_persona:
                identity_keys.append(col.key)
                fmt = col.identity_format or "{value}"
                try:
                    identity_parts.append(fmt.format(value=text, label=col.display_label()))
                except Exception:
                    identity_parts.append(text)

    identity_parts = [p.strip() for p in identity_parts if p.strip()]

    return AgentProfile(
        name=name[:64],
        goal=goal,
        persona=persona,
        skin_url=skin_url,
        notes=notes,
        attributes=attributes,
        traits=traits,
        identity_parts=identity_parts,
        identity_keys=identity_keys,
        attribute_labels=attribute_labels,
        trait_labels=trait_labels,
    )


def _map_headers(headers: list[Any], columns: list[RosterColumn]) -> list[str | None]:
    aliases = _column_alias_map(columns)
    return [aliases.get(_norm_header(h)) for h in headers]


def _require_name_column(keys: list[str | None], columns: list[RosterColumn]) -> None:
    name_keys = {c.key for c in columns if c.role == "name"} or {"name"}
    if not any(k in name_keys for k in keys if k):
        hints = []
        for c in columns:
            if c.role == "name":
                hints.extend(c.headers or [c.display_label()])
        hint = ", ".join(hints) if hints else "Name"
        raise ValueError(f"Roster must include a name column (expected header like: {hint})")


def parse_roster_csv(
    data: bytes,
    *,
    settings: AgentWorkshopSettings | None = None,
) -> list[AgentProfile]:
    workshop = settings or load_workshop_settings()
    columns = workshop.roster_columns
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows_iter = iter(reader)
    try:
        headers = next(rows_iter)
    except StopIteration:
        return []
    keys = _map_headers(headers, columns)
    _require_name_column(keys, columns)

    profiles: list[AgentProfile] = []
    for raw in rows_iter:
        if not any(str(c).strip() for c in raw):
            continue
        mapped: dict[str, Any] = {}
        for key, cell in zip(keys, raw, strict=False):
            if key:
                mapped[key] = cell
        profile = _row_to_profile(mapped, columns)
        if profile:
            profiles.append(profile)
    return profiles


def parse_roster_xlsx(
    data: bytes,
    *,
    settings: AgentWorkshopSettings | None = None,
) -> list[AgentProfile]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ValueError(
            "Excel support requires openpyxl. Install with: pip install openpyxl"
        ) from exc

    workshop = settings or load_workshop_settings()
    columns = workshop.roster_columns
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        headers = list(next(rows_iter))
    except StopIteration:
        return []
    keys = _map_headers(headers, columns)
    _require_name_column(keys, columns)

    profiles: list[AgentProfile] = []
    for raw in rows_iter:
        if raw is None or not any(c is not None and str(c).strip() for c in raw):
            continue
        mapped: dict[str, Any] = {}
        for key, cell in zip(keys, raw, strict=False):
            if key:
                mapped[key] = "" if cell is None else cell
        profile = _row_to_profile(mapped, columns)
        if profile:
            profiles.append(profile)
    return profiles


def parse_roster_file(
    filename: str,
    data: bytes,
    *,
    settings: AgentWorkshopSettings | None = None,
) -> list[AgentProfile]:
    workshop = settings or load_workshop_settings()
    lower = (filename or "").lower()
    if lower.endswith(".csv") or lower.endswith(".tsv") or lower.endswith(".txt"):
        return parse_roster_csv(data, settings=workshop)
    if lower.endswith(".xlsx") or lower.endswith(".xlsm"):
        return parse_roster_xlsx(data, settings=workshop)
    if data[:2] == b"PK":
        return parse_roster_xlsx(data, settings=workshop)
    return parse_roster_csv(data, settings=workshop)
