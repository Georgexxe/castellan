# Castellan — SDK Integration Notes (VERIFIED)

> **This file is authoritative.** It is verified against Band's live docs (`docs.band.ai`, June 2026) and **supersedes any SDK-level detail** (imports, env vars, tool names, adapter arguments, provider routing) written in `CASTELLAN_ARCHITECTURE.md` or `CASTELLAN_AGENTS.md`. When they conflict, follow this file.
>
> Read this before writing a line of code, and run the §12 checklist first.

---

## 1. CRITICAL — package name vs import name (Band is mid-rebrand)

- **pip package:** `band-sdk` (with extras, e.g. `band-sdk[langgraph]`).
- **import module:** Band's own docs currently show **both** `band` and `thenvoi` across different pages. They are the same SDK mid-rename. **You must check which one the installed version exposes.**

```bash
uv run python -c "import band; print('use: band')" 2>/dev/null \
 || uv run python -c "import thenvoi; print('use: thenvoi')"
```

Whichever imports, use it consistently — the submodules mirror it: `band.adapters` / `band.config`, **or** `thenvoi.adapters` / `thenvoi.config`. Call the resolved name `<pkg>` for the rest of this file.

## 2. Connection env vars (required by `Agent.create`)

`Agent.create(...)` needs **both** a WebSocket URL and a REST URL, read from env. The prefix matches the module from §1:

- if module is `band`  → `BAND_WS_URL`, `BAND_REST_URL`
- if module is `thenvoi` → `THENVOI_WS_URL`, `THENVOI_REST_URL`

Get the actual URL values from the Band dashboard / Setup page. Set **both** the matching prefix pair (set both prefixes' pairs if unsure — harmless).

Per-agent Band credentials live in `agent_config.yaml` (`agent_id`, `api_key`), loaded via `load_agent_config("<name>")`.

## 3. Platform tool names (prefix is version-dependent)

The platform tools are: `send_message`, `send_event`, `add_participant`, `remove_participant`, `get_participants`, `lookup_peers`, `create_chatroom` — each carrying the prefix from §1 (`band_…` or `thenvoi_…`).

**CRITICAL behavior:** an agent must call `<prefix>_send_message` (with at least one @mention) to put anything in the room. **Plain text returned by the LLM is NOT delivered.** Every agent's prompt must make it call the send-message tool to respond.

## 4. Canonical agent bootstrap (all agents share this shape)

```python
import asyncio, logging, os
from dotenv import load_dotenv
from band import Agent                      # or: from thenvoi import Agent
from band.adapters import <SomeAdapter>     # mirror the module name
from band.config import load_agent_config

async def main():
    load_dotenv()
    agent_id, api_key = load_agent_config("<agent_name>")   # key in agent_config.yaml
    adapter = <SomeAdapter>(...)                            # see §5
    agent = Agent.create(
        adapter=adapter,
        agent_id=agent_id,
        api_key=api_key,
        ws_url=os.getenv("BAND_WS_URL"),     # or THENVOI_WS_URL
        rest_url=os.getenv("BAND_REST_URL"), # or THENVOI_REST_URL
    )
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
```

Each agent is its **own process / file / container**. Run with `uv run python <agent>.py`.

## 5. Verified adapter signatures, per Castellan agent

### Scanner — `LangGraphAdapter` + Featherless
> **AS BUILT (M1) — read this before reusing the snippet below.** The Scanner's detection,
> Finding formatting, and Band delivery are all **deterministic Python**, not LLM work:
> - The Scanner's single LangChain tool is **`cloud_scan_and_emit_findings`** (in `cloud/tools.py`),
>   not `cloud_describe_tool`. That tool calls `cloud.scan.scan_findings()` (detection in code),
>   formats each Finding with `json.dumps`, and posts it to the Controller via the REST client
>   (`connection/poster.py` → `AsyncRestClient.agent_api_messages.create_agent_chat_message`),
>   resolving the mention from the room participants endpoint (participant id, matched by handle).
> - **Featherless only TRIGGERS the Scanner now** (the LLM's only job is to call that one tool
>   once on an `@Scanner scan now` mention). It authors no JSON and calls no `band_send_message`.
>   Reason: the LLM relay path dropped Featherless connections mid-stream and could corrupt values.
> - **Featherless returns at M6 (now built)** as a separate, NON-BLOCKING **Evidence Analyst / Remediation
>   Explainer** (reads the deterministic Finding JSON, posts risk context). It is never the Risk
>   gate — Risk stays Anthropic.

```python
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from band.adapters import LangGraphAdapter
from cloud.tools import SCANNER_TOOLS   # = [cloud_scan_and_emit_findings]

adapter = LangGraphAdapter(
    llm=ChatOpenAI(
        model="Qwen/Qwen2.5-7B-Instruct",              # verified Featherless catalog id (env-overridable)
        base_url="https://api.featherless.ai/v1",      # verified base URL
        api_key=os.getenv("FEATHERLESS_API_KEY"),
    ),
    checkpointer=InMemorySaver(),
    additional_tools=SCANNER_TOOLS,                    # deterministic scan+deliver tool (not cloud_describe)
)
```
- LangGraph custom tools = LangChain `@tool`-decorated functions in `additional_tools`.
- A custom tool can read the room id from its injected `RunnableConfig` (`configurable.thread_id`
  == room_id), which is how `cloud_scan_and_emit_findings` posts to the right room.

### Controller — `LangGraphAdapter` + ChatAnthropic (AS BUILT — NOT Pydantic-AI)
> **AS BUILT (M2) — the Controller runs on LangGraph + ChatAnthropic, not Pydantic-AI.**
> - **Why not Pydantic-AI:** `crewai` ⊥ `pydantic-ai` in one environment — Band's own README:
>   *crewai pins `pydantic<2.12`, pydantic-ai-slim ≥1.61 needs `pydantic≥2.12`; install one per
>   environment.* Installing both extras held `pydantic-ai` at 1.60, which then fails importing
>   `UserLocation` from `anthropic 0.109` (renamed `BetaUserLocationParam`). pydantic-ai was the
>   ONLY framework breaking the shared venv, and the Controller's reasoning is deterministic
>   (`coordination/board.py`) — the LLM merely triggers a tool — so it needs no pydantic-ai
>   feature. Dropping it keeps every agent (Controller, Risk=Anthropic adapter, Specialists=CrewAI,
>   Featherless Evidence Analyst) in one coherent venv. Still cross-framework: LangGraph + CrewAI
>   + Anthropic, multiple providers.
> - **Model:** `claude-sonnet-4-6` (ChatAnthropic id — NO `anthropic:` prefix, that's pydantic-ai
>   format). Current June 2026; the retired `claude-3-5-sonnet-*` would fail. Env-overridable via
>   **`CONTROLLER_MODEL`**, read after `load_dotenv()`.
> - **Routing is deterministic.** The only custom tool, `controller_route`
>   (`connection/controller_tool.py`), gets `room_id` from the LangGraph run config
>   (`config.configurable.thread_id` — the M1 pattern; LangGraph custom tools do NOT get the
>   room-bound AgentTools), then posts AS the Controller via the REST client
>   (`agent_api_context.get_agent_chat_context` → parse Scanner findings via `coordination/board.py`
>   → key cases by `(cls,resource)` → dedup via stable `[case_id:<sha256[:8]>]` marker under a
>   per-room `asyncio.Lock` → `create_agent_chat_message` @mentioning the specialist resolved from
>   the participants endpoint). The LLM authors no JSON, mentions, or routing.
> - **§8 bug:** avoided — Anthropic path only (no OpenAI), single-tool trigger.

```python
from band.adapters import LangGraphAdapter
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver
from connection.controller_tool import CONTROLLER_TOOLS   # = [controller_route]

adapter = LangGraphAdapter(
    llm=ChatAnthropic(model="claude-sonnet-4-6", api_key=os.getenv("ANTHROPIC_API_KEY")),  # env CONTROLLER_MODEL
    checkpointer=InMemorySaver(),
    custom_section="<controller trigger-only instructions; see agents/controller/controller.py>",
    additional_tools=CONTROLLER_TOOLS,
    enable_execution_reporting=True,
)
```
- Needs `ANTHROPIC_API_KEY`. (The original Pydantic-AI + `provider:model-name` design is retained
  below as historical context, but is NOT what's built.)

### Specialists (IAM / Network / Data) — `CrewAIAdapter` + AI/ML API
```python
from pydantic import BaseModel, Field
from band.adapters import CrewAIAdapter

class CloudDescribeInput(BaseModel):
    """Describe the current state of a cloud resource."""
    resource_type: str = Field(..., description="e.g. s3_bucket, iam_role, security_group")
    resource_id: str = Field(..., description="resource id or arn")

def cloud_describe(inp: CloudDescribeInput) -> str: ...   # may be sync or async

adapter = CrewAIAdapter(
    model="openai/gpt-4o",                 # routed to AI/ML API — see §6
    role="IAM Remediation Specialist",
    goal="Propose minimal, reversible IAM fixes",
    backstory="<see AGENTS.md §2.3>",
    custom_section="<workflow rules>",
    enable_execution_reporting=True,
    additional_tools=[(CloudDescribeInput, cloud_describe)],   # (PydanticModel, handler) tuples
)
```
- CrewAI custom tools = `(PydanticModel, handler)` tuples; tool **name** comes from the model class name, **description** from its docstring. Handlers may be sync or async.

### Risk / Policy — `LangGraphAdapter` + ChatAnthropic (AS BUILT — NOT the AnthropicAdapter)
> **AS BUILT (M3):** Risk runs on **LangGraph + ChatAnthropic**, model **`claude-opus-4-8`**
> (env `RISK_MODEL`) — a model **distinct** from the Controller's `claude-sonnet-4-6` (the
> substantive correlated-error reduction on the gate).
> - **Why not the band `AnthropicAdapter`:** its custom tools are `(PydanticModel, handler)`
>   tuples whose handler is a **pure function of its input — no room context, cannot post**
>   (verified in `band/adapters/anthropic.py`). Risk must deliver a Constraint deterministically,
>   so we use LangGraph, whose custom tool reads `room_id` from `config.configurable.thread_id`
>   (the M2 pattern) and posts via REST. (This means the gate shares an *adapter* with the
>   Controller but uses a *different model* — the independence that matters.)
> - **Deterministic delivery + fail-closed floor:** the LLM judges and calls `risk_emit_constraint`
>   (`connection/risk_tool.py`) with its verdict; the tool picks the proposal Risk was activated on
>   (`coordination.latest_proposal`), applies a deterministic floor
>   (`coordination.structural_violations`, scanning ONLY the fix + rollback presence — BLOCK if
>   LLM-reject OR floor-fires), builds a Pydantic `Constraint`, and posts it to @Controller with
>   case markers byte-identical to the Controller (`board.case_markers`). The system prompt directs
>   the LLM to judge the **fix/rollback, not the diagnosis**.
> - **§8 bug:** N/A — Anthropic path only.

```python
from band.adapters import LangGraphAdapter
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver
from connection.risk_tool import RISK_TOOLS   # = [risk_emit_constraint]

adapter = LangGraphAdapter(
    llm=ChatAnthropic(model="claude-opus-4-8", api_key=os.getenv("ANTHROPIC_API_KEY")),  # env RISK_MODEL
    checkpointer=InMemorySaver(),
    custom_section="<Risk hard-rules prompt; see agents/risk/risk.py>",
    additional_tools=RISK_TOOLS,
    enable_execution_reporting=True,
)
```
- Needs `ANTHROPIC_API_KEY`. (The original `AnthropicAdapter` + `provider:model` design is kept as
  historical context below, but is NOT what's built — that adapter can't post from a custom tool.)
- **Proposal identification — `proposal_id` deferred (M3 decision).** Proposals are matched to a
  case by the `[case:cls:resource]` marker and picked by the **latest-per-case** rule (sort by
  `ChatMessage.inserted_at`, last wins; `coordination.contributions`). No `proposal_id` is assigned
  — sufficient while at most one live proposal per case is in flight (the reject→revise arc just
  posts a newer proposal that supersedes the old). **Introduce a `proposal_id` only if** multiple
  distinct proposals for the same case must be tracked/deduped concurrently, or revisions must be
  correlated to specific Constraints (revisit at M4+).

## 6. Provider routing (the fiddly part — verify at build)

Three providers, two of them via OpenAI-compatible endpoints:

| Provider | Used by | Endpoint | Key | Notes |
| --- | --- | --- | --- | --- |
| **Featherless** | Scanner (LangGraph/ChatOpenAI) | `https://api.featherless.ai/v1` | `FEATHERLESS_API_KEY` | OpenAI-compatible. **Verify base URL + exact open-source model id.** |
| **AI/ML API** | Specialists (CrewAI/LiteLLM) | `https://api.aimlapi.com/v1` | `AIML_API_KEY` | OpenAI-compatible. CrewAI uses LiteLLM — target a custom base with `model="openai/<model>"` + `OPENAI_API_BASE`/`OPENAI_API_KEY`, **or** a CrewAI `LLM(base_url=..., api_key=...)`. **This is the #1 integration gotcha — verify the exact CrewAI mechanism.** |
| **Anthropic** | Controller (Pydantic AI), Risk (Anthropic adapter) | native | `ANTHROPIC_API_KEY` | No routing needed. |

**Hardening:** because each agent is its own process, prefer passing `base_url`/`api_key` **explicitly in code** (as the Scanner does) over relying on global `OPENAI_*` env vars, to avoid cross-talk if you ever co-locate agents. Where CrewAI forces env-based config, scope those vars to the specialist services only.

## 7. Verified model-string reference (from Band docs)

- Pydantic AI: `anthropic:claude-sonnet-4-5-20250929`, `openai:gpt-4o`, `google:gemini-1.5-pro`
- Anthropic adapter: `claude-sonnet-4-5-20250929`, `claude-opus-4-5-20251215`, `claude-3-5-haiku-20241022`

These are Band's documented examples — **confirm current availability/pricing** on each provider before relying on a specific id.

## 8. Known issue → why the Controller uses an Anthropic model

Band documents a Pydantic AI + **OpenAI** failure on complex multi-turn tool sequences:
`Invalid value for 'content': expected a string, got null.` Documented workarounds: **use Anthropic**, or use the **LangGraph adapter** for complex tool sequences.

The Controller is the most tool-intensive, multi-turn agent, so it's the most exposed. Decision: **Controller = Pydantic AI + `anthropic:claude-...`** (keeps the Pydantic AI framework, dodges the bug). AI/ML API's "meaningful use" for the partner prize is carried by the three CrewAI specialists.

**Fallback if you'd rather keep the Controller's reasoning on AI/ML API:** switch the Controller to the **LangGraph adapter** with `ChatOpenAI(base_url="https://api.aimlapi.com/v1", api_key=AIML_API_KEY)`. That also avoids the bug and keeps AI/ML API — at the cost of one fewer distinct framework.

## 9. Non-agent components (no SDK needed)

The **Action Layer** (`actions/`) and **Auditor** (`audit/`) are plain Python modules, not Band agents. They're invoked by the orchestration backend and the human-gate endpoint. They don't use adapters or platform tools. Keep them framework-free and deterministic.

> **AS BUILT (M6b) — Evidence Analyst (`agents/evidence/`, `connection/evidence_tool.py`,
> `scripts/run_evidence.py`) — Featherless, additive, read-only:**
> - **Purely additive.** When @mentioned about a case it posts a plain-language `[evidence_summary]`
>   (human context before the human approves). It produces NO Contribution, passes NO Risk gate, and
>   touches NO Action/audit code. **Nothing in the proven spine changed** — no edits to
>   scanner/controller/risk/data_specialist/action/`coordination/*`.
> - **Featherless (Qwen-7B) on purpose.** `ChatOpenAI` → Featherless (the proven transport), zero new
>   deps. A weak 7B is fine here because it only summarizes — it has no gate to pass. **ONE Featherless
>   call per case.**
> - **Out of the audit path (three guarantees):** (1) `[evidence_summary]` is not a chained record
>   type → `classify_records` returns None; (2) `sanitize_summary` strips fenced code/JSON/markers so
>   the prose can never be misread as a Finding/Contribution/Constraint; (3) it's not in
>   `audit_verify.py` AGGREGATE_KEYS and is addressed to the human. The `eb4379c9` chain stays
>   byte-identical (head `9f55f86d…2946919`, VALID).
> - **Evidence is live, not transcript-derived.** Uses `cloud.describe.cloud_describe` (read-only),
>   so it needs nothing from Band's scoped context except the case key.
> - **Trigger = @mention, no Controller change.** Driver `scripts/run_evidence.py <room> <cls:resource>`
>   (or a human @mention). Fully-automatic case-open activation would require the Controller to
>   @mention it — deliberately NOT built (manual trigger is cleaner for the demo).
> - **Fail-closed:** describe error / model hiccup → a clean "summary unavailable", never a partial
>   or broken post.
> - **UI:** the dashboard's reserved "Evidence Analyst Summary" card is wired in a later step (a new
>   read-only bridge endpoint for the latest `[evidence_summary]`); now built.

> **AS BUILT (M6) — live Data Specialist (`agents/specialists/data/`, `connection/data_tool.py`,
> `coordination/remediations.py`):**
> - **Transport matrix decided this (empirical, not assumed).** Probes: OpenAI-SDK and
>   `ChatOpenAI(base_url=…)` both reach AI/ML API and **authenticate**, but the account is **out of
>   funds** (HTTP 403 "out of funds") so it cannot complete a call; Featherless and Anthropic return
>   completions. `ChatOpenAI(base_url=…)` honors the custom base_url and does **not** fall back to
>   OpenAI (the CrewAI `LLM(base_url)` bug #5139 does not affect `langchain_openai`). **Chosen: LangGraph
>   + `ChatAnthropic` (claude-sonnet-4-6, env `DATA_MODEL`)** — proven live, **zero new deps**
>   (`langchain_anthropic` already installed). **AI/ML API and CrewAI are DEFERRED** (AI/ML: top up the
>   balance then re-probe a valid model string — transport already proven; `litellm` not installed,
>   never reached). **Honest framing: "Anthropic-backed Data Specialist with deterministic remediation
>   building + validation" — NOT CrewAI, NOT AI/ML API.**
> - **Deterministic-first division.** The LLM only **triggers**: it reads the routed case and calls
>   `data_emit_proposal(diagnosis)` once. **Python does everything security-critical**: reads the case
>   from the `[case:cls:resource]` marker, inspects the LIVE bucket (`cloud.describe.cloud_describe`),
>   **builds** the reversible fix+rollback (`build_data_remediation`), **validates**
>   (`structural_violations`), and **posts** the `type=proposal` Contribution to `@Risk Policy` — byte
>   format identical to `post_contribution.py`, so Risk/M4/M5 see it identically.
> - **Evidence-grounded + fail-closed.** The rollback restores the **observed prior** public-access
>   block. The all-false seed baseline is used **only** when `cloud_describe` explicitly returns
>   `public_access_block is None`; an **error / timeout / malformed / missing-key** read is **NOT** a
>   None case → the tool **refuses to propose** ("no reliable evidence → no proposal"). Never
>   substitutes a baseline on a failed read.
> - **Idempotent.** Before posting, the tool scans the room for an existing `[case][proposal_id]`
>   proposal and returns "already proposed" rather than double-posting.
> - **proposal_id invariant (verification, not execution).** For the seeded `acme-public-data`, the
>   built fix/rollback are byte-identical to `_GOOD_S3`, so the live `proposal_id` **equals** the
>   `good_s3` id. `scripts/run_action.py --latest-approved <cls:resource>` (or `--proposal-id <pid>`)
>   **reads and executes the room's approved Contribution itself** (the verdict gate still requires
>   `approve`); the `== good_s3` equality is printed as a **VERIFICATION** that the live specialist
>   produced the identical safe object — the synthetic fixture is **out of the execution loop**.
> - `data_specialist` is added to `audit_verify.py` `AGGREGATE_KEYS` so the author's own scoped view
>   is unioned into the reconstructed transcript.

> **AS BUILT (M5) — provable audit chain (`coordination/audit.py`, `scripts/audit_verify.py`):**
> - **Rebuilt from the blackboard, no side-channel store.** Band scopes each agent's
>   `get_agent_chat_context` to its own + @mention-ed messages, so the full transcript is
>   reconstructed by **aggregating the scoped views of controller + risk_policy + action** (union by
>   message id, sorted by `(inserted_at, source_message_id)` — tiebreaker mandatory for a stable head).
> - **Hash covers attribution.** `entry_hash = sha256(prev + canonical_json({record_type, case_id,
>   proposal_id, sender(=sender_id), sender_type, inserted_at, source_message_id, payload}))` — reuses
>   the single `canonical_json` (M4). Identity + timestamps are inside the hash, so "who approved /
>   when" can't be forged while the chain still verifies. Seven record types
>   (case_open→contribution→constraint→human_approval→action_applied→human_rollback→action_rolled_back);
>   a valid ordered **prefix** is accepted, a genuine gap or an `action_*` without its authorizing
>   human decision (same proposal_id) RAISES.
> - **`case_open` is REQUIRED — a chain cannot be certified without a detection record.** The model
>   was deliberately NOT relaxed to make it optional: a case with no `case_open` is an incomplete
>   chain, and `classify_records` RAISES `AuditError` for it. `scripts/audit_verify.py` **catches
>   `AuditError` and prints a clean `AUDIT INCOMPLETE — cannot certify chain: …` diagnostic** (exit 2)
>   rather than a traceback — a security tool refuses to certify gracefully. The live `case_open` is
>   produced by running the **actual Scanner (M1)**, which posts the S3 Finding for
>   `data:acme-public-data` (case_id `575e729d`); `classify_records` recognizes a real Scanner Finding
>   message (`@handle` + fenced ```json``` Finding body) as `case_open` and derives the same case_id.
> - **Genuine vs synthetic record provenance:** `case_open` (real Scanner Finding), `constraint`
>   (real Risk verdict), `human_approval`/`human_rollback` (real human Band replies), and
>   `action_applied`/`action_rolled_back` (real LocalStack execution outcomes) are **genuine**. As of
>   **M6 the `contribution` is also genuine** for the data path — authored by the live Data Specialist
>   (`agents/specialists/data/`), not `scripts/post_contribution.py`. **No synthetic record remains in
>   the data lifecycle.** (`post_contribution.py` stays only as a fixture harness / for the
>   not-yet-built IAM & Network paths.) A **manual / human-authored `case_open`** (a human pasting a
>   Finding into the room) is a **recognized valid mode** the classifier would accept — but it is **not
>   built/exercised** here; the certified path uses the real Scanner.
> - **External anchor.** `--anchor` writes the head to `.audit/<room_id>.head` (out-of-band, gitignored)
>   AND posts the in-room `[audit_head]` receipt; **refuses to overwrite an existing anchor unless
>   `--force`** (re-anchoring a tampered room would mint a fresh "valid" head). `--verify` (default) is
>   side-effect-free and compares against the file anchor; `--tamper` mutates a record in memory and
>   shows the head break + first broken entry.
> - **Reversibility is proven from the chain**, not just asserted: the verifier recomputes
>   `restored_matches_original` from chain-resident data (`action_applied.state_before` vs
>   `action_rolled_back.state_after_rollback`).
> - **Durable idempotency** (retires M4's deferred boundary, no DB): before executing, the Action
>   Layer scans room history for `[action_applied]` / `[action_rolled_back]` for the proposal_id and
>   refuses a duplicate (survives restart; keyed on proposal_id so a revised proposal isn't blocked).
> - **Honest tamper-evidence scope:** tamper-evidence is relative to the committed head; the file is
>   the demo anchor; **signing the head with an Action-Layer key is the production hardening path
>   (not built).**

> **AS BUILT (M4) — Action Layer:**
> - **Executor** (`actions/executor.py`): deterministic, **no LLM**. `register_action` / `apply_action`
>   / `rollback_action` (AGENTS §3). Runs only **allowlisted** boto3 actions via the reused
>   `cloud/client.get_client` — each action has its own `build_kwargs` (`target` → Bucket/RoleName/
>   GroupId; IAM/bucket policy docs `json.dumps`'d). The allowlist lookup **gates every `getattr`**
>   (an unknown action is refused before dispatch). Idempotency is `proposal_id`-keyed via in-memory
>   sets (`_APPLIED`/`_ROLLEDBACK`); **durable idempotency is deferred to M5** (audit chain).
> - **Three gates, in order** (`scripts/run_action.py`): (1) **policy/verdict gate** — refuse unless
>   the latest Risk Constraint for the `proposal_id` is `approve`; a `reject` (or no verdict) blocks
>   execution. The Constraint is addressed to `@Controller`, so the Action Layer reads it via the
>   **Controller's context view** (`agent_api_context`), correlating by the `[proposal_id]` marker.
>   (2) **human gate** (`actions/gate.py`) — post an approval request and poll for a human reply.
>   ⚠️ `get_agent_chat_context` returns only the agent's own messages + texts that **@mention it**,
>   so the human MUST `@mention` the Action agent in their reply; the matcher is exact/anchored
>   (`^(?:@\S+\s+)*(APPROVE|DENY|ROLLBACK)\s+<proposal_id>\s*$`) and humans are detected by
>   `sender_type != "agent"`. (3) the executor's own `requires_human` approval record.
> - **Reversibility** is executable and asserted (`run_action.py`): for `good_s3`, before == all-false
>   seed baseline → after-apply == all-true → after-rollback == before (byte-identical), via
>   `cloud_describe` readback against a `SEEDED_BASELINE` constant.

## 10. Secret file templates

`.env` (gitignored):
```
# Band connection — set the pair matching your import module (§1); set both if unsure
BAND_WS_URL=
BAND_REST_URL=
THENVOI_WS_URL=
THENVOI_REST_URL=

# Model providers
FEATHERLESS_API_KEY=
AIML_API_KEY=
ANTHROPIC_API_KEY=

# OpenAI-compatible routing for CrewAI specialists → AI/ML API (verify mechanism, §6)
# Prefer setting these only in the specialist services.
OPENAI_API_KEY=
OPENAI_API_BASE=https://api.aimlapi.com/v1
```

`agent_config.yaml` (gitignored):
```yaml
scanner:
  agent_id: "<uuid>"
  api_key: "<band-agent-key>"
controller:
  agent_id: "<uuid>"
  api_key: "<band-agent-key>"
data_specialist:
  agent_id: "<uuid>"
  api_key: "<band-agent-key>"
risk_policy:
  agent_id: "<uuid>"
  api_key: "<band-agent-key>"
# add later: iam_specialist, network_specialist
```

Commit only `.env.example` and `agent_config.example.yaml` (same keys, empty values).

## 11. Adapter extras to install

```bash
uv add "band-sdk[langgraph]" "band-sdk[crewai]" "band-sdk[pydantic-ai]" "band-sdk[anthropic]"
```
(Plus `python-dotenv`, `pyyaml`, `boto3`, and LocalStack tooling.)

## 12. Verify-at-install checklist (run FIRST, before building logic)

1. `uv add` the four extras (§11); resolve the import name (§1).
2. Confirm the **tool prefix** (`band_` vs `thenvoi_`) by inspecting the installed package's tool definitions (docs mention `runtime/tools.py`).
3. Get `WS_URL` + `REST_URL` from the Band dashboard; put them in `.env` under the right prefix (§2).
4. Register the 4 MVP agents in Band; fill `agent_config.yaml` (§10).
5. **M0 smoke test:** bring up the Scanner only; @mention it in a room; confirm it replies via `<prefix>_send_message`. Do not proceed until this passes.
6. Confirm the **CrewAI → AI/ML API** routing with a one-shot specialist call (§6) before wiring the loop — this is the most likely thing to silently misbehave.
