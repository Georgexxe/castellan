"""
Controller's deterministic routing tool (M2), registered on the LangGraph adapter.

Decision (docs/CASTELLAN_SDK_NOTES.md): the Controller runs on **LangGraph + ChatAnthropic**,
NOT Pydantic-AI — because crewai ⊥ pydantic-ai in one environment (Band's documented
incompatibility: crewai pins pydantic<2.12, pydantic-ai needs ≥2.12) and pydantic-ai was the
only framework breaking the shared venv. The Controller's reasoning is deterministic
(coordination.board); the LLM only TRIGGERS this tool.

LangGraph custom tools receive the run config (not the room-bound AgentTools), so we read
`room_id` from `config.configurable.thread_id` (the proven M1 pattern) and post via the Band
REST client AS the Controller — mirroring connection/poster.py.

Hardening: per-room asyncio.Lock (concurrent double-route guard), stable [case_id:<hash>] dedup
marker, content-based parsing of the real wire format ("*" preserved), sender logging on empty,
graceful skip for absent specialists.
"""

from __future__ import annotations

import asyncio
import logging

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from band.config import load_agent_config
from band.client.rest import (
    AsyncRestClient,
    ChatMessageRequest,
    ChatMessageRequestMentionsItem,
    DEFAULT_REQUEST_OPTIONS,
)

from connection.poster import rest_base_url
from coordination.board import (
    CLS_TO_SPECIALIST,
    already_routed_ids,
    case_id,
    case_key,
    case_markers,
    parse_findings_from_messages,
    routed_marker,
)
from coordination.models import Finding

log = logging.getLogger("castellan.controller")

# One lock per room so concurrent controller_route runs (3 findings → ~3 @mentions) are serialized.
_ROUTE_LOCKS: dict[str, asyncio.Lock] = {}


def _attr(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _find_specialist(participants, specialist_name: str):
    """Return the participant whose display name matches (case-insensitive), else None."""
    if not specialist_name:
        return None
    want = specialist_name.strip().lower()
    for p in participants or []:
        if (_attr(p, "name") or "").strip().lower() == want:
            return p
    return None


def _activation_message(finding: Finding, handle: str) -> str:
    cls = finding.cls.value if hasattr(finding.cls, "value") else str(finding.cls)
    sev = finding.severity.value if hasattr(finding.severity, "value") else str(finding.severity)
    return (
        f"{handle} New remediation case opened by the Controller.\n"
        f"- case: {case_key(finding)}\n"
        f"- class: {cls}\n"
        f"- severity: {sev}\n"
        f"- resource: {finding.resource}\n"
        f"- finding: {finding.description}\n"
        f"Load the case context, then propose a reversible fix + rollback addressed to the Controller.\n"
        f"{case_markers(finding)} {routed_marker(finding)}"
    )


@tool
async def controller_route(config: RunnableConfig) -> str:
    """Read the board for this room and activate the right specialist for each new case.

    Call this exactly once when a finding (or any activation) arrives. It opens one case per
    (cls, resource), skips cases already routed, and @mentions the owning specialist. Returns a
    one-line summary. You do not need to send any message or write any JSON yourself.
    """
    room_id = ((config or {}).get("configurable") or {}).get("thread_id")
    if not room_id:
        return "ERROR: no room id available from context; cannot route."

    lock = _ROUTE_LOCKS.setdefault(room_id, asyncio.Lock())
    async with lock:
        try:
            return await _route(room_id)
        except Exception as e:  # never crash the agent turn
            log.exception("controller_route failed in room %s", room_id)
            return f"ERROR routing: {e}"


async def _route(room_id: str) -> str:
    # Post AS the Controller via its own REST client (separate from the agent's WS connection).
    _agent_id, controller_key = load_agent_config("controller")
    client = AsyncRestClient(api_key=controller_key, base_url=rest_base_url())

    ctx = await client.agent_api_context.get_agent_chat_context(
        chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
    )
    messages = list(ctx.data or [])
    # NOTE: single page only — pagination unverified (a 3-finding room is one page). Plan §Hardening #5.

    cases = parse_findings_from_messages(messages)
    routed = already_routed_ids(messages)

    if not cases:
        # Hardening #3: surface who authored messages so a sender/format mismatch is never silent.
        senders = sorted({
            (str(_attr(m, "sender_name")), str(_attr(m, "sender_type"))) for m in messages
        })
        log.warning(
            "controller_route: parsed 0 findings from %d messages; senders=%s", len(messages), senders
        )
        return f"No findings to route yet ({len(messages)} messages scanned)."

    parts = await client.agent_api_participants.list_agent_chat_participants(
        chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
    )
    participants = parts.data or []

    routed_now: list[str] = []
    awaiting: list[str] = []
    skipped: list[str] = []
    for key, finding in cases.items():
        if case_id(finding) in routed:
            skipped.append(key)
            continue
        cls = finding.cls.value if hasattr(finding.cls, "value") else str(finding.cls)
        specialist_name = CLS_TO_SPECIALIST.get(cls)
        spec = _find_specialist(participants, specialist_name)
        if spec is None:
            awaiting.append(key)
            log.info("case %s: specialist '%s' not in room — awaiting (M6)", key, specialist_name)
            continue
        handle = _attr(spec, "handle")
        mention = ChatMessageRequestMentionsItem(id=_attr(spec, "id"), handle=handle)
        await client.agent_api_messages.create_agent_chat_message(
            chat_id=room_id,
            message=ChatMessageRequest(
                content=_activation_message(finding, handle), mentions=[mention]
            ),
            request_options=DEFAULT_REQUEST_OPTIONS,
        )
        routed_now.append(key)
        log.info("routed case %s -> %s (%s)", key, specialist_name, handle)

    return (
        f"Routed {len(routed_now)}: {routed_now}; "
        f"awaiting specialist: {awaiting}; already-routed skipped: {skipped}."
    )


# The Controller LLM gets ONLY this deterministic routing tool (it triggers; code routes).
CONTROLLER_TOOLS = [controller_route]
