# Castellan

Multi-agent cloud-security remediation on the [Band](https://app.band.ai) platform.
Specialist agents detect live cloud misconfigurations, collaborate on a shared
**remediation blackboard**, get **constrained** by a policy agent, **gated** by a human,
and execute as **reversible** actions — every step sealed in a tamper-evident audit chain.

See [`docs/`](docs/) for the full spec. `docs/CASTELLAN_SDK_NOTES.md` is authoritative
for all Band SDK details.

> **Status: M0 (prove the Band pipe).** Only the Scanner agent exists, as a reply-only
> connectivity smoke test. Nothing past M0 is built yet.

## Verified SDK facts (band-sdk 1.0.0, this install)

| Thing | Value |
| --- | --- |
| pip package | `band-sdk` (with extras: `[langgraph] [crewai] [pydantic-ai] [anthropic]`) |
| import module | **`band`** (`thenvoi` is not importable) |
| platform tool prefix | **`band_`** (e.g. `band_send_message`) |
| connection env vars | `BAND_WS_URL`, `BAND_REST_URL` (default to app.band.ai if unset) |
| config loader | `band.config.load_agent_config(key)` reads `./agent_config.yaml` from CWD |

## Setup

```bash
cd castellan
uv sync                                   # install deps from pyproject.toml / uv.lock
cp .env.example .env                      # then fill in
cp agent_config.example.yaml agent_config.yaml   # then fill in
```

Fill in:
- `.env` → `BAND_WS_URL`, `BAND_REST_URL`, `FEATHERLESS_API_KEY`
- `agent_config.yaml` → `scanner.agent_id`, `scanner.api_key` (from registering "Scanner"
  as an External Agent in the Band dashboard)

`.env` and `agent_config.yaml` are gitignored — never commit them.

## Run the Scanner (M0 smoke test)

```bash
cd castellan
uv run python agents/scanner/scanner.py
```

The process connects to Band (WS + REST) and idles. In a Band room, **@mention the
Scanner** with any message. It should reply *in the room*, addressing you by @mention.

**If the process runs but nothing appears in the room**, the agent returned plain LLM
text instead of calling `band_send_message` (SDK_NOTES §3) — that's the M0 trap, fixed
in the system prompt, not the transport.

## Roadmap (built strictly in milestone order — see `docs/CASTELLAN_BUILD_PLAN.md`)

M1 findings · M2 Controller + Data Specialist · **M3 Risk reject→revise loop** ·
**M4 Action Layer + human gate** · M5 audit chain · M6 IAM/Network specialists ·
M7 UI · M8 submission.
