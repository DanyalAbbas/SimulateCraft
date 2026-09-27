"""Persona / roster helpers for agent prompt generation and bulk import."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from simulatecraft.server.persona import (
    AgentProfile,
    build_structured_persona,
    generate_persona,
    parse_roster_csv,
    parse_roster_file,
    parse_roster_xlsx,
)
from simulatecraft.server.workshop_settings import (
    DEFAULT_PROMPT_GENERATOR_INSTRUCTIONS,
    AgentWorkshopSettings,
    RosterColumn,
    default_minimal_settings,
    default_university_settings,
    expected_headers_hint,
)


def test_build_structured_persona_includes_traits_and_attributes() -> None:
    profile = AgentProfile(
        name="Maya Chen",
        identity_parts=["Female", "working as Researcher", "in R&D"],
        attributes={"fun_fact": "Collects rare flowers"},
        attribute_labels={"fun_fact": "Fun fact"},
        traits={"openness": 5, "conscientiousness": 4},
        trait_labels={"openness": "Openness", "conscientiousness": "Conscientiousness"},
    )
    text = build_structured_persona(profile)
    assert "You are Maya Chen" in text
    assert "Researcher" in text
    assert "Openness" in text
    assert "Collects rare flowers" in text
    assert "## Identity" in text
    assert "## Personality" in text


@pytest.mark.asyncio
async def test_generate_persona_template_without_llm() -> None:
    result = await generate_persona(
        text="shy miner who loves diamonds",
        name="Bob",
        use_llm=False,
    )
    assert result.source == "template"
    assert "Bob" in result.persona
    assert "shy miner" in result.persona


@pytest.mark.asyncio
async def test_generate_persona_accepts_instruction_override() -> None:
    """With use_llm=False the override is unused, but the call must still succeed."""
    result = await generate_persona(
        text="notes",
        name="Ada",
        use_llm=False,
        instructions="CUSTOM GENERATOR RULES",
    )
    assert result.source == "template"
    assert "Ada" in result.persona


def test_parse_roster_csv_university_columns() -> None:
    settings = default_university_settings()
    raw = (
        b"Timestamp,Name,Gender,Role,Department,Openness,Conscientiousness,"
        b"Extraversion,Agreeableness,Neuroticism,Skin URL,Fun Fact\n"
        b"2024-01-01,Alex Rivera,Male,Explorer,Field,4,3,5,4,2,"
        b"https://example.com/skin.png,Loves maps\n"
        b",,,, ,,,,,,\n"
        b"2024-01-02,Bea,Female,Builder,Ops,3,5,2,5,1,,Builds castles\n"
    )
    profiles = parse_roster_csv(raw, settings=settings)
    assert len(profiles) == 2
    assert profiles[0].name == "Alex Rivera"
    assert profiles[0].minecraft_username() == "Alex_Rivera"
    assert profiles[0].traits["openness"] == 4
    assert profiles[0].skin_url == "https://example.com/skin.png"
    assert "working as Explorer" in profiles[0].identity_parts
    assert profiles[1].attributes.get("fun_fact") == "Builds castles" or any(
        "Builder" in p for p in profiles[1].identity_parts
    )


def test_parse_roster_minimal_preset() -> None:
    settings = default_minimal_settings()
    raw = b"Name,Goal,Notes\nSteve,build a farm,likes pigs\n"
    profiles = parse_roster_csv(raw, settings=settings)
    assert len(profiles) == 1
    assert profiles[0].name == "Steve"
    assert profiles[0].goal == "build a farm"
    assert profiles[0].notes == "likes pigs"


def test_parse_roster_xlsx_roundtrip() -> None:
    settings = default_university_settings()
    wb = Workbook()
    ws = wb.active
    ws.append(
        [
            "Timestamp",
            "Name",
            "Gender",
            "Role",
            "Department",
            "Openness",
            "Conscientiousness",
            "Extraversion",
            "Agreeableness",
            "Neuroticism",
            "Skin URL",
            "Fun Fact",
        ]
    )
    ws.append(
        [
            "t",
            "Dana",
            "Non-binary",
            "Defender",
            "Security",
            2,
            5,
            3,
            3,
            4,
            "",
            "Never sleeps",
        ]
    )
    buf = io.BytesIO()
    wb.save(buf)
    profiles = parse_roster_xlsx(buf.getvalue(), settings=settings)
    assert len(profiles) == 1
    assert profiles[0].name == "Dana"
    assert profiles[0].traits["neuroticism"] == 4


def test_parse_roster_file_requires_name() -> None:
    settings = default_university_settings()
    with pytest.raises(ValueError, match="name column"):
        parse_roster_file(
            "agents.csv",
            b"Role,Department\nBuilder,Ops\n",
            settings=settings,
        )


def test_workshop_defaults_and_hint() -> None:
    uni = default_university_settings()
    assert "Department" in expected_headers_hint(uni)
    assert DEFAULT_PROMPT_GENERATOR_INSTRUCTIONS in uni.prompt_generator_instructions
    custom = AgentWorkshopSettings(
        prompt_generator_instructions="Write short pirate personas.",
        roster_preset="custom",
        roster_columns=[
            RosterColumn(key="name", label="Name", headers=["Name"], role="name"),
            RosterColumn(
                key="crew",
                label="Crew",
                headers=["Crew"],
                role="attribute",
                identity=True,
            ),
        ],
    )
    assert "Crew" in expected_headers_hint(custom)
