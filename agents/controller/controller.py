"""
Castellan — Controller agent: blackboard routing.

Runs on LangGraph + ChatAnthropic (model claude-sonnet-4-6); see docs/CASTELLAN_SDK_NOTES.md for
the adapter/provider rationale. The Controller's reasoning is deterministic (coordination.board +
connection/controller_tool.py); the LLM only triggers the routing tool.

It reads the Scanner's findings off the room, opens one case per (cls, resource), and activates the
owning specialist by @mention.

Run from the repo root (load_agent_config reads ./agent_config.yaml from the CWD):
  cd castellan && uv run python agents/controller/controller.py
Requires ANTHROPIC_API_KEY in .env and a `controller:` block in agent_config.yaml.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Put the repo root on sys.path so `connection` / `coordination` import when run as a script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

from band import Agent
from band.adapters import LangGraphAdapter
from band.config import load_agent_config

from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver

from connection.controller_tool import CONTROLLER_TOOLS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("castellan.controller")

# ChatAnthropic model id. Env-overridable; read AFTER load_dotenv() (else .env isn't loaded yet).
DEFAULT_CONTROLLER_MODEL = "claude-sonnet-4-6"

CONTROLLER_PROMPT = """\
You are the Controller, the control component of a blackboard remediation system.

When you are @mentioned (a new finding or activation has appeared), do EXACTLY one thing: call
the `controller_route` tool ONCE. It reads the whole case board for this room, opens one case per
(cls, resource), and activates the right specialist by @mention — all in code.

You never diagnose, fix, classify, route, or post messages yourself. You do not write JSON. After
`controller_route` returns its summary, stop. Do not call any other tool and do not send any
additional message.
"""


async def main() -> None:
    load_dotenv()  # MUST precede os.getenv below

    model = os.getenv("CONTROLLER_MODEL", DEFAULT_CONTROLLER_MODEL)

    agent_id, api_key = load_agent_config("controller")

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Add it to castellan/.env (the Controller runs on "
            "Anthropic via LangGraph). See .env.example."
        )

    adapter = LangGraphAdapter(
        llm=ChatAnthropic(model=model, api_key=anthropic_key),
        checkpointer=InMemorySaver(),
        custom_section=CONTROLLER_PROMPT,
        additional_tools=CONTROLLER_TOOLS,  # = [controller_route] (deterministic routing)
        enable_execution_reporting=True,  # surface the controller_route call in the room
    )

    conn = {}
    if os.getenv("BAND_WS_URL"):
        conn["ws_url"] = os.getenv("BAND_WS_URL")
    if os.getenv("BAND_REST_URL"):
        conn["rest_url"] = os.getenv("BAND_REST_URL")

    agent = Agent.create(
        adapter=adapter,
        agent_id=agent_id,
        api_key=api_key,
        **conn,
    )

    log.info(
        "Controller connecting to Band (model=%s, ws=%s, rest=%s) — activated by @mention.",
        model,
        conn.get("ws_url", "default app.band.ai"),
        conn.get("rest_url", "default app.band.ai"),
    )
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
