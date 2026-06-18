# Castellan

Multi-agent cloud-security remediation on the [Band](https://app.band.ai) platform.
Specialist agents detect live cloud misconfigurations, collaborate on a shared
**remediation blackboard**, get **constrained** by a policy agent, **gated** by a human,
and execute as **reversible** actions — every step sealed in a tamper-evident audit chain.

See [`docs/`](docs/) for the full spec. `docs/CASTELLAN_SDK_NOTES.md` is authoritative
for all Band SDK details; `docs/CASTELLAN_BUILD_PLAN.md` tracks milestones and build deviations.

> **Status: M1 complete.** The **Scanner** agent runs a real cloud scan against LocalStack and
> posts the structured findings into a Band room, addressed to the Controller. Detection,
> finding formatting, and delivery are **deterministic Python** — the LLM only triggers the scan.
> M2+ (Controller, specialists, Risk gate, action layer, audit chain) are not built yet.

## Verified SDK facts (band-sdk 1.0.0, this install)

| Thing | Value |
| --- | --- |
| pip package | `band-sdk` (with extras: `[langgraph] [crewai] [pydantic-ai] [anthropic]`) |
| import module | **`band`** (`thenvoi` is not importable) |
| platform tool prefix | **`band_`** (e.g. `band_send_message`) |
| connection env vars | `BAND_WS_URL`, `BAND_REST_URL` (default to app.band.ai if unset) |
| config loader | `band.config.load_agent_config(key)` reads `./agent_config.yaml` from CWD |

## How the Scanner works (M1)

The Scanner is a real Band agent (LangGraph + Featherless), but the security work is
deterministic, not model-generated:

1. A human posts **`@Scanner scan now`** in the room. The Featherless model's only job is to
   call one tool: `cloud_scan_and_emit_findings`.
2. That tool (in [cloud/scan.py](cloud/scan.py) + [connection/poster.py](connection/poster.py))
   inspects the cloud target, builds one `Finding` per real misconfiguration **in code**, and
   posts each as a fenced ```json message to the Controller via the Band REST client — outside
   the LLM loop. The LLM never authors JSON, so values (e.g. an IAM `"*"`) are byte-exact.

Detection (read-only, [cloud/scan.py](cloud/scan.py)) covers three classes:
`data` (public S3 bucket), `iam` (inline policy `Action:"*"`/`Resource:"*"`),
`network` (security group inbound `0.0.0.0/0` on port 22).

> Featherless currently only *triggers* the Scanner. It returns at **M6** as a separate,
> non-blocking **Evidence Analyst** (see `docs/CASTELLAN_BUILD_PLAN.md` → Build deviations).

## Setup

```bash
cd castellan
uv sync                                            # install deps from pyproject.toml / uv.lock
cp .env.example .env                               # then fill in
cp agent_config.example.yaml agent_config.yaml     # then fill in
```

Fill in:
- `.env` → `FEATHERLESS_API_KEY` (required). `BAND_WS_URL` / `BAND_REST_URL` only if your Band
  isn't the standard hosted app.band.ai.
- `agent_config.yaml` → `scanner.agent_id`, `scanner.api_key` (from registering "Scanner" as an
  External Agent in the Band dashboard). Also register a **Controller** agent and add it to the
  room so the Scanner's findings have a valid mention target.

`.env` and `agent_config.yaml` are gitignored — never commit them.

## Run (M1)

**1. Start the cloud target (LocalStack) and seed the demo misconfigurations:**
```bash
cd castellan
docker compose up -d localstack
uv run python -m cloud.seed       # creates: public S3 bucket, over-permissive IAM role, SG open 0.0.0.0/0:22
```

**2a. Drive it through Band (the real path):** start the Scanner, then trigger it from the room.
```bash
uv run python agents/scanner/scanner.py
```
In a Band room (with **Scanner** + **Controller** as participants), post **`@Scanner scan now`**.
The Scanner posts exactly three findings to the Controller (`data` / `iam` / `network`).

**2b. Or run delivery directly (no LLM), useful for debugging:**
```bash
uv run python scripts/scan_and_post.py <room_id>
```

**Inspect detection offline (no Band, no model):**
```bash
uv run python -m cloud.scan        # prints the ready-to-send finding messages
```

## Roadmap (built strictly in milestone order — see `docs/CASTELLAN_BUILD_PLAN.md`)

✅ M0 Band pipe · ✅ M1 deterministic Scanner findings · M2 Controller + Data Specialist ·
**M3 Risk reject→revise loop** · **M4 Action Layer + human gate** · M5 audit chain ·
M6 IAM/Network specialists + Featherless Evidence Analyst · M7 UI · M8 submission.
