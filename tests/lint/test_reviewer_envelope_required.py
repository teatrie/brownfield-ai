"""Lint test enforcing reviewer-envelope emission instructions in agent definitions.

Epic: REVIEWER-ENVELOPE-001 (Wave 1 RED phase).

The ``SCOPE`` and ``BRIDGE_SCOPE`` lists are derived from the canonical
agent-family registry in :mod:`scripts.orchestrator.agent_family_registry`
(TODO-0146). Adding a new agent ID requires editing the registry; this
lint module — and the parser, schema, and shell regex — pick the change
up automatically.

Every test docstring cites the Requirement IDs it enforces.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.orchestrator.agent_family_registry import (
    bridge_lint_scope,
    lint_scope,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENTS_DIR = _REPO_ROOT / ".claude" / "agents"

#: Per-wave envelope-emission lint scope (plan §10.3, B-3 R2). Sourced
#: from :func:`scripts.orchestrator.agent_family_registry.lint_scope`,
#: which enumerates every agent ID in every family with at least one
#: migrated wave. W1 covered claude-native; W2 added codex/gemini
#: bridges; W3 added qa-internal.
SCOPE: list[str] = list(lint_scope())

#: Bridge-only subset for the W2 lint additions (severity-mapping table
#: + verbatim-CLI-prose preservation rule). Sourced from
#: :func:`scripts.orchestrator.agent_family_registry.bridge_lint_scope`.
#: Bridge bodies must be self-contained for headless execution per plan
#: §8 W2 — the DRY cost is the price of headless safety.
BRIDGE_SCOPE: list[str] = list(bridge_lint_scope())

# The discriminated info-string token from §4.3. Agents must instruct the
# model to emit ``json envelope`` (the literal info-string of the final
# fence) — not just ``json``.
_DISCRIMINATOR_TOKEN = "json envelope"

# The canonical reference document agents MUST link to (Req-019).
_CANONICAL_DOC_PATH = "docs/reviewer_envelope.md"

# Distinctive substring of the §6.1.1 severity-mapping table header. This
# token is unique enough that a copy-paste of the verbatim table will
# match, and a paraphrase or partial copy will not. Picked up only by
# the W2 lint check that fires against BRIDGE_SCOPE.
_SEVERITY_MAPPING_TABLE_MARKER = "CLI prose modal verb / signal"

# Per-row tokens — assert each row of §6.1.1 severity-mapping table is
# present in the agent body. Sourced verbatim from plan §6.1.1 lines
# 863-866. Together with the header marker above, this enforces structural
# fidelity: a paraphrased table cannot include all four exact strings
# simultaneously, so the lint catches the contract drift Codex F1/F2 (W2
# tri-family review, 2026-04-30) flagged as too-coarse-to-be-load-bearing.
_SEVERITY_ROW_TOKENS: tuple[str, ...] = (
    '"must" / "MUST" / "blocker"',
    '"should" / "SHOULD" / "significant"',
    '"consider" / "could" / "minor"',
    '"note" / "FYI" / "informational"',
)

# Per-row tokens for the §6.1.1 verdict-mapping table (lines 872-877).
# Same anti-paraphrase guarantee as above.
_VERDICT_ROW_TOKENS: tuple[str, ...] = (
    '"approved" / "looks good"',
    '"approved with notes" / "approved pending nits"',
    '"rejected" / "blocked"',
    '"operator authorization required"',
    '"cannot determine"',
    '"I cannot reach a verdict"',
)

# Distinctive substring of the verbatim-CLI-prose preservation rule
# (plan §6.1.1 audit-trail requirement). The rule mandates that bridge
# `description` fields contain the CLI's prose conclusion verbatim —
# this string is the load-bearing phrase that asserts the rule is
# present in the agent body.
_VERBATIM_CLI_PROSE_RULE_MARKER = "MUST quote the CLI's prose conclusion verbatim"

# Distinctive substring of the W2 Codex F1 closure: the precedence note
# disambiguating envelope-level vs per-finding `next_action`. Without this
# rule, two compliant bridges could legitimately emit different
# `next_action` for the same CLI conclusion (e.g., APPROVED_WITH_NOTES
# with only-minor findings → APPROVE per verdict row OR
# RETURN_TO_WORKER_ADVISORY per severity-row default). The rule pins
# verdict-row precedence.
_PRECEDENCE_RULE_MARKER = "verdict-mapping table assigns the envelope's authoritative `next_action`"

# Required envelope keys (from §4.1). The lint asserts each agent's body
# contains an example envelope mentioning all these keys at least once.
_REQUIRED_ENVELOPE_KEYS: tuple[str, ...] = (
    "envelope_version",
    "agent_id",
    "agent_family",
    "agent_effort_tier",
    "round",
    "status",
    "next_action",
    "feedback_to_forward",
    "recommended_next_tier",
    "halt_trigger",
)

#: Default effort tier when an agent's frontmatter omits the ``effort``
#: key. The base claude-native ``code-review`` agent intentionally has
#: no ``effort`` field — its example envelope encodes the effort as
#: ``"medium"`` per the documented base-tier convention. New base-tier
#: agents added to SCOPE without an explicit ``effort`` MUST follow the
#: same convention.
_DEFAULT_EFFORT_TIER = "medium"

#: Regex matching the YAML frontmatter block at the top of an agent
#: file: ``---\n<key>: <value>\n...\n---``. Group 1 captures the body
#: of the frontmatter (the lines between the fences).
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---", re.DOTALL)

#: Regex extracting every fenced ``json`` block in an agent body. Agent
#: example envelopes use plain ``json`` fences (the discriminated
#: ``json envelope`` info-string is reserved for actual emission). The
#: caller filters the matches for the one whose body parses as a JSON
#: object containing ``envelope_version`` — that ensures the test
#: tolerates ancillary ``json`` examples (e.g. a ``suggested_fix``
#: snippet) without misidentifying them as the envelope example.
_JSON_FENCE_RE = re.compile(r"```json\n(.*?)\n```", re.DOTALL)


def _agent_path(agent_name: str) -> Path:
    """Return the absolute path to the agent definition file."""
    return _AGENTS_DIR / f"{agent_name}.md"


def _agent_body(agent_name: str) -> str:
    """Read the agent definition file as text (UTF-8)."""
    return _agent_path(agent_name).read_text(encoding="utf-8")


def _parse_frontmatter(body: str) -> dict[str, str]:
    """Return the agent's YAML frontmatter as a flat ``key: value`` dict.

    A minimal parser sized for the agent files we ship: each frontmatter
    line is ``key: value`` (single line, no nested dicts, no list values
    on the keys we care about). Lines that do not match the simple
    ``key: value`` shape are skipped. Returning a flat dict avoids a
    PyYAML dependency for what is otherwise a single-line lookup.

    Surrounding single or double quotes on the value are stripped so a
    future agent file that uses ``name: "code-review-high"`` still
    pins correctly against the unquoted basename. Quoted scalars are
    the only YAML escape this parser handles — multi-line block
    scalars, list-form values, and inline-comment trailing fragments
    remain unsupported, and the lint will fail loudly if a SCOPE agent
    introduces one. Switch to PyYAML if that day arrives.
    """
    match = _FRONTMATTER_RE.match(body)
    if match is None:
        return {}
    parsed: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        parsed[key.strip()] = value.strip().strip('"').strip("'")
    return parsed


@pytest.mark.parametrize("agent_name", SCOPE)
def test_each_scope_agent_contains_envelope_token(agent_name: str) -> None:
    """[Req-001] [Req-018] Each in-scope reviewer agent body MUST contain the discriminated info-string token.

    The token ``json envelope`` is the §4.3 fence discriminator that
    distinguishes the structured envelope from any inline ``json`` blocks
    the agent may quote in prose.
    """
    path = _agent_path(agent_name)
    assert path.exists(), f"Agent file does not exist: {path}"
    body = _agent_body(agent_name)
    assert _DISCRIMINATOR_TOKEN in body, (
        f"Agent '{agent_name}' missing discriminated-fence token '{_DISCRIMINATOR_TOKEN}'. See docs/reviewer_envelope.md §4.3."
    )


@pytest.mark.parametrize("agent_name", SCOPE)
def test_each_scope_agent_links_to_canonical_doc(agent_name: str) -> None:
    """[Req-019] [Req-018] Each in-scope reviewer agent body MUST link to docs/reviewer_envelope.md."""
    path = _agent_path(agent_name)
    assert path.exists(), f"Agent file does not exist: {path}"
    body = _agent_body(agent_name)
    assert _CANONICAL_DOC_PATH in body, f"Agent '{agent_name}' missing required link to '{_CANONICAL_DOC_PATH}' per Req-019."


@pytest.mark.parametrize("agent_name", SCOPE)
def test_each_scope_agent_has_envelope_example_with_required_keys(
    agent_name: str,
) -> None:
    """[Req-018] [Req-001] Each in-scope agent body MUST contain an envelope example covering all required keys.

    The lint scans for the §4.1 required-keys set in the agent body. A
    fenced JSON example demonstrating envelope emission satisfies this
    check; missing any required key fails the lint so agents do not ship
    with partial schema documentation.
    """
    path = _agent_path(agent_name)
    assert path.exists(), f"Agent file does not exist: {path}"
    body = _agent_body(agent_name)
    missing = [key for key in _REQUIRED_ENVELOPE_KEYS if key not in body]
    assert not missing, (
        f"Agent '{agent_name}' envelope example missing required keys: {missing}. All §4.1 required keys must appear in the body."
    )


@pytest.mark.parametrize("agent_name", BRIDGE_SCOPE)
def test_each_bridge_scope_agent_has_severity_mapping_table(
    agent_name: str,
) -> None:
    """[Req-007] [Req-018] [B-5] Each W2 bridge agent body MUST embed the §6.1.1 severity-mapping table verbatim.

    The §6.1.1 table is the normative source for translating CLI prose
    modal verbs ("must" / "should" / "consider" / etc.) into envelope
    severity + next_action + blocking values. Per plan §8 W2, each bridge
    agent body embeds the table verbatim — the DRY cost is acceptable
    because headless execution requires self-contained agent bodies.
    The marker substring ``"CLI prose modal verb / signal"`` is the
    table header — it appears nowhere else in the agent body, so a
    paraphrase or partial copy will not match.
    """
    path = _agent_path(agent_name)
    assert path.exists(), f"Bridge agent file does not exist: {path}"
    body = _agent_body(agent_name)
    assert _SEVERITY_MAPPING_TABLE_MARKER in body, (
        f"Bridge agent '{agent_name}' missing §6.1.1 severity-mapping table marker '{_SEVERITY_MAPPING_TABLE_MARKER}'. "
        "Plan §8 W2 requires the table embedded verbatim in each bridge body for headless self-containment."
    )


@pytest.mark.parametrize("agent_name", BRIDGE_SCOPE)
def test_each_bridge_scope_agent_has_all_severity_rows(
    agent_name: str,
) -> None:
    """[Req-007] [B-5] [W2 Codex F2 closure] Each bridge body MUST embed every §6.1.1 severity-mapping row.

    The header-only marker (`test_each_bridge_scope_agent_has_severity_mapping_table`)
    catches a missing table but not a paraphrased one. This stronger
    check asserts every modal-verb token group from the §6.1.1 lines
    863-866 is present, so a future edit that drops or rewords a row
    while keeping the header intact will fail. Codex F2 (W2 tri-family
    review, 2026-04-30) flagged the original header-only check as too
    coarse for a verbatim-embedding contract.
    """
    path = _agent_path(agent_name)
    assert path.exists(), f"Bridge agent file does not exist: {path}"
    body = _agent_body(agent_name)
    missing = [tok for tok in _SEVERITY_ROW_TOKENS if tok not in body]
    assert not missing, (
        f"Bridge agent '{agent_name}' missing §6.1.1 severity-mapping rows: {missing}. "
        "Each row's modal-verb token group MUST appear verbatim."
    )


@pytest.mark.parametrize("agent_name", BRIDGE_SCOPE)
def test_each_bridge_scope_agent_has_all_verdict_rows(
    agent_name: str,
) -> None:
    """[Req-007] [B-5] [W2 Codex F2 closure] Each bridge body MUST embed every §6.1.1 verdict-mapping row.

    Same anti-paraphrase guarantee as the severity-row check, applied
    to the §6.1.1 verdict-mapping table at lines 872-877.
    """
    path = _agent_path(agent_name)
    assert path.exists(), f"Bridge agent file does not exist: {path}"
    body = _agent_body(agent_name)
    missing = [tok for tok in _VERDICT_ROW_TOKENS if tok not in body]
    assert not missing, (
        f"Bridge agent '{agent_name}' missing §6.1.1 verdict-mapping rows: {missing}. "
        "Each row's CLI conclusion phrase MUST appear verbatim."
    )


@pytest.mark.parametrize("agent_name", BRIDGE_SCOPE)
def test_each_bridge_scope_agent_has_precedence_rule(
    agent_name: str,
) -> None:
    """[Req-007] [B-5] [W2 Codex F1 closure] Each bridge body MUST contain the envelope-level vs per-finding next_action precedence rule.

    Without this rule, the §6.1.1 mapping is ambiguous for the
    APPROVED_WITH_NOTES + only-minor-findings case (verdict-row says
    APPROVE; severity-row default says RETURN_TO_WORKER_ADVISORY).
    Two compliant bridges could legitimately emit different next_action
    for the same CLI conclusion. The precedence rule pins verdict-row
    as authoritative; the severity-row next_action column becomes
    advisory (its load-bearing output is the per-finding `blocking`
    flag). Codex F1 (W2 tri-family review, 2026-04-30) flagged the
    ambiguity as a P1 blocker — this lint asserts the closure is
    present in every bridge body.
    """
    path = _agent_path(agent_name)
    assert path.exists(), f"Bridge agent file does not exist: {path}"
    body = _agent_body(agent_name)
    assert _PRECEDENCE_RULE_MARKER in body, (
        f"Bridge agent '{agent_name}' missing precedence rule marker. "
        f"Expected substring: '{_PRECEDENCE_RULE_MARKER}'. See plan §6.1.1 W2 Codex F1 closure."
    )


@pytest.mark.parametrize("agent_name", BRIDGE_SCOPE)
def test_each_bridge_scope_agent_has_verbatim_cli_prose_rule(
    agent_name: str,
) -> None:
    """[Req-007] [Req-018] [B-5] Each W2 bridge agent body MUST state the verbatim-CLI-prose preservation rule.

    Per §6.1.1 audit-trail requirement, the bridge MUST quote the
    external CLI's prose conclusion verbatim in each finding's
    ``description``. This rule is the load-bearing audit-trail guarantee
    that prevents the bridge from re-rubricking, re-ranking, or paraphrasing
    the CLI's output. The marker substring is the exact rule phrasing.
    """
    path = _agent_path(agent_name)
    assert path.exists(), f"Bridge agent file does not exist: {path}"
    body = _agent_body(agent_name)
    assert _VERBATIM_CLI_PROSE_RULE_MARKER in body, (
        f"Bridge agent '{agent_name}' missing verbatim-CLI-prose preservation rule marker. "
        f"Expected substring: '{_VERBATIM_CLI_PROSE_RULE_MARKER}'. See plan §6.1.1 audit-trail requirement."
    )


@pytest.mark.parametrize("agent_name", SCOPE)
def test_each_scope_agent_envelope_example_pins_frontmatter_identity(
    agent_name: str,
) -> None:
    """[Req-018] [TODO-0149] Each agent's envelope example MUST pin agent_id and agent_effort_tier to frontmatter.

    A copy-paste between effort-tier variants is the failure mode this
    lint catches: e.g. duplicating ``code-review-high.md`` to seed
    ``code-review-xhigh.md`` and forgetting to update the example
    envelope's ``agent_id`` / ``agent_effort_tier`` would ship a
    body whose example contradicts the frontmatter. The W3 EXCLUDED_BASES
    exclusions in ``tests/agents/test_variant_parity.py`` mean the
    parity-style check does not catch this; a per-file pin lint is the
    minimal closure (Codex F2 in W3 tri-family diff review,
    gemini-reviewer-high concurred).

    Convention: when frontmatter omits ``effort`` (the base claude-native
    ``code-review`` agent), the example envelope MUST encode the
    documented base-tier value ``"medium"``.
    """
    path = _agent_path(agent_name)
    assert path.exists(), f"Agent file does not exist: {path}"
    body = _agent_body(agent_name)
    frontmatter = _parse_frontmatter(body)
    expected_agent_id = frontmatter.get("name")
    assert expected_agent_id == agent_name, (
        f"Agent '{agent_name}' frontmatter `name` is '{expected_agent_id}'; expected '{agent_name}' (file basename)."
    )
    expected_effort_tier = frontmatter.get("effort", _DEFAULT_EFFORT_TIER)
    envelope_examples: list[dict[str, object]] = []
    for fence_match in _JSON_FENCE_RE.finditer(body):
        try:
            candidate = json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and "envelope_version" in candidate:
            envelope_examples.append(candidate)
    assert envelope_examples, (
        f"Agent '{agent_name}' missing fenced ```json``` envelope example whose body parses as a JSON object containing 'envelope_version'. "
        "Per Req-018 each agent body must illustrate the schema with a complete example."
    )
    assert len(envelope_examples) == 1, (
        f"Agent '{agent_name}' contains {len(envelope_examples)} fenced ```json``` envelope examples. "
        "The lint pins the example envelope's agent_id and agent_effort_tier to the frontmatter; "
        "multiple examples would silently validate only the first. Consolidate to one canonical example, "
        "or move illustrative variants into the canonical doc (docs/reviewer_envelope.md) instead of the agent body."
    )
    parsed = envelope_examples[0]
    assert parsed["agent_id"] == expected_agent_id, (
        f"Agent '{agent_name}' example envelope agent_id is '{parsed['agent_id']}'; "
        f"frontmatter `name` is '{expected_agent_id}'. The two MUST match (TODO-0149 copy-paste guard)."
    )
    assert parsed["agent_effort_tier"] == expected_effort_tier, (
        f"Agent '{agent_name}' example envelope agent_effort_tier is '{parsed['agent_effort_tier']}'; "
        f"frontmatter `effort` is '{expected_effort_tier}'. The two MUST match (TODO-0149 copy-paste guard)."
    )
