# Castellan — Technical Architecture & Build Spec

> Companion to `CASTELLAN_PRODUCT_BRIEF.md`. Audience: developers reviewing feasibility, and Claude Code as the build foundation.
> Platform facts below are drawn from Band's docs (`docs.band.ai`); registration is at `app.band.ai`. **The pip package is `band-sdk`; the import module is `band` or `thenvoi` depending on version. For all SDK specifics — imports, env vars, tool names, adapter signatures, provider routing — defer to `CASTELLAN_SDK_NOTES.md`, which is authoritative and supersedes SDK details in this file** (e.g. the Controller runs on an Anthropic model, not AI/ML API — SDK_NOTES §8).

---

## 1. System overview

Castellan is a set of **independent agent processes** that connect *out* to a single **Band room** and coordinate there. No agent runs "on" Band — each runs in our environment (locally, or one container each), uses its own framework and its own LLM provider, and connects to Band over **REST (commands out) + WebSocket (events in)** via `band-sdk`.

The room is a **routed group chat for agents** where an agent only receives a message if it is **@mentioned**. Humans see everything; agents see only what's addressed to them. We exploit this to run a **blackboard control loop**: the room is the shared blackboard, agents read the shared case via context fetch, and a Controller uses @mention to *activate* the specialist whose expertise the current case state calls for. Coordination is cooperative and emergent — not a hardcoded pipeline, not an auction, not a debate.

```
                         ┌─────────────────────────────────────────┐
                         │       BAND ROOM = SHARED BLACKBOARD       │
                         │   (case file + routed activation + audit) │
                         └─────────────────────────────────────────┘
        REST out / WS in        ▲      ▲      ▲      ▲      ▲
        ┌──────────────┬────────┘      │      │      │      └────────┐
        │              │               │      │      │               │
  ┌───────────┐  ┌──────────────┐  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────┐
  │  Scanner  │  │  Controller  │  │  IAM   │ │ Network│ │  Data  │ │  Risk /  │
  │ (Intake)  │  │ (blackboard  │  │  Spec. │ │  Spec. │ │  Spec. │ │  Policy  │
  │           │  │  control)    │  │        │ │        │ │        │ │ (constr.)│
  └───────────┘  └──────────────┘  └────────┘ └────────┘ └────────┘ └──────────┘
   Featherless     Anthropic         ── AI/ML API specialists ──       distinct Claude
   (LangGraph)     (Pydantic AI)         (CrewAI)                     (Anthropic adapter)
        │                                   │                              │
        │                                   ▼                              │
        │                          ┌─────────────────┐                    │
        └────────────────────────► │  Action Layer   │ ◄──── human gate ──┘
                                    │  + Rollback     │      (approval = key)
                                    │   Registry      │
                                    └─────────────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐        ┌──────────────┐
                                    │  Live target    │        │  Audit Chain │
                                    │  LocalStack/AWS │        │ (SHA-256 seal│
                                    │  (boto3)        │        │  of Band log)│
                                    └─────────────────┘        └──────────────┘
```

## 2. How Band is the coordination layer (not a wrapper)

We use Band's primitives as the *substance* of the blackboard architecture:

- **@mention routing = activation.** The Controller wakes the specialist whose preconditions match the current case state by @mentioning it. Specialists that aren't relevant to the current state never receive the message and never burn cycles.
- **Shared context = reading the blackboard.** An activated specialist rehydrates the full case via `GET /agent/chats/{id}/context` before contributing — it sees every prior contribution and constraint, even ones not addressed to it.
- **Structured messages = blackboard contributions.** Each contribution (diagnosis, proposed fix, dependency, rollback, constraint) is a typed JSON payload in a Band message, parsed by type. The Controller derives board state from these.
- **Dynamic participant management.** The Controller recruits specialists at runtime via `thenvoi_lookup_peers` / `thenvoi_add_participant` based on the finding's class. A Data-encryption case never pulls in the Network specialist.
- **Unified transcript = audit substrate.** Band already records the full typed trace; our audit chain seals *that*, so the blackboard's entire evolution is provably intact without us reinventing logging.

Platform tools available to every SDK agent: `<prefix>_send_message`, `<prefix>_send_event`, `<prefix>_add_participant`, `<prefix>_remove_participant`, `<prefix>_get_participants`, `<prefix>_lookup_peers`, and `<prefix>_create_chatroom`, where `<prefix>` is resolved at install time as `band` or `thenvoi` (SDK_NOTES §1, §3). **Note:** plain LLM output is not delivered into the Band room unless the agent calls `<prefix>_send_message` with at least one @mention.

## 3. Agent roster

| Agent | Role | Framework | Model provider | Why this provider |
| --- | --- | --- | --- | --- |
| **Scanner / Intake** | Ingest cloud config + CSPM findings; normalize; open a case (blackboard) per finding | LangGraph | **Featherless** (open-source model) | High-volume parsing/extraction → Featherless partner prize |
| **Controller** | Blackboard control: read case state, activate the right specialist, detect convergence, drive to a complete vetted plan | Pydantic AI | **Anthropic** (`claude-sonnet-4-5`) | Most tool-intensive/multi-turn agent; an Anthropic model dodges the documented Pydantic-AI + OpenAI `content:null` bug (SDK_NOTES §8) |
| **IAM Specialist** | When activated, contribute identity/permission diagnosis + reversible IAM fix | CrewAI | **AI/ML API** | Reasoning specialist |
| **Network Specialist** | Contribute network/security-group diagnosis + reversible fix | CrewAI | **AI/ML API** | Reasoning specialist |
| **Data/Encryption Specialist** | Contribute storage/encryption diagnosis + reversible fix | CrewAI | **AI/ML API** | Reasoning specialist |
| **Risk / Policy** | Post **hard constraints** onto the case; invalidate non-compliant proposals; force revision | Anthropic adapter | **Anthropic** (a *different* Claude model, e.g. `claude-opus-4-5`) | Independent model + adapter reduces correlated error on the gate |
| **Auditor** | Seal each Band record into the hash chain; expose verification | — (service/tool) | — | Deterministic proof layer; no LLM needed |

Satisfies the bar comfortably: **6 collaborating chat agents across 4 frameworks and ≥3 model providers**, Band as coordination layer, human-in-the-loop gate, audit trail.

> Minimum-viable fallback if time-boxed: Scanner + Controller + **one** Specialist + Risk = 4 agents, still cross-framework, still the full loop. Add specialists by composition.

## 4. Pillar 1 — Blackboard control loop

A faithful (compact) blackboard architecture. The **case file** is the blackboard; the **Controller** is the control component; specialists are **knowledge sources**.

1. **Open case.** Scanner posts a finding and initializes a structured case object in the room: `{finding_id, class, severity, resource, raw, state: "open", contributions: [], constraints: []}`.
2. **Evaluate & activate.** The Controller reads current case state and activates the knowledge source whose preconditions are met — e.g. an IAM-class finding with no proposal yet → activate IAM Specialist (`@IAM Specialist`). Activation is precondition-driven, not round-robin.
3. **Contribute.** The activated specialist fetches the case (`GET .../context`), then writes a typed contribution back: `{type: diagnosis|proposal|dependency|rollback, payload, confidence, est_blast_radius, reversible: bool}`.
4. **Constrain.** The Risk/Policy agent posts hard constraints as case entries: `{type: constraint, rule, rationale}`. The Controller marks any proposal violating an active constraint `invalid` and re-opens that part of the case.
5. **Converge.** The Controller loops steps 2–4 until: no knowledge source has a pending contribution, **and** all constraints are satisfied, **and** the case contains a complete `{fix, rollback}`. State → `converged`. A hard cap on iterations prevents loops; on cap, escalate to human with the best partial plan.
6. **Gate → act → seal.** Converged plan → human gate (§5) → reversible execution (§5) → audit seal (§6).

Implementation note: all contributions/constraints are small typed JSON objects (Pydantic models) embedded in messages — machine-parseable *and* human-legible in the transcript, which matters for the demo. The Controller maintains a derived `BoardState` view computed from the message history; it is never the sole writer.

## 5. Pillar 2 — Reversible action layer + human gate

- **Action interface.** A converged case yields an `Action`, never raw side-effects: `{description, apply_fn, rollback_fn, target, requires_human: bool, dry_run_result}`. Specialists *propose*; only the **Action Layer** executes.
- **Rollback registry.** Before any `apply`, the corresponding `rollback` is registered and persisted. Examples: open SG ingress → record prior rules; detach IAM policy → record prior attachment; enable bucket block-public-access → record prior ACL. One-click revert from the UI.
- **Human gate.** Consequential actions (`requires_human: true` — anything touching IAM, network exposure, or data access) block on an explicit human approval event before `apply`. The human is the keyholder: the safety story *and* the Track-3 compliance story.
- **Live target.** Primary: **LocalStack** (`boto3` pointed at the LocalStack endpoint) — free, local, deterministic, safe to demo. Secondary/"real": a sandbox AWS account behind a hard allowlist. The Action Layer is identical against both; only endpoint/credentials change.

## 6. Pillar 3 — Provable audit chain

- After each decision-critical Band record, the **Auditor** computes `entry_hash = SHA256(prev_hash + canonical(record))` and appends `{seq, prev_hash, record_ref, entry_hash, ts}` to an append-only store.
- The chain head is exposed for verification; recomputing from genesis must reproduce the head, or the log has been tampered with.
- Covers: case open, every contribution, every constraint, convergence, human approval, action `tool_call`/`tool_result`. Source records pulled via `GET /agent/chats/{id}/context`.
- **Optional stretch:** anchor the head (periodic external timestamp) for stronger tamper-evidence. Flagged, not required.

## 7. End-to-end sequence (the demo spine)

**Official MVP demo = the S3/Data path** (safest reversible LocalStack mutation; build this first):

```
Scanner       → opens cases: C-7 (S3 bucket public), C-19 (SG 0.0.0.0/0:22)
Controller    → C-7 state=open, class=data, no proposal → activate @Data Specialist
Data Spec.    → fetches case; contributes proposal P: disable public access on the bucket
                (BUT first pass omits a restorative rollback / blocks public access too broadly)
Risk/Policy   → posts constraint, verdict=reject, invalidates_proposal=true:
                "no change may ship without a restorative rollback; scope to the offending grant"
Controller    → proposal P invalid → re-open C-7
Data Spec.    → revises: proposal P' = put_public_access_block scoped to the bucket
                + rollback: restore prior ACL/policy (registered)
Risk/Policy   → constraints satisfied → verdict=approve
Controller    → case C-7 has {fix P', rollback}, no pending contributions → CONVERGED
Action Layer  → requires_human:true → BLOCKS
Human         → approves (the key)
Action Layer  → apply against LocalStack; rollback registered; tool_result posted
Auditor       → seals every step; UI shows verifiable chain head
```

Run C-19 (network) in parallel to show multi-finding throughput; C-7 is the on-camera reject-and-revise moment.

**Stretch climax (add only after the MVP path is green):** the IAM/PassRole case is the stronger, more dramatic version of the same loop — swap C-7 for `C-12 (IAM *:*)`: the IAM Specialist proposes a scoped policy, Risk rejects it for granting org-wide `iam:PassRole`, the specialist narrows it, and (optionally) the Network Specialist is activated by a dependency because the role is attached to the C-19 host. Identical mechanics, higher stakes — use it as the headline demo once the safe path is proven end-to-end.

## 8. Tech stack

- **Language/runtime:** Python 3.11+, `uv`.
- **Band SDK:** `band-sdk` with adapters — `[langgraph]`, `[crewai]`, `[pydantic-ai]`, `[anthropic]`. Import is `band` or `thenvoi` depending on version (SDK_NOTES §1).
- **LLM providers:** Featherless (Scanner) · AI/ML API (the three CrewAI Specialists) · Anthropic (Controller + Risk, on different Claude models). See SDK_NOTES §6 for routing.
- **Cloud target:** LocalStack + `boto3` (primary); sandbox AWS (secondary).
- **Audit store:** SQLite (append-only) or JSONL ledger — deterministic, no external dep.
- **Demo UI:** thin Next.js viewer **or** Streamlit showing (a) the case/blackboard assembling, (b) the pending human approval, (c) the live audit chain + a "verify chain" button. Band's own UI can stand in for (a) to save time.
- **Process orchestration:** `docker compose up`, one service per agent.

## 9. Repo structure

```
castellan/
  agents/
    scanner/            # LangGraph + Featherless; cloud-config → cases
    controller/         # Pydantic AI + Anthropic (claude-sonnet); blackboard control loop
    specialists/
      iam/              # CrewAI + AI/ML API
      network/          # CrewAI + AI/ML API
      data/             # CrewAI + AI/ML API
    risk/               # Anthropic adapter + Anthropic (different Claude model); constraint authority
  coordination/         # blackboard: case-file + contribution/constraint models, BoardState, convergence
  actions/              # Action interface, executor, rollback registry
  audit/                # hash-chain sealing + verification
  connection/           # OPTIONAL custom helpers ONLY (e.g. room setup, env validation).
                        #   NEVER name a local package `band` — it shadows the installed SDK
                        #   module `band` and breaks `from band import Agent`.
                        #   `load_agent_config` comes from the SDK (`band.config`) — do NOT
                        #   reimplement it. For M0 this folder may not be needed at all.
  cloud/                # LocalStack/boto3 adapters + seeded misconfigurations
  ui/                   # demo viewer (blackboard + approval + audit chain)
  docs/                 # CASTELLAN_*.md
  docker-compose.yml
  .env.example
  agent_config.example.yaml
```

## 10. Configuration

- Each agent is registered in the Band dashboard as an **External Agent**; registration yields a per-agent **UUID + API key** (key shows once — store immediately).
- `agent_config.yaml` holds `{agent_id, api_key}` per agent. `.env` holds LLM provider keys. **Both gitignored.**
- Provider keys: `FEATHERLESS_API_KEY`, `AIML_API_KEY`, `ANTHROPIC_API_KEY` (names per each provider's SDK).

## 11. Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| Blackboard convergence reads as undramatic on video | UI animates each contribution + constraint as it lands; narrate the Risk-constraint-forces-revision beat as the climax |
| Live action feels staged | Use a real (reversible) LocalStack mutation; show state before/after via `boto3` describe calls |
| Convergence loop never terminates | Hard iteration cap; on cap, escalate to human with best partial plan |
| Too many agents to stabilize in time | Ship the 4-agent MVP first (Scanner, Controller, one Specialist, Risk), add specialists once green |
| Secret leakage | `.env` + `agent_config.yaml` gitignored; `.example` files only in repo |
| Demo depends on flaky live cloud | LocalStack is local + deterministic; no network dependency at demo time |

## 12. Left to AGENTS.md / BUILD_PLAN.md

- Per-agent system prompts, exact tool signatures, contribution/constraint schemas (→ `AGENTS.md`).
- Milestone sequencing, integration checkpoints, video script (→ `BUILD_PLAN.md`).
