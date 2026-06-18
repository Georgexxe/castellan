"""
boto3 client factory pointed at LocalStack (primary target — free, local, deterministic).

To target a real sandbox AWS account instead, unset LOCALSTACK_URL and supply normal AWS
credentials/region; the rest of the Action Layer is identical (ARCHITECTURE §5).
"""

from __future__ import annotations

import os

import boto3

# LocalStack default edge endpoint. Override via env for a different host/port.
LOCALSTACK_URL = os.getenv("LOCALSTACK_URL", "http://localhost:4566")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def get_client(service: str):
    """Return a boto3 client for *service*, pointed at LocalStack unless LOCALSTACK_URL is empty.

    LocalStack accepts any non-empty credentials; we use the conventional dummy "test"/"test".
    """
    endpoint = LOCALSTACK_URL or None
    kwargs = {"region_name": AWS_REGION}
    if endpoint:
        kwargs.update(
            endpoint_url=endpoint,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        )
    return boto3.client(service, **kwargs)
