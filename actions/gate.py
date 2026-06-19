r"""
Human gate — READ path (M4): post an approval request to the Band room and await a HUMAN reply.

Deterministic, no LLM. The Action Layer (a plain module, §9) posts via REST and polls room context
for the room owner's decision. This module implements the read path; execution is the executor's
job (wired in M4 step 3). In the step-2 dry-run, execution is STUBBED.

Human detection: a message is from a human if its `sender_type` is NOT an agent type
(AGENT_SENDER_TYPES). We log the observed sender_types so the exact human value is confirmable on
the first live reply rather than hardcoding an unverified string.

Decision match is EXACT (anchored), not a loose substring:
    ^(APPROVE|DENY|ROLLBACK)\s+<proposal_id>\s*$
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from band.client.rest import (
    AsyncRestClient,
    ChatMessageRequest,
    ChatMessageRequestMentionsItem,
    DEFAULT_REQUEST_OPTIONS,
)

log = logging.getLogger("castellan.action.gate")

# Sender/participant types treated as NON-human. Anything else (user/human/owner/…) is a human.
AGENT_SENDER_TYPES = frozenset({"agent"})


def _attr(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _is_human_type(value) -> bool:
    return str(value or "").strip().lower() not in AGENT_SENDER_TYPES


def _is_human_message(msg) -> bool:
    return _is_human_type(_attr(msg, "sender_type"))


def decision_pattern(proposal_id: str) -> re.Pattern:
    """Anchored matcher for `APPROVE|DENY|ROLLBACK <proposal_id>`, tolerating leading @mention(s).

    The human MUST @mention the Action agent for the reply to enter the agent's scoped context
    (`get_agent_chat_context` = the agent's own messages + text messages that @mention it). So the
    verb may be preceded ONLY by @mention tokens — still exact (no other prose), still rejects loose
    substrings like "please APPROVE <id> now".
    """
    return re.compile(rf"^(?:@\S+\s+)*(APPROVE|DENY|ROLLBACK)\s+{re.escape(proposal_id)}\s*$")


def find_human_participant(participants):
    """First participant whose type is not an agent type (the room owner / human approver)."""
    for p in participants or []:
        if _is_human_type(_attr(p, "type")):
            return p
    return None


def find_participant_by_id(participants, agent_id):
    """Find a participant by its id (used to resolve the Action agent's own @handle)."""
    for p in participants or []:
        if _attr(p, "id") == agent_id:
            return p
    return None


async def _messages(client: AsyncRestClient, room_id: str) -> list:
    return list(
        (
            await client.agent_api_context.get_agent_chat_context(
                chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
            )
        ).data
        or []
    )


async def _participants(client: AsyncRestClient, room_id: str) -> list:
    return (
        await client.agent_api_participants.list_agent_chat_participants(
            chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
        )
    ).data or []


async def request_and_await_decision(
    client: AsyncRestClient,
    room_id: str,
    proposal_id: str,
    summary: str,
    *,
    self_agent_id: str | None = None,
    timeout_s: float = 120.0,
    poll_interval_s: float = 3.0,
) -> dict:
    """Post the approval request (mentioning the human), then poll for an exact human decision.

    The human MUST @mention this agent in their reply or it won't enter the agent's scoped context
    (get_agent_chat_context). The request therefore tells them to reply `@<self> APPROVE <id>`, and
    the matcher tolerates that leading mention.

    Returns {"decision": "APPROVE"|"DENY"|"ROLLBACK"|None, "by", "message_id",
             "human_sender_type", "reason"}. decision=None means a graceful timeout (no hang).
    Between-poll replies are caught: we snapshot existing message ids before posting and only
    consider NEW human messages, so a reply landing between two polls is seen on the next poll.
    """
    pattern = decision_pattern(proposal_id)

    # 1) snapshot existing message ids (a reply between polls will be a NEW id)
    before = await _messages(client, room_id)
    seen_ids = {_attr(m, "id") for m in before}
    log.info(
        "gate: room %s — sender_types present: %s",
        room_id,
        sorted({str(_attr(m, "sender_type")) for m in before}),
    )

    # 2) resolve the human to address the request to + this agent's own handle (for the reply mention)
    parts = await _participants(client, room_id)
    log.info("gate: participant types: %s", sorted({str(_attr(p, "type")) for p in parts}))
    human = find_human_participant(parts)
    if human is None:
        return {"decision": None, "reason": "no human participant found in room"}
    h_handle = _attr(human, "handle")
    mention = ChatMessageRequestMentionsItem(id=_attr(human, "id"), handle=h_handle)

    self_part = find_participant_by_id(parts, self_agent_id) if self_agent_id else None
    self_handle = _attr(self_part, "handle") if self_part else None
    if self_handle:
        reply_hint = f"reply `{self_handle} APPROVE {proposal_id}` (or DENY / ROLLBACK)"
    else:
        reply_hint = f"reply `@<mention me> APPROVE {proposal_id}` (or DENY / ROLLBACK)"
        log.warning("gate: could not resolve own handle (self_agent_id=%s); human must @mention me", self_agent_id)

    # 3) post the approval request — instruct the human to @MENTION this agent (required for visibility)
    content = (
        f"{h_handle} {summary}\n"
        f"To decide, {reply_hint}. You MUST @mention me so I receive your reply."
    )
    await client.agent_api_messages.create_agent_chat_message(
        chat_id=room_id,
        message=ChatMessageRequest(content=content, mentions=[mention]),
        request_options=DEFAULT_REQUEST_OPTIONS,
    )
    log.info("gate: posted approval request for proposal %s to %s", proposal_id, h_handle)

    # 4) poll for the earliest exact human decision among NEW messages, until the deadline
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        await asyncio.sleep(poll_interval_s)
        matches = []
        for m in await _messages(client, room_id):
            if _attr(m, "id") in seen_ids or not _is_human_message(m):
                continue
            text = str(_attr(m, "content") or "").strip()
            log.info("gate: saw human message: %r", text)  # surfaces the stored reply format
            hit = pattern.match(text)
            if hit:
                matches.append((str(_attr(m, "inserted_at") or ""), hit.group(1).upper(), m))
        if matches:
            matches.sort(key=lambda c: c[0])  # earliest decision after the request
            _ts, decision, m = matches[0]
            return {
                "decision": decision,
                "by": _attr(m, "sender_name"),
                "message_id": _attr(m, "id"),
                "human_sender_type": _attr(m, "sender_type"),
                "reason": "matched",
            }
    return {"decision": None, "reason": "timeout"}
