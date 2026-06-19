"""
Castellan — shared coordination data models.

Finding/FindingClass/Severity (the Scanner's detections) and ActionSpec/Contribution/Constraint
(the proposal + policy-gate payloads).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


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


class ActionSpec(BaseModel):
    """A concrete, executable remediation step (or its rollback). boto3-shaped (AGENTS §1)."""

    action: str  # e.g. "put_public_access_block"
    target: str  # resource id/arn
    params: dict  # boto3 kwargs (may embed an IAM policy document, etc.)


class Contribution(BaseModel):
    """A specialist's contribution to a case. M3 evaluates `type="proposal"` (fix + rollback)."""

    type: Literal["diagnosis", "proposal", "dependency"]
    finding_id: str  # display-only reference; case identity is keyed by (cls, resource)
    author: str  # agent name
    diagnosis: Optional[str] = None
    fix: Optional[ActionSpec] = None
    rollback: Optional[ActionSpec] = None
    est_blast_radius: Optional[Literal["low", "med", "high"]] = None
    reversible: Optional[bool] = None
    confidence: Optional[float] = None  # 0..1
    note: Optional[str] = None


class Constraint(BaseModel):
    """The Risk/Policy gate's verdict on a proposal (AGENTS §1, §2.6). Posted to @Controller."""

    type: Literal["constraint"] = "constraint"
    finding_id: str  # display-only reference
    rule: str  # human-readable rule applied
    rationale: str
    verdict: Literal["approve", "reject"]
    invalidates_proposal: bool
