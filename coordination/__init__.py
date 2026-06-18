"""Castellan coordination layer: shared data models + blackboard helpers (case keying, parsing)."""

from coordination.models import (
    ActionSpec,
    Constraint,
    Contribution,
    Finding,
    FindingClass,
    Severity,
)
from coordination.board import (
    CLS_TO_SPECIALIST,
    already_routed_ids,
    case_id,
    case_key,
    case_markers,
    parse_findings_from_messages,
)
from coordination.contributions import (
    latest_proposal,
    parse_contribution,
    parse_contributions_from_messages,
    proposal_id,
    proposal_id_from_content,
    proposal_id_marker,
    structural_violations,
)

__all__ = [
    # models
    "ActionSpec",
    "Constraint",
    "Contribution",
    "Finding",
    "FindingClass",
    "Severity",
    # board (case keying / findings)
    "CLS_TO_SPECIALIST",
    "already_routed_ids",
    "case_id",
    "case_key",
    "case_markers",
    "parse_findings_from_messages",
    # contributions (proposals / risk floor / proposal identity)
    "latest_proposal",
    "parse_contribution",
    "parse_contributions_from_messages",
    "proposal_id",
    "proposal_id_from_content",
    "proposal_id_marker",
    "structural_violations",
]
