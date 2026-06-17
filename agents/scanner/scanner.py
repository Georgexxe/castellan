"""
Castellan — Scanner agent (M0: prove the Band pipe).

VERIFIED AT INSTALL (SDK_NOTES §12, band-sdk 1.0.0):
  - import module    : `band`         (NOT `thenvoi` — not importable in this version)
  - platform tools   : `band_*`       (e.g. band_send_message) — zero `thenvoi_*` present
  - connection env   : BAND_WS_URL / BAND_REST_URL (default to app.band.ai if unset)
  - config loader    : band.config.load_agent_config reads ./agent_config.yaml from CWD,
                       so run from the repo root: `cd castellan && uv run python agents/scanner/scanner.py`

M0 SCOPE: reply-only smoke test. The Scanner connects to Band and, when @mentioned,
replies in the room via the `band_send_message` tool. There is intentionally NO
cloud_describe / LocalStack / Finding JSON here — that is M1.

THE M0 TRAP (SDK_NOTES §3): plain LLM output is NOT delivered into the Band room.
An agent only puts text in the room by calling `band_send_message` with at least one
@mention. The system prompt below makes the model do exactly that, addressing the
user who sent the triggering message.
"""

import asyncio
import logging
import os

from dotenv import load_dotenv

from band import Agent
from band.adapters import LangGraphAdapter
from band.config import load_agent_config

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

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

# M0 system prompt. The single most important line is the send-message instruction.
SCANNER_M0_PROMPT = """\
You are the Scanner agent in the Castellan cloud-security system. This is a
connectivity smoke test.

CRITICAL — how to reply: plain text you generate is NOT delivered to the room.
To say anything, you MUST call the `band_send_message` tool, and the message MUST
contain at least one @mention. Address your reply to the person who just messaged
you (use their @mention, taken from the most recent incoming message). If you truly
cannot determine the sender, fall back to mentioning @Scanner.

When @mentioned, reply with a short confirmation that the Scanner is online and
connected to Band (one or two sentences). Do not do any scanning yet.
"""


async def main() -> None:
    load_dotenv()  # MUST run before any os.getenv() below so .env values are read.

    # Resolve the model AFTER load_dotenv() so a FEATHERLESS_MODEL set in .env is honored.
    model = os.getenv("FEATHERLESS_MODEL", DEFAULT_FEATHERLESS_MODEL)

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
        custom_section=SCANNER_M0_PROMPT,
        enable_execution_reporting=True,  # surfaces the band_send_message tool call in the demo
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
        "Scanner connecting to Band (model=%s, ws=%s, rest=%s) — @mention it in a room to test.",
        model,
        conn.get("ws_url", "default app.band.ai"),
        conn.get("rest_url", "default app.band.ai"),
    )
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
