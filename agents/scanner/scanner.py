"""
Castellan — Scanner agent: posts structured Findings to the Controller.

Detection, Finding formatting, and Band delivery are all deterministic Python (cloud/scan.py +
the cloud_scan_and_emit_findings tool); the Featherless LLM only triggers that one tool on an
`@Scanner scan now` mention — it authors no JSON and calls no band_send_message.

Findings are posted to the Controller's FULL namespaced Band handle (e.g. @g18797056/controller);
a bare @Controller does not resolve on a programmatic send.

THE BAND TRAP: plain LLM output is NOT delivered into the room — an agent only puts text in the
room via band_send_message with at least one @mention.

Run from the repo root (load_agent_config reads ./agent_config.yaml from the CWD):
  cd castellan && uv run python agents/scanner/scanner.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Put the repo root on sys.path so `cloud` / `coordination` import when run as a script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

from band import Agent
from band.adapters import LangGraphAdapter
from band.config import load_agent_config

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from cloud.tools import SCANNER_TOOLS
from cloud.scan import DEFAULT_CONTROLLER_HANDLE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("castellan.scanner")

# Featherless provider. Model id overridable via env FEATHERLESS_MODEL, read inside main()
# AFTER load_dotenv() — reading it at import time would run before .env loads and miss the value.
FEATHERLESS_BASE_URL = "https://api.featherless.ai/v1"
DEFAULT_FEATHERLESS_MODEL = "Qwen/Qwen2.5-7B-Instruct"  # open, ungated

# Controller's Band handle is single-sourced in cloud.scan (DEFAULT_CONTROLLER_HANDLE),
# since cloud.scan.scan_finding_messages() embeds it in the formatted messages. Band
# NAMESPACES handles as "<user>/<agent>"; a bare "@Controller" does not resolve on a
# programmatic send. Override via env CONTROLLER_HANDLE.

# System prompt: a pure trigger. Detection, formatting, and delivery are all done in code by the
# cloud_scan_and_emit_findings tool; the LLM only triggers it once and never writes JSON or calls
# band_send_message. {controller} is filled in at runtime (main()).
SCANNER_PROMPT_TEMPLATE = """\
You are the Scanner in a cloud-security remediation system. Detection AND delivery are done for
you by a single tool. You never write JSON, and you never send messages yourself.

When @mentioned or asked to scan, do EXACTLY this:
1. Call the `cloud_scan_and_emit_findings` tool ONCE. It scans the cloud target and posts each
   finding directly to the Controller ({controller}) in this room, on its own.
2. That is all. Do not call any other tool. Do not call band_send_message. Do not write, paste,
   or "fix" any JSON. Do not send a summary, status, acknowledgement, or "scan complete"
   message — the findings have already been delivered by the tool.

The only tool you may call is `cloud_scan_and_emit_findings`.
"""


async def main() -> None:
    load_dotenv()  # MUST run before any os.getenv() below so .env values are read.

    # Resolve the model AFTER load_dotenv() so a FEATHERLESS_MODEL set in .env is honored.
    model = os.getenv("FEATHERLESS_MODEL", DEFAULT_FEATHERLESS_MODEL)

    # Full namespaced Controller handle the Scanner addresses findings to (env-overridable).
    controller_handle = os.getenv("CONTROLLER_HANDLE", DEFAULT_CONTROLLER_HANDLE)
    scanner_prompt = SCANNER_PROMPT_TEMPLATE.format(controller=controller_handle)

    # Credentials: Band agent (UUID + key) from agent_config.yaml; Featherless key from .env.
    agent_id, api_key = load_agent_config("scanner")

    featherless_key = os.getenv("FEATHERLESS_API_KEY")
    if not featherless_key:
        raise SystemExit(
            "FEATHERLESS_API_KEY is not set. Add it to castellan/.env "
            "(copy from .env.example)."
        )

    adapter = LangGraphAdapter(
        llm=ChatOpenAI(
            model=model,
            base_url=FEATHERLESS_BASE_URL,
            api_key=featherless_key,
        ),
        checkpointer=InMemorySaver(),
        custom_section=scanner_prompt,
        additional_tools=SCANNER_TOOLS,  # = [cloud_scan_finding_messages] (deterministic, Python-formatted)
        enable_execution_reporting=True,  # surface tool calls in the room
    )

    # ws_url/rest_url default to app.band.ai inside Agent.create; only override when the
    # env vars are set, so the standard hosted Band works out of the box.
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
        "Scanner connecting to Band (model=%s, controller=%s, ws=%s, rest=%s) — @mention it to scan.",
        model,
        controller_handle,
        conn.get("ws_url", "default app.band.ai"),
        conn.get("rest_url", "default app.band.ai"),
    )
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
