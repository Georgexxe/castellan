"""
Seed the three demo misconfigurations into LocalStack (BUILD_PLAN M1 / ARCHITECTURE §7):

  C-7  data    : public S3 bucket            -> acme-public-data
  C-12 iam     : over-permissive IAM role    -> acme-admin-role  (Action/Resource "*")
  C-19 network : security group open 0.0.0.0/0 on port 22

Idempotent: re-running tolerates already-existing resources. Returns an inventory of
(resource_type, resource_id) pairs the Scanner can enumerate and describe.

Run directly:  cd castellan && uv run python -m cloud.seed
"""

from __future__ import annotations

import json
import logging

from botocore.exceptions import ClientError

from cloud.client import get_client

log = logging.getLogger("castellan.cloud.seed")

BUCKET_NAME = "acme-public-data"
ROLE_NAME = "acme-admin-role"
SG_NAME = "acme-open-ssh-sg"


def _seed_public_bucket() -> dict:
    s3 = get_client("s3")
    try:
        s3.create_bucket(Bucket=BUCKET_NAME)
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise

    # Remove the public-access-block guardrail so the bucket can actually be public.
    s3.put_public_access_block(
        Bucket=BUCKET_NAME,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": False,
            "IgnorePublicAcls": False,
            "BlockPublicPolicy": False,
            "RestrictPublicBuckets": False,
        },
    )
    # Wide-open read policy = the misconfiguration.
    public_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PublicRead",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{BUCKET_NAME}/*",
            }
        ],
    }
    s3.put_bucket_policy(Bucket=BUCKET_NAME, Policy=json.dumps(public_policy))
    return {"resource_type": "s3_bucket", "resource_id": BUCKET_NAME}


def _seed_overpermissive_role() -> dict:
    iam = get_client("iam")
    assume = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    try:
        iam.create_role(RoleName=ROLE_NAME, AssumeRolePolicyDocument=json.dumps(assume))
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
    # Inline admin-everything policy = the misconfiguration.
    star_policy = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}],
    }
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="admin-all",
        PolicyDocument=json.dumps(star_policy),
    )
    return {"resource_type": "iam_role", "resource_id": ROLE_NAME}


def _seed_open_security_group() -> dict:
    ec2 = get_client("ec2")
    # Use the default VPC LocalStack provisions.
    vpcs = ec2.describe_vpcs().get("Vpcs", [])
    vpc_id = vpcs[0]["VpcId"] if vpcs else None

    # Reuse the SG if it already exists.
    existing = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [SG_NAME]}]
    ).get("SecurityGroups", [])
    if existing:
        group_id = existing[0]["GroupId"]
    else:
        kwargs = {"GroupName": SG_NAME, "Description": "Demo SG open to the world on SSH"}
        if vpc_id:
            kwargs["VpcId"] = vpc_id
        group_id = ec2.create_security_group(**kwargs)["GroupId"]

    try:
        ec2.authorize_security_group_ingress(
            GroupId=group_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                }
            ],
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "InvalidPermission.Duplicate":
            raise
    return {"resource_type": "security_group", "resource_id": group_id}


def seed_all() -> list[dict]:
    """Seed all three misconfigurations and return the resource inventory."""
    inventory = [
        _seed_public_bucket(),
        _seed_overpermissive_role(),
        _seed_open_security_group(),
    ]
    return inventory


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    inv = seed_all()
    print("Seeded inventory:")
    print(json.dumps(inv, indent=2))
