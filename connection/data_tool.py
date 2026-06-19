"""
Data Specialist's proposal tool, registered on the Data Specialist LangGraph adapter.

The LLM only triggers: it calls `data_emit_proposal(diagnosis)` once. This tool then does the
security-critical work deterministically (no LLM):
  1. room_id from config.configurable.thread_id,
  2. fetch the specialist's scoped context; read the data case (cls:resource) from the [case:...]
     marker on the Controller's activation message that @mentions this specialist,
  3. inspect the live bucket via cloud_describe — FAIL CLOSED if the read is unreliable
     (error/timeout/malformed/missing-key) -> refuse to propose; never substitute a baseline,
  4. build the canonical reversible fix+rollback (coordination.remediations.build_data_remediation),
  5. self-check the deterministic floor (coordination.structural_violations),
  6. idempotency: skip with "already proposed" if the room already holds this [case][proposal_id],
  7. post the type=proposal Contribution to @Risk Policy via REST as `data_specialist`
     (byte-identical format to scripts/post_contribution.py, so Risk and the audit chain see it identically).

LangGraph custom tools don't get room-bound AgentTools, so we post via our own REST client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from types import SimpleNamespace

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from band.config import load_agent_config
from band.client.rest import (
    AsyncRestClient,
    ChatMessageRequest,
    ChatMessageRequestMentionsItem,
    DEFAULT_REQUEST_OPTIONS,
)

from cloud.describe import cloud_describe
from connection.poster import rest_base_url
from coordination.board import case_markers
from coordination.contributions import (
    parse_contribution,
    proposal_id,
    proposal_id_from_content,
    proposal_id_marker,
    structural_violations,
)
from coordination.remediations import build_data_remediation

log = logging.getLogger("castellan.data")

_PROPOSAL_LOCKS: dict[str, asyncio.Lock] = {}
RISK_NAME = "Risk Policy"  # display name to resolve the proposal's mention target
_CASE_RE = re.compile(r"\[case:([^\]]+)\]")


def _attr(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _content(msg) -> str:
    return _attr(msg, "content") or ""


def _find_participant(participants, name: str):
    want = (name or "").strip().lower()
    for p in participants or []:
        if (_attr(p, "name") or "").strip().lower() == want:
            return p
    return None


def _latest_data_case(messages) -> str | None:
    """Most recent data-class case_key (cls:resource) from [case:...] markers in scoped context.

    The Controller's activation message @mentions the specialist and carries the marker; a human can
    also trigger with `@Data Specialist propose a fix for case data:...`. Last (chronological) wins.
    """
    found = None
    for m in messages:
        for ck in _CASE_RE.findall(_content(m)):
            ck = ck.strip()
            if ck.split(":", 1)[0] == "data":
                found = ck
    return found


def _already_proposed(messages, pid: str) -> bool:
    """True if the room already holds a type=proposal Contribution carrying this proposal_id."""
    for m in messages:
        content = _content(m)
        if proposal_id_from_content(content) != pid:
            continue
        c = parse_contribution(content)
        if c is not None and c.type == "proposal":
            return True
    return False


@tool
async def data_emit_proposal(config: RunnableConfig, diagnosis: str = "") -> str:
    """Propose a reversible remediation for the data (S3) misconfiguration you were activated on.

    Call this EXACTLY ONCE after reading the case. Pass a short `diagnosis` naming the exposure.
    You do NOT specify the fix: this tool inspects the live bucket and builds the concrete,
    reversible fix + rollback deterministically, validates it, and posts it to the Risk gate.
    """
    room_id = ((config or {}).get("configurable") or {}).get("thread_id")
    if not room_id:
        return "ERROR: no room id available from context; cannot emit proposal."
    lock = _PROPOSAL_LOCKS.setdefault(room_id, asyncio.Lock())
    async with lock:
        try:
            return await _emit(room_id, diagnosis)
        except Exception as e:  # never crash the agent turn
            log.exception("data_emit_proposal failed in room %s", room_id)
            return f"ERROR emitting proposal: {e}"


async def _emit(room_id: str, diagnosis: str) -> str:
    _agent_id, data_key = load_agent_config("data_specialist")
    client = AsyncRestClient(api_key=data_key, base_url=rest_base_url())

    ctx = await client.agent_api_context.get_agent_chat_context(
        chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
    )
    messages = list(ctx.data or [])

    case_key = _latest_data_case(messages)
    if case_key is None:
        return "No data case in context (no [case:data:...] marker). Nothing to propose."
    cls, _, resource = case_key.partition(":")

    # --- live evidence; FAIL CLOSED on an unreliable read ---
    try:
        evidence = cloud_describe("s3_bucket", resource)
    except Exception as e:  # timeout / network / non-ClientError -> NOT a None case
        log.warning("cloud_describe raised for %s: %s", resource, e)
        return f"No reliable evidence for {resource} (describe failed: {e}) -> no proposal."
    try:
        contrib = build_data_remediation(cls, resource, evidence, diagnosis=diagnosis)
    except ValueError as e:  # unreliable/malformed evidence, or non-data case
        log.warning("refusing to propose for %s: %s", resource, e)
        return f"No reliable evidence for {resource} ({e}) -> no proposal."

    # --- deterministic floor self-check (fail closed at the source) ---
    floor = structural_violations(contrib)
    if floor:
        return f"Refusing to post: deterministic floor fired ({'; '.join(floor)})."

    pid = proposal_id(case_key, contrib.fix, contrib.rollback)

    # --- idempotency: do not double-post the same [case][proposal_id] ---
    if _already_proposed(messages, pid):
        log.info("data: proposal %s for %s already in room — skipping", pid, case_key)
        return f"already proposed: {case_key} [proposal_id:{pid}] is already in the room."

    ns = SimpleNamespace(cls=cls, resource=resource)
    # Case markers byte-identical to the Controller; proposal_id from the SAME validated ActionSpecs
    # the Risk gate and the audit chain recompute, so all three correlate.
    markers = f"{case_markers(ns)} {proposal_id_marker(case_key, contrib.fix, contrib.rollback)}"

    participants = (
        await client.agent_api_participants.list_agent_chat_participants(
            chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
        )
    ).data or []
    risk = _find_participant(participants, RISK_NAME)
    if risk is None:
        return f"'{RISK_NAME}' not in room {room_id}; cannot deliver proposal for {case_key}."
    handle = _attr(risk, "handle")
    mention = ChatMessageRequestMentionsItem(id=_attr(risk, "id"), handle=handle)

    body = json.dumps(contrib.model_dump(mode="json"), indent=2)
    content = (
        f"{handle} Data Specialist proposal for {case_key}.\n"
        f"{markers}\n\n```json\n{body}\n```"
    )
    await client.agent_api_messages.create_agent_chat_message(
        chat_id=room_id,
        message=ChatMessageRequest(content=content, mentions=[mention]),
        request_options=DEFAULT_REQUEST_OPTIONS,
    )
    log.info("data: posted proposal for %s (proposal_id=%s) to @%s", case_key, pid, RISK_NAME)
    return f"Posted proposal for {case_key} [proposal_id:{pid}] to @{RISK_NAME}."


DATA_SPECIALIST_TOOLS = [data_emit_proposal]
