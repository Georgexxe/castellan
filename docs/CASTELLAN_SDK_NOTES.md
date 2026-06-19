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
> - **Featherless returns at M6** as a separate, NON-BLOCKING **Evidence Analyst / Remediation
>   Explainer** (reads the deterministic Finding JSON, posts risk context). It is never the Risk
>   gate — Risk stays Anthropic. See `CASTELLAN_BUILD_PLAN.md` → "Build deviations".

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
