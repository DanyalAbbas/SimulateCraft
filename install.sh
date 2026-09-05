#!/usr/bin/env bash
# SimulateCraft one-line installer (macOS / Linux)
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/DanyalAbbas/SimulateCraft/main/install.sh | bash
# Optional env:
#   SIMULATECRAFT_DIR=~/SimulateCraft
#   OPENROUTER_API_KEY=...        # written into .env if set
#   OPENAI_BASE_URL=...           # for 9Router / own OpenAI-compatible API
#   OPENAI_API_KEY=...
#   SIMULATECRAFT_MODEL=...
#   SIMULATECRAFT_SKIP_RUN=1      # clone + sync only, don't launch
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

echo "==> SimulateCraft installer"
echo "    Target: $TARGET_DIR"

need git "Install git, then re-run this installer."
need node "Install Node.js 18+ from https://nodejs.org"
need npm "npm ships with Node.js — reinstall from https://nodejs.org"

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

if ! grep -qE '^(OPENROUTER_API_KEY|OPENAI_BASE_URL|GROQ_API_KEY)=.+' .env 2>/dev/null; then
  echo
  echo "No LLM provider configured in .env yet."
  echo "Prefer OpenRouter, 9Router, or your own OpenAI-compatible API (Groq rate-limits quickly)."
  echo "Edit $TARGET_DIR/.env — see https://danyalabbas.github.io/SimulateCraft/llm-providers/"
  echo "Then: cd \"$TARGET_DIR\" && ./run.sh"
  echo
fi

chmod +x run.sh

if [[ "${SIMULATECRAFT_SKIP_RUN:-}" == "1" ]]; then
  echo "==> Setup complete (skip run). Next:"
  echo "    cd \"$TARGET_DIR\" && ./run.sh"
  exit 0
fi

EXTRA_ARGS=()
if [[ "${SIMULATECRAFT_NO_DOCKER:-}" == "1" ]]; then
  EXTRA_ARGS+=(--no-docker)
fi

echo "==> Launching SimulateCraft…"
exec ./run.sh "${EXTRA_ARGS[@]}" "$@"
