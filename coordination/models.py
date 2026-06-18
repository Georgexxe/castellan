"""
Castellan — shared coordination data models (AGENTS.md §1).

M1 introduces only the finding-related models (Finding, FindingClass, Severity), since
the Scanner is the only agent that exists. Contribution / Constraint / BoardState arrive
with the Controller and specialists in later milestones (M2/M3), per build-order discipline.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class FindingClass(str, Enum):
    """Drives which specialist the Controller activates — classify precisely."""

    IAM = "iam"
    NETWORK = "network"
    DATA = "data"


class Severity(str, Enum):
    LOW = "low"
    MED = "med"
    HIGH = "high"
    CRITICAL = "critical"


class Finding(BaseModel):
    """One normalized misconfiguration. Emitted by the Scanner, one per message to @Controller."""

    finding_id: str
    cls: FindingClass
    severity: Severity
    resource: str  # e.g. "arn:aws:s3:::acme-public"
    description: str
    raw_evidence: dict
