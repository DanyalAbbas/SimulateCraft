# LLM providers

SimulateCraft talks to models through [pydantic-ai](https://ai.pydantic.dev/).
Set a model with `SIMULATECRAFT_MODEL`, or let [`resolve_model()`](reference/brains/llm.md)
pick a free default from your environment.

**Auto-select order:** `SIMULATECRAFT_MODEL` → `GROQ_API_KEY` → `OPENROUTER_API_KEY` → offline `test`.

Install the LLM extra once:

```bash
uv sync --extra llm
# or: pip install 'simulatecraft[llm]'
```

---

## OpenRouter

[OpenRouter](https://openrouter.ai) is a single API that routes to many providers.
It has a free tier (rate-limited) and paid models.

### Setup

1. Create a key at [openrouter.ai/keys](https://openrouter.ai/keys).
2. Put it in `.env` at the repo root (or export it):

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

3. Run SimulateCraft — with no `SIMULATECRAFT_MODEL`, it auto-picks a free Llama model:

```bash
./run.sh
# equivalent model string:
# openrouter:meta-llama/llama-3.1-8b-instruct:free
```

### Choose a model

Prefix every OpenRouter id with `openrouter:`:

```bash
# Free examples — browse https://openrouter.ai/models?q=:free
export SIMULATECRAFT_MODEL="openrouter:meta-llama/llama-3.1-8b-instruct:free"
export SIMULATECRAFT_MODEL="openrouter:google/gemma-3-27b-it:free"
export SIMULATECRAFT_MODEL="openrouter:mistralai/mistral-7b-instruct:free"

# Paid examples
export SIMULATECRAFT_MODEL="openrouter:anthropic/claude-sonnet-4.6"
export SIMULATECRAFT_MODEL="openrouter:openai/gpt-4o-mini"
```

### How it works in code

`openrouter:…` is built with pydantic-ai’s `OpenRouterModel` and reads
`OPENROUTER_API_KEY` from the environment. Missing key → clear error pointing at
the OpenRouter keys page.

### Tips

- Free models often throttle under multi-agent load; prefer Groq or 9Router for
  faster tick loops.
- Keep the key in `.env` — never commit it.
- Credits / usage: [openrouter.ai/activity](https://openrouter.ai/activity).

---

## 9Router (OpenAI-compatible gateway)

[9Router](https://9router.com/) is a **local** OpenAI-compatible proxy
([GitHub](https://github.com/decolua/9router)). It sits between SimulateCraft and
40+ backends, with routing, fallback, and token-saving features.

Default local endpoint:

| | |
|---|---|
| Dashboard | `http://localhost:20128` |
| OpenAI API base | `http://localhost:20128/v1` |

### Setup

1. Install and start 9Router (see [9router.com](https://9router.com/) or the
   [decolua/9router](https://github.com/decolua/9router) README).
2. Open the dashboard, connect a provider, and copy the **local API key**.
3. Configure SimulateCraft:

```bash
# .env
OPENAI_BASE_URL=http://localhost:20128/v1
OPENAI_API_KEY=<key from 9Router dashboard>
SIMULATECRAFT_MODEL=oc/mimo-v2.5-free
```

Model ids are whatever 9Router exposes (often prefixed), for example:

| Example id | Typical route |
|---|---|
| `oc/mimo-v2.5-free` | OpenCode / free-tier combo |
| `kr/claude-sonnet-4.5` | Kiro-routed Claude |
| `cc/claude-opus-4-7` | Claude Code route |

List models from the gateway:

```bash
curl -s http://localhost:20128/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY" | head
```

Then:

```bash
./run.sh
# or
uv run simulatecraft --model oc/mimo-v2.5-free
```

### Explicit model strings

When `OPENAI_BASE_URL` is set, bare ids (anything that is not a native provider
prefix like `groq:` / `openrouter:`) use chat-completions against that base URL.
You can also be explicit:

```bash
export SIMULATECRAFT_MODEL="openai-compatible:oc/mimo-v2.5-free"
export SIMULATECRAFT_MODEL="openai:oc/mimo-v2.5-free"   # also uses OPENAI_BASE_URL
```

!!! note "Chat Completions, not Responses"
    Local gateways usually implement `/v1/chat/completions`. SimulateCraft routes
    these models through pydantic-ai’s OpenAI **chat** client so 9Router / LiteLLM /
    vLLM work without the Responses API.

### Troubleshooting

| Symptom | Fix |
|---|---|
| `OPENAI_BASE_URL is not set` | Export the base URL including `/v1` |
| Connection refused | Start 9Router; confirm `curl http://localhost:20128/v1/models` |
| 401 / invalid key | Paste the key from the 9Router dashboard into `OPENAI_API_KEY` |
| Model not found | Pick an id from `/v1/models` or the dashboard |
| `./run.sh` says no LLM key | Set `OPENAI_BASE_URL` + `OPENAI_API_KEY` + `SIMULATECRAFT_MODEL` |

Same pattern works for other OpenAI-compatible servers (LiteLLM, vLLM, LocalAI,
Ollama’s OpenAI shim) — only the base URL and model id change.

---

## Groq (fast free tier)

```bash
# https://console.groq.com/keys
GROQ_API_KEY=gsk_...
# optional override:
SIMULATECRAFT_MODEL=groq:openai/gpt-oss-120b
```

Good default for agent tick loops (low latency).

---

## Direct cloud providers

```bash
export SIMULATECRAFT_MODEL="anthropic:claude-sonnet-4-5"   # ANTHROPIC_API_KEY
export SIMULATECRAFT_MODEL="openai:gpt-4o-mini"            # OPENAI_API_KEY (official API)
export SIMULATECRAFT_MODEL="google-gla:gemini-2.0-flash"   # GOOGLE_API_KEY
```

If both `OPENAI_BASE_URL` and an official OpenAI key are set, `openai:…` is sent
to the **gateway**. Unset `OPENAI_BASE_URL` to hit OpenAI directly.

---

## Offline / CI

```bash
export SIMULATECRAFT_MODEL=test
```

Uses pydantic-ai’s `TestModel` (no network). Useful for wiring tests without keys.

---

## Environment cheat sheet

| Variable | Purpose |
|---|---|
| `SIMULATECRAFT_MODEL` | Full model string (wins over auto-select) |
| `GROQ_API_KEY` | Auto → `groq:openai/gpt-oss-120b` |
| `OPENROUTER_API_KEY` | Auto → free OpenRouter Llama |
| `OPENAI_BASE_URL` | OpenAI-compatible gateway (e.g. 9Router) |
| `OPENAI_API_KEY` | Key for that gateway (or official OpenAI) |
| `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` | Direct providers |

Example `.env` for OpenRouter:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
# SIMULATECRAFT_MODEL=openrouter:google/gemma-3-27b-it:free
```

Example `.env` for 9Router:

```bash
OPENAI_BASE_URL=http://localhost:20128/v1
OPENAI_API_KEY=your-9router-dashboard-key
SIMULATECRAFT_MODEL=oc/mimo-v2.5-free
```
