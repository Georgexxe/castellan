"""
Castellan Mission Control — FastAPI read-bridge.

ZERO-LOGIC PASS-THROUGH. Every endpoint calls the shared `connection.audit_reader` functions (which
call the proven pure functions in `coordination.audit`) and serializes their output. This module
contains NO parsing/hashing/classification/aggregation of its own, so the UI is guaranteed to show
results byte-identical to what `scripts/audit_verify.py` computes on the CLI.

The browser NEVER holds Band creds and NEVER calls Band — all Band access happens here, server-side,
using the existing agent creds in agent_config.yaml.

Run from the repo root (so `connection`/`coordination` import):
    cd castellan
    uv run uvicorn ui.api.main:app --reload --port 8000
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(dotenv_path=_REPO_ROOT / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from coordination.audit import AuditError
from connection.audit_reader import (
    cases_overview,
    case_detail,
    cloud_state,
    latest_evidence_summary,
    reconstruct,
    summarize,
    tamper_room,
    verify_room,
)

app = FastAPI(title="Castellan Mission Control (read-bridge)", version="0.1.0")

# Pass 2's Next.js dev server origin. Read-only API; permissive for local dev only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


async def _records(room_id: str):
    """Reconstruct the chain for a room; a genuine gap is a 422 (never a 500), mirroring the CLI's
    'AUDIT INCOMPLETE — cannot certify chain' refusal."""
    try:
        return await reconstruct(room_id)
    except AuditError as e:
        raise HTTPException(status_code=422, detail=f"AUDIT INCOMPLETE — cannot certify chain: {e}")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "castellan-mission-control", "mode": "read-only"}


@app.get("/rooms/{room_id}/summary")
async def get_summary(room_id: str) -> dict:
    records = await _records(room_id)
    return summarize(records, verify_room(records, room_id))


@app.get("/rooms/{room_id}/cases")
async def get_cases(room_id: str) -> list:
    return cases_overview(await _records(room_id))


@app.get("/rooms/{room_id}/case/{case_id}")
async def get_case(room_id: str, case_id: str) -> dict:
    detail = case_detail(await _records(room_id), case_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"case {case_id} not found in room {room_id}")
    return detail


@app.get("/rooms/{room_id}/audit")
async def get_audit(room_id: str) -> dict:
    return verify_room(await _records(room_id), room_id)


@app.get("/rooms/{room_id}/tamper-demo")
async def get_tamper_demo(room_id: str) -> dict:
    records = await _records(room_id)
    anchor = verify_room(records, room_id)["anchor"]
    return tamper_room(records, anchor)


@app.get("/rooms/{room_id}/cloud-state")
async def get_cloud_state(room_id: str) -> dict:
    return cloud_state(await _records(room_id))


@app.get("/rooms/{room_id}/evidence/{case_id}")
async def get_evidence(room_id: str, case_id: str) -> dict | None:
    # Read-only, outside the audit chain. Returns null cleanly if no summary exists yet
    # (the dashboard card then shows its reserved/empty state — not an error).
    return await latest_evidence_summary(room_id, case_id)
