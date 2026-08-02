"""Reviewer envelope circuit-breaker state machine (Wave 4 of REVIEWER-ENVELOPE-001).

Per plan §7 (lines 934-1032) the circuit-breaker tracks consecutive
envelope-parse failures per (epic_id, agent_family) tuple, trips at
N=2, and persists state to the Execution Ledger as a
circuit_breaker_state artifact keyed on epic_id (Claude Agent SDK has
no long-lived in-process orchestrator, so in-memory state is lost
across spawns).

The W4 RED phase ships only the dataclass + function stubs; bodies
raise NotImplementedError until the GREEN phase lands the lifecycle
logic. The dataclass IS fully populated so tests may construct
expected state values for assertion purposes.

Lifecycle invariants (Req-016 / Req-017 / G-3 R2 / S-5):

- Successful parse resets failure_counts[family] to 0.
- Failed parse increments failure_counts[family] by 1.
- On N=2 hit: family added to BOTH tripped_families AND
  cb_legacy_fallback_families; orchestrator_tier set to high
  (sticky for the rest of the epic per Req-017).
- After trip, envelope-absence on that family is degraded fallback
  rather than further CB increment (G-3 R2 spin-loop guard).
- Output excerpt redacted before ledger write (S-5 secret-pattern
  strip; fail-closed on regex error).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from datetime import UTC, datetime
from typing import Literal

# ---------------------------------------------------------------------------
# Module-scope constants
# ---------------------------------------------------------------------------

#: Trip threshold for the circuit-breaker (plan §7.1).
_TRIP_THRESHOLD: int = 2

#: Default truncation budget for the redacted output excerpt (plan §7.3).
_DEFAULT_REDACTION_MAX_CHARS: int = 1000

#: Common-secret-pattern regex (plan §7.3 lines 990-995). Matches
#: assignments such as ``api_key=...`` / ``token: "..."`` / ``Bearer ...``
#: where the value is at least 16 characters of base64-ish text.
_SECRET_ASSIGN_RE: re.Pattern[str] = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|bearer|aws_[a-z_]*key)"
    r"\s*[:=]?\s*[\"']?[A-Za-z0-9+/=_-]{16,}",
)

#: Env-var-like assignments (plan §7.3 lines 990-995). Catches
#: GitHub PATs (``ghp_...``), Stripe-style ``sk_...``, etc.
_ENVVAR_TOKEN_RE: re.Pattern[str] = re.compile(
    r"(?i)(SK|GHP|GHS|PAT)_[A-Za-z0-9]{20,}",
)

#: Sentinel inserted by :func:`redact_output_excerpt` for any matched
#: secret-shaped substring.
_REDACTED_SENTINEL: str = "<REDACTED>"


@dataclass(frozen=True)
class CircuitBreakerState:
    """Persisted circuit-breaker state for one epic (plan §7.2).

    Mirrors the ledger artifact body shape for the
    circuit_breaker_state artifact type. The artifact is keyed on
    (epic_id, artifact_type=circuit_breaker_state); successive writes
    overwrite the prior record (latest wins).

    :ivar epic_id: Owning epic identifier; the ledger key.
    :ivar failure_counts: Per-family consecutive-failure counter.
        Resets to 0 on a successful parse for that family.
    :ivar tripped_families: Set of families that have hit N=2 at
        least once during this epic (audit trail; never cleared).
    :ivar cb_legacy_fallback_families: G-3 R2 set - families removed
        from MIGRATED_AGENT_FAMILIES allowlist for the rest of the
        epic. Subsequent envelope-absence is degraded fallback (no
        further CB increment).
    :ivar orchestrator_tier: Starts at medium; upgrades to high on
        first trip and stays (Req-017).
    :ivar last_updated_at: ISO 8601 UTC; for retrospective metrics.
    :ivar schema_version: Bumped on shape change; default 2 (G-3 R2
        added cb_legacy_fallback_families field; the introductory
        version is 2 - no v1 artifacts exist anywhere).
    """

    epic_id: str
    failure_counts: dict[str, int] = field(default_factory=dict)
    tripped_families: frozenset[str] = field(default_factory=frozenset)
    cb_legacy_fallback_families: frozenset[str] = field(default_factory=frozenset)
    orchestrator_tier: Literal["medium", "high"] = "medium"
    last_updated_at: str = ""
    schema_version: int = 2

    def __post_init__(self) -> None:
        """Pin the minimum schema version (2 - introductory release).

        Per plan §7.2 migration note (Round 3 V3-N02 / MINOR-1):
        the introductory schema version is 2; no v1 artifacts exist
        anywhere so no migration shim is needed. Reject explicit
        construction with schema_version less than 2 to catch
        downgrade-by-mistake during the W4 GREEN implementation.
        """
        if self.schema_version < 2:
            msg = f"CircuitBreakerState.schema_version must be at least 2 (introductory release); got {self.schema_version}"
            raise ValueError(msg)


def record_parse_failure(
    state: CircuitBreakerState,
    agent_family: str,
    *,
    output_excerpt: str | None = None,
    parse_error_message: str | None = None,
    now: str | None = None,
) -> CircuitBreakerState:
    """Increment the failure counter for agent_family; trip at N=2.

    Returns a NEW CircuitBreakerState (frozen dataclass; never
    mutates the input). When the post-increment counter equals 2
    AND the family is not already in tripped_families, this:

    - Adds the family to tripped_families.
    - Adds the family to cb_legacy_fallback_families (G-3 R2).
    - Sets orchestrator_tier to high (sticky per Req-017).

    The optional output_excerpt is redacted via
    redact_output_excerpt before being persisted; the redacted
    text and the redaction_applied flag are surfaced on the
    design_decision ledger artifact emitted alongside the trip.

    G-3 R2 spin-loop guard: post-trip the counter is capped at the
    trip threshold; calling this function again on a tripped family
    does NOT continue to grow the counter indefinitely. The
    parser's :func:`_current_migrated_families` already removes
    tripped families from the migration allowlist so the typical
    next-spawn-after-trip code path is degraded fallback (no
    further CB increment), but this cap defends against a buggy
    caller that ignores the fallback path.
    """
    # output_excerpt and parse_error_message are accepted for
    # forward-compat with the orchestrator's design_decision artifact
    # emission. The merge / CB module itself does not surface them on
    # the CircuitBreakerState; redaction happens at the caller via
    # :func:`redact_output_excerpt`. Validate redaction here when an
    # excerpt was supplied so a regex blowup at orchestration time is
    # caught early.
    if output_excerpt is not None:
        redact_output_excerpt(output_excerpt)
    new_counts = dict(state.failure_counts)
    current = new_counts.get(agent_family, 0)
    new_count = min(current + 1, _TRIP_THRESHOLD)
    new_counts[agent_family] = new_count
    new_tripped = state.tripped_families
    new_legacy = state.cb_legacy_fallback_families
    new_tier: Literal["medium", "high"] = state.orchestrator_tier
    if new_count >= _TRIP_THRESHOLD and agent_family not in state.tripped_families:
        new_tripped = frozenset(state.tripped_families | {agent_family})
        new_legacy = frozenset(state.cb_legacy_fallback_families | {agent_family})
        new_tier = "high"
    timestamp = now if now is not None else _now_iso()
    return dc_replace(
        state,
        failure_counts=new_counts,
        tripped_families=new_tripped,
        cb_legacy_fallback_families=new_legacy,
        orchestrator_tier=new_tier,
        last_updated_at=timestamp,
    )


def record_parse_success(
    state: CircuitBreakerState,
    agent_family: str,
    *,
    now: str | None = None,
) -> CircuitBreakerState:
    """Reset the failure counter for agent_family to 0 (Req-017).

    Returns a NEW CircuitBreakerState. orchestrator_tier is NEVER
    downgraded - once tripped, the high tier is sticky for the
    rest of the epic per Req-017 (a single transient parse success
    does not prove the underlying issue is fixed).
    """
    new_counts = dict(state.failure_counts)
    new_counts[agent_family] = 0
    timestamp = now if now is not None else _now_iso()
    return dc_replace(
        state,
        failure_counts=new_counts,
        last_updated_at=timestamp,
    )


def to_ledger_artifact(state: CircuitBreakerState) -> dict[str, object]:
    """Serialize state to the §7.2 ledger artifact body shape.

    Output shape (plan §7.2 lines 960-973):

      artifact_type: circuit_breaker_state
      epic_id: state.epic_id
      schema_version: 2
      body:
        failure_counts: state.failure_counts
        tripped_families: sorted list of state.tripped_families
        cb_legacy_fallback_families: sorted list
        orchestrator_tier: state.orchestrator_tier
        last_updated_at: state.last_updated_at

    Sorted list serialization keeps the JSON output deterministic
    across re-serializations (sets are unordered).
    """
    body: dict[str, object] = {
        "failure_counts": dict(state.failure_counts),
        "tripped_families": sorted(state.tripped_families),
        "cb_legacy_fallback_families": sorted(state.cb_legacy_fallback_families),
        "orchestrator_tier": state.orchestrator_tier,
        "last_updated_at": state.last_updated_at,
    }
    return {
        "artifact_type": "circuit_breaker_state",
        "epic_id": state.epic_id,
        "schema_version": state.schema_version,
        "body": body,
    }


def from_ledger_artifact(payload: dict[str, object]) -> CircuitBreakerState:
    """Reconstruct CircuitBreakerState from a ledger artifact body.

    Inverse of to_ledger_artifact. Reading on every orchestrator
    spawn is the load-bearing path that bridges the in-memory
    statelessness of the Claude Agent SDK to the persisted state
    machine semantics required by Req-016.
    """
    artifact_type = payload.get("artifact_type")
    if artifact_type != "circuit_breaker_state":
        msg = f"unexpected artifact_type {artifact_type!r}; expected 'circuit_breaker_state'"
        raise ValueError(msg)
    schema_version_raw = payload.get("schema_version")
    if not isinstance(schema_version_raw, int) or schema_version_raw < 2:
        msg = f"schema_version must be an int >= 2; got {schema_version_raw!r}"
        raise ValueError(msg)
    epic_id_raw = payload.get("epic_id")
    if not isinstance(epic_id_raw, str):
        msg = f"epic_id must be a string; got {type(epic_id_raw).__name__}"
        raise ValueError(msg)
    body = payload.get("body")
    if not isinstance(body, dict):
        msg = f"body must be a dict; got {type(body).__name__}"
        raise ValueError(msg)
    failure_counts_raw = body.get("failure_counts", {})
    if not isinstance(failure_counts_raw, dict):
        msg = f"body.failure_counts must be a dict; got {type(failure_counts_raw).__name__}"
        raise ValueError(msg)
    tripped_raw = body.get("tripped_families", [])
    if not isinstance(tripped_raw, list):
        msg = f"body.tripped_families must be a list; got {type(tripped_raw).__name__}"
        raise ValueError(msg)
    legacy_raw = body.get("cb_legacy_fallback_families", [])
    if not isinstance(legacy_raw, list):
        msg = f"body.cb_legacy_fallback_families must be a list; got {type(legacy_raw).__name__}"
        raise ValueError(msg)
    tier_raw = body.get("orchestrator_tier", "medium")
    if tier_raw not in {"medium", "high"}:
        msg = f"body.orchestrator_tier must be 'medium' or 'high'; got {tier_raw!r}"
        raise ValueError(msg)
    last_updated_raw = body.get("last_updated_at", "")
    if not isinstance(last_updated_raw, str):
        msg = f"body.last_updated_at must be a string; got {type(last_updated_raw).__name__}"
        raise ValueError(msg)
    return CircuitBreakerState(
        epic_id=epic_id_raw,
        failure_counts={str(k): int(v) for k, v in failure_counts_raw.items()},
        tripped_families=frozenset(str(name) for name in tripped_raw),
        cb_legacy_fallback_families=frozenset(str(name) for name in legacy_raw),
        orchestrator_tier=tier_raw,
        last_updated_at=last_updated_raw,
        schema_version=schema_version_raw,
    )


def redact_output_excerpt(
    raw: str | None,
    *,
    max_chars: int = _DEFAULT_REDACTION_MAX_CHARS,
) -> tuple[str, bool]:
    """Redact secret-shaped substrings from a reviewer output excerpt (S-5).

    Returns (redacted_text, redaction_applied). Strategy per plan
    §7.3 step 1 lines 990-995:

    - Truncate to first max_chars characters.
    - Apply (case-insensitive) regex strip of common secret
      patterns: api_key, secret, token, password, bearer,
      aws_*_key followed by a 16+ char value.
    - Strip env-var-like assignments matching SK / GHP / GHS / PAT
      followed by 20+ alphanumeric characters.
    - On any redaction failure (regex error etc.), fail-closed:
      return an empty string with redaction_applied=True so the
      caller stores ONLY the parse error message and the
      agent_family on the artifact body (the raw excerpt is
      dropped entirely).
    """
    if raw is None or raw == "":
        # None means the caller had no excerpt to surface; treat as a
        # fail-closed signal so the artifact body omits the excerpt.
        # Empty string is similarly degenerate.
        return "", True
    truncated = raw[:max_chars]
    try:
        first_pass, count_secret = _SECRET_ASSIGN_RE.subn(
            _REDACTED_SENTINEL,
            truncated,
        )
        second_pass, count_envvar = _ENVVAR_TOKEN_RE.subn(
            _REDACTED_SENTINEL,
            first_pass,
        )
    except re.error:
        # Fail-closed: regex blowup means we cannot prove the redaction
        # is complete; drop the raw excerpt entirely.
        return "", True
    redaction_applied = (count_secret + count_envvar) > 0
    return second_pass, redaction_applied


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 second-precision string.

    The circuit-breaker's ``last_updated_at`` field is a string, not a
    datetime, so the ledger artifact body remains JSON-serializable
    without a custom encoder. Tests pass an explicit ``now`` to keep
    results deterministic; this helper is the runtime default.
    """
    return datetime.now(UTC).isoformat(timespec="seconds")
