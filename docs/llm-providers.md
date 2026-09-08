# Connect an LLM

Prefer **OpenRouter**, **9Router**, or your own OpenAI-compatible API. Groq is fine for a quick smoke test but rate-limits quickly under agent load.

SimulateCraft needs a language model to decide each agent’s next action.
Pick **one** path below and put it in `.env` at the repo root.

Auto-select order when `SIMULATECRAFT_MODEL` is unset:

1. `OPENROUTER_API_KEY` → free OpenRouter Llama  
2. `GROQ_API_KEY` → Groq default model  
3. Otherwise → offline `test` model (no real thinking)

For 9Router / custom gateways, always set `SIMULATECRAFT_MODEL` yourself.

---

## Option A — OpenRouter (recommended)

One key for many models, including free ones.

1. Create a key at [openrouter.ai/keys](https://openrouter.ai/keys).
2. In `.env`:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

3. Run `.\run.ps1` / `./run.sh` (auto-picks a free Llama model), or set a model:

```bash
SIMULATECRAFT_MODEL=openrouter:meta-llama/llama-3.1-8b-instruct:free
# browse free models: https://openrouter.ai/models?q=:free
```

!!! note
    Free OpenRouter models can still rate-limit with several agents. Switch to a paid OpenRouter model, 9Router, or your own API if ticks feel slow.

---

## Option B — 9Router (local gateway)

[9Router](https://9router.com/) is a local OpenAI-compatible proxy. Start it first
(dashboard usually at `http://localhost:20128`), then point SimulateCraft at it:

```bash
OPENAI_BASE_URL=http://localhost:20128/v1
OPENAI_API_KEY=<key from 9Router dashboard>
SIMULATECRAFT_MODEL=oc/mimo-v2.5-free
```

Model ids come from the 9Router dashboard / `GET /v1/models` (e.g. `kr/...`, `oc/...`).

Check the gateway:

```bash
curl -s http://localhost:20128/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

---

## Option C — Your own OpenAI-compatible API

Same three variables as 9Router — any endpoint that speaks the OpenAI chat API:

```bash
OPENAI_BASE_URL=https://your-gateway.example/v1
OPENAI_API_KEY=...
SIMULATECRAFT_MODEL=your-model-id
```

---

## Option D — Groq (quick try only — rate limits fast)

Useful for a short smoke test, not sustained multi-agent runs.

1. Create a key at [console.groq.com/keys](https://console.groq.com/keys).
2. In `.env`:

```bash
GROQ_API_KEY=gsk_...
```

Optional model override:

```bash
SIMULATECRAFT_MODEL=groq:openai/gpt-oss-120b
# or a smaller/faster one:
# SIMULATECRAFT_MODEL=groq:openai/gpt-oss-20b
```

---

## Option E — Offline (no key)

For wiring tests only — agents use canned responses:

```bash
SIMULATECRAFT_MODEL=test
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Script exits “No LLM provider” | Set a non-empty `OPENROUTER_API_KEY` (or 9Router / Groq vars) in `.env` |
| `OPENAI_BASE_URL` set but still fails | Also set `SIMULATECRAFT_MODEL` (and usually `OPENAI_API_KEY`) |
| OpenRouter auth error | Key must look like `sk-or-...` |
| 9Router connection refused | Start 9Router; base URL must include `/v1` |
| Agents barely chat / act slowly | Use a paid OpenRouter model, 9Router, or your own API — free tiers throttle |

Next: [Use the live viewer](viewer.md)
