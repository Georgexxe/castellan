"""
scripts/scan_and_post.py — deterministic REST poster, standalone CLI.

Scans LocalStack and posts each finding to a Band room AS the Scanner via the REST client,
completely outside the LLM/LangGraph loop (no Featherless, no model). Delegates to the shared
core in connection.poster (also used by the Scanner agent's tool).

Usage (no secrets on the command line):
    cd castellan
    uv run python scripts/scan_and_post.py <room_id>

Creds: Scanner api_key from agent_config.yaml (key "scanner"). Controller handle from
CONTROLLER_HANDLE env (else the default in cloud.scan). LocalStack must be up + seeded.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Put the repo root on sys.path so `cloud` / `connection` import when run as a script.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

from connection.poster import post_findings_to_controller, rest_base_url


async def main() -> None:
    load_dotenv()

    if len(sys.argv) < 2 or not sys.argv[1].strip():
        raise SystemExit("usage: uv run python scripts/scan_and_post.py <room_id>")
    room_id = sys.argv[1].strip()

    print(f"REST base_url: {rest_base_url()}")
    result = await post_findings_to_controller(room_id)

    print(f"participants in room {room_id}:")
    for p in result["participants"]:
        print(f"  id={p['id']} handle={p['handle']!r} name={p['name']!r}")
    print(f"resolved controller -> id={result['controller_id']} handle={result['controller_handle']!r}")
    print(f"posted {result['posted']} finding message(s); ids={result['message_ids']}")
    print(f"DONE: {result['posted']} findings to {result['controller_handle']} in room {room_id}")


if __name__ == "__main__":
    asyncio.run(main())
