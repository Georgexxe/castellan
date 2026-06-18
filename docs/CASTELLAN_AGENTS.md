# Castellan — Agent Specifications

> Companion to `CASTELLAN_ARCHITECTURE.md`. This is the implementation contract: data models, per-agent system prompts, tool signatures, and convergence logic. Build from this directly.
>
> ⚠️ **Read `CASTELLAN_SDK_NOTES.md` first.** It is the authoritative, verified Band SDK reference and **supersedes any SDK detail in this file** (imports, env vars, tool names, adapter arguments, provider routing).
>
> **Stack (corrected & verified): 3 model providers across 4 frameworks.**
> - Scanner → LangGraph + **Featherless**
> - Controller → Pydantic AI + **Anthropic model** (an Anthropic model, *not* AI/ML API, to dodge a documented Pydantic-AI + OpenAI multi-turn-tool bug — SDK_NOTES §8)
> - Specialists (IAM/Network/Data) → CrewAI + **AI/ML API**
> - Risk → Anthropic adapter + **Anthropic model** (a *different* Claude model than the Controller)
>
> **Platform tool prefix:** tools are `band_…` **or** `thenvoi_…` depending on the installed SDK version (Band is mid-rebrand). Wherever this file writes `thenvoi_send_message`, read it as `<prefix>_send_message`; verify the prefix at install (SDK_NOTES §1, §3).

---

## 0. Conventions

- **Agent names are @mention identities.** The names below (`Scanner`, `Controller`, `IAM Specialist`, etc.) must **exactly** match the agent names you register in the Band dashboard, because routing is by @mention.
- **All coordination payloads are JSON in a fenced ```json block** inside a Band text message. Agents parse by reading the latest relevant JSON in the case, never by regex over prose.
- **Agents read the board via context.** Before contributing, an activated agent calls `GET /agent/chats/{id}/context` (exposed by the SDK) to load the full case — every prior contribution and constraint.
- **Specialists propose; they never execute.** Only the Action Layer touches the live cloud, and only after the human gate.

---

## 1. Shared data models (Pydantic)

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional
from enum import Enum

class FindingClass(str, Enum):
    IAM = "iam"
    NETWORK = "network"
    DATA = "data"

class Severity(str, Enum):
    LOW = "low"; MED = "med"; HIGH = "high"; CRITICAL = "critical"

class Finding(BaseModel):
    finding_id: str
    cls: FindingClass
    severity: Severity
    resource: str                 # e.g. "arn:aws:s3:::acme-public"
    description: str
    raw_evidence: dict

class ActionSpec(BaseModel):
    action: str                   # e.g. "put_public_access_block"
    target: str                   # resource id/arn
    params: dict                  # boto3 kwargs

class Contribution(BaseModel):
    type: Literal["diagnosis", "proposal", "dependency"]
    finding_id: str
    author: str                   # agent name
    diagnosis: Optional[str] = None
    fix: Optional[ActionSpec] = None
    rollback: Optional[ActionSpec] = None
    est_blast_radius: Optional[Literal["low", "med", "high"]] = None
    reversible: Optional[bool] = None
    confidence: Optional[float] = None     # 0..1
    note: Optional[str] = None             # for dependency entries

class Constraint(BaseModel):
    type: Literal["constraint"] = "constraint"
    finding_id: str
    rule: str                     # human-readable rule
    rationale: str
    verdict: Literal["approve", "reject"]
    invalidates_proposal: bool

class CaseState(str, Enum):
    OPEN = "open"; IN_PROGRESS = "in_progress"
    CONVERGED = "converged"; ESCALATED = "escalated"; DONE = "done"

class BoardState(BaseModel):
    """Derived by the Controller from the room's message history. Not the sole writer."""
    finding: Finding
    state: CaseState = CaseState.OPEN
    contributions: list[Contribution] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    rounds: int = 0
    active_proposal: Optional[Contribution] = None

class AuditEntry(BaseModel):
    seq: int
    prev_hash: str
    record_ref: str               # Band message/event id
    entry_hash: str
    ts: str
```

---

## 2. Per-agent specifications

### 2.1 Scanner (Intake)
- **Framework / provider:** LangGraph · **Featherless** (open-source model)
- **Activated by:** a human/seed posting raw cloud config, or a `scan` trigger.
- **Produces:** one `Finding` JSON per misconfiguration, each in a message addressed to `@Controller`.
- **Custom tools:** `cloud_describe`.
- **System prompt:**
> You are the Scanner in a cloud security remediation system. You ingest raw cloud configuration and security findings and convert each into a normalized, structured finding. For each distinct misconfiguration, emit one JSON object matching the `Finding` schema: `finding_id`, `cls` (one of iam|network|data), `severity`, `resource`, `description`, `raw_evidence`. Classify precisely — `cls` drives which specialist is activated. Post one message per finding addressed to `@Controller`, with the JSON in a fenced ```json block. You only detect and structure. Never propose or apply fixes.

### 2.2 Controller (blackboard control)
- **Framework / provider:** Pydantic AI · **Anthropic model** (`anthropic:claude-sonnet-4-5-20250929`) — see SDK_NOTES §8 for why not AI/ML API
- **Activated by:** any new finding or contribution in the room.
- **Produces:** activation @mentions, convergence summaries to `@Human`, escalations.
- **Custom tools:** Band platform tools (`thenvoi_send_message`, `thenvoi_lookup_peers`, `thenvoi_add_participant`, `thenvoi_get_participants`); maintains `BoardState` from history.
- **Case keying (deterministic):** the Controller identifies/dedupes cases by **`(cls, resource)`**, NOT by `finding_id`. `finding_id` (`C-1`, `C-2`, …) is assigned in scan-enumeration order by the Scanner and is **display-only / not stable across scans** — never key a case on it. Use the helper `case_key(finding) -> f"{finding.cls}:{finding.resource}"` (e.g. `data:acme-public-data`) when deriving `BoardState` from message history.
- **Activation rules (deterministic, enforce in code around the LLM):**
  - case `cls=iam`, no active proposal → `@IAM Specialist`
  - case `cls=network`, no active proposal → `@Network Specialist`
  - case `cls=data`, no active proposal → `@Data Specialist`
  - new proposal present, not yet evaluated → `@Risk Policy`
  - constraint with `invalidates_proposal=true` → re-activate the owning specialist, passing the constraint
- **Convergence (a case is CONVERGED when ALL):** an `active_proposal` exists with both `fix` and `rollback`; every `Constraint` has `verdict=approve` against the active proposal; no specialist has a pending turn. Then post a CONVERGED summary to `@Human` (fix, blast radius, rollback) and set state.
- **Guardrail:** max **4** rounds per case; on cap → `ESCALATED`, post best partial plan to `@Human`.
- **System prompt:**
> You are the Controller, the control component of a blackboard remediation system. You never diagnose or fix findings yourself. You read each case's current state and decide which single participant to activate next, strictly by the activation rules you are given. Coordinate only through @mentions and the case JSON. After a specialist posts a proposal, activate @Risk Policy. If Risk posts a constraint that invalidates a proposal, re-activate the owning specialist and include the constraint. When a case is converged per the rules, post a clear CONVERGED summary addressed to @Human containing the fix, its estimated blast radius, and the rollback. Enforce the round cap; if exceeded, escalate the best available plan to @Human. Never invent technical remediation content.

### 2.3 IAM Specialist
- **Framework / provider:** CrewAI · **AI/ML API**
- **Activated by:** `@IAM Specialist` from Controller.
- **Produces:** a `Contribution` (`type=proposal`) with `fix` + `rollback`, addressed to `@Controller`.
- **Custom tools:** `cloud_describe`.
- **System prompt:**
> You are the IAM Remediation Specialist. When @mentioned, first load the full case context, then contribute a `Contribution` JSON (type "proposal"): a `diagnosis` of the IAM misconfiguration, a minimal least-privilege `fix` (as an ActionSpec), and an explicit `rollback` ActionSpec that restores the prior state. Set `reversible`, `est_blast_radius`, and `confidence`. You must respect every Constraint already on the case — never propose a change that violates one; if a prior proposal of yours was invalidated, produce a revised proposal that satisfies the stated rule. Prefer narrowly scoped policies over broad ones. Address your message to @Controller. You never apply changes yourself.

### 2.4 Network Specialist
- **Framework / provider:** CrewAI · **AI/ML API**
- **Domain:** security groups, network exposure, public ingress.
- **Typical fix/rollback:** restrict SG ingress from `0.0.0.0/0` to a scoped CIDR → rollback restores prior rules.
- **System prompt:** as IAM Specialist, with: *You are the Network Remediation Specialist. Focus on security groups, ingress/egress rules, and network exposure. Reduce exposure to the minimum required; pair every change with a rollback that restores the prior rule set.*

### 2.5 Data / Encryption Specialist
- **Framework / provider:** CrewAI · **AI/ML API**
- **Domain:** S3 public access, bucket policies, encryption at rest.
- **Typical fix/rollback:** enable public-access-block / enable default encryption → rollback restores prior ACL/config.
- **System prompt:** as IAM Specialist, with: *You are the Data & Encryption Remediation Specialist. Focus on storage exposure and encryption. Pair every change with a rollback that restores the prior bucket/object configuration.*

### 2.6 Risk / Policy
- **Framework / provider:** Anthropic adapter · **distinct model (Claude)**
- **Activated by:** `@Risk Policy` from Controller when a proposal needs evaluation.
- **Produces:** a `Constraint` JSON (`verdict` + `invalidates_proposal`), addressed to `@Controller`.
- **Hard rules (reject if any true):** grants org-wide privilege (e.g. `iam:PassRole` on `*`); widens network exposure; removes/weakens encryption; touches production data without explicit scoping; rollback missing or non-restorative.
- **System prompt:**
> You are the Risk & Policy authority and the independent gate. When @mentioned with a proposed fix, evaluate it for policy compliance and blast radius, and emit a `Constraint` JSON. Reject (verdict "reject", invalidates_proposal true) any change that grants org-wide privileges, widens network exposure, weakens encryption, touches production data without explicit scoping, or lacks a restorative rollback — and state the violated rule plainly so the specialist can revise. Approve (verdict "approve") only when the proposal is scoped, reversible, and policy-compliant. Be conservative: forcing a revision is always preferable to approving an over-broad change. Address @Controller.

### 2.7 Auditor (service, not an LLM agent)
- **Implementation:** deterministic module; optionally a Band participant that posts seal confirmations for demo visibility, but performs **no reasoning**.
- **Seals:** case open, every contribution, every constraint, convergence, human approval, action tool_call/tool_result.
- **Functions:** see §4.

---

## 3. Custom tool signatures

```python
# cloud/ — boto3 against LocalStack (primary) or sandbox AWS
def cloud_describe(resource_type: str, resource_id: str) -> dict: ...

# actions/ — the ONLY module that mutates the live target
def register_action(fix: ActionSpec, rollback: ActionSpec,
                    requires_human: bool, finding_id: str) -> str:  # returns action_id
    """Registers the rollback, runs a dry-run, returns action_id. Does NOT apply."""

def apply_action(action_id: str) -> dict:
    """Applies fix against the live target. MUST be preceded by a human-approval event
       when the registered action has requires_human=True."""

def rollback_action(action_id: str) -> dict: ...

# audit/ — hash chain
def audit_seal(record_ref: str, record: dict) -> AuditEntry: ...
def audit_verify() -> dict:   # {"ok": bool, "head": str, "length": int}
    ...
```

**Human gate mechanism:** the Action Layer blocks on an approval event for `requires_human=True` actions. Two acceptable implementations: (a) the human posts `APPROVE <finding_id>` in the Band room and the Action Layer waits for it; (b) a UI button hits an `/approve/{action_id}` endpoint that releases the block. Use (b) for a clean demo, (a) as fallback.

---

## 4. Minimal-viable build order within agents

If time-boxed, the 4-agent MVP that still shows the full loop: **Scanner + Controller + Data Specialist + Risk Policy**, with a single seeded finding (public S3 bucket). The Data fix (public-access-block) is the simplest reversible LocalStack mutation, which makes it the safest demo spine. Add IAM and Network specialists by composition once green.
