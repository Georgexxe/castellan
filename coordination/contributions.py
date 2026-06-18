"""
Contribution parsing + the Risk gate's deterministic fail-closed floor (M3).

Pure, deterministic, no Band/SDK imports — unit-testable in isolation. Keeps `board.py` untouched.

- `parse_contributions_from_messages(messages)` → latest PROPOSAL per case (keyed by the
  `[case:cls:resource]` marker in the message), ordered by `inserted_at` (last wins). So a newer
  `good_s3` supersedes a stale `bad_s3`, and a newer proposal for a *different* case never bleeds
  into this one (per-case segregation).
- `structural_violations(contribution)` → the two Amendment-2 conditions, scanning ONLY the
  proposed `fix` + rollback presence (never the diagnosis / evidence-of-the-problem).
"""

from __future__ import annotations

import json
import re

from coordination.models import Contribution

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)
_CASE_RE = re.compile(r"\[case:([^\]]+)\]")  # captures "cls:resource"


def _content(msg) -> str:
    if isinstance(msg, dict):
        return msg.get("content") or ""
    return getattr(msg, "content", None) or ""


def _inserted_at(msg) -> str:
    if isinstance(msg, dict):
        return msg.get("inserted_at") or ""
    return getattr(msg, "inserted_at", None) or ""


def _as_list(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _case_key_from_content(content: str) -> str | None:
    m = _CASE_RE.search(content or "")
    return m.group(1).strip() if m else None


def parse_contribution(content: str) -> Contribution | None:
    """Parse the first fenced JSON block that validates as a Contribution (any type)."""
    for m in _FENCE_RE.finditer(content or ""):
        try:
            data = json.loads(m.group(1).strip())
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            return Contribution(**data)
        except Exception:
            continue
    return None


def parse_contributions_from_messages(messages) -> dict[str, Contribution]:
    """Return the latest PROPOSAL Contribution per case_key (cls:resource), by inserted_at.

    A message qualifies only if it carries a `[case:cls:resource]` marker AND a fenced block that
    validates as a `type="proposal"` Contribution. Diagnoses/dependencies are ignored.
    """
    latest: dict[str, tuple] = {}  # case_key -> (order_key, Contribution)
    for idx, m in enumerate(messages):
        content = _content(m)
        case_key = _case_key_from_content(content)
        if case_key is None:
            continue
        contrib = parse_contribution(content)
        if contrib is None or contrib.type != "proposal":
            continue
        order_key = (_inserted_at(m), idx)  # ISO timestamps sort chronologically; idx breaks ties
        if case_key not in latest or order_key > latest[case_key][0]:
            latest[case_key] = (order_key, contrib)
    return {ck: c for ck, (_ok, c) in latest.items()}


def latest_proposal(messages) -> tuple[str, Contribution] | None:
    """The single most-recent proposal across all cases — the one Risk was just activated on.

    Returns (case_key, Contribution) or None. Used by the Risk tool to pick the proposal to judge
    (newest wins); per-case segregation still holds because the case_key travels with it.
    """
    best = None  # (order_key, case_key, Contribution)
    for idx, m in enumerate(messages):
        content = _content(m)
        case_key = _case_key_from_content(content)
        if case_key is None:
            continue
        contrib = parse_contribution(content)
        if contrib is None or contrib.type != "proposal":
            continue
        order_key = (_inserted_at(m), idx)
        if best is None or order_key > best[0]:
            best = (order_key, case_key, contrib)
    return (best[1], best[2]) if best else None


def _iter_statements(obj):
    """Yield IAM-Statement-like dicts (have Action or Resource) anywhere inside *obj*."""
    if isinstance(obj, dict):
        if "Action" in obj or "Resource" in obj:
            yield obj
        for v in obj.values():
            yield from _iter_statements(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_statements(item)


def _fix_has_orgwide_wildcard(fix) -> bool:
    """True if the proposed fix grants Action '*' on Resource '*', or iam:PassRole on '*'.

    Scans ONLY the fix's params (where a proposed IAM policy document lives) — never a diagnosis.
    """
    if fix is None:
        return False
    for stmt in _iter_statements(getattr(fix, "params", None) or {}):
        resources = _as_list(stmt.get("Resource"))
        if not any(r == "*" for r in resources):
            continue
        for a in _as_list(stmt.get("Action")):
            if a == "*" or (isinstance(a, str) and a.lower() == "iam:passrole"):
                return True
    return False


def structural_violations(contribution: Contribution) -> list[str]:
    """The deterministic fail-closed floor (Amendment 2). Scans ONLY the fix + rollback presence.

    Returns a list of violated structural conditions (empty = clean). Exactly two conditions:
      1. org-wide wildcard privilege in the proposed fix
      2. rollback missing or empty
    Semantic rules (widens exposure, weakens encryption, prod-data scoping) are NOT here — they
    stay LLM-judged. The floor is intentionally narrow so it cannot false-block a clean fix.
    """
    violations: list[str] = []
    if _fix_has_orgwide_wildcard(contribution.fix):
        violations.append(
            "org-wide wildcard privilege in fix (Action '*' on Resource '*', or iam:PassRole on '*')"
        )
    rollback = contribution.rollback
    if rollback is None or not (getattr(rollback, "action", "") or "").strip():
        violations.append("rollback missing or empty")
    return violations
