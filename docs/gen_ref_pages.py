"""Auto-generate one MkDocs page per SimulateCraft Python module.

Runs on every ``mkdocs build`` / ``mkdocs serve`` via the gen-files plugin.
Editing docstrings in ``src/simulatecraft`` is enough to keep the API docs
in sync — no hand-maintained reference pages.
"""

from __future__ import annotations

from pathlib import Path

import mkdocs_gen_files

PACKAGE = "simulatecraft"
SRC = Path("src") / PACKAGE
REF = Path("reference")

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
            # Root package is covered by the hand-written API landing page.
            continue
        doc_path = REF.joinpath(*parts, "index.md")
        ident = ".".join((PACKAGE, *parts))
    else:
        doc_path = REF.joinpath(*parts).with_suffix(".md")
        ident = ".".join((PACKAGE, *parts))

    nav[tuple(_label(p) for p in parts)] = doc_path.relative_to(REF).as_posix()

    with mkdocs_gen_files.open(doc_path, "w") as fd:
        fd.write(f"# `{ident}`\n\n")
        fd.write(f"::: {ident}\n")

    mkdocs_gen_files.set_edit_path(doc_path, path)

with mkdocs_gen_files.open(REF / "SUMMARY.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())

with mkdocs_gen_files.open(REF / "index.md", "w") as index:
    index.write(
        """# API reference

Every public module under `simulatecraft` is documented here. Pages are
**generated from source** on each docs build — edit docstrings in
`src/simulatecraft/`, then rebuild.

## Start here

| Area | Modules |
|---|---|
| **Core loop** | [`Runner`](core/runner.md), [`Agent`](core/agent.md), [`Environment`](core/environment.md), [`Events`](core/events.md), [`Schemas`](core/schemas.md) |
| **Minecraft** | [`MinecraftEnvironment`](minecraft/env.md), [`Actions`](minecraft/actions.md), [`Observations`](minecraft/observations.md), [`Bridge`](minecraft/connection.md) |
| **Cognition** | [`LLMBrain`](brains/llm.md), [`MemoryStream`](memory/stream.md), [`Retriever`](memory/retrieval.md), [`Planner`](planning/planner.md), [`SkillRegistry`](skills/registry.md) |
| **Viewer** | [`SimulationServer`](server/app.md), [`JsonlLogger`](viewers/log.md) |
| **CLI / examples** | [`CLI`](cli.md), [`minecraft_explorer`](examples/minecraft_explorer/index.md) |

Browse the full package tree in the left sidebar.
"""
    )
