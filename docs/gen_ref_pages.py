"""Auto-generate one MkDocs page per SimulateCraft Python module.

Runs on every ``mkdocs build`` / ``mkdocs serve`` via the gen-files plugin.
Edit docstrings under ``src/simulatecraft`` — no hand-written guide pages.
"""

from __future__ import annotations

from pathlib import Path

import mkdocs_gen_files

PACKAGE = "simulatecraft"
SRC = Path("src") / PACKAGE

NAV_LABELS = {
    "brains": "brains",
    "base": "Brain",
    "llm": "LLMBrain",
    "cli": "CLI",
    "core": "core",
    "agent": "Agent",
    "environment": "Environment",
    "events": "Events",
    "runner": "Runner",
    "schemas": "Schemas",
    "examples": "examples",
    "minecraft_explorer": "minecraft_explorer",
    "agents": "agent personas",
    "main": "example entrypoint",
    "memory": "memory",
    "reflection": "Reflection",
    "retrieval": "Retrieval",
    "stream": "MemoryStream",
    "minecraft": "minecraft",
    "actions": "Actions",
    "connection": "Bridge",
    "env": "MinecraftEnvironment",
    "observations": "Observations",
    "planning": "planning",
    "planner": "Planner",
    "server": "server",
    "app": "SimulationServer",
    "skills": "skills",
    "registry": "SkillRegistry",
    "viewers": "viewers",
    "log": "JsonlLogger",
}

nav = mkdocs_gen_files.Nav()


def _label(part: str) -> str:
    return NAV_LABELS.get(part, part.replace("_", " "))


for path in sorted(SRC.rglob("*.py")):
    if "node_modules" in path.parts:
        continue

    module_path = path.relative_to(SRC).with_suffix("")
    parts = tuple(module_path.parts)

    if parts[-1] == "__main__":
        continue

    if parts[-1] == "__init__":
        parts = parts[:-1]
        if not parts:
            continue
        doc_path = Path(*parts, "index.md")
        ident = ".".join((PACKAGE, *parts))
    else:
        doc_path = Path(*parts).with_suffix(".md")
        ident = ".".join((PACKAGE, *parts))

    nav[tuple(_label(p) for p in parts)] = doc_path.as_posix()

    with mkdocs_gen_files.open(doc_path, "w") as fd:
        fd.write(f"# `{ident}`\n\n")
        fd.write(f"::: {ident}\n")

    mkdocs_gen_files.set_edit_path(doc_path, path)

with mkdocs_gen_files.open("SUMMARY.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())

with mkdocs_gen_files.open("index.md", "w") as index:
    index.write(
        f"""# SimulateCraft

Auto-generated API reference for `{PACKAGE}`. Edit module docstrings under
`src/{PACKAGE}/` — this site rebuilds from source on every docs build.

Use the sidebar to open any module.
"""
    )
