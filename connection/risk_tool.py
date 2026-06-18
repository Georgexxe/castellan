"""
Risk/Policy gate's constraint tool (M3), registered on the Risk LangGraph adapter.

Risk runs on LangGraph + ChatAnthropic (a distinct model from the Controller). The LLM makes the
policy *judgment* and calls `risk_emit_constraint` once with its verdict; this tool then:
  1. fetches context and picks the proposal Risk was activated on (newest, via coordination.latest_proposal),
  2. applies the deterministic fail-closed FLOOR (coordination.structural_violations) over the
     proposal's fix + rollback — BLOCK if (LLM reject) OR (floor fires); APPROVE only if both clear,
  3. builds a Pydantic-validated Constraint (deterministic wire format), carrying case markers
     byte-identical to the Controller's (board.case_id/case_markers),
  4. posts it to @Controller via REST as `risk_policy`.

LangGraph custom tools get `room_id` from `config.configurable.thread_id` (the M2 pattern); they
do not get the room-bound AgentTools, so we post via our own REST client (like connection/poster).
"""

from __future__ import annotations

import asyncio
import json
import logging
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

from connection.poster import rest_base_url
from coordination.board import case_id, case_markers
from coordination.contributions import latest_proposal, proposal_id_marker, structural_violations
from coordination.models import Constraint

log = logging.getLogger("castellan.risk")

_CONSTRAINT_LOCKS: dict[str, asyncio.Lock] = {}

CONTROLLER_NAME = "Controller"  # display name to resolve the Constraint's mention target


def _attr(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _find_participant(participants, name: str):
    want = (name or "").strip().lower()
    for p in participants or []:
        if (_attr(p, "name") or "").strip().lower() == want:
            return p
    return None


def _case_ns(case_key: str):
    """Split 'cls:resource' into a shim that board.case_* accept (cls then resource)."""
    cls, _, resource = case_key.partition(":")
    return SimpleNamespace(cls=cls, resource=resource)


def decide_verdict(
    llm_verdict: str, floor: list[str], rule: str, rationale: str
) -> tuple[str, str, str]:
    """Pure final-verdict logic (Amendment 2), unit-testable in isolation.

    BLOCK if (LLM rejected) OR (the deterministic floor fired). APPROVE only if both are clear.
    Returns (final_verdict, final_rule, final_rationale). When the floor overrides an LLM approve,
    the rationale states the floor fired and which condition.
    """
    llm_verdict = (llm_verdict or "").strip().lower()
    if floor:
        final_rationale = f"Deterministic safety floor fired ({'; '.join(floor)})."
        if llm_verdict == "approve":
            final_rationale += " This overrode the model's approve."
        if rationale:
            final_rationale += f" Model note: {rationale}"
        return "reject", "deterministic floor: " + "; ".join(floor), final_rationale
    final_verdict = "reject" if llm_verdict == "reject" else "approve"
    final_rule = rule or ("policy review" if final_verdict == "approve" else "policy violation")
    final_rationale = rationale or f"Risk {final_verdict} after policy review."
    return final_verdict, final_rule, final_rationale


@tool
async def risk_emit_constraint(
    config: RunnableConfig,
    verdict: str,
    rule: str,
    rationale: str,
    finding_ref: str = "",
) -> str:
    """Post your policy verdict on the current proposal to the Controller.

    Call this exactly once after judging the proposal. Args:
      verdict: your judgement, "approve" or "reject".
      rule: the policy rule you applied (short).
      rationale: one or two sentences explaining the verdict.
      finding_ref: the proposal's finding_id, if shown (display-only).
    A deterministic safety floor may still downgrade an approve to reject; that is expected.
    """
    room_id = ((config or {}).get("configurable") or {}).get("thread_id")
    if not room_id:
        return "ERROR: no room id available from context; cannot emit constraint."
    lock = _CONSTRAINT_LOCKS.setdefault(room_id, asyncio.Lock())
    async with lock:
        try:
            return await _emit(room_id, verdict, rule, rationale, finding_ref)
        except Exception as e:  # never crash the agent turn
            log.exception("risk_emit_constraint failed in room %s", room_id)
            return f"ERROR emitting constraint: {e}"


async def _emit(room_id: str, verdict: str, rule: str, rationale: str, finding_ref: str) -> str:
    _agent_id, risk_key = load_agent_config("risk_policy")
    client = AsyncRestClient(api_key=risk_key, base_url=rest_base_url())

    ctx = await client.agent_api_context.get_agent_chat_context(
        chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
    )
    messages = list(ctx.data or [])

    found = latest_proposal(messages)
    if found is None:
        log.warning("risk_emit_constraint: no proposal found in %d messages", len(messages))
        return "No proposal found in the room to evaluate."
    case_key, proposal = found

    floor = structural_violations(proposal)
    final_verdict, final_rule, final_rationale = decide_verdict(verdict, floor, rule, rationale)

    constraint = Constraint(
        finding_id=finding_ref or "",
        rule=final_rule,
        rationale=final_rationale,
        verdict=final_verdict,  # type: ignore[arg-type]
        invalidates_proposal=(final_verdict == "reject"),
    )

    ns = _case_ns(case_key)
    # Case markers byte-identical to the Controller; proposal_id computed from the SAME validated
    # ActionSpecs the poster used, so it matches the Contribution's [proposal_id] marker.
    markers = f"{case_markers(ns)} {proposal_id_marker(case_key, proposal.fix, proposal.rollback)}"

    participants = (
        await client.agent_api_participants.list_agent_chat_participants(
            chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
        )
    ).data or []
    controller = _find_participant(participants, CONTROLLER_NAME)
    if controller is None:
        return f"Controller not in room {room_id}; cannot deliver constraint for {case_key}."
    handle = _attr(controller, "handle")
    mention = ChatMessageRequestMentionsItem(id=_attr(controller, "id"), handle=handle)

    body = json.dumps(constraint.model_dump(mode="json"), indent=2)
    content = (
        f"{handle} Risk verdict for {case_key}: {final_verdict.upper()}\n"
        f"{markers}\n\n```json\n{body}\n```"
    )
    await client.agent_api_messages.create_agent_chat_message(
        chat_id=room_id,
        message=ChatMessageRequest(content=content, mentions=[mention]),
        request_options=DEFAULT_REQUEST_OPTIONS,
    )
    log.info(
        "risk: %s case %s (case_id=%s, floor=%s)",
        final_verdict, case_key, case_id(ns), floor or "clean",
    )
    return f"Posted {final_verdict.upper()} constraint for {case_key} to @{CONTROLLER_NAME}."


RISK_TOOLS = [risk_emit_constraint]
