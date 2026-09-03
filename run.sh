#!/usr/bin/env bash
# One command: install Python + Node deps, start Minecraft, run LLM agents.
set -euo pipefail
cd "$(dirname "$0")"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing \`$1\`."
    echo "$2"
    exit 1
  fi
}

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (Python package runner)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi
need uv "uv install failed. See https://docs.astral.sh/uv/"
need node "Install Node.js 18+ from https://nodejs.org (needed for the Minecraft bot)."
need npm "npm ships with Node.js."

echo "Installing Python packages…"
uv sync --extra llm

echo
exec uv run simulatecraft "$@"
