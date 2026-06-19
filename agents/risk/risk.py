"""
Castellan — Risk/Policy agent: the independent policy gate.

Runs on LangGraph + ChatAnthropic, model claude-opus-4-8 (env RISK_MODEL) — deliberately DISTINCT
from the Controller's claude-sonnet-4-6, for genuine independence on the gate. (See
docs/CASTELLAN_SDK_NOTES.md for why LangGraph rather than the band AnthropicAdapter.)

When @mentioned with a proposal, it evaluates the proposal against policy and posts a Constraint
(approve/reject + the violated rule) to @Controller. The LLM makes the judgment; Python validates +
posts it, and a deterministic fail-closed floor (connection/risk_tool.py +
coordination/contributions.py) can downgrade an over-broad approve.

Run from the repo root:  cd castellan && uv run python agents/risk/risk.py
Requires ANTHROPIC_API_KEY in .env and a `risk_policy:` block in agent_config.yaml.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

from band import Agent
from band.adapters import LangGraphAdapter
from band.config import load_agent_config

from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver

from connection.risk_tool import RISK_TOOLS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("castellan.risk")

# A DIFFERENT Claude model than the Controller (claude-sonnet-4-6). Env-overridable; read after
# load_dotenv(). ⚠️ Confirm this id is enabled on the Anthropic key (retired ids fail at call time).
DEFAULT_RISK_MODEL = "claude-opus-4-8"

RISK_PROMPT = """\
You are the Risk & Policy authority — the independent gate of a blackboard remediation system.

When @mentioned with a proposed remediation, evaluate it and record your verdict by calling the
`risk_emit_constraint` tool exactly once (verdict "approve" or "reject", plus the rule and a short
rationale). Do not post messages yourself; the tool delivers the Constraint to the Controller.

JUDGE THE PROPOSED FIX AND ITS ROLLBACK — NOT THE DIAGNOSIS. The diagnosis describes the problem
being remediated and will often mention dangerous things (e.g. "Action '*' on Resource '*'");
that is the problem, not the proposal. Base your verdict ONLY on what the `fix` actually does and
whether a restorative `rollback` is present. A fix that REMOVES an over-broad grant is good even
if the diagnosis describes that grant.

Reject (and say which rule) if the FIX: grants org-wide privilege (e.g. iam:PassRole on '*', or
Action '*' on Resource '*'); widens network exposure; weakens or removes encryption; touches
production data without explicit scoping; or lacks a restorative rollback. Approve only when the
fix is scoped, reversible, and policy-compliant. Be conservative — forcing a revision is better
than approving an over-broad change. (A deterministic safety floor may also downgrade an approve;
that is expected.)

FOR IAM PROPOSALS specifically: approve only if the fix demonstrably REMOVES or OVERWRITES the
offending grant — i.e. it deletes or replaces the *named inline policy* that carries the wildcard
(e.g. put_role_policy on that same policy name with a scoped document, or delete_role_policy on it).
Adding a NEW scoped policy ALONGSIDE an existing over-broad one does NOT remove the grant: IAM
inline policies are a union, so the wildcard policy still applies and effective access is unchanged.
If the fix only adds a scoped policy without removing/replacing the offending one, reject and ask
for a fix that removes or overwrites the wildcard policy.
"""


async def main() -> None:
    load_dotenv()  # MUST precede os.getenv below

    model = os.getenv("RISK_MODEL", DEFAULT_RISK_MODEL)

    agent_id, api_key = load_agent_config("risk_policy")

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Add it to castellan/.env (Risk runs on Anthropic via "
            "LangGraph). See .env.example."
        )

    adapter = LangGraphAdapter(
        llm=ChatAnthropic(model=model, api_key=anthropic_key),
        checkpointer=InMemorySaver(),
        custom_section=RISK_PROMPT,
        additional_tools=RISK_TOOLS,  # = [risk_emit_constraint] (deterministic Constraint delivery)
        enable_execution_reporting=True,
    )

    conn = {}
    if os.getenv("BAND_WS_URL"):
        conn["ws_url"] = os.getenv("BAND_WS_URL")
    if os.getenv("BAND_REST_URL"):
        conn["rest_url"] = os.getenv("BAND_REST_URL")

    agent = Agent.create(adapter=adapter, agent_id=agent_id, api_key=api_key, **conn)

    log.info(
        "Risk/Policy connecting to Band (model=%s, ws=%s, rest=%s) — activated by @mention.",
        model,
        conn.get("ws_url", "default app.band.ai"),
        conn.get("rest_url", "default app.band.ai"),
    )
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
