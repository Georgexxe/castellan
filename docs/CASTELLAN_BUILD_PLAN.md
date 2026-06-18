# Castellan — Build Plan

> Companion to `CASTELLAN_ARCHITECTURE.md` and `CASTELLAN_AGENTS.md`. Ordered milestones with explicit "done when" checks, cut lines if you fall behind, the demo video script, and the submission checklist.

---

## Build deviations (decisions made during implementation — authoritative)

- **M1 Scanner delivery is deterministic, not LLM-driven.** Detection AND finding delivery run
  in code: `cloud/scan.py` builds the findings + formats the messages (`json.dumps`), and
  `scripts/scan_and_post.py` posts them to the Band room via the REST client
  (`AsyncRestClient.agent_api_messages.create_agent_chat_message`), AS the Scanner, outside the
  LLM/LangGraph loop. Reason: the LLM relay path failed on Featherless connection drops
  (`RemoteProtocolError` → `APIConnectionError`) and could silently alter values (e.g. `"*"`→`""`).
  Mentions resolve via the room participants endpoint (participant id, matched by handle).
- **Featherless moves off the Scanner → a NEW, NON-BLOCKING M6 agent.** Because the Scanner is
  now deterministic, Featherless is no longer in the M1 critical path. To keep the Featherless
  partner prize, add a Featherless-powered **"Evidence Analyst / Remediation Explainer"**: it
  reads the deterministic Finding JSON and posts human-readable risk context into Band. It is
  advisory only — it must NOT gate or block the remediation loop.
- **Do NOT put Featherless in the Risk/Policy agent.** Risk is the safety gate and must stay on
  a stable provider (Anthropic). The Featherless role is the Evidence Analyst, nothing else.
- ⚠️ **Prize claim gate:** the Featherless Evidence Analyst must actually be **built and demoed**
  before we claim the Featherless prize in the submission. Do not list Featherless as used until
  that agent is real and shown in the demo.

---

## Pre-flight (do before any code)

1. **Claim credits / accounts** (slowest path — do first): Band + Pro (`BANDHACK26`), AI/ML API (`lablab.ai/redeem-coupon/ai-ml-api-coupon-band-hackathon`), Featherless (`BOA26`), Anthropic API key (`console.anthropic.com`).
2. **Register agents in Band** (manual; can't be automated). For the MVP, register these four as **External Agent**, copying each **UUID + API key** (key shows once):
   - `Scanner`, `Controller`, `Data Specialist`, `Risk Policy`
   - Later: `IAM Specialist`, `Network Specialist`.
3. **Local tooling:** Python 3.11+, `uv`, Docker + Compose, git + a public GitHub repo.
4. **Secrets:** create `.env` (provider keys) and `agent_config.yaml` (per-agent Band UUID+key) and **gitignore both before the first commit.**

---

## Milestones

### M0 — Prove the Band pipe *(do not skip; everything depends on it)*
- Scaffold the repo per `CASTELLAN_ARCHITECTURE.md` §9.
- Get **one** trivial agent (`Scanner`) connecting to Band and replying in a chat room when @mentioned.
- **Done when:** you @mention the agent in a Band room and it responds. Network/auth path proven.

### M1 — Scanner → structured findings on the board
- Implement `cloud_describe` against **LocalStack**; seed misconfigurations (public S3 bucket, over-permissive IAM role, SG open `0.0.0.0/0:22`).
- Scanner emits `Finding` JSON per issue, addressed to `@Controller`.
- **Done when:** running a scan posts well-formed `Finding` JSON for each seeded issue.

### M2 — Controller + one Specialist (the core loop)
- Implement the Controller's `BoardState` derivation and deterministic activation rules.
- Implement the **Data Specialist** (simplest reversible fix: public-access-block).
- **Done when:** Scanner posts the S3 finding → Controller activates Data Specialist → Specialist posts a `proposal` with `fix`+`rollback`.

### M3 — Risk constraints + the revision loop *(the differentiator)*
- Implement **Risk Policy** (Anthropic adapter) with the hard rules.
- Wire the Controller's invalidate→re-activate path and the 4-round cap.
- **Done when:** the **S3/Data** case runs the full loop — Data Specialist's first proposal is rejected by Risk (missing restorative rollback, or blocks public access too broadly), the specialist revises to a scoped fix with a proper rollback, and Risk approves. **This is the official on-camera moment — make it repeatable.** (The IAM/PassRole version is the M6 stretch climax, not the MVP demo.)

### M4 — Action Layer + human gate + live mutation
- Implement `register_action` / `apply_action` / `rollback_action` against LocalStack.
- Implement the human gate (UI button → `/approve/{action_id}` releasing the block).
- **Done when:** on approval, the fix actually changes LocalStack state (verify via `cloud_describe` before/after), and rollback restores it.

### M5 — Provable audit chain
- Implement `audit_seal` / `audit_verify` over the decision-critical records.
- **Done when:** the chain verifies from genesis to head, and tampering with any record makes `audit_verify` fail.

### M6 — Add remaining specialists (by composition)
- Register + implement `IAM Specialist` and `Network Specialist` (same contract as Data).
- **Done when:** all three classes route correctly and converge.

### M7 — Demo UI
- Thin viewer (Streamlit fastest, Next.js nicer): (a) the case/blackboard assembling, (b) the pending approval button, (c) the live audit chain + "verify" button.
- **Done when:** a non-technical viewer can watch a finding go from open → converged → approved → executed, and click "verify chain."

### M8 — Submission package
- Public GitHub repo (README with architecture + run steps), hosted demo URL, video, slides, cover image, tags.

---

## Cut lines (if you fall behind, drop in this order)

1. **Drop M6** — ship with the single Data Specialist. The full loop with one specialist still satisfies the bar.
2. **Simplify M7** — record the demo against Band's own room UI + a minimal audit-chain print, skip the custom UI.
3. **Trim M5** — keep the hash chain but drop external anchoring (it was already a stretch).
4. **Never cut M3 or M4.** The Risk-revision loop and the real reversible action are the entire reason Castellan beats the field. If anything survives, it's these.

---

## Demo video script (~90 seconds)

> The video is graded (Presentation) and is where good builds lose points. Show, don't narrate the architecture.

- **0:00–0:12 — The problem.** "Cloud scanners find thousands of misconfigurations and fix none of them. Auto-remediation tools exist but nobody turns them on, because they're not reversible and not gated. Castellan fixes that." Show the seeded findings appearing.
- **0:12–0:30 — The room assembles.** Scanner posts findings → Controller pulls in the right specialist. Caption the frameworks/models live (Scanner=Featherless, Specialists=AI/ML API, Controller & Risk=Claude) — this is your cross-provider evidence.
- **0:30–0:55 — The climax (M3).** The Data Specialist proposes a fix → **Risk rejects it** with a clear rule (no restorative rollback / over-broad public-access change) → the specialist **revises** to a scoped fix with a proper rollback → Risk approves. Let this beat breathe; it's the proof of real agent-to-agent coordination. *(If the M6 IAM/PassRole climax is built, use that instead — same beat, higher stakes: "grants org-wide PassRole.")*
- **0:55–1:15 — Consequential action (M4).** The human approval button → the fix **executes against the live target** → show LocalStack state before/after.
- **1:15–1:30 — Proof + pitch.** Click "verify chain" → tamper-evident audit intact. Close on the one-liner: "Remediate critical cloud risk in minutes, reversibly, with an audit trail your auditor accepts."

---

## Submission checklist (lablab)

- [ ] Public **GitHub repo** (no secrets committed; README with setup + architecture)
- [ ] **Demo URL** (hosted, or a clearly-runnable `docker compose up`)
- [ ] **Video** (~90s, the script above)
- [ ] **Slide deck** (problem, architecture, the three pillars, business case, prize-tech used)
- [ ] **Cover image**
- [ ] **Tags:** Band, AI/ML API, Featherless, Anthropic Claude, LangGraph, CrewAI, Pydantic AI, LocalStack
- [ ] Long + short description (lift from `CASTELLAN_PRODUCT_BRIEF.md`)
- [ ] Explicitly call out **AI/ML API** and **Featherless** usage in the writeup (required for partner prizes)

---

## What makes or breaks this

The judges reward Band being the *real* coordination layer, a visible human-in-the-loop gate, and originality. Castellan's edge is concentrated in **M3 + M4**: agents coordinating through Band to converge on a fix, a real veto-and-revise, and an actual reversible action a human authorized. Protect those two milestones above all else.
