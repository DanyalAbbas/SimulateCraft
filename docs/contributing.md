# Contributing

Thanks for helping improve SimulateCraft. Small, focused PRs are easiest to review.

## Setup

```bash
git clone https://github.com/DanyalAbbas/SimulateCraft.git
cd SimulateCraft
uv sync --extra llm --extra dev --extra docs
```

Avoid `uv sync --all-extras` unless you need embeddings — that pulls a large
Torch/CUDA stack.

## Checks

```bash
uv run ruff check src tests
uv run ruff format src tests
uv run pytest
uv run mypy src/simulatecraft
DISABLE_MKDOCS_2_WARNING=true uv run mkdocs build
```

Coverage (optional):

```bash
uv pip install pytest-cov
uv run pytest --cov=simulatecraft --cov-report=term-missing
```

As of the last local run: **~95%** line coverage across `src/simulatecraft`
(~151 tests). Core packages, Minecraft env/bridge/RCON (mocked), viewers,
CLI, explorer, and server control paths are covered. Remaining gaps are mostly
uvicorn `serve()` wiring and a few rare error branches.

## Guidelines

- Match existing style (Ruff, type hints where the surrounding code has them).
- Prefer tests for runner/server/control and brain helpers; Minecraft live
  servers are not required for unit tests.
- Keep secrets out of commits (`.env`, API keys).
- Docs live in `docs/`; API reference under `reference/` is **generated** —
  improve docstrings in `src/simulatecraft/` instead of hand-editing those pages.
- Use `staging` for integration work; `main` publishes docs to GitHub Pages.

## Pull requests

1. Branch from `staging` (or `main` for docs-only fixes).
2. Describe *why* the change exists.
3. Note how you tested (commands + expected result).

Questions? Open an issue on
[GitHub](https://github.com/DanyalAbbas/SimulateCraft/issues).
