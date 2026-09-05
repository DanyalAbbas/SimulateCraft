# Contributing

Thanks for helping. Small, focused PRs are easiest to review.

## Dev setup

```bash
git clone https://github.com/DanyalAbbas/SimulateCraft.git
cd SimulateCraft
uv sync --extra llm --extra dev --extra docs
```

Avoid `--all-extras` unless you need embeddings (large Torch download).

## Before you open a PR

```bash
uv run ruff check src tests
uv run ruff format src tests
uv run pytest
uv run mypy src/simulatecraft
```

## Guidelines

- Match existing style (Ruff).
- Prefer unit tests with mocks — a live Minecraft server is not required.
- Never commit `.env` or API keys.
- Tutorial docs live in `docs/*.md`. The **API reference** is generated from
  docstrings — improve the code comments, don’t hand-edit `reference/`.
- Integrate on `staging`; `main` publishes the docs site.

## Pull requests

1. Branch from `staging` (docs-only fixes can use `main`).
2. Explain *why* the change exists.
3. Note how you tested.

Issues: [GitHub](https://github.com/DanyalAbbas/SimulateCraft/issues).
