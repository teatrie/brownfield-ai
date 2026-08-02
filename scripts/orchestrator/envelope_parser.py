"""Reviewer Output Envelope parser (Wave 1 of REVIEWER-ENVELOPE-001).

This module implements the discriminated-fence detector and the
schema-validating parser for the Reviewer Output Envelope contract
defined in ``docs/schemas/reviewer_envelope.schema.json`` and described
in ``docs/reviewer_envelope.md``.

The public entry point is :func:`parse_or_fallback`, which accepts a
reviewer agent's raw text output, locates the discriminated
``json envelope`` fence (Req-001 / B-2), validates the JSON body
against the schema (Req-002 / Req-N01), and applies the per-family
ceiling normalization (Req-005 / S-1) and reroute (G-1 / Round 3
V3-N01) primitives. When the envelope is absent, behavior depends on
whether the caller's ``agent_family`` is in the per-wave
``MIGRATED_AGENT_FAMILIES`` allowlist (Req-015 / G-2).

The module is purposely free of I/O beyond a one-shot schema load and
contains no LLM/network dependencies — the parser is the deterministic
contract boundary between LLM-emitted reviewer output and the
orchestrator's routing logic.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from dataclasses import replace as dc_replace
from pathlib import Path
from typing import Any

import jsonschema

from scripts.orchestrator.agent_family_registry import (
    bridge_ceilings as _registry_bridge_ceilings,
)
from scripts.orchestrator.agent_family_registry import (
    migrated_families_by_wave as _registry_migrated_families_by_wave,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Effort-tier ordering (lowest to highest), used by :data:`TIER_RANK` for
#: the per-family ceiling comparison in :func:`_normalize_recommended_tier`.
TIER_ORDER: list[str] = ["medium", "high", "xhigh", "max"]

#: Ordinal rank for each tier, derived from :data:`TIER_ORDER`.
TIER_RANK: dict[str, int] = {tier: idx for idx, tier in enumerate(TIER_ORDER)}

#: Per-wave allowlist of agent families REQUIRED to emit the envelope
#: (Req-015 / G-2 R2). Derived from
#: :mod:`scripts.orchestrator.agent_family_registry` (TODO-0146 — single
#: source of truth across parser / merge / schema / shell-regex). The
#: returned mapping is keyed by wave string (``"W1"`` … ``"W4"``); each
#: value is a frozenset of family names whose ``waves`` field includes
#: that wave.
MIGRATED_AGENT_FAMILIES: dict[str, frozenset[str]] = _registry_migrated_families_by_wave()

#: Per-family tier ceiling table (S-1 R2 / G-1 R2). Derived from
#: :mod:`scripts.orchestrator.agent_family_registry` (TODO-0146 — same
#: single source of truth as :data:`MIGRATED_AGENT_FAMILIES`). Only
#: bridge families have real binding ceilings; ``claude-native`` and
#: ``qa-internal`` are intentionally absent and fall through the
#: ``.get(family, "max")`` default in :func:`_normalize_recommended_tier`
#: and the membership guard in :func:`_reroute_at_ceiling`.
_BRIDGE_CEILINGS: dict[str, str] = _registry_bridge_ceilings()

#: Repository-relative path to the canonical envelope schema. Resolved
#: against this module's filesystem location so the parser works
#: regardless of the caller's CWD.
_SCHEMA_PATH: Path = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "reviewer_envelope.schema.json"

#: Pre-parse byte ceiling for the envelope JSON body (TODO-0137 DoS guard).
#: Sized for the worst-case in-spec envelope (50 findings × 2000-char
#: ``description`` + 2000-char ``suggested_fix`` + per-finding overhead +
#: top-level fields) plus ~2× headroom. Bodies exceeding this raise
#: :class:`EnvelopeParseError` with ``reason="envelope_too_large"`` BEFORE
#: :func:`json.loads` runs, so the parser never spends CPU on adversarial
#: payloads engineered to OOM or trigger pathological allocator behavior.
_MAX_ENVELOPE_BODY_BYTES: int = 256_000

#: Discriminated-fence regex from plan §4.3 (lines 428-431). The
#: ``envelope`` info-string token is the §4.3 discriminator that prevents
#: plain ``json`` fences (e.g. inline ``suggested_fix`` examples) from
#: being promoted as the envelope.
ENVELOPE_FENCE_RE: re.Pattern[str] = re.compile(
    r"^```\s*json\s+envelope\s*\n(.*?)\n```\s*$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)

#: Permissive opener-only detector used by :func:`find_envelope_block`
#: to distinguish "tried to emit an envelope but malformed it" from "did
#: not try at all" (TODO-0152). Matches the discriminated opener line
#: in isolation. When :data:`ENVELOPE_FENCE_RE` returns no full match
#: but this pattern does, the agent attempted an envelope whose body or
#: closer is structurally broken (e.g. literal-empty-fence with no body
#: line at all, or a closer attached to the body line with no preceding
#: newline). The parser raises ``reason="malformed_envelope_fence"``
#: rather than routing through the envelope-absent path so the
#: orchestrator's circuit-breaker classifier can distinguish the two
#: failure modes for non-migrated families and surface a malformed-body
#: error for migrated families instead of the envelope-absent error.
_ENVELOPE_OPENER_RE: re.Pattern[str] = re.compile(
    r"^```\s*json\s+envelope\s*$",
    re.IGNORECASE | re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class EnvelopeParseError(Exception):
    """Raised for any parser failure that MUST trip the circuit-breaker.

    Per Req-N05, malformed-envelope cases (JSON decode failure, schema
    violation, multiple discriminated fences, empty body, or absent
    envelope from a migrated agent_family) raise this exception.
    Silent fallback is forbidden for these cases — the orchestrator
    relies on the exception to drive RETRY_REVIEWER routing and to
    increment the per-family failure counter.

    All four constructor parameters are explicit and named (TODO-0145):
    ``agent_id`` and ``cause`` are positional-or-keyword; ``reason`` and
    ``envelope_required`` are keyword-only. The previous variadic
    ``*args`` signature accepted any tuple shape, which made call sites
    visually ambiguous about whether the second positional was the
    underlying exception or a free-form message. Fixed kwargs make the
    intent unambiguous at the call site and let mypy catch misuse.
    """

    def __init__(
        self,
        agent_id: str | None = None,
        cause: BaseException | None = None,
        *,
        reason: str | None = None,
        envelope_required: bool = False,
    ) -> None:
        """Store the structured failure context.

        Args:
            agent_id: The reviewer agent id whose output failed parsing,
                when known. ``None`` for failures detected before the
                agent context is available (e.g.
                :func:`find_envelope_block` rejecting multiple fences).
            cause: The underlying exception being wrapped, when this
                error is raised from within an ``except`` clause. Used
                with ``raise ... from cause`` for traceback chaining.
            reason: Machine-readable failure tag used by the
                orchestrator's circuit-breaker classifier
                (e.g. ``"envelope_too_large"``,
                ``"multiple_envelope_fences"``,
                ``"malformed_envelope_fence"``,
                ``"envelope_absent_for_migrated_family"``).
            envelope_required: ``True`` when the failure is "migrated
                family omitted the envelope" (G-2 R2) — the
                orchestrator routes these through RETRY_REVIEWER.
        """
        message_args: tuple[Any, ...]
        if agent_id is not None and cause is not None:
            message_args = (agent_id, cause)
        elif agent_id is not None:
            message_args = (agent_id,)
        elif cause is not None:
            message_args = (cause,)
        else:
            message_args = ()
        super().__init__(*message_args)
        self.agent_id: str | None = agent_id
        self.cause: BaseException | None = cause
        self.reason: str | None = reason
        self.envelope_required: bool = envelope_required


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """A single review finding inside ``feedback_to_forward`` (Req-007).

    Mirrors the schema's ``feedback_to_forward[*]`` item shape. The
    ``blocking`` field defaults to ``True`` per the B-2 R2 / Req-007
    note: "when absent, defaults to true" — the default lives in code,
    not the schema, so envelopes that omit ``blocking`` are still
    schema-valid but treated as blocking by downstream merge logic.
    """

    severity: str
    description: str
    file_path: str | None = None
    line_range: str | None = None
    suggested_fix: str | None = None
    rule_id: str | None = None
    blocking: bool = True


@dataclass(frozen=True)
class Envelope:
    """Reviewer Output Envelope value object (Req-002).

    Field set mirrors the schema's required + optional top-level keys.
    The schema declares ``additionalProperties: false`` so this dataclass
    never carries auxiliary annotations — out-of-band metadata
    (e.g. :class:`RerouteAudit`) lives on :class:`ParseResult` instead
    (Round 3 V3-N01 / MINOR-3 / N3-1).

    Field-level requirement citations (full enum membership and
    structural constraints live in the schema; this dataclass merely
    types each field):

    - ``status`` — [Req-003] reviewer verdict enum. [Req-N04] membership
      enforced via a single ``enum`` clause (no oneOf/anyOf overlay).
    - ``next_action`` — [Req-004] orchestrator routing primitive enum;
      consumed by the merge function as a discrete discriminator
      (Risk-007 / Req-N02 trojan-horse defense).
    - ``halt_trigger`` — [Req-006] HALT classification; non-null only
      when ``next_action == "HALT_FOR_OPERATOR"`` per the §4.1.1
      if/then matrix.
    """

    envelope_version: str
    agent_id: str
    agent_family: str
    agent_effort_tier: str
    round: int
    status: str
    next_action: str
    feedback_to_forward: tuple[Finding, ...] = field(default_factory=tuple)
    recommended_next_tier: str | None = None
    halt_trigger: str | None = None
    spillover_findings_path: str | None = None

    def __post_init__(self) -> None:
        """Coerce ``feedback_to_forward`` items into :class:`Finding` tuples.

        Tests construct envelopes via ``Envelope(**dict)`` where
        ``feedback_to_forward`` may be a list of plain dicts (the
        schema-shape) or a list / tuple of :class:`Finding` instances
        (parser internal path). Normalize to a tuple of Finding so
        attribute access is uniform regardless of construction source.
        """
        coerced: list[Finding] = []
        for item in self.feedback_to_forward:
            if isinstance(item, Finding):
                coerced.append(item)
            elif isinstance(item, dict):
                coerced.append(Finding(**item))
            else:
                msg = f"feedback_to_forward items must be Finding or dict, got {type(item).__name__}"
                raise TypeError(msg)
        # frozen dataclass — bypass __setattr__
        object.__setattr__(self, "feedback_to_forward", tuple(coerced))

    def replace(self, **changes: Any) -> Envelope:
        """Return a new :class:`Envelope` with ``changes`` applied.

        Wraps :func:`dataclasses.replace` so callers do not need to
        import ``dataclasses`` directly. Used by
        :func:`_normalize_recommended_tier` and
        :func:`_reroute_at_ceiling`.
        """
        return dc_replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        """Return the envelope as a plain dict (schema-conformant shape).

        Tuples of :class:`Finding` are converted back to lists of dicts
        so the result round-trips through :func:`json.dumps`. Used by
        tests to assert that no ``_audit`` key has leaked onto the
        envelope.
        """
        body = asdict(self)
        body["feedback_to_forward"] = list(body["feedback_to_forward"])
        return body


@dataclass(frozen=True)
class RerouteAudit:
    """Out-of-band reroute audit produced by :func:`_reroute_at_ceiling`.

    Carried on :attr:`ParseResult.audit_annotations`, never serialized
    into the envelope JSON (Round 3 V3-N01 / MINOR-3 / N3-1). The
    envelope schema's ``additionalProperties: false`` rule would reject
    any ``_audit`` key on the envelope itself; downstream consumers
    therefore receive the audit out-of-band via the ParseResult, and
    the orchestrator forwards it to the Execution Ledger as part of
    the ``step_result`` artifact.
    """

    agent_id: str
    original_family: str
    reroute_reason: str


@dataclass(frozen=True)
class LegacyVerdict:
    """Coarse verdict extracted from prose-only reviewer output.

    Used by the Req-015 fallback path when a non-migrated agent family
    omits the envelope. The migration window keeps this stub small
    intentionally — see :func:`_legacy_prose_verdict_extractor`.
    """

    verdict: str
    parse_failure: bool = False


@dataclass
class ParseResult:
    """Return type for :func:`parse_or_fallback` (plan §9).

    Carries either an :class:`Envelope` (success path) OR a
    :class:`LegacyVerdict` (degraded fallback path), plus optional
    out-of-band audit metadata. The dataclass is intentionally NOT
    frozen — :attr:`audit_annotations` is a mutable list that the
    orchestrator may extend with additional audit entries when later
    waves introduce normalization steps beyond the W1 reroute.
    """

    envelope: Envelope | None
    degraded: bool
    legacy_verdict: LegacyVerdict | None = None
    degradation_reason: str | None = None
    audit_annotations: list[RerouteAudit] | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_or_fallback(
    agent_output: str,
    *,
    agent_id: str,
    agent_family: str,
    cb_state: Any,
    current_wave: str,
) -> ParseResult:
    """Parse the reviewer envelope or fall back per Req-015 / G-2 R2.

    Order of operations (plan §9 lines 1132-1175):

    1. Locate the discriminated envelope fence via
       :func:`find_envelope_block`. Two-or-more discriminated fences
       (Req-N08 / B-4 R2) raise :class:`EnvelopeParseError` with
       ``reason="multiple_envelope_fences"``. A discriminated opener
       without a well-formed body+closer (TODO-0152) raises with
       ``reason="malformed_envelope_fence"`` so the malformed fence
       does not get conflated with the envelope-absent path.
    2. Envelope absent: branch on the per-wave migration allowlist
       (G-2 R2). Agents whose family is currently in the active
       allowlist raise :class:`EnvelopeParseError` with
       ``envelope_required=True``; agents whose family has been
       removed (legacy or post-CB-trip per G-3 R2) fall back to a
       degraded :class:`ParseResult` carrying a :class:`LegacyVerdict`.
    3. Envelope present: parse JSON, validate against the schema, and
       construct an :class:`Envelope`. JSON-decode and schema-validation
       failures both raise :class:`EnvelopeParseError` (Req-N05) — no
       silent fallback from a malformed envelope.
    4. Apply :func:`_normalize_recommended_tier` (S-1 R2) then
       :func:`_reroute_at_ceiling` (G-1 R2). The optional
       :class:`RerouteAudit` produced by step 4 is carried on
       :attr:`ParseResult.audit_annotations`.

    The ``cb_state`` parameter is duck-typed: any object exposing a
    ``cb_legacy_fallback_families`` attribute (a set / frozenset of
    agent-family strings) is accepted. The orchestrator passes its
    persisted ``CircuitBreakerState`` instance here; tests pass a
    minimal stub.
    """
    fence_body = find_envelope_block(agent_output)
    if fence_body is None:
        active_families = _current_migrated_families(
            cb_state,
            current_wave=current_wave,
        )
        if agent_family in active_families:
            raise EnvelopeParseError(
                agent_id=agent_id,
                envelope_required=True,
                reason="envelope_absent_for_migrated_family",
            )
        return ParseResult(
            envelope=None,
            degraded=True,
            legacy_verdict=_legacy_prose_verdict_extractor(agent_output),
            degradation_reason=f"no envelope found in {agent_id} output",
        )
    try:
        envelope = _validate(fence_body)
    except (json.JSONDecodeError, jsonschema.ValidationError, RecursionError) as exc:
        # RecursionError catches deeply-nested JSON DoS (Req-N05): json.loads on
        # adversarial input like ``[[[[...]]]]`` with depth > sys.getrecursionlimit()
        # raises RecursionError, which would otherwise escape uncaught and bypass
        # the circuit-breaker counter increment. Wrapping it as EnvelopeParseError
        # routes the failure through the standard CB path and RETRY_REVIEWER routing.
        raise EnvelopeParseError(agent_id=agent_id, cause=exc) from exc
    envelope = _normalize_recommended_tier(envelope)
    envelope, reroute_audit = _reroute_at_ceiling(envelope)
    audit_annotations = [reroute_audit] if reroute_audit else None
    return ParseResult(
        envelope=envelope,
        degraded=False,
        audit_annotations=audit_annotations,
    )


def find_envelope_block(agent_output: str) -> str | None:
    """Return the JSON body of the discriminated envelope fence, or None.

    Per plan §4.3 the parser scans for fenced blocks whose opening
    info-string is ``json envelope``. Plain ``json`` fences are
    deliberately ignored even when they contain envelope-shaped JSON
    (B-3 R2 — closes the smuggling vector).

    Two or more discriminated fences in a single output raise
    :class:`EnvelopeParseError` with ``reason="multiple_envelope_fences"``
    (Req-N08 / B-4 R2). A "last-wins" fallback would let a buggy or
    malicious reviewer append a second envelope that overrides the
    first, so the parser refuses to choose.

    A discriminated opener line that does NOT pair with a well-formed
    body+closer (e.g. literal-empty-fence with no body line at all, or
    a closer attached to the body line with no preceding newline) raises
    :class:`EnvelopeParseError` with ``reason="malformed_envelope_fence"``
    (TODO-0152). The pre-scan guard fires only when
    :data:`ENVELOPE_FENCE_RE` returned zero matches AND the permissive
    opener pattern :data:`_ENVELOPE_OPENER_RE` did match — distinguishing
    "tried to emit an envelope and failed" from "did not try at all" so
    the orchestrator's circuit-breaker classifier can route the malformed
    case through RETRY_REVIEWER instead of the envelope-absent path. A
    body line whose JSON fails to parse already routes through
    :class:`EnvelopeParseError` via :func:`_validate`; the new pre-scan
    extends that coverage to fence shapes the regex can never reach.
    """
    matches = list(ENVELOPE_FENCE_RE.finditer(agent_output))
    if len(matches) > 1:
        raise EnvelopeParseError(reason="multiple_envelope_fences")
    if not matches:
        if _ENVELOPE_OPENER_RE.search(agent_output):
            raise EnvelopeParseError(reason="malformed_envelope_fence")
        return None
    return matches[0].group(1)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_recommended_tier(envelope: Envelope) -> Envelope:
    """Apply the per-family ceiling to ``recommended_next_tier`` (S-1 R2).

    When the envelope's requested tier exceeds the family's binding
    ceiling, the tier is silently lowered to the ceiling. When the
    request is at or below the ceiling, the envelope is returned
    unchanged. ``None`` is a no-op (Req-005).
    """
    if envelope.recommended_next_tier is None:
        return envelope
    ceiling = _BRIDGE_CEILINGS.get(envelope.agent_family, "max")
    requested = envelope.recommended_next_tier
    if requested not in TIER_RANK or ceiling not in TIER_RANK:
        # Defensive: schema validation already restricts the tier enum,
        # but if a future wave widens it we must not crash. Treat
        # unknown tiers as a no-op rather than raising.
        return envelope
    if TIER_RANK[requested] > TIER_RANK[ceiling]:
        return envelope.replace(recommended_next_tier=ceiling)
    return envelope


def _reroute_at_ceiling(
    envelope: Envelope,
) -> tuple[Envelope, RerouteAudit | None]:
    """Reroute bridge ESCALATE-at-own-ceiling to claude-native (G-1 R2).

    A bridge requesting escalation to its own binding ceiling is a
    no-op — re-running the same reviewer at the same tier in round
    N+1 wastes a round. The reroute swaps ``agent_family`` to
    ``claude-native`` (the family with actual tier headroom) and
    returns the audit as a separate value so the envelope schema's
    ``additionalProperties: false`` invariant is preserved
    (Round 3 V3-N01 / MINOR-3 / N3-1).

    Runs after :func:`_normalize_recommended_tier`.
    """
    if envelope.next_action != "ESCALATE_REVIEWER_TIER":
        return envelope, None
    if envelope.agent_family not in _BRIDGE_CEILINGS:
        return envelope, None
    if envelope.recommended_next_tier is None:
        return envelope, None
    ceiling = _BRIDGE_CEILINGS[envelope.agent_family]
    if envelope.recommended_next_tier == ceiling:
        audit = RerouteAudit(
            agent_id=envelope.agent_id,
            original_family=envelope.agent_family,
            reroute_reason="ceiling_collision",
        )
        return envelope.replace(agent_family="claude-native"), audit
    return envelope, None


#: Sentinel verdict tag for the negation-rung short-circuit (TODO-0153).
#: Mapped to a degraded ``ABSTAIN`` (``parse_failure=True``) by
#: :func:`_legacy_prose_verdict_extractor` so the orchestrator's
#: circuit-breaker classifier flags the case as un-trustable rather
#: than promoting the negated phrase to a positive verdict.
_LEGACY_NEGATED_VERDICT_TAG: str = "ABSTAIN_NEGATED"

#: Strict whitelist of verbatim UPPER_SNAKE_CASE verdict sentinels for
#: the legacy fallback ladder. Non-migrated reviewers MUST emit one of
#: these tokens verbatim to express a verdict; informal natural-language
#: phrases (e.g. "looks good", "ship it", "do not merge") are NOT
#: trusted by this layer because the prose-extraction surface is
#: unbounded and cannot be exhaustively negation-protected without
#: infinite regress (see TODO-0153 round-1 / round-2 reviewer findings).
#: The migration is moving all families to the structured envelope
#: contract; this rung is deliberately narrow as a forcing function for
#: that migration. Anything without a verbatim sentinel falls through
#: to ABSTAIN(parse_failure=True), and the orchestrator's circuit-breaker
#: handles repeated abstains via tier escalation.
_LEGACY_VERDICT_SENTINELS: str = r"HALT_FOR_OPERATOR|REJECTED|BLOCKED|APPROVED_WITH_NOTES|APPROVED"

#: Priority-ordered legacy verdict ladder (TODO-0136 / TODO-0153 /
#: TODO-0153-followup). Each entry is a ``(verdict, patterns)`` tuple;
#: the first verdict whose pattern list matches the output wins.
#:
#: The rung is **sentinel-only** (TODO-0153-followup): the matchable
#: surface is restricted to a strict whitelist of verbatim
#: UPPER_SNAKE_CASE tokens (:data:`_LEGACY_VERDICT_SENTINELS`).
#: Informal natural-language phrases (``looks good``, ``ship it``,
#: ``do not merge``, ``operator authorization required``, lowercase
#: ``approved with notes``) are deliberately NOT matched. The earlier
#: ladder layered informal-prose matchers on top of the sentinels,
#: which created an unbounded negation-coverage class — every round of
#: review surfaced another natural-language negation that leaked
#: through (``not yet approved``, ``never approved``, ``do not approve
#: — looks good``, ``won't ship it``, etc.). The strict-whitelist
#: design collapses the entire class because there is no fuzzy prose
#: for negation to leak through: prose without a verbatim sentinel
#: simply falls through to ABSTAIN(parse_failure=True) at the default
#: rung, and the orchestrator's circuit-breaker handles repeated
#: abstains via tier escalation.
#:
#: The top rung (``ABSTAIN_NEGATED``) catches the narrow case where a
#: reviewer writes ``not BLOCKED`` / ``never APPROVED`` (i.e. negates a
#: sentinel verbatim) — same conservative-fallback semantics as the
#: rest of the ladder, mapped to ``LegacyVerdict("ABSTAIN",
#: parse_failure=True)`` by :func:`_legacy_prose_verdict_extractor`.
#:
#: Word-boundary anchoring on the sentinels prevents false positives
#: such as ``\bAPPROVED\b`` matching inside ``DISAPPROVED`` or
#: ``\bBLOCKED\b`` matching inside ``UNBLOCKED``. Sentinels are
#: case-sensitive by intent: a reviewer writing ``approved`` (lowercase
#: prose) does NOT trigger the APPROVE rung — only the verbatim
#: ``APPROVED`` sentinel does. The sentinel-negation rung's negation
#: prefix is case-INsensitive via an inline ``(?i:not|never)`` flag
#: (TODO-0153-followup R3 / F1): formal review summaries commonly use
#: all-caps verdict prefixes (``NOT APPROVED:`` / ``NOT BLOCKED:``) to
#: mirror the verbatim-sentinel style, so the prefix half MUST catch
#: ``NOT`` / ``Not`` / ``not`` / ``NEVER`` / ``Never`` / ``never``
#: while the sentinel half remains strictly case-sensitive (lowercase
#: ``approved`` / ``blocked`` still falls through to default-rung
#: ABSTAIN). Nested tuples (rather than nested lists) match the file's
#: frozen-dataclass house style for module-scope constants.
_LEGACY_VERDICT_RULES: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        _LEGACY_NEGATED_VERDICT_TAG,
        (
            # Sentinel-only negation: prose like "this is not BLOCKED" or
            # "never APPROVED" short-circuits to ABSTAIN. Natural-language
            # negations like "not yet approved" or "won't ship it" no
            # longer require pattern coverage because the rung only
            # matches verbatim UPPER_SNAKE_CASE sentinels — lowercase or
            # informal prose simply falls through to ABSTAIN at the
            # default rung. The negation prefix uses an inline
            # ``(?i:not|never)`` flag (TODO-0153-followup R3 / F1) so
            # uppercase / title-case prefixes (``NOT APPROVED`` /
            # ``Not APPROVED`` / ``NEVER REJECTED``) also short-circuit;
            # the sentinel half remains case-sensitive so lowercase
            # ``approved`` / ``blocked`` still falls through to the
            # default ABSTAIN rung as the strict-whitelist design demands.
            re.compile(rf"\b(?i:not|never)\s+(?:{_LEGACY_VERDICT_SENTINELS})\b"),
        ),
    ),
    (
        "HALT",
        (re.compile(r"\bHALT_FOR_OPERATOR\b"),),
    ),
    (
        "RETURN_TO_WORKER",
        (
            re.compile(r"\bREJECTED\b"),
            re.compile(r"\bBLOCKED\b"),
        ),
    ),
    (
        "APPROVE_WITH_NOTES",
        (re.compile(r"\bAPPROVED_WITH_NOTES\b"),),
    ),
    (
        "APPROVE",
        (re.compile(r"\bAPPROVED\b"),),
    ),
)


def _legacy_prose_verdict_extractor(output: str) -> LegacyVerdict:
    """Extract a coarse verdict from prose-only reviewer output (Req-015).

    Implements the priority-ordered sentinel scan from plan §9
    lines 1116-1129 as an in-file stub. The repo does not currently
    ship a separate ``scripts/orchestrator/legacy_verdict.py`` parser
    (the pre-envelope orchestrator inlined this logic in skill prose),
    so the W1 GREEN-phase implementation is the canonical home for
    the helper. Subsequent waves may relocate it without changing the
    public contract.

    The ladder is **sentinel-only** (TODO-0153-followup): only verbatim
    UPPER_SNAKE_CASE sentinels in :data:`_LEGACY_VERDICT_SENTINELS`
    promote a verdict. Informal prose (``looks good``, ``ship it``,
    ``do not merge``, lowercase ``approved``, etc.) does NOT match any
    rung and falls through to ABSTAIN(parse_failure=True). This
    intentional narrowness eliminates the unbounded-negation-coverage
    class: prose like ``not yet approved`` / ``won't ship it`` / ``do
    not approve`` no longer requires per-phrasing pattern coverage
    because the underlying positive rungs no longer match those
    informal phrases either.

    Word-boundary anchoring (TODO-0136) keeps ``\\bAPPROVED\\b`` from
    matching inside ``DISAPPROVED`` and ``\\bBLOCKED\\b`` from matching
    inside ``UNBLOCKED``. The verdict ladder
    (ABSTAIN_NEGATED > HALT > RETURN_TO_WORKER > APPROVE_WITH_NOTES >
    APPROVE > ABSTAIN) is preserved by iterating
    :data:`_LEGACY_VERDICT_RULES` top-to-bottom.

    The top rung (``ABSTAIN_NEGATED``) catches verbatim-sentinel
    negation only — ``not BLOCKED`` / ``never APPROVED`` / etc. Returns
    ``LegacyVerdict("ABSTAIN", parse_failure=True)`` so the
    orchestrator's circuit-breaker classifier flags the case as
    un-trustable rather than promoting the negated sentinel to a
    positive verdict.
    """
    haystack = output or ""
    for verdict, patterns in _LEGACY_VERDICT_RULES:
        if any(pattern.search(haystack) for pattern in patterns):
            if verdict == _LEGACY_NEGATED_VERDICT_TAG:
                return LegacyVerdict(verdict="ABSTAIN", parse_failure=True)
            return LegacyVerdict(verdict=verdict)
    return LegacyVerdict(verdict="ABSTAIN", parse_failure=True)


def _current_migrated_families(
    state: Any,
    *,
    current_wave: str,
) -> set[str]:
    """Return the active migration allowlist after CB removals (G-3 R2).

    Subtracts any agent families that have tripped the circuit-breaker
    during the current epic (``state.cb_legacy_fallback_families``)
    from the wave's static :data:`MIGRATED_AGENT_FAMILIES` allowlist.
    The state argument is duck-typed for ease of testing; production
    callers pass a ``CircuitBreakerState`` instance.
    """
    base: frozenset[str] = MIGRATED_AGENT_FAMILIES[current_wave]
    removed: frozenset[str] = getattr(state, "cb_legacy_fallback_families", frozenset())
    return set(base) - set(removed)


_SCHEMA_CACHE: dict[str, Any] | None = None


def _load_schema() -> dict[str, Any]:
    """Load and return the envelope JSON Schema (memoized via module cache).

    Reads :data:`_SCHEMA_PATH` once on first call and caches the parsed
    dict in :data:`_SCHEMA_CACHE`. Subsequent calls return the cached
    value. The cache lives at module scope so concurrent callers share
    the parsed schema (the schema file is treated as immutable at
    runtime — edits require a re-import, which is the desired CI
    behavior).
    """
    global _SCHEMA_CACHE
    cached = _SCHEMA_CACHE
    if cached is None:
        cached = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        _SCHEMA_CACHE = cached
    return cached


def _validate(body: str) -> Envelope:
    """Parse and schema-validate an envelope body, returning an Envelope.

    Raises :class:`json.JSONDecodeError` for malformed JSON (including
    empty / whitespace-only bodies) and :class:`jsonschema.ValidationError`
    for schema violations. Callers (currently :func:`parse_or_fallback`)
    are expected to wrap both into :class:`EnvelopeParseError` per
    Req-N05.

    Pre-parse byte-length guard (TODO-0137): bodies exceeding
    :data:`_MAX_ENVELOPE_BODY_BYTES` raise :class:`EnvelopeParseError`
    directly with ``reason="envelope_too_large"`` BEFORE :func:`json.loads`
    runs. The guard is intentionally raised here rather than wrapped via
    the ``except`` in :func:`parse_or_fallback` so the failure carries a
    distinguishable ``reason`` for the orchestrator's circuit-breaker
    classifier.
    """
    if len(body.encode("utf-8")) > _MAX_ENVELOPE_BODY_BYTES:
        raise EnvelopeParseError(reason="envelope_too_large")
    parsed = json.loads(body)
    schema = _load_schema()
    jsonschema.validate(parsed, schema)
    envelope_kwargs: dict[str, Any] = {
        "envelope_version": parsed["envelope_version"],
        "agent_id": parsed["agent_id"],
        "agent_family": parsed["agent_family"],
        "agent_effort_tier": parsed["agent_effort_tier"],
        "round": parsed["round"],
        "status": parsed["status"],
        "next_action": parsed["next_action"],
        "feedback_to_forward": parsed.get("feedback_to_forward", []),
        "recommended_next_tier": parsed.get("recommended_next_tier"),
        "halt_trigger": parsed.get("halt_trigger"),
        "spillover_findings_path": parsed.get("spillover_findings_path"),
    }
    return Envelope(**envelope_kwargs)
