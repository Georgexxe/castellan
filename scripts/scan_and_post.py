"""
scripts/scan_and_post.py — deterministic REST poster (M1).

Scans LocalStack (cloud.scan.scan_findings), formats each finding ENTIRELY IN PYTHON as a
"@controller + fenced-json" message (cloud.scan.scan_finding_messages), and posts each one to
a Band room AS the Scanner via the REST client — completely outside the LLM / LangGraph loop.
No Featherless, no model, no generation step that can drop a connection mid-stream.

Why this exists: the LLM relay path was failing on Featherless connection drops
(RemoteProtocolError -> APIConnectionError). Delivery must be deterministic.

Mention resolution (verified against band.runtime.tools._resolve_mentions): the Band SDK
resolves a mention by looking the handle up in the ROOM's participant list and using that
participant's `id` — i.e. the mention id is the ChatParticipant.id from
list_agent_chat_participants, NOT the agent's own id. This script resolves it the same way.

Connection: AsyncRestClient defaults to the dev thenvoi host, so we explicitly point base_url
at the Scanner's endpoint (BAND_REST_URL, else app.band.ai — same as Agent.create's default).

Usage (no secrets on the command line):
    cd castellan
    uv run python scripts/scan_and_post.py <room_id>

Creds: Scanner api_key from agent_config.yaml (key "scanner"). Controller handle from
CONTROLLER_HANDLE env (else the default in cloud.scan). LocalStack must be up + seeded.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Put the repo root on sys.path so `cloud` / `coordination` import when run as a script.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

from band.config import load_agent_config
from band.client.rest import (
    AsyncRestClient,
    ChatMessageRequest,
    ChatMessageRequestMentionsItem,
    DEFAULT_REQUEST_OPTIONS,
)

from cloud.scan import controller_handle, scan_finding_messages


def _rest_base_url() -> str:
    """Match the endpoint the Scanner agent uses; never fall through to the SDK's dev default."""
    return os.getenv("BAND_REST_URL") or "https://app.band.ai"


async def main() -> None:
    load_dotenv()

    if len(sys.argv) < 2 or not sys.argv[1].strip():
        raise SystemExit("usage: uv run python scripts/scan_and_post.py <room_id>")
    room_id = sys.argv[1].strip()

    # Scanner credentials (post AS the Scanner). agent_id unused here; key authenticates.
    _scanner_id, scanner_key = load_agent_config("scanner")
    handle = controller_handle()
    handle_key = handle.lstrip("@")

    client = AsyncRestClient(api_key=scanner_key, base_url=_rest_base_url())

    # 1) Resolve the controller mention from the ROOM participants (SDK uses participant id).
    parts = await client.agent_api_participants.list_agent_chat_participants(
        chat_id=room_id,
        request_options=DEFAULT_REQUEST_OPTIONS,
    )
    participants = parts.data or []
    print(f"participants in room {room_id}:")
    for p in participants:
        print(
            f"  id={p.id} handle={p.handle!r} name={p.name!r} "
            f"type={getattr(p, 'type', None)} role={getattr(p, 'role', None)}"
        )

    controller = next(
        (p for p in participants if (p.handle or "").lstrip("@") == handle_key), None
    )
    if controller is None:  # fall back to display-name match
        controller = next(
            (p for p in participants if (p.name or "").lower() == "controller"), None
        )
    if controller is None:
        raise SystemExit(
            f"Controller not found in room participants by handle '{handle}' or name "
            "'Controller'. Add the Controller agent to the room first."
        )
    print(f"resolved controller -> id={controller.id} handle={controller.handle!r}")

    mention = ChatMessageRequestMentionsItem(
        id=controller.id, handle=controller.handle or handle
    )

    # 2) Scan + post one message per finding. Content is formatted in Python (json.dumps);
    #    nothing here is model-generated, so "*" and every value are byte-exact.
    messages = scan_finding_messages()
    print(f"posting {len(messages)} finding message(s) to {handle} as Scanner...")
    for i, content in enumerate(messages, 1):
        resp = await client.agent_api_messages.create_agent_chat_message(
            chat_id=room_id,
            message=ChatMessageRequest(content=content, mentions=[mention]),
            request_options=DEFAULT_REQUEST_OPTIONS,
        )
        msg_id = getattr(resp, "id", None) or getattr(getattr(resp, "data", None), "id", None)
        print(f"  posted {i}/{len(messages)} (message id={msg_id})")

    print(f"DONE: posted {len(messages)} findings to {handle} in room {room_id}")


if __name__ == "__main__":
    asyncio.run(main())
