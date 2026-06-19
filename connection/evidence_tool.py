"""
Evidence Analyst — Featherless-backed, read-only, additive.

Produces a plain-language risk summary for an opened case and posts it as an `[evidence_summary]`
message addressed to a human reviewer. It NEVER posts a Contribution / Constraint / action record,
and `coordination.audit.classify_records` ignores `[evidence_summary]` — so the audit chain is
unaffected (it is not a chained record type). Evidence comes from `cloud_describe` (live, read-only),
not the transcript, so the agent depends on nothing in the proven spine.

Transport: `ChatOpenAI` -> Featherless (Qwen-7B). ONE Featherless call per case. On any failure →
a clean "summary unavailable", never a partial/broken post.

THREE out-of-audit guarantees:
  1. `[evidence_summary]` is not one of the chained record types → classify_records returns None.
  2. `sanitize_summary` strips fenced code / JSON so the prose can never be misread as a record.
  3. It is not in audit_verify's AGGREGATE_KEYS and is addressed to the human, not an aggregated agent.
"""

from __future__ import annotations

import json
import logging
import os
import re
from types import SimpleNamespace

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from band.config import load_agent_config
from band.client.rest import (
    AsyncRestClient,
    ChatMessageRequest,
    ChatMessageRequestMentionsItem,
    DEFAULT_REQUEST_OPTIONS,
)

from connection.poster import rest_base_url
from cloud.describe import cloud_describe
from coordination.board import case_markers

log = logging.getLogger("castellan.evidence")

FEATHERLESS_BASE_URL = "https://api.featherless.ai/v1"
DEFAULT_FEATHERLESS_MODEL = "Qwen/Qwen2.5-7B-Instruct"
EVIDENCE_MARKER = "[evidence_summary]"
MAX_SUMMARY_CHARS = 700

# cls -> the cloud_describe resource_type (read-only inspection).
_CLS_TO_RESOURCE_TYPE = {
    "data": "s3_bucket",
    "iam": "iam_role",
    "network": "security_group",
}

_CASE_RE = re.compile(r"\[case:([^\]]+)\]")
# any structured marker the model might echo — stripped so the post is inert to every parser
_MARKER_RE = re.compile(
    r"\[(?:case|case_id|proposal_id|routed|evidence_summary|action_applied|action_rolled_back|audit_head)[^\]]*\]"
)

SYSTEM_PROMPT = (
    "You are a cloud-security Evidence Analyst. Given a finding's raw evidence, write a SHORT "
    "plain-language risk summary for a human reviewer: what is exposed, why it matters, and a rough "
    "severity in human terms. Two to four sentences. Plain prose ONLY — no JSON, no code blocks, no "
    "backticks, no markdown headers, no bullet points."
)


def _attr(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def sanitize_summary(text: str) -> str:
    """Force the model's output to inert plain prose: strip fenced code blocks, backticks, any
    structured markers, collapse whitespace, and cap length. This is what guarantees the posted
    message can never be misclassified as an audit record (guarantee #2)."""
    if not text:
        return ""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)  # whole fenced blocks
    text = re.sub(r"`+", "", text)  # stray backticks
    text = _MARKER_RE.sub("", text)  # any [marker] tokens the model echoed
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_SUMMARY_CHARS:
        text = text[:MAX_SUMMARY_CHARS].rsplit(" ", 1)[0].rstrip() + "…"
    return text


async def _summarize(evidence: dict) -> str:
    """The ONE Featherless call. Returns sanitized plain prose, or '' on any failure."""
    key = os.getenv("FEATHERLESS_API_KEY")
    if not key:
        raise RuntimeError("FEATHERLESS_API_KEY not set")
    model = os.getenv("FEATHERLESS_MODEL", DEFAULT_FEATHERLESS_MODEL)
    llm = ChatOpenAI(
        model=model,
        base_url=FEATHERLESS_BASE_URL,
        api_key=key,
        max_tokens=220,
        temperature=0.2,
    )
    msg = await llm.ainvoke(
        [
            ("system", SYSTEM_PROMPT),
            (
                "human",
                f"Finding evidence (JSON):\n{json.dumps(evidence, indent=2)}\n\nWrite the summary.",
            ),
        ]
    )
    return sanitize_summary(getattr(msg, "content", "") or "")


def _resolve_target(parts, self_id, *, prefer_id=None, prefer_handle=None):
    """Pick whom to address: the requester (by id/handle) if given, else the Controller, else any
    other participant. The summary is addressed to a human reviewer; never to ourselves."""
    others = [p for p in parts if _attr(p, "id") != self_id]
    if prefer_id:
        m = next((p for p in others if _attr(p, "id") == prefer_id), None)
        if m:
            return m
    if prefer_handle:
        h = prefer_handle.lstrip("@")
        m = next((p for p in others if (_attr(p, "handle") or "").lstrip("@") == h), None)
        if m:
            return m
    ctrl = next(
        (p for p in others if (_attr(p, "name") or "").strip().lower() == "controller"), None
    )
    if ctrl:
        return ctrl
    return others[0] if others else None


async def summarize_and_post(
    room_id: str,
    case_key: str,
    *,
    prefer_id: str | None = None,
    prefer_handle: str | None = None,
) -> dict:
    """Shared core, used by both the CLI driver and the agent tool. cloud_describe -> ONE Featherless
    call -> sanitize -> post [evidence_summary]. Fail-closed (clean 'unavailable', never partial)."""
    cls, _, resource = case_key.partition(":")
    rtype = _CLS_TO_RESOURCE_TYPE.get(cls)
    if not rtype or not resource:
        return {"posted": False, "reason": f"unsupported or malformed case_key {case_key!r}"}

    try:
        evidence = cloud_describe(rtype, resource)
    except Exception as e:  # timeout / non-ClientError — never substitute, just mark unreliable
        log.warning("cloud_describe failed for %s/%s: %s", rtype, resource, e)
        evidence = {"error": "describe_failed", "message": str(e)}
    reliable = isinstance(evidence, dict) and "error" not in evidence

    summary = ""
    if reliable:
        try:
            summary = await _summarize(evidence)
        except Exception as e:  # model hiccup = no summary, never corruption
            log.warning("featherless summary failed for %s: %s", case_key, e)
            summary = ""

    body = summary or (
        "Evidence summary unavailable — the analyst could not produce a summary for this case."
    )

    self_id, key = load_agent_config("evidence_analyst")
    client = AsyncRestClient(api_key=key, base_url=rest_base_url())
    parts = (
        await client.agent_api_participants.list_agent_chat_participants(
            chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
        )
    ).data or []
    target = _resolve_target(parts, self_id, prefer_id=prefer_id, prefer_handle=prefer_handle)

    mentions = []
    prefix = ""
    if target is not None:
        h = _attr(target, "handle")
        mentions = [ChatMessageRequestMentionsItem(id=_attr(target, "id"), handle=h)]
        prefix = f"{h} "

    ns = SimpleNamespace(cls=cls, resource=resource)
    content = f"{prefix}{EVIDENCE_MARKER} {case_markers(ns)}\n\n{body}"
    await client.agent_api_messages.create_agent_chat_message(
        chat_id=room_id,
        message=ChatMessageRequest(content=content, mentions=mentions),
        request_options=DEFAULT_REQUEST_OPTIONS,
    )
    log.info(
        "evidence: posted summary for %s (reliable=%s, chars=%d, to=%s)",
        case_key, reliable, len(body), _attr(target, "handle") if target else None,
    )
    return {
        "posted": True,
        "case_key": case_key,
        "reliable": reliable,
        "summary_chars": len(body),
        "addressed_to": _attr(target, "handle") if target else None,
    }


# --- LangGraph tool for the band agent (on @mention) ---------------------------------------------
def _latest_case_and_requester(messages, self_id):
    """From the agent's scoped context, the most recent [case:cls:resource] and the latest non-self
    sender id (the requester to address)."""
    case_key = None
    requester_id = None
    for m in messages:
        found = _CASE_RE.findall(_attr(m, "content") or "")
        if found:
            case_key = found[-1].strip()
        sid = _attr(m, "sender_id")
        if sid and sid != self_id:
            requester_id = sid
    return case_key, requester_id


@tool
async def post_evidence_summary(config: RunnableConfig) -> str:
    """Post a plain-language risk summary for the case you were @mentioned about. Call this once."""
    room_id = ((config or {}).get("configurable") or {}).get("thread_id")
    if not room_id:
        return "ERROR: no room id available from context."
    try:
        self_id, key = load_agent_config("evidence_analyst")
        client = AsyncRestClient(api_key=key, base_url=rest_base_url())
        ctx = await client.agent_api_context.get_agent_chat_context(
            chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
        )
        messages = list(ctx.data or [])
        case_key, requester_id = _latest_case_and_requester(messages, self_id)
        if not case_key:
            return (
                "No [case:cls:resource] marker found in the mention — ask the requester to include "
                "the case, e.g. data:acme-public-data."
            )
        res = await summarize_and_post(room_id, case_key, prefer_id=requester_id)
        return f"Posted evidence summary for {case_key} (reliable={res.get('reliable')})."
    except Exception as e:  # never crash the agent turn
        log.exception("post_evidence_summary failed in room %s", room_id)
        return f"ERROR posting evidence summary: {e}"


EVIDENCE_ANALYST_TOOLS = [post_evidence_summary]
