"""
M5 auditor — rebuild the audit chain from Band room history and verify it against an out-of-band
anchor; tamper demo. Pure-chain logic lives in coordination.audit; this script does the Band I/O.

Because Band scopes each agent's context to its own + @mention-ed messages, the full transcript is
reconstructed by AGGREGATING the scoped views of controller + risk_policy + action (union by
message id, sorted by (inserted_at, id)).

Modes (room is the untrusted medium; the file anchor is authoritative):
  (default) --verify  : rebuild, compare head to the existing anchor file -> VALID/BREAK. No writes.
  --anchor [--force]  : write head to .audit/<room_id>.head (refuse if exists unless --force) AND
                        post the in-room [audit_head] receipt. The rare, guarded write.
  --tamper            : verify against the anchor, then mutate one record in memory -> BREAK,
                        identifying the first broken entry. Never writes.

Usage:
    cd castellan
    uv run python scripts/audit_verify.py --anchor <room_id>
    uv run python scripts/audit_verify.py <room_id>
    uv run python scripts/audit_verify.py --tamper <room_id>
"""

from __future__ import annotations

import asyncio
import copy
import logging
import sys
from pathlib import Path

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

from connection.poster import rest_base_url
from coordination.audit import AuditError, build_chain, classify_records, first_divergence, verify
from coordination.board import case_markers
from types import SimpleNamespace

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("castellan.audit")

# Agents whose scoped views, unioned, reconstruct the full case transcript.
AGGREGATE_KEYS = ["controller", "risk_policy", "action"]
ANCHOR_DIR = _REPO_ROOT / ".audit"


def _g(msg, name):
    return msg.get(name) if isinstance(msg, dict) else getattr(msg, name, None)


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
    """Union of {controller, risk_policy, action} scoped contexts, deduped by message id."""
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


def _anchor_path(room_id: str) -> Path:
    safe = room_id.replace("/", "_")
    return ANCHOR_DIR / f"{safe}.head"


def _print_chain(records) -> None:
    for e in build_chain(records):
        r = e.record
        print(f"  [{e.seq}] {r.record_type:18} case={r.case_id} pid={r.proposal_id} "
              f"by={r.sender_name!r}/{r.sender_type} hash={e.entry_hash[:12]}…")


async def main() -> None:
    load_dotenv()
    args = sys.argv[1:]
    flags = {a for a in args if a.startswith("--")}
    positional = [a for a in args if not a.startswith("--")]
    if not positional:
        raise SystemExit("usage: uv run python scripts/audit_verify.py [--verify|--anchor [--force]|--tamper] <room_id>")
    room_id = positional[0]
    mode = "anchor" if "--anchor" in flags else ("tamper" if "--tamper" in flags else "verify")
    force = "--force" in flags

    messages = await aggregate_messages(room_id)
    # A security tool refuses to certify gracefully — it never crashes on an incomplete chain.
    try:
        records = classify_records(messages)
    except AuditError as e:
        print(f"AUDIT INCOMPLETE — cannot certify chain: {e}")
        print("(e.g. a case is missing its case_open / detection record, or an action lacks its "
              "authorizing human decision. Ensure the Scanner posted the Finding and the relevant "
              "agents' contexts were aggregated.)")
        raise SystemExit(2)
    head = build_chain(records)[-1].entry_hash if records else "0" * 64
    print(f"reconstructed {len(records)} record(s) from room {room_id}; head={head}")
    _print_chain(records)
    anchor_file = _anchor_path(room_id)

    if mode == "anchor":
        if anchor_file.exists() and not force:
            raise SystemExit(
                f"!!! REFUSING to overwrite existing anchor {anchor_file}. "
                f"Re-anchoring a (possibly tampered) room would mint a fresh 'valid' head and destroy "
                f"the guarantee. Pass --force ONLY if you intend to re-anchor."
            )
        ANCHOR_DIR.mkdir(exist_ok=True)
        anchor_file.write_text(head, encoding="utf-8")
        print(f"WROTE anchor {anchor_file} = {head}")
        # post the in-room receipt (blackboard story). Representative case = the one with proposal
        # activity (the executed case); reuse board.case_markers on its case_open Finding payload so
        # the receipt's [case:...]/[case_id:...] are byte-identical to every other record for the case.
        # (rep.case_id is the 8-hex hash, NOT a cls:resource key — never feed it back into case_markers.)
        pid = next((r.proposal_id for r in reversed(records) if r.proposal_id), None)
        rep_case_id = next(
            (r.case_id for r in reversed(records) if pid and r.proposal_id == pid and r.case_id),
            None,
        ) or next((r.case_id for r in reversed(records) if r.case_id), None)
        case_open = next(
            (r for r in records if r.record_type == "case_open" and r.case_id == rep_case_id), None
        )
        markers = f"[audit_head:{head}]"
        if case_open is not None:
            ns = SimpleNamespace(cls=case_open.payload.get("cls"), resource=case_open.payload.get("resource"))
            markers += f" {case_markers(ns)}"  # -> [case:data:acme-public-data] [case_id:575e729d]
        elif rep_case_id:
            markers += f" [case_id:{rep_case_id}]"
        if pid:
            markers += f" [proposal_id:{pid}]"
        _aid, action_key = load_agent_config("action")
        client = AsyncRestClient(api_key=action_key, base_url=rest_base_url())
        parts = (await client.agent_api_participants.list_agent_chat_participants(
            chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS)).data or []
        ctrl = next((p for p in parts if (_g(p, "name") or "").strip().lower() == "controller"), None)
        if ctrl is not None:
            h = _g(ctrl, "handle")
            await client.agent_api_messages.create_agent_chat_message(
                chat_id=room_id,
                message=ChatMessageRequest(content=f"{h} audit head committed.\n{markers}",
                                           mentions=[ChatMessageRequestMentionsItem(id=_g(ctrl, "id"), handle=h)]),
                request_options=DEFAULT_REQUEST_OPTIONS)
            print(f"POSTED in-room receipt: {markers}")
        return

    # verify / tamper both require an existing anchor
    if not anchor_file.exists():
        raise SystemExit(f"no anchor at {anchor_file} — run `--anchor {room_id}` first.")
    anchor = anchor_file.read_text(encoding="utf-8").strip()
    result = verify(records, anchor)
    print(f"anchor={anchor}")
    print(f"reversibility: {result['reversibility']} (ok={result['reversibility_ok']})")
    if result["ok"]:
        print(f"VALID ✓  recomputed head == anchor ({head})")
    else:
        print(f"BREAK ✗  recomputed head ({head}) != anchor ({anchor})")

    if mode == "tamper":
        original_chain = build_chain(records)
        tampered = copy.deepcopy(records)
        # mutate one mid-chain record's payload to simulate sophisticated tampering
        target = next((r for r in tampered if r.record_type == "constraint"), tampered[len(tampered) // 2])
        before = copy.deepcopy(target.payload)
        target.payload["rule"] = (target.payload.get("rule", "") or "") + " [TAMPERED]"
        print(f"\n--- TAMPER: mutated record_type={target.record_type} payload.rule ---")
        tampered_chain = build_chain(tampered)
        new_head = tampered_chain[-1].entry_hash
        idx = first_divergence(original_chain, tampered_chain)
        if new_head == anchor:
            print("UNEXPECTED: tampered head still matches anchor")
        else:
            print(f"BREAK ✗  tampered head ({new_head}) != anchor ({anchor})")
            print(f"first broken entry: seq {idx} (record_type={original_chain[idx].record.record_type}); "
                  f"all {len(tampered_chain) - idx - 1} entries after it are invalidated (chain property).")


if __name__ == "__main__":
    asyncio.run(main())
