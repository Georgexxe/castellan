"""
Deterministic REST delivery of Scanner findings, shared by:
  - scripts/scan_and_post.py  (standalone CLI)
  - the Scanner agent's cloud_scan_and_emit_findings tool (Band @mention trigger)

Posts AS the Scanner via the Band REST client. Detection + message formatting are done in code
(cloud.scan), so values (e.g. "*") are byte-exact. Mentions resolve via the room participants
endpoint (participant id, matched by handle) — the same resolution the SDK's own send_message performs.
"""

from __future__ import annotations

import os

from band.config import load_agent_config
from band.client.rest import (
    AsyncRestClient,
    ChatMessageRequest,
    ChatMessageRequestMentionsItem,
    DEFAULT_REQUEST_OPTIONS,
)

from cloud.scan import controller_handle, scan_finding_messages


def rest_base_url() -> str:
    """The REST endpoint the Scanner uses; never fall through to AsyncRestClient's dev default."""
    return os.getenv("BAND_REST_URL") or "https://app.band.ai"


async def _resolve_controller(client: AsyncRestClient, room_id: str, handle: str):
    """Return (controller_participant_or_None, all_participants) for the room."""
    handle_key = handle.lstrip("@")
    parts = await client.agent_api_participants.list_agent_chat_participants(
        chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
    )
    participants = parts.data or []
    controller = next(
        (p for p in participants if (p.handle or "").lstrip("@") == handle_key), None
    )
    if controller is None:  # fall back to display-name match
        controller = next(
            (p for p in participants if (p.name or "").lower() == "controller"), None
        )
    return controller, participants


async def post_findings_to_controller(
    room_id: str, *, scanner_key: str | None = None
) -> dict:
    """Scan the cloud target and post one message per finding to the Controller in *room_id*,
    AS the Scanner, via REST. Returns a summary dict. Raises ValueError on bad room/controller.
    """
    if not room_id:
        raise ValueError("room_id is required")
    if scanner_key is None:
        _scanner_id, scanner_key = load_agent_config("scanner")

    handle = controller_handle()
    client = AsyncRestClient(api_key=scanner_key, base_url=rest_base_url())

    controller, participants = await _resolve_controller(client, room_id, handle)
    if controller is None:
        raise ValueError(
            f"Controller not found in room {room_id} by handle '{handle}' or name 'Controller'. "
            "Add the Controller agent to the room first."
        )

    mention = ChatMessageRequestMentionsItem(
        id=controller.id, handle=controller.handle or handle
    )

    messages = scan_finding_messages()
    message_ids: list = []
    for content in messages:
        resp = await client.agent_api_messages.create_agent_chat_message(
            chat_id=room_id,
            message=ChatMessageRequest(content=content, mentions=[mention]),
            request_options=DEFAULT_REQUEST_OPTIONS,
        )
        message_ids.append(
            getattr(resp, "id", None) or getattr(getattr(resp, "data", None), "id", None)
        )

    return {
        "posted": len(messages),
        "controller_id": controller.id,
        "controller_handle": controller.handle or handle,
        "message_ids": message_ids,
        "participants": [
            {"id": p.id, "handle": p.handle, "name": p.name} for p in participants
        ],
    }
