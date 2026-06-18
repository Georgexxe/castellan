"""
Deterministic, read-only finding detection (M1).

`scan_findings()` enumerates resources (via cloud.describe.list_resources), inspects each
(via cloud.describe.cloud_describe), and builds the Finding list ENTIRELY IN CODE — no LLM
classification. The Scanner LLM only relays the returned findings via band_send_message.

Detection covers exactly three misconfiguration classes, and copies values verbatim from the
cloud_describe output (an Action of "*" stays "*"):
  - data    : S3 bucket with public-access-block disabled and/or a bucket policy whose
              Statement allows Principal "*"
  - iam     : IAM role whose INLINE policy has a Statement with Action "*" AND Resource "*"
  - network : security group with an INBOUND rule from 0.0.0.0/0 covering port 22

Nothing here mutates the target. Each detected issue is validated against the shared Finding
schema (coordination.models.Finding) before being returned, and gets a stable id C-1, C-2, …
in detection order.
"""

from __future__ import annotations

import json
import os

from cloud.describe import cloud_describe, list_resources
from coordination.models import Finding, FindingClass, Severity

# Controller's namespaced Band handle (single-sourced here; scanner.py imports it). Band
# namespaces handles as "<user>/<agent>"; a bare "@Controller" does not resolve on a
# programmatic send. Override via env CONTROLLER_HANDLE.
DEFAULT_CONTROLLER_HANDLE = "@g18797056/controller"


def controller_handle() -> str:
    """Resolve the controller's full @handle (env CONTROLLER_HANDLE, else the default)."""
    return os.getenv("CONTROLLER_HANDLE", DEFAULT_CONTROLLER_HANDLE)


def _as_list(x) -> list:
    """Normalize a scalar-or-list IAM field (Action/Resource) to a list for membership tests."""
    return x if isinstance(x, list) else [x]


def _principal_is_wildcard(principal) -> bool:
    """True if an S3 policy Statement Principal is the public wildcard ("*" or {"AWS": "*"})."""
    if principal == "*":
        return True
    if isinstance(principal, dict):
        for v in principal.values():
            if v == "*" or (isinstance(v, list) and "*" in v):
                return True
    return False


def _detect_s3(resource_id: str) -> dict | None:
    d = cloud_describe("s3_bucket", resource_id)
    if d.get("error"):  # failed describe is not a finding
        return None
    policy = d.get("policy") or {}
    # Require an ACTUAL public policy statement to flag. Public-access-block being disabled is
    # a risk indicator, not proof of exposure, so it does not flag on its own (kept as evidence).
    public_stmts = [
        s
        for s in _as_list(policy.get("Statement", []))  # AWS allows a single Statement object
        if s.get("Effect") == "Allow" and _principal_is_wildcard(s.get("Principal"))
    ]
    if not public_stmts:
        return None
    return {
        "cls": FindingClass.DATA,
        "severity": Severity.HIGH,
        "resource": d.get("bucket", resource_id),
        "description": (
            f"S3 bucket '{resource_id}' is publicly exposed via a bucket policy that allows "
            "Principal '*'."
        ),
        "raw_evidence": {
            "public_access_block": d.get("public_access_block"),  # context, verbatim
            "public_policy_statements": public_stmts,            # the proof, verbatim
        },
    }


def _detect_iam(resource_id: str) -> dict | None:
    d = cloud_describe("iam_role", resource_id)
    if d.get("error"):  # failed describe is not a finding
        return None
    offending: dict = {}
    for name, doc in (d.get("inline_policies") or {}).items():
        for s in _as_list(doc.get("Statement", [])):  # AWS allows a single Statement object
            if (
                s.get("Effect") == "Allow"
                and "*" in _as_list(s.get("Action"))      # only a literal "*" matches, not "s3:*"
                and "*" in _as_list(s.get("Resource"))
            ):
                offending[name] = doc  # verbatim inline policy document
    if not offending:
        return None
    return {
        "cls": FindingClass.IAM,
        "severity": Severity.CRITICAL,
        "resource": d.get("role_name", resource_id),
        "description": (
            f"IAM role '{resource_id}' has an inline policy granting Action '*' on Resource '*'."
        ),
        "raw_evidence": {"inline_policies": offending},
    }


def _detect_sg(resource_id: str) -> dict | None:
    d = cloud_describe("security_group", resource_id)
    if d.get("error"):  # failed describe (or "not found") is not a finding
        return None
    offending: list = []
    for p in d.get("ip_permissions", []):
        fp, tp = p.get("FromPort"), p.get("ToPort")
        covers_22 = fp is not None and tp is not None and fp <= 22 <= tp
        open_world = any(r.get("CidrIp") == "0.0.0.0/0" for r in p.get("IpRanges", []))
        if covers_22 and open_world:
            offending.append(p)  # verbatim ingress rule
    if not offending:
        return None
    return {
        "cls": FindingClass.NETWORK,
        "severity": Severity.HIGH,
        "resource": d.get("group_id", resource_id),
        "description": (
            f"Security group '{resource_id}' allows inbound traffic from 0.0.0.0/0 on port 22 (SSH)."
        ),
        "raw_evidence": {"ip_permissions": offending},
    }


_DETECTORS = {
    "s3_bucket": _detect_s3,
    "iam_role": _detect_iam,
    "security_group": _detect_sg,
}


def scan_findings() -> list[dict]:
    """Enumerate + inspect every resource and return validated Finding dicts — one per real
    misconfiguration, detection done entirely in code. Read-only; never mutates the target."""
    raw: list[dict] = []
    for r in list_resources():
        detector = _DETECTORS.get(r["resource_type"])
        if detector is None:
            continue
        finding = detector(r["resource_id"])
        if finding is not None:
            raw.append(finding)

    findings: list[dict] = []
    for i, f in enumerate(raw, 1):
        # Validate + normalize through the shared schema; assign stable C-N ids in scan order.
        findings.append(Finding(finding_id=f"C-{i}", **f).model_dump(mode="json"))
    return findings


def scan_finding_messages() -> list[str]:
    """Scan and return fully-formatted, ready-to-send Band message strings — one per finding.

    PYTHON does the json.dumps and the message formatting here, so the LLM never authors or
    relays the JSON (it only forwards each returned string verbatim). Each message is:

        <controller @handle>
        <blank line>
        ```json
        { ...the Finding object... }
        ```

    so "*" and all values are preserved exactly as detected.
    """
    handle = controller_handle()
    messages: list[str] = []
    for finding in scan_findings():
        body = json.dumps(finding, indent=2)
        messages.append(f"{handle}\n\n```json\n{body}\n```")
    return messages


if __name__ == "__main__":
    for m in scan_finding_messages():
        print(m)
        print("-" * 60)
