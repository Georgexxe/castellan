# Castellan Mission Control — read-bridge (M7 Pass 1)

A thin, **read-only** FastAPI bridge that exposes the genuine Castellan audit data to the (future)
Next.js UI. It is a **zero-logic pass-through**: every endpoint calls the shared functions in
[`connection/audit_reader.py`](../../connection/audit_reader.py) (which call the proven pure
functions in [`coordination/audit.py`](../../coordination/audit.py)) and serializes their output, so
the UI is byte-identical to what `scripts/audit_verify.py` prints on the CLI. The same module is
imported by **both** the CLI and this API — no logic is duplicated.

The browser never holds Band credentials and never calls Band. All Band access happens here,
server-side, using the agent creds in `agent_config.yaml`.

## Run

```bash
cd castellan
uv run uvicorn ui.api.main:app --reload --port 8000
```
(Run from the repo root so `connection`/`coordination` import. Deps live in the root `pyproject.toml`:
`fastapi`, `uvicorn`.)

## Endpoints (all read-only)

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/rooms/{room_id}/summary` | spine status counts + audit VALID/BREAK |
| GET | `/rooms/{room_id}/cases` | cases with lifecycle status |
| GET | `/rooms/{room_id}/case/{case_id}` | full lifecycle records for one case |
| GET | `/rooms/{room_id}/audit` | reconstructed chain (records + hashes + head) + anchor comparison |
| GET | `/rooms/{room_id}/tamper-demo` | in-memory tamper → BREAK + first broken seq |
| GET | `/rooms/{room_id}/cloud-state` | before / after-apply / after-rollback PAB (chain-resident) |

A genuine audit gap returns **422** `AUDIT INCOMPLETE — cannot certify chain` (never a 500),
mirroring the CLI's graceful refusal.

## Verified

Against room `eb4379c9-165a-4139-bc8a-dd166f8280d8`: `/audit.head ==
9f55f86d…2946919`, status VALID, 9 records; `/tamper-demo.first_broken_seq == 4`; `/summary` counts
match the CLI. Out of scope this pass: any write/execute endpoints (Pass 2), auth, DB, frontend.
