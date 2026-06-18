"""
Read-only cloud inspection (AGENTS.md §3): `cloud_describe(resource_type, resource_id)`.

Plus `list_resources()` — a thin enumerator so the Scanner can discover what to inspect
during a scan. Both are read-only; nothing here mutates the target (that is the Action Layer,
M4). Returns plain JSON-serializable dicts.
"""

from __future__ import annotations

import json
import logging

from botocore.exceptions import ClientError

from cloud.client import get_client

log = logging.getLogger("castellan.cloud.describe")


def _describe_s3_bucket(bucket: str) -> dict:
    s3 = get_client("s3")
    out: dict = {"bucket": bucket}

    try:
        pab = s3.get_public_access_block(Bucket=bucket)
        out["public_access_block"] = pab["PublicAccessBlockConfiguration"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchPublicAccessBlockConfiguration":
            out["public_access_block"] = None  # no block configured at all = wide open
        else:
            raise

    try:
        out["policy"] = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchBucketPolicy", "NoSuchBucket"):
            out["policy"] = None
        else:
            raise

    return out


def _describe_iam_role(role_name: str) -> dict:
    iam = get_client("iam")
    out: dict = {"role_name": role_name}

    role = iam.get_role(RoleName=role_name)["Role"]
    out["assume_role_policy"] = role.get("AssumeRolePolicyDocument")

    inline_names = iam.list_role_policies(RoleName=role_name).get("PolicyNames", [])
    out["inline_policies"] = {
        name: iam.get_role_policy(RoleName=role_name, PolicyName=name)["PolicyDocument"]
        for name in inline_names
    }
    out["attached_policies"] = [
        p["PolicyArn"]
        for p in iam.list_attached_role_policies(RoleName=role_name).get("AttachedPolicies", [])
    ]
    return out


def _describe_security_group(group_id: str) -> dict:
    ec2 = get_client("ec2")
    groups = ec2.describe_security_groups(GroupIds=[group_id]).get("SecurityGroups", [])
    if not groups:
        return {"group_id": group_id, "error": "not found"}
    sg = groups[0]
    return {
        "group_id": group_id,
        "group_name": sg.get("GroupName"),
        "ip_permissions": sg.get("IpPermissions", []),
    }


_DESCRIBERS = {
    "s3_bucket": _describe_s3_bucket,
    "iam_role": _describe_iam_role,
    "security_group": _describe_security_group,
}


def cloud_describe(resource_type: str, resource_id: str) -> dict:
    """Describe the current state of one cloud resource. Read-only.

    resource_type: one of s3_bucket | iam_role | security_group
    resource_id:   bucket name | role name | security-group id
    """
    fn = _DESCRIBERS.get(resource_type)
    if fn is None:
        return {"error": f"unsupported resource_type: {resource_type}"}
    try:
        return fn(resource_id)
    except ClientError as e:
        return {"error": e.response["Error"].get("Code", "ClientError"), "message": str(e)}


def list_resources() -> list[dict]:
    """Enumerate inspectable resources currently in the target, as (resource_type, resource_id)."""
    inventory: list[dict] = []

    s3 = get_client("s3")
    for b in s3.list_buckets().get("Buckets", []):
        inventory.append({"resource_type": "s3_bucket", "resource_id": b["Name"]})

    iam = get_client("iam")
    for r in iam.list_roles().get("Roles", []):
        inventory.append({"resource_type": "iam_role", "resource_id": r["RoleName"]})

    ec2 = get_client("ec2")
    for sg in ec2.describe_security_groups().get("SecurityGroups", []):
        inventory.append({"resource_type": "security_group", "resource_id": sg["GroupId"]})

    return inventory
