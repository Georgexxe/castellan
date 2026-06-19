"""
Deterministic remediation builder (pure; no Band/LLM/boto3).

The Data Specialist's LLM only triggers; THIS module turns real cloud evidence (a `cloud.describe`
result) into the concrete, reversible fix + rollback — and FAILS CLOSED when the evidence is not
reliable. For the seeded `acme-public-data` bucket the output's fix/rollback are byte-identical to
`coordination.fixtures._GOOD_S3`, so `proposal_id` matches the `good_s3` path.

Fail-closed contract:
  - `public_access_block is None`  -> the bucket has NO block configured; restoring the documented
    all-false seed baseline is a *valid* rollback target.
  - a well-formed PAB dict (all four bool flags) -> restore the OBSERVED prior state.
  - anything else (error key / missing key / malformed / non-dict) -> NOT reliable; the builder
    raises ValueError and the caller refuses to propose. A failed read is NEVER treated as None.
"""

from __future__ import annotations

from coordination.models import ActionSpec, Contribution

_PAB_KEYS = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")
# The documented seed baseline (cloud/seed.py _seed_public_bucket): all four flags FALSE.
_SEED_BASELINE_PAB = {k: False for k in _PAB_KEYS}
_SECURE_PAB = {k: True for k in _PAB_KEYS}


def _is_valid_pab(pab) -> bool:
    """A well-formed public-access-block: a dict with all four keys present and boolean-valued."""
    return isinstance(pab, dict) and all(
        k in pab and isinstance(pab[k], bool) for k in _PAB_KEYS
    )


def evidence_is_reliable(evidence) -> bool:
    """True only if a `cloud_describe('s3_bucket', ...)` result is trustworthy enough to act on.

    Reliable = a dict, with NO `error` key, carrying a `public_access_block` that is either
    explicitly None (no block configured) or a well-formed PAB dict. Error/timeout/malformed/
    missing-key reads are NOT reliable — the caller must refuse to propose (fail closed).
    """
    if not isinstance(evidence, dict):
        return False
    if "error" in evidence:
        return False
    if "public_access_block" not in evidence:
        return False
    pab = evidence["public_access_block"]
    return pab is None or _is_valid_pab(pab)


def build_data_remediation(cls: str, resource: str, evidence: dict, diagnosis: str = "") -> Contribution:
    """Build the canonical reversible S3 public-access remediation from real evidence.

    fix      = put_public_access_block with all four flags TRUE (block public access).
    rollback = put_public_access_block restoring the OBSERVED prior PAB; only when the bucket has no
               block configured (public_access_block is None) is the all-false seed baseline used.

    Raises ValueError on a non-data case or unreliable evidence (fail closed). `diagnosis` is the
    LLM's prose; it does NOT affect proposal_id (which is keyed on case_key + fix + rollback only).
    """
    if cls != "data":
        raise ValueError(f"build_data_remediation handles cls='data' only, got {cls!r}")
    if not evidence_is_reliable(evidence):
        raise ValueError(f"unreliable cloud evidence for {resource!r} — refusing to build a fix")

    pab = evidence["public_access_block"]
    prior = dict(_SEED_BASELINE_PAB) if pab is None else {k: bool(pab[k]) for k in _PAB_KEYS}

    fix = ActionSpec(
        action="put_public_access_block",
        target=resource,
        params={"PublicAccessBlockConfiguration": dict(_SECURE_PAB)},
    )
    rollback = ActionSpec(
        action="put_public_access_block",
        target=resource,
        params={"PublicAccessBlockConfiguration": prior},
    )
    return Contribution(
        type="proposal",
        finding_id="C-1",  # display-only; case identity is (cls, resource), not this
        author="Data Specialist",
        diagnosis=(
            diagnosis
            or f"S3 bucket {resource} is publicly exposed; enabling the public-access block "
            f"(all four flags) removes public access. Reversible to the prior block state."
        ),
        fix=fix,
        rollback=rollback,
        est_blast_radius="low",
        reversible=True,
        confidence=0.9,
    )
