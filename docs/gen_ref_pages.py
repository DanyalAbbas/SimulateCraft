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

nav = mkdocs_gen_files.Nav()

for path in sorted(SRC.rglob("*.py")):
    if "node_modules" in path.parts:
        continue

    module_path = path.relative_to(SRC).with_suffix("")
    parts = tuple(module_path.parts)

    if parts[-1] == "__main__":
        continue

    if parts[-1] == "__init__":
        parts = parts[:-1]
        doc_path = REF.joinpath(*parts, "index.md") if parts else REF / "index.md"
        ident = PACKAGE if not parts else ".".join((PACKAGE, *parts))
    else:
        doc_path = REF.joinpath(*parts).with_suffix(".md")
        ident = ".".join((PACKAGE, *parts))

    nav_key = parts if parts else (PACKAGE,)
    nav[nav_key] = doc_path.relative_to(REF).as_posix()

    with mkdocs_gen_files.open(doc_path, "w") as fd:
        title = ident
        fd.write(f"# `{title}`\n\n")
        fd.write(f"::: {ident}\n")

    mkdocs_gen_files.set_edit_path(doc_path, path)

with mkdocs_gen_files.open(REF / "SUMMARY.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())
