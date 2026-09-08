#!/usr/bin/env bash
# SimulateCraft one-line installer (macOS / Linux)
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/DanyalAbbas/SimulateCraft/main/install.sh | bash
# Prerequisites (install yourself first): Git, Node.js 18+, Docker Desktop (for bundled MC)
# Optional env:
#   SIMULATECRAFT_DIR=~/SimulateCraft
#   OPENROUTER_API_KEY=...        # written into .env if set
#   OPENAI_BASE_URL=...           # for 9Router / own OpenAI-compatible API
#   OPENAI_API_KEY=...
#   SIMULATECRAFT_MODEL=...
#   SIMULATECRAFT_SKIP_RUN=1      # clone only, don't launch
#   SIMULATECRAFT_FORCE_RUN=1     # launch even if no LLM provider configured
#   SIMULATECRAFT_NO_DOCKER=1     # pass --no-docker to the launcher
set -euo pipefail

REPO_URL="${SIMULATECRAFT_REPO:-https://github.com/DanyalAbbas/SimulateCraft.git}"
TARGET_DIR="${SIMULATECRAFT_DIR:-$HOME/SimulateCraft}"
BRANCH="${SIMULATECRAFT_BRANCH:-main}"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing \`$1\`."
    echo "$2"
    exit 1
  fi
}

env_value_set() {
  # True if KEY=non-empty-value exists in .env (ignores blank KEY= lines).
  local key="$1"
  grep -qE "^${key}=.+" .env 2>/dev/null
}

echo "==> SimulateCraft installer"
echo "    Target: $TARGET_DIR"

need git "Install git, then re-run this installer."
need node "Install Node.js 18+ from https://nodejs.org"
need npm "npm ships with Node.js — reinstall from https://nodejs.org"

NODE_MAJOR="$(node -p "process.versions.node.split('.')[0]" 2>/dev/null || echo 0)"
if [[ "${NODE_MAJOR}" -lt 18 ]]; then
  echo "Node.js 18+ required (found $(node -v 2>/dev/null || echo unknown))."
  echo "Install from https://nodejs.org and re-run."
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
fi
need uv "uv install failed. See https://docs.astral.sh/uv/"

if [[ -d "$TARGET_DIR/.git" ]]; then
  echo "==> Updating existing clone…"
  git -C "$TARGET_DIR" fetch origin
  git -C "$TARGET_DIR" checkout "$BRANCH"
  git -C "$TARGET_DIR" pull --ff-only origin "$BRANCH" || true
else
  if [[ -e "$TARGET_DIR" ]]; then
    echo "Refusing to overwrite non-git path: $TARGET_DIR"
    echo "Set SIMULATECRAFT_DIR to an empty/new folder and retry."
    exit 1
  fi
  echo "==> Cloning SimulateCraft…"
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$TARGET_DIR"
fi

cd "$TARGET_DIR"

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
  else
    touch .env
  fi
fi

write_env_kv() {
  local key="$1" val="$2"
  if grep -q "^${key}=" .env 2>/dev/null; then
    sed -i.bak "s|^${key}=.*|${key}=${val}|" .env && rm -f .env.bak
  else
    echo "${key}=${val}" >> .env
  fi
}

if [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
  write_env_kv OPENROUTER_API_KEY "$OPENROUTER_API_KEY"
  echo "==> Wrote OPENROUTER_API_KEY into .env"
fi
if [[ -n "${OPENAI_BASE_URL:-}" ]]; then
  write_env_kv OPENAI_BASE_URL "$OPENAI_BASE_URL"
  echo "==> Wrote OPENAI_BASE_URL into .env"
fi
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  write_env_kv OPENAI_API_KEY "$OPENAI_API_KEY"
  echo "==> Wrote OPENAI_API_KEY into .env"
fi
if [[ -n "${SIMULATECRAFT_MODEL:-}" ]]; then
  write_env_kv SIMULATECRAFT_MODEL "$SIMULATECRAFT_MODEL"
  echo "==> Wrote SIMULATECRAFT_MODEL into .env"
fi
if [[ -n "${GROQ_API_KEY:-}" ]]; then
  write_env_kv GROQ_API_KEY "$GROQ_API_KEY"
  echo "==> Wrote GROQ_API_KEY into .env"
fi

HAS_PROVIDER=0
if env_value_set OPENROUTER_API_KEY \
  || env_value_set OPENAI_BASE_URL \
  || env_value_set GROQ_API_KEY \
  || env_value_set SIMULATECRAFT_MODEL; then
  HAS_PROVIDER=1
fi

chmod +x run.sh install.sh 2>/dev/null || true

if [[ "${SIMULATECRAFT_SKIP_RUN:-}" == "1" ]]; then
  echo "==> Setup complete (skip run). Next:"
  echo "    1. Edit $TARGET_DIR/.env with OpenRouter / 9Router / your API"
  echo "    2. cd \"$TARGET_DIR\" && ./run.sh"
  exit 0
fi

if [[ "$HAS_PROVIDER" -eq 0 && "${SIMULATECRAFT_FORCE_RUN:-}" != "1" ]]; then
  echo
  echo "==> Repo ready at $TARGET_DIR"
  echo "No LLM provider configured yet (blank keys in .env do not count)."
  echo
  echo "Edit .env, then launch:"
  echo "    Prefer OpenRouter:  OPENROUTER_API_KEY=sk-or-..."
  echo "    Or 9Router / own API:"
  echo "      OPENAI_BASE_URL=http://localhost:20128/v1"
  echo "      OPENAI_API_KEY=..."
  echo "      SIMULATECRAFT_MODEL=oc/mimo-v2.5-free"
  echo "    Docs: https://danyalabbas.github.io/SimulateCraft/llm-providers/"
  echo
  echo "    cd \"$TARGET_DIR\" && ./run.sh"
  echo
  echo "(Docker Desktop needed for the bundled Minecraft 1.21.4 server.)"
  exit 0
fi

EXTRA_ARGS=()
if [[ "${SIMULATECRAFT_NO_DOCKER:-}" == "1" ]]; then
  EXTRA_ARGS+=(--no-docker)
fi

echo "==> Launching SimulateCraft…"
exec ./run.sh "${EXTRA_ARGS[@]}" "$@"
