"""
M5 Action Layer ledger — post execution-outcome records to the room, and provide DURABLE
idempotency by scanning room history (no DB; retires M4's in-memory-only boundary).

Outcomes are posted as the action identity and @mention @Controller (so they also enter the
Controller's context for the auditor's aggregation). Each carries `[action_applied]` /
`[action_rolled_back]` + `[case:..][case_id:..][proposal_id:..]` markers + a fenced JSON payload.

`restored_matches_original` is computed from CHAIN-RESIDENT data: the room's `action_applied`
record's `state_before` for the same proposal_id (not an in-memory value), so the auditor can
independently reconstruct it.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from band.client.rest import (
    AsyncRestClient,
    ChatMessageRequest,
    ChatMessageRequestMentionsItem,
    DEFAULT_REQUEST_OPTIONS,
)

from coordination.board import case_markers
from coordination.contributions import proposal_id_from_content

log = logging.getLogger("castellan.action.ledger")

APPLIED_MARKER = "[action_applied]"
ROLLED_BACK_MARKER = "[action_rolled_back]"


def _content(msg) -> str:
    return msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "") or ""


def _attr(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _first_json(content: str) -> dict | None:
    import re

    for m in re.finditer(r"```(?:json)?\s*\n?(.*?)```", content or "", re.DOTALL):
        try:
            data = json.loads(m.group(1).strip())
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


async def _room_messages(client: AsyncRestClient, room_id: str) -> list:
    return list(
        (
            await client.agent_api_context.get_agent_chat_context(
                chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
            )
        ).data
        or []
    )


def _outcome_records(messages, marker: str, proposal_id: str) -> list:
    return [
        m for m in messages
        if marker in _content(m) and proposal_id_from_content(_content(m)) == proposal_id
    ]


async def already_applied_in_room(client: AsyncRestClient, room_id: str, proposal_id: str) -> bool:
    """Durable idempotency: an [action_applied] for this proposal_id already exists in the room."""
    return bool(_outcome_records(await _room_messages(client, room_id), APPLIED_MARKER, proposal_id))


async def already_rolled_back_in_room(client: AsyncRestClient, room_id: str, proposal_id: str) -> bool:
    return bool(_outcome_records(await _room_messages(client, room_id), ROLLED_BACK_MARKER, proposal_id))


async def _applied_state_before(client: AsyncRestClient, room_id: str, proposal_id: str):
    """Chain-resident source for restored_matches_original: the action_applied(state_before)."""
    recs = _outcome_records(await _room_messages(client, room_id), APPLIED_MARKER, proposal_id)
    if not recs:
        return None
    return (_first_json(_content(recs[0])) or {}).get("state_before")


async def _resolve_controller(client: AsyncRestClient, room_id: str):
    parts = (
        await client.agent_api_participants.list_agent_chat_participants(
            chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
        )
    ).data or []
    for p in parts:
        if (_attr(p, "name") or "").strip().lower() == "controller":
            return p
    return None


async def _post(client, room_id, marker, case_key, proposal_id, payload) -> str | None:
    controller = await _resolve_controller(client, room_id)
    if controller is None:
        raise ValueError(f"Controller not in room {room_id}; cannot post {marker}.")
    handle = _attr(controller, "handle")
    cls, _, resource = case_key.partition(":")
    markers = f"{marker} {case_markers(SimpleNamespace(cls=cls, resource=resource))} [proposal_id:{proposal_id}]"
    body = json.dumps(payload, indent=2)
    resp = await client.agent_api_messages.create_agent_chat_message(
        chat_id=room_id,
        message=ChatMessageRequest(
            content=f"{handle} {markers}\n\n```json\n{body}\n```",
            mentions=[ChatMessageRequestMentionsItem(id=_attr(controller, "id"), handle=handle)],
        ),
        request_options=DEFAULT_REQUEST_OPTIONS,
    )
    return getattr(resp, "id", None) or getattr(getattr(resp, "data", None), "id", None)


async def post_action_applied(
    client, room_id, case_key, proposal_id, action_id, tool_call, tool_result, state_before, state_after
) -> str | None:
    payload = {
        "action_id": action_id, "tool_call": tool_call, "tool_result": tool_result,
        "state_before": state_before, "state_after": state_after,
    }
    log.info("ledger: posting action_applied for %s", proposal_id)
    return await _post(client, room_id, APPLIED_MARKER, case_key, proposal_id, payload)


async def post_action_rolled_back(
    client, room_id, case_key, proposal_id, action_id, tool_call, tool_result,
    state_before_rollback, state_after_rollback,
) -> bool:
    # restored_matches_original from CHAIN-RESIDENT data (the room's action_applied.state_before).
    original = await _applied_state_before(client, room_id, proposal_id)
    restored = original is not None and state_after_rollback == original
    payload = {
        "action_id": action_id, "tool_call": tool_call, "tool_result": tool_result,
        "state_before_rollback": state_before_rollback, "state_after_rollback": state_after_rollback,
        "restored_matches_original": restored,
    }
    log.info("ledger: posting action_rolled_back for %s (restored_matches_original=%s)", proposal_id, restored)
    await _post(client, room_id, ROLLED_BACK_MARKER, case_key, proposal_id, payload)
    return restored
