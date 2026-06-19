"""
Castellan — Data Specialist agent: proposes reversible S3 remediations.

Runs on LangGraph + ChatAnthropic, model claude-sonnet-4-6 (env DATA_MODEL).

Deterministic-first: the LLM only triggers — it reads the routed case and calls `data_emit_proposal`
once with a short diagnosis. Python (connection/data_tool.py + coordination/remediations.py) inspects
the live bucket, builds + validates the reversible fix/rollback, fails closed on unreliable evidence,
and posts the proposal to the Risk gate.

Run from the repo root:  cd castellan && uv run python agents/specialists/data/data_specialist.py
Requires ANTHROPIC_API_KEY in .env and a `data_specialist:` block in agent_config.yaml.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Put the repo root on sys.path so `cloud` / `coordination` / `connection` import when run as a script.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

from band import Agent
from band.adapters import LangGraphAdapter
from band.config import load_agent_config

from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver

from connection.data_tool import DATA_SPECIALIST_TOOLS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("castellan.data")

# Env-overridable; read after load_dotenv(). ⚠️ Confirm the id is enabled on the Anthropic key.
DEFAULT_DATA_MODEL = "claude-sonnet-4-6"

DATA_SPECIALIST_PROMPT = """\
You are the Data Specialist in a cloud-security remediation system — the owner of data-class
(S3 storage) findings on a shared blackboard.

When @mentioned with a data misconfiguration case, record your proposal by calling the
`data_emit_proposal` tool EXACTLY ONCE, passing a short `diagnosis` (one or two sentences naming the
exposure, e.g. a public bucket). Do NOT post messages yourself, and do NOT specify the fix actions
or parameters: the tool inspects the LIVE bucket and builds the concrete, reversible fix + rollback
deterministically, then delivers the proposal to the Risk gate. Your job is to recognize the case
and trigger the tool — the deterministic layer handles correctness, reversibility, and delivery.
"""


async def main() -> None:
    load_dotenv()  # MUST precede os.getenv below

    model = os.getenv("DATA_MODEL", DEFAULT_DATA_MODEL)

    agent_id, api_key = load_agent_config("data_specialist")

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Add it to castellan/.env (the Data Specialist runs on "
            "Anthropic via LangGraph)."
        )

    adapter = LangGraphAdapter(
        llm=ChatAnthropic(model=model, api_key=anthropic_key),
        checkpointer=InMemorySaver(),
        custom_section=DATA_SPECIALIST_PROMPT,
        additional_tools=DATA_SPECIALIST_TOOLS,  # = [data_emit_proposal] (deterministic delivery)
        enable_execution_reporting=True,
    )

    conn = {}
    if os.getenv("BAND_WS_URL"):
        conn["ws_url"] = os.getenv("BAND_WS_URL")
    if os.getenv("BAND_REST_URL"):
        conn["rest_url"] = os.getenv("BAND_REST_URL")

    agent = Agent.create(adapter=adapter, agent_id=agent_id, api_key=api_key, **conn)

    log.info(
        "Data Specialist connecting to Band (model=%s, ws=%s, rest=%s) — activated by @mention.",
        model,
        conn.get("ws_url", "default app.band.ai"),
        conn.get("rest_url", "default app.band.ai"),
    )
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
