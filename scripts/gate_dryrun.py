"""
Dry-run: prove the human-gate READ path with execution STUBBED.

Posts an approval request to the room and waits for your reply. On an EXACT human
`APPROVE|DENY|ROLLBACK <proposal_id>` it prints "would execute" — it performs NO mutation. This
proves the poll loop reads + correctly matches a human reply before the gate is wired to the
executor.

Usage:
    cd castellan
    uv run python scripts/gate_dryrun.py <room_id> <proposal_id> [timeout_s]

Identity: posts as the agent under ACTION_AGENT_KEY in agent_config.yaml (default "action").
Register an "Action Layer" agent and add it to the room, or set ACTION_AGENT_KEY=controller to
reuse an existing identity for the dry-run.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

from band.config import load_agent_config
from band.client.rest import AsyncRestClient

from connection.poster import rest_base_url
from actions.gate import request_and_await_decision

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def main() -> None:
    load_dotenv()
    if len(sys.argv) < 3 or not sys.argv[1].strip():
        raise SystemExit("usage: uv run python scripts/gate_dryrun.py <room_id> <proposal_id> [timeout_s]")
    room_id = sys.argv[1].strip()
    proposal_id = sys.argv[2].strip()
    timeout_s = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0

    agent_key = os.getenv("ACTION_AGENT_KEY", "action")
    self_agent_id, api_key = load_agent_config(agent_key)
    client = AsyncRestClient(api_key=api_key, base_url=rest_base_url())

    summary = f"[DRY-RUN] Proposed execution for proposal {proposal_id}. (Read-path test — nothing will be executed.)"
    print(f"posting approval request (proposal {proposal_id}) as '{agent_key}'; waiting up to {timeout_s:.0f}s for your reply…")
    result = await request_and_await_decision(
        client, room_id, proposal_id, summary, self_agent_id=self_agent_id, timeout_s=timeout_s
    )

    decision = result.get("decision")
    if decision is None:
        print(f"NO DECISION ({result.get('reason')}). Read path exercised; no mutation. (graceful timeout)")
        return
    print(
        f"DECISION: {decision} by {result.get('by')} "
        f"(human sender_type={result.get('human_sender_type')!r}, msg={result.get('message_id')})"
    )
    print(f"[STUB] would execute {decision} for proposal {proposal_id} — NO mutation performed (dry-run).")


if __name__ == "__main__":
    asyncio.run(main())
