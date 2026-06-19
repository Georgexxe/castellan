"""
scripts/post_contribution.py — post a synthetic Contribution fixture into a Band room, addressed
to @Risk Policy (a testing stand-in for a live specialist's proposal).

It posts AS the Controller (simulating the Controller activating Risk after a specialist proposal):
the message carries the proposal Contribution JSON in a fenced block plus the case markers
([case:cls:resource] [case_id:<hash>], byte-identical to the Controller via board.case_markers),
and @mentions Risk Policy.

Usage:
    cd castellan
    uv run python scripts/post_contribution.py <room_id> <fixture>
      fixture in: bad_s3 | good_s3 | dangerous_iam | good_iam

Creds: Controller api_key from agent_config.yaml. Risk Policy must be a participant in the room.
"""

from __future__ import annotations

import asyncio
import json
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
from coordination.board import case_markers
from coordination.contributions import proposal_id_marker
from coordination.fixtures import FIXTURES, get_fixture
from coordination.models import Contribution

RISK_NAME = "Risk Policy"


def _attr(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


async def main() -> None:
    load_dotenv()

    if len(sys.argv) < 3 or not sys.argv[1].strip():
        raise SystemExit(
            f"usage: uv run python scripts/post_contribution.py <room_id> <{' | '.join(sorted(FIXTURES))}>"
        )
    room_id = sys.argv[1].strip()
    fixture_name = sys.argv[2].strip()
    fx = get_fixture(fixture_name)

    _cid, controller_key = load_agent_config("controller")
    client = AsyncRestClient(api_key=controller_key, base_url=rest_base_url())

    participants = (
        await client.agent_api_participants.list_agent_chat_participants(
            chat_id=room_id, request_options=DEFAULT_REQUEST_OPTIONS
        )
    ).data or []
    risk = next(
        (p for p in participants if (_attr(p, "name") or "").strip().lower() == RISK_NAME.lower()),
        None,
    )
    if risk is None:
        raise SystemExit(
            f"'{RISK_NAME}' not found in room {room_id} participants. Register it and add it to the room."
        )
    handle = _attr(risk, "handle")
    mention = ChatMessageRequestMentionsItem(id=_attr(risk, "id"), handle=handle)

    ns = SimpleNamespace(cls=fx["cls"], resource=fx["resource"])
    case_key = f"{fx['cls']}:{fx['resource']}"
    # Validate the fixture, then compute the proposal_id from the VALIDATED ActionSpecs so it
    # matches Risk's computation byte-for-byte (canonical-JSON contract).
    contrib = Contribution(**fx["contribution"])
    markers = f"{case_markers(ns)} {proposal_id_marker(case_key, contrib.fix, contrib.rollback)}"
    body = json.dumps(fx["contribution"], indent=2)
    content = (
        f"{handle} Please evaluate this proposal ({fixture_name}).\n"
        f"{markers}\n\n```json\n{body}\n```"
    )

    await client.agent_api_messages.create_agent_chat_message(
        chat_id=room_id,
        message=ChatMessageRequest(content=content, mentions=[mention]),
        request_options=DEFAULT_REQUEST_OPTIONS,
    )
    print(f"posted fixture '{fixture_name}' ({fx['cls']}:{fx['resource']}) to @{RISK_NAME} in room {room_id}")


if __name__ == "__main__":
    asyncio.run(main())
