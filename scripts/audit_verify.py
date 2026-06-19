"""
Auditor (CLI) — rebuild the audit chain from Band room history and verify it against an
out-of-band anchor; tamper demo. The reconstruction + verify + tamper logic lives in the shared
module `connection.audit_reader` (imported by BOTH this CLI and the FastAPI read-bridge), which in
turn calls the pure functions in `coordination.audit`. This script only does CLI argument handling,
printing, and the guarded `--anchor` write path.

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
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

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
from connection.audit_reader import ANCHOR_DIR, aggregate_messages, anchor_path, tamper_room
from coordination.audit import AuditError, build_chain, classify_records, verify
from coordination.board import case_markers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("castellan.audit")


def _g(msg, name):
    return msg.get(name) if isinstance(msg, dict) else getattr(msg, name, None)


def _safe(s: str, fallback: str) -> str:
    """Return *s* if the active stdout encoding can render it, else *fallback* (ASCII).

    Keeps the proof-bearing text (head, VALID/BREAK, seq) byte-identical while never crashing on a
    Windows cp1252 console over the decorative glyphs (checkmark/cross/ellipsis)."""
    try:
        s.encode(sys.stdout.encoding or "utf-8")
        return s
    except (UnicodeEncodeError, LookupError):
        return fallback


def _print_chain(records) -> None:
    ell = _safe("…", "...")
    for e in build_chain(records):
        r = e.record
        print(f"  [{e.seq}] {r.record_type:18} case={r.case_id} pid={r.proposal_id} "
              f"by={r.sender_name!r}/{r.sender_type} hash={e.entry_hash[:12]}{ell}")


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
    anchor_file = anchor_path(room_id)

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
        print(f"VALID {_safe(chr(0x2713), 'OK')}  recomputed head == anchor ({head})")
    else:
        print(f"BREAK {_safe(chr(0x2717), 'X')}  recomputed head ({head}) != anchor ({anchor})")

    if mode == "tamper":
        # The tamper computation lives in the shared module (single source of truth); print from it.
        t = tamper_room(records, anchor)
        print(f"\n--- TAMPER: mutated record_type={t['mutated_record_type']} payload.rule ---")
        if not t["break"]:
            print("UNEXPECTED: tampered head still matches anchor")
        else:
            print(f"BREAK {_safe(chr(0x2717), 'X')}  tampered head ({t['tampered_head']}) != anchor ({anchor})")
            print(f"first broken entry: seq {t['first_broken_seq']} (record_type={t['first_broken_type']}); "
                  f"all {t['invalidated_after']} entries after it are invalidated (chain property).")


if __name__ == "__main__":
    asyncio.run(main())
