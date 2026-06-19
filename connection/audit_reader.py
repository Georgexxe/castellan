"""
Shared audit reconstruction layer (M7) — the SINGLE source of truth for rebuilding + verifying the
audit chain from a Band room, imported by BOTH the CLI (`scripts/audit_verify.py`) and the FastAPI
read-bridge (`ui/api`). No logic is duplicated: this module does the Band I/O (aggregating scoped
contexts, reading the anchor) and calls the proven pure functions in `coordination.audit`
(classify/build/verify/first_divergence) — it never re-parses, re-hashes, or re-classifies.

Lives in `connection/` (the Band-I/O layer) so `coordination/` stays pure (zero Band imports).
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path

from band.config import load_agent_config
from band.client.rest import AsyncRestClient, DEFAULT_REQUEST_OPTIONS

from connection.poster import rest_base_url
from coordination.audit import (
    GENESIS,
    AuditError,  # re-exported for callers that catch it
    build_chain,
    classify_records,
    first_divergence,
    recompute_reversibility,
    verify,
)

log = logging.getLogger("castellan.audit")

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Agents whose scoped views, unioned, reconstruct the full case transcript. data_specialist (M6)
# authors the contribution; including its own view ensures the proposal is captured even if the
# mention-scoping of @Risk Policy ever changes.
AGGREGATE_KEYS = ["controller", "risk_policy", "action", "data_specialist"]
ANCHOR_DIR = _REPO_ROOT / ".audit"

__all__ = [
    "AGGREGATE_KEYS", "ANCHOR_DIR", "AuditError",
    "aggregate_messages", "anchor_path", "reconstruct",
    "verify_room", "tamper_room", "summarize", "cases_overview", "case_detail", "cloud_state",
]


def _g(msg, name):
    return msg.get(name) if isinstance(msg, dict) else getattr(msg, name, None)


# --- Band I/O: aggregate scoped contexts, read the out-of-band anchor (moved verbatim) -----------
async def _fetch_all(api_key: str, room_id: str) -> list:
    client = AsyncRestClient(api_key=api_key, base_url=rest_base_url())
    out, page = [], 1
    while True:
        resp = await client.agent_api_context.get_agent_chat_context(
            chat_id=room_id, page=page, page_size=100, request_options=DEFAULT_REQUEST_OPTIONS
        )
        batch = list(resp.data or [])
        out.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return out


async def aggregate_messages(room_id: str) -> list:
    """Union of {controller, risk_policy, action, data_specialist} scoped contexts, deduped by id."""
    by_id: dict[str, object] = {}
    for key in AGGREGATE_KEYS:
        try:
            _id, api_key = load_agent_config(key)
        except Exception as e:
            log.warning("skipping %s context (no creds): %s", key, e)
            continue
        for m in await _fetch_all(api_key, room_id):
            by_id[str(_g(m, "id"))] = m
    return list(by_id.values())


def anchor_path(room_id: str) -> Path:
    safe = room_id.replace("/", "_")
    return ANCHOR_DIR / f"{safe}.head"


async def reconstruct(room_id: str):
    """Aggregate the room's scoped contexts and classify into ordered AuditRecords.

    Raises coordination.audit.AuditError on a genuine gap / unauthorized action."""
    messages = await aggregate_messages(room_id)
    return classify_records(messages)


# --- serialization (pure presentation over the proven records; no re-derivation) -----------------
def _entry_dict(entry) -> dict:
    r = entry.record
    return {
        "seq": entry.seq,
        "prev_hash": entry.prev_hash,
        "entry_hash": entry.entry_hash,
        "record_type": r.record_type,
        "case_id": r.case_id,
        "proposal_id": r.proposal_id,
        "sender_name": r.sender_name,
        "sender_type": r.sender_type,
        "inserted_at": r.inserted_at,
        "payload": r.payload,
    }


# --- API-oriented views (shared so the bridge stays zero-logic) ----------------------------------
def verify_room(records, room_id: str) -> dict:
    """Build the chain, compare head to the file anchor (if present), recompute reversibility."""
    chain = build_chain(records)
    head = chain[-1].entry_hash if chain else GENESIS
    af = anchor_path(room_id)
    anchor = af.read_text(encoding="utf-8").strip() if af.exists() else None
    result = verify(records, anchor) if anchor is not None else None
    status = "NO_ANCHOR" if anchor is None else ("VALID" if result["ok"] else "BREAK")
    return {
        "room_id": room_id,
        "head": head,
        "anchor": anchor,
        "ok": bool(result["ok"]) if result else False,
        "status": status,
        "length": len(records),
        "reversibility": result["reversibility"] if result else recompute_reversibility(records),
        "reversibility_ok": (result["reversibility_ok"] if result
                             else (all(x["ok"] for x in recompute_reversibility(records))
                                   if recompute_reversibility(records) else None)),
        "records": [_entry_dict(e) for e in chain],
    }


def tamper_room(records, anchor: str | None) -> dict:
    """In-memory tamper demo: mutate one constraint payload, rebuild, locate the first broken entry.

    Returns the dict the CLI prints from AND the API serves — the single tamper implementation."""
    original_chain = build_chain(records)
    tampered = copy.deepcopy(records)
    target = next((r for r in tampered if r.record_type == "constraint"),
                  tampered[len(tampered) // 2] if tampered else None)
    if target is None:
        return {"break": False, "reason": "no records to tamper"}
    target.payload["rule"] = (target.payload.get("rule", "") or "") + " [TAMPERED]"
    tampered_chain = build_chain(tampered)
    new_head = tampered_chain[-1].entry_hash
    original_head = original_chain[-1].entry_hash if original_chain else GENESIS
    idx = first_divergence(original_chain, tampered_chain)
    baseline = anchor if anchor is not None else original_head
    return {
        "mutated_record_type": target.record_type,
        "original_head": original_head,
        "tampered_head": new_head,
        "anchor": anchor,
        "break": new_head != baseline,
        "first_broken_seq": idx,
        "first_broken_type": original_chain[idx].record.record_type if idx is not None else None,
        "invalidated_after": (len(tampered_chain) - idx - 1) if idx is not None else 0,
    }


def summarize(records, verify_result: dict) -> dict:
    """Spine status counts derived from the proven records (no re-parse)."""
    def n(t):
        return sum(1 for r in records if r.record_type == t)
    return {
        "findings": n("case_open"),
        "cases": len({r.case_id for r in records if r.case_id}),
        "proposals": n("contribution"),
        "verdicts": [r.payload.get("verdict") for r in records if r.record_type == "constraint"],
        "approvals": n("human_approval"),
        "rollback_requests": n("human_rollback"),
        "applied": n("action_applied"),
        "rolled_back": n("action_rolled_back"),
        "audit": verify_result.get("status"),
        "audit_ok": verify_result.get("ok"),
        "reversibility_ok": verify_result.get("reversibility_ok"),
    }


def _case_status(types: set, verdicts: list) -> str:
    if "action_rolled_back" in types:
        return "rolled_back"
    if "action_applied" in types:
        return "applied"
    if "human_approval" in types:
        return "approved"
    if "constraint" in types:
        return "rejected" if "reject" in verdicts else "vetted"
    if "contribution" in types:
        return "proposed"
    if "case_open" in types:
        return "open"
    return "unknown"


def _group_by_case(records) -> dict:
    by_case: dict[str, list] = {}
    for r in records:
        if r.case_id:
            by_case.setdefault(r.case_id, []).append(r)
    return by_case


def cases_overview(records) -> list:
    out = []
    for cid, recs in _group_by_case(records).items():
        types = {r.record_type for r in recs}
        verdicts = [r.payload.get("verdict") for r in recs if r.record_type == "constraint"]
        co = next((r for r in recs if r.record_type == "case_open"), None)
        cls = co.payload.get("cls") if co else None
        resource = co.payload.get("resource") if co else None
        out.append({
            "case_id": cid,
            "case_key": f"{cls}:{resource}" if cls and resource else None,
            "cls": cls,
            "resource": resource,
            "status": _case_status(types, verdicts),
            "record_count": len(recs),
            "proposal_id": next((r.proposal_id for r in recs if r.proposal_id), None),
            "first_seen": min((r.inserted_at for r in recs), default=""),
        })
    out.sort(key=lambda c: c["first_seen"])
    return out


def case_detail(records, case_id: str) -> dict | None:
    chain = build_chain(records)
    entries = [e for e in chain if e.record.case_id == case_id]
    if not entries:
        return None
    recs = [e.record for e in entries]
    types = {r.record_type for r in recs}
    verdicts = [r.payload.get("verdict") for r in recs if r.record_type == "constraint"]
    co = next((r for r in recs if r.record_type == "case_open"), None)
    cls = co.payload.get("cls") if co else None
    resource = co.payload.get("resource") if co else None
    return {
        "case_id": case_id,
        "case_key": f"{cls}:{resource}" if cls and resource else None,
        "cls": cls,
        "resource": resource,
        "status": _case_status(types, verdicts),
        "proposal_id": next((r.proposal_id for r in recs if r.proposal_id), None),
        "records": [_entry_dict(e) for e in entries],
    }


def cloud_state(records) -> dict:
    """Before / after-apply / after-rollback PAB states — read from the chain-resident action
    payloads (actions/ledger.py), NOT a live cloud_describe, so it matches what the chain proves."""
    applied = next((r for r in records if r.record_type == "action_applied"), None)
    rolled = next((r for r in records if r.record_type == "action_rolled_back"), None)
    anchor_rec = applied or rolled
    return {
        "proposal_id": anchor_rec.proposal_id if anchor_rec else None,
        "case_id": anchor_rec.case_id if anchor_rec else None,
        "before": applied.payload.get("state_before") if applied else None,
        "after_apply": applied.payload.get("state_after") if applied else None,
        "after_rollback": rolled.payload.get("state_after_rollback") if rolled else None,
        "restored_matches_original": rolled.payload.get("restored_matches_original") if rolled else None,
    }
