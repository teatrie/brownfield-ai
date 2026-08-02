"""Forward-compat reviewer agent-family registry (TODO-0146).

Single source of truth for the four reviewer-envelope surfaces that
otherwise duplicated agent-family metadata:

1. :mod:`scripts.orchestrator.envelope_parser` — needs
   ``MIGRATED_AGENT_FAMILIES`` (per-wave allowlist for Req-015 / G-2 R2)
   and ``_BRIDGE_CEILINGS`` (per-family tier ceilings for S-1 R2 / G-1 R2).
2. :mod:`scripts.orchestrator.envelope_merge` (W4) — will need the same
   ceiling table for the Cross-Family Asymmetry softening tier comparison
   (plan §5.2). Adding a third copy of the ceiling values across a
   third module is the drift surface this registry closes.
3. ``docs/schemas/reviewer_envelope.schema.json`` — the ``agent_family``
   enum lists the same set of family names.
4. ``ci/lint_staged.sh`` — the ``ENVELOPE_AGENTS`` regex selects agent
   markdown paths whose stems are exactly the agent IDs declared here.

The registry stores the canonical fact about each family in one place;
the four surfaces above derive their views from it. The schema enum
and shell regex stay hand-maintained for portability (JSON Schema and
shell scripts can't import Python at runtime), but a registry-driven
consistency test catches drift the moment a new family or agent ID is
added without updating one of the dependents.

The W4 merge function will import :data:`AGENT_FAMILY_REGISTRY` and
:func:`bridge_ceilings` directly. The W4 circuit-breaker's mutation of
the migrated-allowlist (G-3 R2 — moving a tripped family into
``cb_legacy_fallback_families``) operates on the derived view returned
by :func:`migrated_families_by_wave`, so the registry remains immutable
at runtime — only the per-epic ``CircuitBreakerState`` object mutates.

This module is intentionally free of I/O and side effects: it is a
data-only module that downstream consumers import for the static
view, and tests cross-reference it against the schema/shell-script
hand-maintained copies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Effort-tier ordering shared with :mod:`envelope_parser`. Re-declared
#: here rather than imported from :mod:`envelope_parser` to avoid a
#: circular dependency: :mod:`envelope_parser` imports from this module
#: but its own ``TIER_ORDER`` is a runtime concern of the parser, while
#: ``BRIDGE_CEILING_VALUES`` is a registry-author-time check. The two
#: lists must stay in lockstep — see
#: :func:`tests.scripts.orchestrator.test_agent_family_registry.test_tier_order_consistent`.
BRIDGE_CEILING_VALUES: frozenset[str] = frozenset({"medium", "high", "xhigh", "max"})

#: All known wave identifiers. New waves are appended by editing the
#: tuple AND adding the wave string to the relevant family's
#: ``waves`` field below.
KNOWN_WAVES: tuple[str, ...] = ("W1", "W2", "W3", "W4")


@dataclass(frozen=True)
class AgentFamily:
    """Per-family registry entry.

    :ivar name: The canonical family name (matches the schema's
        ``agent_family`` enum value, e.g. ``"claude-native"``).
    :ivar bridge_ceiling: The family's binding tier ceiling, or ``None``
        when the family has no real cap (claude-native and qa-internal
        run up to ``max``). Bridges have a CLI-imposed ceiling that
        lower bounds prevent escalation past — see plan §4.3
        ``_normalize_recommended_tier`` and ``_reroute_at_ceiling``.
    :ivar waves: Tuple of wave identifiers (subset of
        :data:`KNOWN_WAVES`) where this family is REQUIRED to emit the
        envelope. Empty tuple means the family is in the schema enum
        for forward-compat but no agents have been migrated yet (e.g.,
        ``copilot-bridge`` as of W4).
    :ivar agent_ids: Tuple of frontmatter agent IDs in this family
        (e.g., ``("code-review", "code-review-high", ...)``). Empty
        tuple when the family is not yet realized as concrete agent
        files. Used by the lint test SCOPE and the shell regex
        cross-check.
    """

    name: str
    bridge_ceiling: str | None
    waves: tuple[str, ...] = field(default_factory=tuple)
    agent_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Validate the registry entry's invariants at import time.

        Catches the "added a family but forgot to update KNOWN_WAVES /
        BRIDGE_CEILING_VALUES" footgun before it escapes to runtime.
        """
        if self.bridge_ceiling is not None and self.bridge_ceiling not in BRIDGE_CEILING_VALUES:
            msg = f"AgentFamily {self.name!r}: bridge_ceiling={self.bridge_ceiling!r} not in BRIDGE_CEILING_VALUES={BRIDGE_CEILING_VALUES}"
            raise ValueError(msg)
        for wave in self.waves:
            if wave not in KNOWN_WAVES:
                msg = f"AgentFamily {self.name!r}: wave {wave!r} not in KNOWN_WAVES={KNOWN_WAVES}"
                raise ValueError(msg)


#: Canonical reviewer agent-family registry. The dict insertion order
#: matches the order families are exposed in the schema enum and is
#: load-bearing for the schema-consistency test.
AGENT_FAMILY_REGISTRY: dict[str, AgentFamily] = {
    "claude-native": AgentFamily(
        name="claude-native",
        bridge_ceiling=None,
        waves=("W1", "W2", "W3", "W4"),
        agent_ids=(
            "code-review",
            "code-review-high",
            "code-review-xhigh",
            "code-review-max",
        ),
    ),
    "codex-bridge": AgentFamily(
        name="codex-bridge",
        bridge_ceiling="xhigh",
        waves=("W2", "W3", "W4"),
        agent_ids=(
            "codex-reviewer",
            "codex-reviewer-high",
            "codex-reviewer-xhigh",
            "codex-reviewer-max",
        ),
    ),
    "gemini-bridge": AgentFamily(
        name="gemini-bridge",
        bridge_ceiling="high",
        waves=("W2", "W3", "W4"),
        agent_ids=(
            "gemini-reviewer",
            "gemini-reviewer-high",
            "gemini-reviewer-xhigh",
            "gemini-reviewer-max",
        ),
    ),
    "copilot-bridge": AgentFamily(
        name="copilot-bridge",
        bridge_ceiling="high",
        waves=(),  # forward-compat: schema enum reserves the slot, no agents migrated yet
        agent_ids=(),
    ),
    "qa-internal": AgentFamily(
        name="qa-internal",
        bridge_ceiling=None,
        waves=("W3", "W4"),
        agent_ids=(
            "qa-standards",
            "qa-standards-high",
            "qa-standards-xhigh",
            "qa-standards-max",
            "qa-lint",
            "qa-test",
        ),
    ),
}


# ---------------------------------------------------------------------------
# Derived views
# ---------------------------------------------------------------------------


def migrated_families_by_wave() -> dict[str, frozenset[str]]:
    """Return the per-wave allowlist (Req-015 / G-2 R2).

    Equivalent to the previously-hand-maintained
    ``MIGRATED_AGENT_FAMILIES`` dict in :mod:`envelope_parser`, derived
    here from the registry. Each wave's frozenset contains the names of
    families whose ``waves`` field includes that wave string.
    """
    return {wave: frozenset(family.name for family in AGENT_FAMILY_REGISTRY.values() if wave in family.waves) for wave in KNOWN_WAVES}


def bridge_ceilings() -> dict[str, str]:
    """Return the per-bridge tier ceiling table (S-1 R2 / G-1 R2).

    Equivalent to the previously-hand-maintained ``_BRIDGE_CEILINGS``
    dict in :mod:`envelope_parser`. Only families whose
    :attr:`AgentFamily.bridge_ceiling` is non-None are included; the
    parser's ``.get(family, "max")`` default in
    ``_normalize_recommended_tier`` and the membership-guard in
    ``_reroute_at_ceiling`` already handle non-bridge families
    correctly without an explicit entry.
    """
    return {family.name: family.bridge_ceiling for family in AGENT_FAMILY_REGISTRY.values() if family.bridge_ceiling is not None}


def lint_scope() -> tuple[str, ...]:
    """Return the agent-IDs covered by the per-wave envelope lint.

    Equivalent to the hand-maintained ``SCOPE`` constant in
    ``tests/lint/test_reviewer_envelope_required.py``. Includes every
    agent in every family whose ``waves`` field is non-empty
    (i.e., the family has at least one migrated wave).
    Order is deterministic: registry-insertion order across families,
    declaration order within each family.
    """
    return tuple(agent_id for family in AGENT_FAMILY_REGISTRY.values() if family.waves for agent_id in family.agent_ids)


def bridge_lint_scope() -> tuple[str, ...]:
    """Return the agent-IDs covered by the W2 bridge-only lint additions.

    Equivalent to the hand-maintained ``BRIDGE_SCOPE`` constant in
    ``tests/lint/test_reviewer_envelope_required.py``. Includes every
    agent in every bridge family with at least one migrated wave (the
    severity-mapping + verbatim-CLI-prose lint rules apply only to
    bridges per plan §10.3 W2).
    """
    return tuple(
        agent_id
        for family in AGENT_FAMILY_REGISTRY.values()
        if family.waves and family.bridge_ceiling is not None
        for agent_id in family.agent_ids
    )


def schema_family_enum() -> tuple[str, ...]:
    """Return the family-enum tuple expected in the JSON Schema.

    The schema declares ``agent_family.enum`` as a hand-maintained
    array; the registry-consistency test cross-checks that the schema's
    enum matches this tuple exactly (same set, same order). Adding a
    family here without updating the schema fails the test.
    """
    return tuple(AGENT_FAMILY_REGISTRY.keys())


def lint_staged_agent_ids() -> tuple[str, ...]:
    """Return every agent-ID that the shell ``ENVELOPE_AGENTS`` regex
    in ``ci/lint_staged.sh`` MUST match.

    The shell script's regex is hand-maintained for portability (CI
    bash on macOS doesn't import Python at runtime). The
    registry-consistency test compiles the agent-ID list here, runs
    them through the regex, and asserts every entry matches. Adding a
    new agent ID here without widening the shell regex fails the test.

    Returns every realized agent ID, including those in families with
    empty ``waves`` (forward-compat coverage — when a family is added
    to a future wave, the shell regex MUST already cover it).
    """
    return tuple(agent_id for family in AGENT_FAMILY_REGISTRY.values() for agent_id in family.agent_ids)
