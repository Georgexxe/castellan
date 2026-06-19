"""
Synthetic Contribution fixtures for M3 Risk testing (no live specialist).

Each fixture carries the case `(cls, resource)` so the poster can compute byte-identical case
markers via `board.case_markers`, plus a schema-valid proposal `Contribution`. Expected outcomes:

  bad_s3        data:acme-public-data   fix present, ROLLBACK MISSING        -> floor reject
  good_s3       data:acme-public-data   scoped fix + restorative rollback    -> floor clean -> approve
  dangerous_iam iam:acme-admin-role     fix grants iam:PassRole on '*'       -> floor reject
  good_iam      iam:acme-admin-role     diagnosis names '*'/'*', fix REMOVES -> floor clean -> approve
                                        the wildcard (scoped least-privilege)

good_iam is the false-positive guard: its diagnosis describes the wildcard problem, but the floor
(and the LLM, per the system prompt) must judge the FIX — which removes it — not the diagnosis.
"""

from __future__ import annotations

# --- data case (S3 public bucket) ----------------------------------------------------------------

_BAD_S3 = {
    "type": "proposal",
    "finding_id": "C-1",
    "author": "Data Specialist",
    "diagnosis": "S3 bucket acme-public-data is public via a bucket policy that allows Principal '*'.",
    "fix": {
        "action": "put_public_access_block",
        "target": "acme-public-data",
        "params": {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            }
        },
    },
    # rollback intentionally OMITTED -> floor condition 2 fires (reject).
    "est_blast_radius": "med",
    "reversible": False,
    "confidence": 0.6,
}

_GOOD_S3 = {
    "type": "proposal",
    "finding_id": "C-1",
    "author": "Data Specialist",
    "diagnosis": "S3 bucket acme-public-data is public via a bucket policy that allows Principal '*'.",
    "fix": {
        "action": "put_public_access_block",
        "target": "acme-public-data",
        "params": {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            }
        },
    },
    # Explicit-restorative rollback: restore the SEEDED BASELINE public-access-block —
    # put_public_access_block with all four flags FALSE, byte-identical to cloud/seed.py's
    # _seed_public_bucket. Reversibility asserts all-false (baseline) -> all-true (fix) -> all-false
    # (rollback), with before == after-rollback. It restores prior state (not a new public grant):
    # NO Principal:"*" bucket policy is re-added.
    "rollback": {
        "action": "put_public_access_block",
        "target": "acme-public-data",
        "params": {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            }
        },
    },
    "est_blast_radius": "low",
    "reversible": True,
    "confidence": 0.9,
}

# --- iam case (over-permissive role) -------------------------------------------------------------

_DANGEROUS_IAM = {
    "type": "proposal",
    "finding_id": "C-2",
    "author": "IAM Specialist",
    "diagnosis": "Role acme-admin-role needs to assume EC2 roles; granting pass-role broadly.",
    "fix": {
        "action": "put_role_policy",
        "target": "acme-admin-role",
        "params": {
            "PolicyName": "passrole-anywhere",
            "PolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {"Effect": "Allow", "Action": "iam:PassRole", "Resource": "*"}
                ],
            },
        },
    },
    "rollback": {
        "action": "delete_role_policy",
        "target": "acme-admin-role",
        "params": {"PolicyName": "passrole-anywhere"},
    },
    "est_blast_radius": "high",
    "reversible": True,
    "confidence": 0.7,
}

_GOOD_IAM = {
    "type": "proposal",
    "finding_id": "C-2",
    "author": "IAM Specialist",
    # Diagnosis NAMES the wildcard problem on purpose — the floor/LLM must judge the fix, not this.
    "diagnosis": "Role acme-admin-role has an inline policy granting Action '*' on Resource '*' "
    "(org-wide admin). Replace it with least privilege.",
    "fix": {
        "action": "put_role_policy",
        "target": "acme-admin-role",
        # OVERWRITE the offending policy IN PLACE: same PolicyName ("admin-all") with a scoped
        # document, so the wildcard grant is REPLACED, not merely supplemented. IAM inline policies
        # are a union — adding a NEW-named policy would leave admin-all's '*'/'*' intact (unsafe).
        "params": {
            "PolicyName": "admin-all",
            "PolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetObject"],
                        "Resource": ["arn:aws:s3:::acme-app-data/*"],
                    }
                ],
            },
        },
    },
    # Restorative AND safe: reverse the fix by deleting the (now-scoped) admin-all policy it
    # overwrote — does NOT re-install the admin-all wildcard (Action:"*"/Resource:"*").
    "rollback": {
        "action": "delete_role_policy",
        "target": "acme-admin-role",
        "params": {"RoleName": "acme-admin-role", "PolicyName": "admin-all"},
    },
    "est_blast_radius": "low",
    "reversible": True,
    "confidence": 0.92,
}


FIXTURES: dict[str, dict] = {
    "bad_s3": {"cls": "data", "resource": "acme-public-data", "finding_id": "C-1", "contribution": _BAD_S3},
    "good_s3": {"cls": "data", "resource": "acme-public-data", "finding_id": "C-1", "contribution": _GOOD_S3},
    "dangerous_iam": {"cls": "iam", "resource": "acme-admin-role", "finding_id": "C-2", "contribution": _DANGEROUS_IAM},
    "good_iam": {"cls": "iam", "resource": "acme-admin-role", "finding_id": "C-2", "contribution": _GOOD_IAM},
}


def get_fixture(name: str) -> dict:
    if name not in FIXTURES:
        raise KeyError(f"unknown fixture '{name}'. Available: {sorted(FIXTURES)}")
    return FIXTURES[name]
