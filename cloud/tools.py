"""
LangChain tools exposed to the Scanner (LangGraph adapter → additional_tools, SDK_NOTES §5).

M1 detection AND message formatting are deterministic and live in code (cloud.scan). The
Scanner LLM is given a SINGLE tool — `cloud_scan_finding_messages` — which returns
fully-formatted, ready-to-send message strings (Python did the json.dumps). The LLM only
forwards each string verbatim via band_send_message; it never authors or relays JSON.

The read-only `cloud_describe` / `cloud_list_resources` / `cloud_scan_findings` tools remain
defined (used internally, and available for future agents) but are intentionally NOT in
SCANNER_TOOLS, to keep the Scanner's behavior deterministic on a small model.
"""

from __future__ import annotations

from langchain_core.tools import tool

from cloud.describe import cloud_describe as _cloud_describe
from cloud.describe import list_resources as _list_resources
from cloud.scan import scan_findings as _scan_findings
from cloud.scan import scan_finding_messages as _scan_finding_messages


@tool
def cloud_scan_finding_messages() -> list:
    """Scan the cloud target and return ready-to-send message strings, one per finding.

    Each returned string is already fully formatted by code: it contains the controller
    @mention on its own line, a blank line, then a fenced ```json block holding the Finding.
    Send each string back VERBATIM via band_send_message (mentioning the controller). Do NOT
    edit, reformat, summarize, or merge them, and do NOT write any JSON yourself.
    """
    return _scan_finding_messages()


@tool
def cloud_scan_findings() -> list:
    """Scan the cloud target and return the list of Finding objects (read-only, structured)."""
    return _scan_findings()


@tool
def cloud_describe(resource_type: str, resource_id: str) -> dict:
    """Describe the current state of one cloud resource (read-only).

    Args:
        resource_type: one of "s3_bucket", "iam_role", "security_group".
        resource_id: bucket name, role name, or security-group id.
    """
    return _cloud_describe(resource_type, resource_id)


@tool
def cloud_list_resources() -> list:
    """List the cloud resources available to inspect, as {resource_type, resource_id} entries."""
    return _list_resources()


# The Scanner LLM gets ONLY the deterministic, pre-formatted-message tool (plus band_*).
SCANNER_TOOLS = [cloud_scan_finding_messages]
