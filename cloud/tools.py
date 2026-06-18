"""
LangChain tools exposed to the Scanner (LangGraph adapter → additional_tools, SDK_NOTES §5).

The Scanner LLM is given a SINGLE tool — `cloud_scan_and_emit_findings` — which scans the
cloud target AND posts each finding to the Controller itself, deterministically, via the Band
REST client (connection.poster). Detection + formatting + delivery all happen in code, so the
LLM never authors JSON, never calls band_send_message, and a Featherless hiccup can at worst
mean "tool not triggered" — never a partial or corrupted finding in the room.

The room id is obtained from the injected LangGraph RunnableConfig (configurable.thread_id ==
room_id), so the tool can post to the correct room without the LLM supplying it.

The read-only cloud_describe / cloud_list_resources / cloud_scan_findings tools remain defined
(used internally, and available for future agents) but are NOT in SCANNER_TOOLS.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from cloud.describe import cloud_describe as _cloud_describe
from cloud.describe import list_resources as _list_resources
from cloud.scan import scan_findings as _scan_findings


@tool
async def cloud_scan_and_emit_findings(config: RunnableConfig) -> str:
    """Scan the cloud target and deliver every finding to the Controller in this room.

    Call this ONCE when asked to scan. It performs detection AND posts the findings itself
    (one message per finding, addressed to the Controller). You do NOT need to send any message
    yourself or write any JSON — delivery is handled in code. Returns a one-line summary.
    """
    # Imported lazily so importing this module never pulls in the REST client unnecessarily.
    from connection.poster import post_findings_to_controller

    room_id = ((config or {}).get("configurable") or {}).get("thread_id")
    if not room_id:
        return "ERROR: could not determine the room id from context; no findings posted."
    try:
        result = await post_findings_to_controller(room_id)
    except Exception as e:  # surface a concise reason to the agent log; do not crash the turn
        return f"ERROR posting findings: {e}"
    return (
        f"Posted {result['posted']} finding(s) to {result['controller_handle']} "
        f"(message ids: {result['message_ids']})."
    )


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


# The Scanner LLM gets ONLY the deterministic scan+deliver tool (it triggers; code delivers).
SCANNER_TOOLS = [cloud_scan_and_emit_findings]
