# Castellan — Mission Control

> Autonomous cloud-security remediation that an auditor can trust.

Five AI agents coordinate in one Band room to take a cloud-security misconfiguration from detection to a reversed, audited fix. Every remediation is **gated by a human**, **reversible to the exact prior state**, and sealed in a **tamper-evident SHA-256 audit chain** reconstructed from the Band room itself.

Built for Track 3 — Regulated & High-Stakes Workflows — Band of Agents Hackathon 2026.

---

## What it does

When a cloud misconfiguration is detected, Castellan walks it through a disciplined pipeline:

```
Scanner → Controller → Data Specialist → Risk Policy → Human gate → Action Layer → Audit
```

Each step is a real message in the Band room. The audit chain is reconstructed *from that room* — not written to a separate log — so it can never disagree with what the agents actually did, and Band is load-bearing, not a wrapper.

A **Mission Control** UI lets anyone inspect the full case, walk the sealed chain, and run a live tamper test: mutate one record and watch the chain break at that record and cascade through every downstream entry.

---

## Agents

| Agent | Model | Role |
|---|---|---|
| Scanner | deterministic | Detects misconfigurations, opens a case in the Band room |
| Controller | Anthropic Claude | Routes each case to the right specialist |
| Data Specialist | Anthropic Claude | Inspects the resource live, proposes a reversible fix + rollback |
| Risk Policy | Anthropic Claude + deterministic floor | Vets every proposal; fail-closed before LLM weighs in |
| Action Layer | deterministic | Executes only after human approval; reversible and idempotent |
| Evidence Analyst | Featherless AI (Qwen 2.5) | Posts plain-language case summary for the human approver |

---

## Design decisions

**Deterministic-first.** The LLM only triggers — it proposes a fix, judges a risk, or summarises evidence. Every security-critical decision (validation, gating, execution, hashing) is deterministic Python. A model hiccup degrades to *no action*, never a corrupted one.

**A hash chain that is actually proof.** Two corrections most audit chains skip:

1. **Hash the attribution, not just the payload.** Sender, role, and timestamp are inside the hash — so *who approved* is part of what's proven, not loose metadata that can be quietly rewritten.
2. **Anchor the head out-of-band.** Storing the trusted head inside the same room you're declaring untrusted is circular. The anchor lives outside the room; a room-level attacker can't reach it.

**Audit reconstructed from Band.** The hash chain is rebuilt from the Band room's message history, not a side-channel database. This ties the proof directly to the coordination medium and means the audit can't drift from what the agents actually did.

---

## Proof

Live Band room: `eb4379c9-165a-4139-bc8a-dd166f8280d8`

```
head   : 9f55f86d84ddbd016aeba56fd45ab2f50e91b1a8dd64e8d8c2317ddd82946919
result : VALID
tamper : first broken seq = 4  (Risk Verdict)
```

Verified with:
```bash
uv run python scripts/audit_verify.py eb4379c9-165a-4139-bc8a-dd166f8280d8
uv run python scripts/audit_verify.py --tamper eb4379c9-165a-4139-bc8a-dd166f8280d8
```

---

## Stack

- **Band** — multi-agent coordination and system of record
- **Anthropic Claude** — Controller, Data Specialist, Risk Policy
- **Featherless AI** — Evidence Analyst (Qwen/Qwen2.5-7B-Instruct)
- **LangGraph + LangChain** — agent runtime
- **Python** — all deterministic safety-critical logic
- **FastAPI** — read-only bridge between Mission Control and the audit functions
- **Next.js + Tailwind CSS** — Mission Control frontend

---

## Running locally

### Prerequisites

- Python 3.12+ with `uv`
- Node.js 18+
- LocalStack (for the mock cloud environment)
- A Band account with agent handles configured

### Setup

```bash
# Clone and install
git clone https://github.com/Georgexxe/castellan
cd castellan
uv sync

# Copy and fill in your credentials
cp .env.example .env
cp agent_config.example.yaml agent_config.yaml
# Edit both files with your Band handles, Anthropic key, and Featherless key
```

### Seed the mock cloud

```bash
docker compose up -d          # starts LocalStack
uv run python -m cloud.seed
```

### Run a full pipeline

```bash
# 1 — Scanner: detect and post findings
uv run python scripts/scan_and_post.py <room_id>

# 2 — Controller, Risk Policy, Data Specialist: start agents in separate terminals
uv run python agents/controller/controller.py
uv run python agents/risk/risk.py
uv run python agents/specialists/data/data_specialist.py

# 3 — Run the Action Layer (it requests human approval in Band, then executes)
uv run python scripts/run_action.py <room_id> --latest-approved <cls:resource>

# 4 — Verify the audit chain
uv run python scripts/audit_verify.py <room_id>
uv run python scripts/audit_verify.py --tamper <room_id>
```

### Mission Control UI

```bash
# Terminal 1 — FastAPI read-bridge
uv run uvicorn ui.api.main:app --reload --port 8000

# Terminal 2 — Next.js frontend
cd ui/web && npm install && npm run dev
```

Open `http://localhost:3000`.

---

## Repository structure

```
agents/           Agent implementations (Scanner, Controller, Risk, Specialist, Evidence)
connection/       Band SDK wrappers, tools, and the audit reader
coordination/     Shared models, board state, hash chain, remediation fixtures
actions/          Executor, human gate, ledger
cloud/            LocalStack client, scanner, seeder
scripts/          CLI runners and audit verifier
ui/
  api/            FastAPI read-bridge (zero-logic passthrough)
  web/            Mission Control — Next.js frontend
docs/             CASTELLAN_SDK_NOTES.md — authoritative AS-BUILT decisions
```

---

## Docs

**`docs/CASTELLAN_SDK_NOTES.md`** — the full authoritative AS-BUILT: every transport decision, model choice, and non-obvious gotcha documented as it was discovered.

---

*Band of Agents Hackathon 2026 — Track 3: Regulated & High-Stakes Workflows*
