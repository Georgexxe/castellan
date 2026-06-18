"""
Castellan — Scanner agent (M1: structured findings on the board).

VERIFIED AT INSTALL (SDK_NOTES §12, band-sdk 1.0.0):
  - import module    : `band`         (NOT `thenvoi` — not importable in this version)
  - platform tools   : `band_*`       (e.g. band_send_message) — zero `thenvoi_*` present
  - connection env   : BAND_WS_URL / BAND_REST_URL (default to app.band.ai if unset)
  - config loader    : band.config.load_agent_config reads ./agent_config.yaml from CWD,
                       so run from the repo root: `cd castellan && uv run python agents/scanner/scanner.py`

M1 SCOPE: detection is DETERMINISTIC and done in code by the `cloud_scan_findings` tool
(cloud/scan.py); the Scanner LLM only relays each returned Finding via band_send_message,
posted to the Controller's full namespaced Band handle (e.g. @g18797056/controller — bare
@Controller does not resolve). It only detects and structures — it never
proposes or applies fixes (that is the specialists / Action Layer, later milestones).
Prereq: LocalStack up + seeded — `docker compose up -d localstack` then
`uv run python -m cloud.seed`.

THE BAND TRAP (SDK_NOTES §3): plain LLM output is NOT delivered into the Band room.
An agent only puts text in the room by calling `band_send_message` with at least one
@mention. The system prompt makes the model post each finding via that tool to @Controller.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Run-from-anywhere: put the repo root (castellan/) on sys.path so `cloud` / `coordination`
# import cleanly even when launched as `python agents/scanner/scanner.py` (which otherwise
# only puts agents/scanner/ on the path).
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

# Featherless provider (SDK_NOTES §5/§6). Model id overridable via env (FEATHERLESS_MODEL)
# so you can swap models without editing code. NOTE: the env read happens inside main(),
# AFTER load_dotenv() — reading it here at module-import time would run before .env is
# loaded and silently ignore the .env value.
FEATHERLESS_BASE_URL = "https://api.featherless.ai/v1"
DEFAULT_FEATHERLESS_MODEL = "Qwen/Qwen2.5-7B-Instruct"  # open, ungated

# Controller's Band handle is single-sourced in cloud.scan (DEFAULT_CONTROLLER_HANDLE),
# since cloud.scan.scan_finding_messages() embeds it in the formatted messages. Band
# NAMESPACES handles as "<user>/<agent>"; a bare "@Controller" does not resolve on a
# programmatic send. Override via env CONTROLLER_HANDLE.

# M1 system prompt: a pure RELAY. Detection is deterministic and done in code by the
# cloud_scan_findings tool; the LLM only forwards each returned Finding via band_send_message.
# {controller} is filled in with the full namespaced handle at runtime (see main()).
SCANNER_PROMPT_TEMPLATE = """\
You are the Scanner in a cloud-security remediation system. Detection AND message formatting
are already done for you by a tool. You NEVER write JSON yourself — you only forward
ready-made message strings into the room.

When @mentioned or asked to scan, do EXACTLY this, in order:
1. Call the `cloud_scan_finding_messages` tool. It returns a list of fully-formatted message
   strings — one per finding — each already containing the controller @mention, a blank line,
   and a fenced ```json block.
2. For EACH string in that list, call `band_send_message` with:
     - content  = that string, copied EXACTLY and VERBATIM (do not edit, reformat, re-indent,
                  summarize, or change a single character — especially do not change "*" to "")
     - mention  = {controller}
   Send one band_send_message per string — do not bundle multiple strings into one message.

HARD RULES:
- Do NOT call `band_send_message` until `cloud_scan_finding_messages` has returned this run.
- Forward the strings exactly as returned: never invent, modify, drop, reorder, or re-author
  any content. You do not write or "fix" JSON — the tool already wrote it.
- Plain text you generate is NOT delivered to the room — only `band_send_message` reaches it.
- Mention the full handle {controller} (exactly this, including the "{controller}" namespace
  prefix) — never a bare "@Controller", never the human who asked.
- Send NO other messages: no "starting", "scanning", "complete", summary, status, or
  acknowledgement text. Your only outgoing messages are the verbatim finding strings.
- If `cloud_scan_finding_messages` returns an empty list, send exactly one band_send_message
  to {controller} stating that no misconfigurations were found.

The only tools you may call are `cloud_scan_finding_messages` (read-only) and `band_send_message`.
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
        enable_execution_reporting=True,  # surfaces tool calls in the room for the demo
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
