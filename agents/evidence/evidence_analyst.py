"""
Castellan — Evidence Analyst (M6b: Featherless, the second sponsor basket).

A deliberately LOWER-STAKES, READ-ONLY, ADDITIVE agent. When @mentioned about an opened case, it
reads the resource's live evidence (cloud_describe) and posts a plain-language risk summary — human
context before the human approves. It is on Featherless (Qwen-7B) precisely because it only
summarizes: it produces NO Contribution, passes NO Risk gate, touches NO Action/audit machinery, and
changes NOTHING in the proven Scanner→Controller→Specialist→Risk→action→audit spine. Its
[evidence_summary] message is ignored by the audit chain reconstruction (not a chained record type).

STACK: LangGraph + ChatOpenAI -> Featherless (the proven transport; agents/scanner/scanner.py), zero
new deps. The deterministic work (evidence fetch, the one Featherless summarization call, sanitize,
post) lives in connection/evidence_tool.py; this agent just listens and triggers it.

Run from the repo root:  cd castellan && uv run python agents/evidence/evidence_analyst.py
Requires FEATHERLESS_API_KEY in .env and an `evidence_analyst:` block in agent_config.yaml.
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

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from connection.evidence_tool import (
    DEFAULT_FEATHERLESS_MODEL,
    FEATHERLESS_BASE_URL,
    EVIDENCE_ANALYST_TOOLS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("castellan.evidence")

EVIDENCE_PROMPT = """\
You are the Evidence Analyst — you give a human reviewer plain-language context about a security case.

When you are @mentioned about a case, call the `post_evidence_summary` tool EXACTLY ONCE. Do not
write the summary yourself in chat and do not post messages directly — the tool inspects the live
resource, writes the summary, and delivers it. You produce no fixes and no decisions; you only help a
human understand what was found.
"""


async def main() -> None:
    load_dotenv()  # MUST precede os.getenv below

    model = os.getenv("FEATHERLESS_MODEL", DEFAULT_FEATHERLESS_MODEL)

    agent_id, api_key = load_agent_config("evidence_analyst")

    featherless_key = os.getenv("FEATHERLESS_API_KEY")
    if not featherless_key:
        raise SystemExit(
            "FEATHERLESS_API_KEY is not set. Add it to castellan/.env (the Evidence Analyst runs on "
            "Featherless via ChatOpenAI)."
        )

    adapter = LangGraphAdapter(
        llm=ChatOpenAI(
            model=model,
            base_url=FEATHERLESS_BASE_URL,
            api_key=featherless_key,
        ),
        checkpointer=InMemorySaver(),
        custom_section=EVIDENCE_PROMPT,
        additional_tools=EVIDENCE_ANALYST_TOOLS,  # = [post_evidence_summary] (deterministic delivery)
        enable_execution_reporting=True,
    )

    conn = {}
    if os.getenv("BAND_WS_URL"):
        conn["ws_url"] = os.getenv("BAND_WS_URL")
    if os.getenv("BAND_REST_URL"):
        conn["rest_url"] = os.getenv("BAND_REST_URL")

    agent = Agent.create(adapter=adapter, agent_id=agent_id, api_key=api_key, **conn)

    log.info(
        "Evidence Analyst connecting to Band (model=%s, ws=%s, rest=%s) — @mention it with a case.",
        model,
        conn.get("ws_url", "default app.band.ai"),
        conn.get("rest_url", "default app.band.ai"),
    )
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
