"""
M4 driver — human-gated, reversible execution against LocalStack (no LLM in the action path).

Flow for a proposal (synthetic fixture in M4):
  1. register_action (dry-run validates fix + rollback against the allowlist).
  2. capture the SEEDED_BASELINE before-state and assert it (== cloud/seed.py baseline).
  3. Band human gate (round 1): you reply `@<action> APPROVE <proposal_id>` -> apply the fix;
     `DENY` -> refuse, no mutation.
  4. Band human gate (round 2): you reply `@<action> ROLLBACK <proposal_id>` -> apply the rollback.
  5. Hard reversibility assertions (good_s3 / any put_public_access_block fix):
        before == all-false (baseline);  after-apply == all-true;  after-rollback == before (byte-identical).

Usage:
    cd castellan
    uv run python scripts/run_action.py <room_id> [fixture=good_s3]
Prereqs: LocalStack up + seeded (`uv run python -m cloud.seed`); Action Layer agent registered and
added to the room (creds under ACTION_AGENT_KEY, default "action"); you act as the human approver.
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
from band.client.rest import AsyncRestClient, DEFAULT_REQUEST_OPTIONS

from actions.executor import apply_action, record_approval, register_action, rollback_action
from actions.gate import request_and_await_decision
from actions.ledger import (
    already_applied_in_room,
    already_rolled_back_in_room,
    post_action_applied,
    post_action_rolled_back,
)
from cloud.describe import cloud_describe
from connection.poster import rest_base_url
from coordination.contributions import latest_constraint_for_proposal, proposal_id
from coordination.fixtures import FIXTURES, get_fixture
from coordination.models import Contribution

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("castellan.action.run")

# Equal to cloud/seed.py _seed_public_bucket — the S3 reversibility round-trip is asserted against it.
SEEDED_BASELINE = {
    "BlockPublicAcls": False, "IgnorePublicAcls": False,
    "BlockPublicPolicy": False, "RestrictPublicBuckets": False,
}
ALL_TRUE = {k: True for k in SEEDED_BASELINE}


async def main() -> None:
    load_dotenv()
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        raise SystemExit(f"usage: uv run python scripts/run_action.py <room_id> [{' | '.join(sorted(FIXTURES))}]")
    room_id = sys.argv[1].strip()
    fixture = (sys.argv[2].strip() if len(sys.argv) > 2 else "good_s3")

    fx = get_fixture(fixture)
    contrib = Contribution(**fx["contribution"])
    case_key = f"{fx['cls']}:{fx['resource']}"
    pid = proposal_id(case_key, contrib.fix, contrib.rollback)
    aid = register_action(contrib.fix, contrib.rollback, requires_human=True, proposal_id=pid)
    print(f"registered {fixture}: case={case_key} proposal_id={pid} fix={contrib.fix.action} rollback={contrib.rollback.action if contrib.rollback else None}")

    # --- VERDICT GATE: only a Risk-APPROVED proposal may reach the human gate ---
    # The Constraint is addressed to @Controller, so we read it via the Controller's context view
    # (the action agent isn't mentioned on it). Refuse on REJECT *because of the verdict*, before
    # any human gate or mutation. (Distinct from "no verdict found" = unvetted.)
    _cid, controller_key = load_agent_config("controller")
    ctrl_client = AsyncRestClient(api_key=controller_key, base_url=rest_base_url())
    ctrl_msgs = list(
        (
            await ctrl_client.agent_api_context.get_agent_chat_context(
                chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
            )
        ).data
        or []
    )
    constraint = latest_constraint_for_proposal(ctrl_msgs, pid)
    if constraint is None:
        print(f"REFUSED: no Risk verdict found for proposal {pid} (unvetted). No mutation, no human gate.")
        return
    if constraint.verdict == "reject":
        print(
            f"REFUSED: Risk REJECTED proposal {pid} — rule: {constraint.rule}. "
            f"Not executing. No LocalStack mutation, no human gate."
        )
        return
    print(f"Risk verdict for {pid}: APPROVE (rule: {constraint.rule}) — proceeding to the human gate.")

    # Hard reversibility assertions apply to S3 public-access-block fixes (good_s3).
    is_s3_pab = contrib.fix.action == "put_public_access_block"
    bucket = contrib.fix.target

    def pab() -> dict | None:
        return cloud_describe("s3_bucket", bucket).get("public_access_block")

    before = None
    if is_s3_pab:
        before = pab()
        print("state before:", before)
        assert before == SEEDED_BASELINE, f"before != seeded baseline (run `uv run python -m cloud.seed`): {before}"

    agent_key = os.getenv("ACTION_AGENT_KEY", "action")
    self_agent_id, api_key = load_agent_config(agent_key)
    client = AsyncRestClient(api_key=api_key, base_url=rest_base_url())

    # --- DURABLE idempotency (M5): scan room history; refuse if already applied (survives restart) ---
    if await already_applied_in_room(client, room_id, pid):
        print(f"REFUSED (durable idempotency): [action_applied] for proposal {pid} already in the room. No second mutation.")
        return

    # --- Gate round 1: APPROVE -> apply fix ; DENY -> refuse ---
    r1 = await request_and_await_decision(
        client, room_id, pid,
        f"Apply fix for case {case_key}: {contrib.fix.action} on {contrib.fix.target}.",
        self_agent_id=self_agent_id, timeout_s=180,
    )
    d1 = r1.get("decision")
    if d1 == "DENY":
        print("DENY -> refusing execution. No mutation."); return
    if d1 != "APPROVE":
        print(f"no APPROVE ({r1.get('reason')}) -> nothing applied."); return

    record_approval(aid)
    apply_res = apply_action(aid)
    print("apply:", apply_res)
    after_apply = None
    if is_s3_pab:
        after_apply = pab()
        print("state after-apply:", after_apply)
        assert after_apply == ALL_TRUE, f"after-apply != all-true: {after_apply}"

    # --- In-process idempotency re-trigger (same process; module-level _APPLIED guard) ---
    # A second apply MUST short-circuit at the guard: status "already_applied", NO boto3 call,
    # state unchanged. (Durable across-restart idempotency is the room-scan above.)
    second = apply_action(aid)
    print("apply (2nd, idempotency re-trigger):", second)
    assert second["status"] == "already_applied", f"2nd apply must be a no-op (guarded): {second}"
    if is_s3_pab:
        after_second = pab()
        print("state after 2nd apply:", after_second)
        assert after_second == after_apply == ALL_TRUE, f"2nd apply changed state: {after_second}"
        print("IDEMPOTENCY (in-process) PASSED: 2nd apply -> already_applied, no boto3 call, state unchanged.")

    # --- M5: post the action_applied outcome record to the room (chain-captured) ---
    tool_call = {"action": contrib.fix.action, "target": contrib.fix.target, "params": contrib.fix.params}
    await post_action_applied(client, room_id, case_key, pid, aid, tool_call, apply_res, before, after_apply)

    # --- Gate round 2: ROLLBACK -> revert (reversibility) ---
    r2 = await request_and_await_decision(
        client, room_id, pid,
        f"Reversibility for case {case_key}: reply ROLLBACK {pid} to revert to the prior state.",
        self_agent_id=self_agent_id, timeout_s=180,
    )
    if r2.get("decision") != "ROLLBACK":
        print(f"no ROLLBACK ({r2.get('reason')}) -> fix left applied (state changed)."); return

    # --- DURABLE idempotency for rollback ---
    if await already_rolled_back_in_room(client, room_id, pid):
        print(f"REFUSED (durable idempotency): [action_rolled_back] for proposal {pid} already in the room.")
        return

    rollback_res = rollback_action(aid)
    print("rollback:", rollback_res)
    after_rollback = None
    if is_s3_pab:
        after_rollback = pab()
        print("state after-rollback:", after_rollback)
        assert after_rollback == SEEDED_BASELINE == before, f"after-rollback != baseline/before: {after_rollback}"
        print("REVERSIBILITY ASSERTION PASSED: before == after-rollback (byte-identical); apply flipped baseline -> all-true.")

    # --- M5: post the action_rolled_back outcome record (restored_matches_original from chain-resident data) ---
    rb_tool_call = (
        {"action": contrib.rollback.action, "target": contrib.rollback.target, "params": contrib.rollback.params}
        if contrib.rollback else None
    )
    restored = await post_action_rolled_back(
        client, room_id, case_key, pid, aid, rb_tool_call, rollback_res, after_apply, after_rollback
    )
    print(f"action_rolled_back posted (restored_matches_original={restored}).")


if __name__ == "__main__":
    asyncio.run(main())
