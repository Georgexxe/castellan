"""
Blackboard helpers for the Controller (M2) — pure, deterministic, no Band/SDK imports so they
are unit-testable in isolation.

Cases are keyed by (cls, resource) per AGENTS §2.2:
  - `case_key(finding)`  -> "cls:resource"          (human-readable; finding_id is display-only)
  - `case_id(finding)`   -> sha256(case_key)[:8]    (stable dedup id; robust to ARNs/slashes/"*")
Both are embedded as markers in the Controller's activation messages so re-derivation from room
history is idempotent; dedup keys on the hash (free text in messages is unreliable otherwise).
"""

from __future__ import annotations

import hashlib
import json
import re

from coordination.models import Finding

# cls → the registered Band agent display-name of the specialist that owns that class.
CLS_TO_SPECIALIST: dict[str, str] = {
    "data": "Data Specialist",
    "iam": "IAM Specialist",
    "network": "Network Specialist",
}


def _cls_str(finding: Finding) -> str:
    return finding.cls.value if hasattr(finding.cls, "value") else str(finding.cls)


def case_key(finding: Finding) -> str:
    """Human-readable case identity: 'cls:resource' (e.g. 'data:acme-public-data')."""
    return f"{_cls_str(finding)}:{finding.resource}"


def case_id(finding: Finding) -> str:
    """Stable 8-hex dedup id = sha256(case_key)[:8]. Robust to slashes/wildcards in resource."""
    return hashlib.sha256(case_key(finding).encode("utf-8")).hexdigest()[:8]


def case_markers(finding: Finding) -> str:
    """Markers embedded in an activation message: a readable one + the stable hash for dedup."""
    return f"[case:{case_key(finding)}] [case_id:{case_id(finding)}]"


def _content(msg) -> str:
    """Read a message's content whether it's a dict or a Fern ChatMessage object."""
    if isinstance(msg, dict):
        return msg.get("content") or ""
    return getattr(msg, "content", None) or ""


# A fenced code block, optionally tagged ```json. Finds the block regardless of any leading
# @mention prefix or surrounding prose (the Scanner posts "@controller\n\n```json ... ```").
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)
_CASE_ID_RE = re.compile(r"\[case_id:([0-9a-f]{8})\]")


def extract_json_blocks(content: str) -> list[str]:
    """Return the inner text of every fenced code block in *content* (mention prefix ignored)."""
    return [m.group(1).strip() for m in _FENCE_RE.finditer(content or "")]


def parse_finding(content: str) -> Finding | None:
    """Parse the first fenced JSON block that validates as a Finding (preserving values like '*')."""
    for block in extract_json_blocks(content):
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            return Finding(**data)
        except Exception:
            continue
    return None


def parse_findings_from_messages(messages) -> dict[str, Finding]:
    """Derive cases from room history, content-based (any message whose fenced block validates as a
    Finding). Keyed by `case_key`; first finding per key wins. Content-based parsing is deliberate:
    it does NOT depend on a brittle sender display-name match, so a renamed Scanner can't silently
    yield zero findings. (The Controller's own activation messages contain markers, not a Finding
    block, so they are naturally excluded.)"""
    cases: dict[str, Finding] = {}
    for m in messages:
        finding = parse_finding(_content(m))
        if finding is None:
            continue
        key = case_key(finding)
        if key not in cases:
            cases[key] = finding
    return cases


def already_routed_ids(messages) -> set[str]:
    """Set of case_id hashes already activated, read from `[case_id:<hash>]` markers in history.
    Only the Controller emits these markers, so author-matching is unnecessary."""
    routed: set[str] = set()
    for m in messages:
        routed.update(_CASE_ID_RE.findall(_content(m)))
    return routed
