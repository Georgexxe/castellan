"""
M5 — provable audit chain (pure, deterministic; no Band/LLM).

Rebuilds a SHA-256 hash chain over the decision-critical records reconstructed from Band room
messages. The chain is the single source of truth (the blackboard); this module classifies room
messages into records, enforces completeness + authorization, hashes them with attribution INSIDE
the hash, and verifies (including recomputing reversibility from chain-resident data).

Pure: takes already-fetched messages (dicts or Fern ChatMessage objects) — no I/O, no Band, no LLM.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from coordination.board import case_id as board_case_id
from coordination.contributions import (
    canonical_json,
    parse_constraint,
    parse_contribution,
    proposal_id_from_content,
)
from coordination.models import Finding

GENESIS = "0" * 64

# Canonical order of decision-critical records for a case. A valid case is a PREFIX of this.
ORDER = [
    "case_open",
    "contribution",
    "constraint",
    "human_approval",
    "action_applied",
    "human_rollback",
    "action_rolled_back",
]
_PREDECESSOR = {t: ORDER[i - 1] for i, t in enumerate(ORDER) if i > 0}

# action_* records require an authorizing human decision for the SAME proposal_id, earlier in order.
_AUTHORIZER = {"action_applied": "human_approval", "action_rolled_back": "human_rollback"}

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)
_CASE_ID_RE = re.compile(r"\[case_id:([0-9a-f]{8})\]")
# Human decision: exact/anchored, mention-tolerant; captures verb + 12-hex proposal_id.
_HUMAN_DECISION_RE = re.compile(r"^(?:@\S+\s+)*(APPROVE|ROLLBACK)\s+([0-9a-f]{12})\s*$")
_VERB_TO_TYPE = {"APPROVE": "human_approval", "ROLLBACK": "human_rollback"}


class AuditError(Exception):
    """Raised on a genuine gap / unauthorized action — never silently chain a partial history."""


@dataclass
class AuditRecord:
    record_type: str
    case_id: str | None
    proposal_id: str | None
    sender: str | None  # sender_id — the stable, hashed identity
    sender_name: str | None  # display only (not the hashed identity)
    sender_type: str | None
    inserted_at: str
    source_message_id: str
    payload: dict

    def hashed_dict(self) -> dict:
        # Attribution + timestamps INSIDE the hash (sender = stable sender_id).
        return {
            "record_type": self.record_type,
            "case_id": self.case_id,
            "proposal_id": self.proposal_id,
            "sender": self.sender,
            "sender_type": self.sender_type,
            "inserted_at": self.inserted_at,
            "source_message_id": self.source_message_id,
            "payload": self.payload,
        }


@dataclass
class ChainEntry:
    seq: int
    prev_hash: str
    entry_hash: str
    record: AuditRecord


# --- message field access (dict or Fern ChatMessage) ---------------------------------------------
def _g(msg, name):
    return msg.get(name) if isinstance(msg, dict) else getattr(msg, name, None)


def _content(msg) -> str:
    return _g(msg, "content") or ""


def _first_json(content: str) -> dict | None:
    for m in _FENCE_RE.finditer(content or ""):
        import json

        try:
            data = json.loads(m.group(1).strip())
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _case_id_marker(content: str) -> str | None:
    m = _CASE_ID_RE.search(content or "")
    return m.group(1) if m else None


def _classify_one(msg) -> AuditRecord | None:
    """Classify a single room message into an AuditRecord, or None to skip (non-decision)."""
    content = _content(msg)
    sender_type = _g(msg, "sender_type")
    is_human = str(sender_type or "").strip().lower() != "agent"
    common = dict(
        sender=_g(msg, "sender_id"),
        sender_name=_g(msg, "sender_name"),
        sender_type=sender_type,
        inserted_at=str(_g(msg, "inserted_at") or ""),
        source_message_id=str(_g(msg, "id") or ""),
    )

    if "[audit_head:" in content:
        return None  # the receipt is NEVER a hashed record
    if "[action_applied]" in content:
        return AuditRecord(record_type="action_applied", case_id=_case_id_marker(content),
                           proposal_id=proposal_id_from_content(content),
                           payload=_first_json(content) or {}, **common)
    if "[action_rolled_back]" in content:
        return AuditRecord(record_type="action_rolled_back", case_id=_case_id_marker(content),
                           proposal_id=proposal_id_from_content(content),
                           payload=_first_json(content) or {}, **common)

    constraint = parse_constraint(content)
    if constraint is not None:
        return AuditRecord(record_type="constraint", case_id=_case_id_marker(content),
                           proposal_id=proposal_id_from_content(content),
                           payload=constraint.model_dump(mode="json"), **common)

    contribution = parse_contribution(content)
    if contribution is not None and contribution.type == "proposal":
        return AuditRecord(record_type="contribution", case_id=_case_id_marker(content),
                           proposal_id=proposal_id_from_content(content),
                           payload=contribution.model_dump(mode="json"), **common)

    # case_open: a bare Finding JSON (no proposal/constraint). case_id derived from cls:resource.
    data = _first_json(content)
    if data is not None and constraint is None and contribution is None:
        try:
            finding = Finding(**data)
        except Exception:
            finding = None
        if finding is not None:
            return AuditRecord(record_type="case_open", case_id=board_case_id(finding),
                               proposal_id=None, payload=data, **common)

    # human decision (APPROVE/ROLLBACK <pid>) — exact match, human sender
    if is_human:
        m = _HUMAN_DECISION_RE.match(content.strip())
        if m:
            return AuditRecord(record_type=_VERB_TO_TYPE[m.group(1)], case_id=None,
                               proposal_id=m.group(2),
                               payload={"decision": m.group(1)}, **common)

    return None  # activations, gate requests, chatter → not decision-critical


def _backfill_case_ids(records: list[AuditRecord]) -> None:
    """Human decisions carry only proposal_id; backfill case_id from contribution/constraint records."""
    pid_to_case = {
        r.proposal_id: r.case_id
        for r in records
        if r.proposal_id and r.case_id and r.record_type in ("contribution", "constraint")
    }
    for r in records:
        if r.case_id is None and r.proposal_id in pid_to_case:
            r.case_id = pid_to_case[r.proposal_id]


def _assert_complete(records: list[AuditRecord]) -> None:
    """Accept any valid ordered PREFIX; raise only on a genuine gap or unauthorized action."""
    by_case: dict[str | None, list[AuditRecord]] = {}
    for r in records:
        by_case.setdefault(r.case_id, []).append(r)

    for cid, recs in by_case.items():
        present = {r.record_type for r in recs}
        # gap check: every present type must have its canonical predecessor present (transitive prefix)
        for t in present:
            pred = _PREDECESSOR.get(t)
            if pred and pred not in present:
                raise AuditError(
                    f"audit gap in case {cid}: '{t}' present but its predecessor '{pred}' is missing "
                    f"(present={sorted(present)})"
                )
        # authorization links: action_* needs its human decision for the SAME proposal_id, earlier
        order = {id(r): i for i, r in enumerate(recs)}
        for r in recs:
            authz = _AUTHORIZER.get(r.record_type)
            if not authz:
                continue
            ok = any(
                a.record_type == authz and a.proposal_id == r.proposal_id and order[id(a)] < order[id(r)]
                for a in recs
            )
            if not ok:
                raise AuditError(
                    f"unauthorized {r.record_type} for proposal {r.proposal_id} in case {cid}: "
                    f"no preceding '{authz}' for the same proposal_id"
                )


def classify_records(messages) -> list[AuditRecord]:
    """Messages -> ordered, deduped, completeness-checked AuditRecords.

    Order is deterministic: (inserted_at, source_message_id). Dedup by source_message_id.
    Raises AuditError on a genuine gap / unauthorized action (never chains a partial history).
    """
    seen: set[str] = set()
    records: list[AuditRecord] = []
    for msg in messages:
        rec = _classify_one(msg)
        if rec is None:
            continue
        if rec.source_message_id in seen:
            continue
        seen.add(rec.source_message_id)
        records.append(rec)
    records.sort(key=lambda r: (r.inserted_at, r.source_message_id))
    _backfill_case_ids(records)
    _assert_complete(records)
    return records


def build_chain(records: list[AuditRecord]) -> list[ChainEntry]:
    """Hash chain: entry_hash = sha256(prev_hash + canonical_json(record.hashed_dict()))."""
    chain: list[ChainEntry] = []
    prev = GENESIS
    for i, rec in enumerate(records):
        entry_hash = hashlib.sha256(
            (prev + canonical_json(rec.hashed_dict())).encode("utf-8")
        ).hexdigest()
        chain.append(ChainEntry(seq=i, prev_hash=prev, entry_hash=entry_hash, record=rec))
        prev = entry_hash
    return chain


def chain_head(records: list[AuditRecord]) -> str:
    chain = build_chain(records)
    return chain[-1].entry_hash if chain else GENESIS


def first_divergence(chain_a: list[ChainEntry], chain_b: list[ChainEntry]) -> int | None:
    """First seq where two chains' entry_hash differ (the first broken entry). None if identical."""
    for i in range(min(len(chain_a), len(chain_b))):
        if chain_a[i].entry_hash != chain_b[i].entry_hash:
            return i
    if len(chain_a) != len(chain_b):
        return min(len(chain_a), len(chain_b))
    return None


def recompute_reversibility(records: list[AuditRecord]) -> list[dict]:
    """For each action_rolled_back, recompute restored_matches_original from CHAIN-RESIDENT data:
    the action_applied(state_before) for the same proposal_id vs this record's state_after_rollback.
    Flags a posted-vs-recomputed mismatch — reversibility is provable from the chain, not just posted."""
    applied_before = {
        r.proposal_id: r.payload.get("state_before")
        for r in records
        if r.record_type == "action_applied"
    }
    results = []
    for r in records:
        if r.record_type != "action_rolled_back":
            continue
        original = applied_before.get(r.proposal_id)
        after_rb = r.payload.get("state_after_rollback")
        recomputed = original is not None and after_rb == original
        posted = bool(r.payload.get("restored_matches_original"))
        results.append({
            "proposal_id": r.proposal_id,
            "recomputed": recomputed,
            "posted": posted,
            "match": recomputed == posted,
            "ok": recomputed and (recomputed == posted),
        })
    return results


def verify(records: list[AuditRecord], expected_head: str) -> dict:
    """Rebuild the chain, compare head to the trusted anchor, and recompute reversibility from chain."""
    head = chain_head(records)
    rev = recompute_reversibility(records)
    return {
        "ok": head == expected_head,
        "head": head,
        "expected_head": expected_head,
        "length": len(records),
        "reversibility": rev,
        "reversibility_ok": all(x["ok"] for x in rev) if rev else None,
    }
