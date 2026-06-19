"""
scripts/run_evidence.py — additive trigger for the Evidence Analyst (M6b).

Posts a plain-language risk summary for a case to the room, AS the Evidence Analyst, via the shared
deterministic core (cloud_describe -> ONE Featherless call -> sanitize -> post [evidence_summary]).
Additive + read-only: touches NOTHING in the proven spine, and the audit chain ignores the post.

Usage:
    cd castellan
    uv run python scripts/run_evidence.py <room_id> <cls:resource> [--to <handle>]
      e.g. uv run python scripts/run_evidence.py <room_id> data:acme-public-data

Creds: evidence_analyst from agent_config.yaml; FEATHERLESS_API_KEY from .env. The Evidence Analyst
must be a participant in the room.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

from connection.evidence_tool import summarize_and_post


async def main() -> None:
    load_dotenv()
    args = sys.argv[1:]
    if len(args) < 2 or not args[0].strip() or not args[1].strip():
        raise SystemExit(
            "usage: uv run python scripts/run_evidence.py <room_id> <cls:resource> [--to <handle>]"
        )
    room_id = args[0].strip()
    case_key = args[1].strip()
    prefer_handle = None
    if "--to" in args:
        i = args.index("--to")
        if i + 1 < len(args):
            prefer_handle = args[i + 1].strip()

    res = await summarize_and_post(room_id, case_key, prefer_handle=prefer_handle)
    print(res)


if __name__ == "__main__":
    asyncio.run(main())
