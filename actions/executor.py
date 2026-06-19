"""
Action Layer executor — deterministic, allowlisted, idempotent. NO LLM in the path.

register_action / apply_action / rollback_action. Reuses cloud/client.get_client (the shared
boto3→LocalStack client). Only allowlisted actions can run, each with its own build_kwargs
(target → the resource-id kwarg; IAM/bucket policy docs JSON-stringified). The allowlist lookup
GATES every getattr — an unknown action is refused before dispatch.

Idempotency is keyed on proposal_id via in-memory sets; durable idempotency (surviving a process
restart) is derived from the room's audit history, not a DB.
"""

from __future__ import annotations

import json
import logging

from cloud.client import get_client
from coordination.models import ActionSpec

log = logging.getLogger("castellan.action.executor")


class ActionError(Exception):
    """Raised for a non-allowlisted action or missing/invalid params (caught at register/dry-run)."""


def _maybe_json(v):
    """boto3 wants policy documents as JSON STRINGS — stringify a dict, pass a str through."""
    return v if isinstance(v, str) else json.dumps(v)


# --- per-action kwarg builders (target -> the resource-id kwarg; never **params-splat) ----------
def _b_put_pab(a: ActionSpec) -> dict:
    return {"Bucket": a.target, "PublicAccessBlockConfiguration": a.params["PublicAccessBlockConfiguration"]}


def _b_del_pab(a: ActionSpec) -> dict:
    return {"Bucket": a.target}


def _b_put_bucket_policy(a: ActionSpec) -> dict:
    return {"Bucket": a.target, "Policy": _maybe_json(a.params["Policy"])}


def _b_del_bucket_policy(a: ActionSpec) -> dict:
    return {"Bucket": a.target}


def _b_put_role_policy(a: ActionSpec) -> dict:
    return {
        "RoleName": a.target,
        "PolicyName": a.params["PolicyName"],
        "PolicyDocument": _maybe_json(a.params["PolicyDocument"]),
    }


def _b_del_role_policy(a: ActionSpec) -> dict:
    return {"RoleName": a.target, "PolicyName": a.params["PolicyName"]}


def _b_authorize_sg(a: ActionSpec) -> dict:
    return {"GroupId": a.target, "IpPermissions": a.params["IpPermissions"]}


def _b_revoke_sg(a: ActionSpec) -> dict:
    return {"GroupId": a.target, "IpPermissions": a.params["IpPermissions"]}


# action name -> (boto3 service, build_kwargs). The ONLY actions the executor may run.
ALLOWLIST: dict[str, tuple] = {
    "put_public_access_block": ("s3", _b_put_pab),
    "delete_public_access_block": ("s3", _b_del_pab),
    "put_bucket_policy": ("s3", _b_put_bucket_policy),
    "delete_bucket_policy": ("s3", _b_del_bucket_policy),
    "put_role_policy": ("iam", _b_put_role_policy),
    "delete_role_policy": ("iam", _b_del_role_policy),
    "authorize_security_group_ingress": ("ec2", _b_authorize_sg),
    "revoke_security_group_ingress": ("ec2", _b_revoke_sg),
}

# In-memory state (proposal_id-keyed). Durable persistence is an M5 concern.
_REGISTRY: dict[str, dict] = {}
_APPROVED: set[str] = set()
_APPLIED: set[str] = set()
_ROLLEDBACK: set[str] = set()


def _validate(a: ActionSpec) -> None:
    """Allowlist-gate + dry-run build_kwargs (no execution). Raises ActionError if not allowed/bad."""
    if a is None:
        raise ActionError("missing ActionSpec")
    if a.action not in ALLOWLIST:  # GATE — before any getattr
        raise ActionError(f"action not allowlisted: {a.action!r}")
    _service, build = ALLOWLIST[a.action]
    try:
        build(a)
    except KeyError as e:
        raise ActionError(f"missing param {e} for action {a.action!r}") from e


def _execute(a: ActionSpec) -> dict:
    if a.action not in ALLOWLIST:  # GATE — never getattr on an unvalidated string
        raise ActionError(f"action not allowlisted: {a.action!r}")
    service, build = ALLOWLIST[a.action]
    client = get_client(service)
    kwargs = build(a)
    log.info("executing %s on %s (%s)", a.action, a.target, service)
    getattr(client, a.action)(**kwargs)
    return {"action": a.action, "target": a.target, "service": service}


def register_action(
    fix: ActionSpec, rollback: ActionSpec | None, requires_human: bool, proposal_id: str
) -> str:
    """Dry-run validate fix (+rollback) against the allowlist, store, return action_id (=proposal_id).
    Does NOT apply anything."""
    _validate(fix)
    if rollback is not None:
        _validate(rollback)
    _REGISTRY[proposal_id] = {"fix": fix, "rollback": rollback, "requires_human": requires_human}
    log.info(
        "registered action %s (fix=%s, rollback=%s, requires_human=%s)",
        proposal_id, fix.action, rollback.action if rollback else None, requires_human,
    )
    return proposal_id


def record_approval(action_id: str) -> None:
    """Record a human approval (called by the driver on a human APPROVE) — gates apply_action."""
    if action_id not in _REGISTRY:
        raise ActionError(f"unknown action_id: {action_id}")
    _APPROVED.add(action_id)


def apply_action(action_id: str) -> dict:
    """Apply the registered fix. Refuses without a recorded human approval (when requires_human).
    Idempotent on action_id: a second call is a no-op."""
    reg = _REGISTRY.get(action_id)
    if reg is None:
        raise ActionError(f"unknown action_id: {action_id}")
    if reg["requires_human"] and action_id not in _APPROVED:
        return {"status": "refused", "reason": "human approval required and not recorded", "action_id": action_id}
    if action_id in _APPLIED:  # idempotency guard (covers non-idempotent actions like delete)
        return {"status": "already_applied", "action_id": action_id}
    result = _execute(reg["fix"])
    _APPLIED.add(action_id)
    return {"status": "applied", "action_id": action_id, **result}


def rollback_action(action_id: str) -> dict:
    """Apply the registered rollback. Idempotent on action_id."""
    reg = _REGISTRY.get(action_id)
    if reg is None:
        raise ActionError(f"unknown action_id: {action_id}")
    if reg["rollback"] is None:
        return {"status": "no_rollback", "action_id": action_id}
    if action_id in _ROLLEDBACK:  # idempotency guard
        return {"status": "already_rolled_back", "action_id": action_id}
    result = _execute(reg["rollback"])
    _ROLLEDBACK.add(action_id)
    return {"status": "rolled_back", "action_id": action_id, **result}
