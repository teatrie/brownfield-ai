"""Registry-consistency tests for the reviewer agent-family registry.

Epic: REVIEWER-ENVELOPE-001 (TODO-0146 W4 prep).

The registry in :mod:`scripts.orchestrator.agent_family_registry` is the
single source of truth across five hand-maintained surfaces. Three of
those surfaces import the registry directly at runtime (parser, merge
function, lint test SCOPE). The other two — the JSON Schema's
``agent_family`` enum and the ``ENVELOPE_AGENTS`` regexes carried by
``ci/lint_staged.sh`` and ``ci/lint_changed.sh`` — cannot import Python
at runtime (JSON has no import; bash CI must stay portable across
macOS / Linux without a Python bootstrap). These tests cross-check
those two surfaces against the registry so drift surfaces in CI rather
than silently in production.

Adding a new family or agent ID without updating either dependent
fails one of these tests immediately.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.orchestrator.agent_family_registry import (
    AGENT_FAMILY_REGISTRY,
    KNOWN_WAVES,
    bridge_ceilings,
    bridge_lint_scope,
    lint_router_agent_ids,
    lint_scope,
    migrated_families_by_wave,
    schema_family_enum,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA_PATH = _REPO_ROOT / "docs" / "schemas" / "reviewer_envelope.schema.json"
_LINT_STAGED_PATH = _REPO_ROOT / "ci" / "lint_staged.sh"
_LINT_CHANGED_PATH = _REPO_ROOT / "ci" / "lint_changed.sh"

#: Both lint routers hand-maintain their own ``ENVELOPE_AGENTS`` regex;
#: ``lint_changed.sh`` is the one the CI ``lint`` job gates PRs on.
_LINT_ROUTER_PATHS = (_LINT_STAGED_PATH, _LINT_CHANGED_PATH)


def test_schema_enum_matches_registry() -> None:
    """[Req-002] [TODO-0146] Schema agent_family enum MUST match the registry.

    Adding a family to the registry without updating the schema, or
    vice-versa, breaks the contract that the parser validates envelopes
    against. The schema is the wire-format authority but the registry
    is the architectural authority — they MUST agree.
    """
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_enum = tuple(schema["properties"]["agent_family"]["enum"])
    registry_enum = schema_family_enum()
    assert schema_enum == registry_enum, (
        f"Schema agent_family enum drift: schema={schema_enum} vs registry={registry_enum}. "
        f"Update one of: docs/schemas/reviewer_envelope.schema.json or scripts/orchestrator/agent_family_registry.py."
    )


@pytest.mark.parametrize("router_path", _LINT_ROUTER_PATHS, ids=lambda path: path.name)
def test_lint_router_regex_covers_every_registry_agent_id(router_path: Path) -> None:
    """[TODO-0146] Shell ENVELOPE_AGENTS regex MUST match every registry agent ID.

    Each router's regex is hand-maintained (CI bash can't import Python)
    but MUST cover every realized agent ID in the registry. A registry
    agent ID that a router's regex fails to match would silently bypass
    the envelope gate on changes that touch only that agent — on the
    local pre-commit fast path for ``lint_staged.sh``, and on the PR
    itself for ``lint_changed.sh``.
    """
    shell_text = router_path.read_text(encoding="utf-8")
    match = re.search(r"^ENVELOPE_AGENTS=.*?-E\s+'([^']+)'", shell_text, re.MULTILINE)
    assert match, (
        f"Could not locate ENVELOPE_AGENTS regex in {router_path}. "
        f"The test depends on the line shape `ENVELOPE_AGENTS=$(... -E '<regex>' ...)`."
    )
    shell_regex = re.compile(match.group(1))
    registry_agent_ids = lint_router_agent_ids()
    unmatched = [agent_id for agent_id in registry_agent_ids if not shell_regex.match(f".claude/agents/{agent_id}.md")]
    assert not unmatched, (
        f"ci/{router_path.name} ENVELOPE_AGENTS regex does not match registry agent IDs: {unmatched}. "
        f"Widen the regex in ci/{router_path.name} or remove the agent ID from the registry."
    )


def test_lint_staged_regex_does_not_match_outside_registry() -> None:
    """[TODO-0146] Shell ENVELOPE_AGENTS regex MUST NOT match unknown agents.

    Registry forward-compat reserves families like ``copilot-bridge``
    with empty ``agent_ids`` until Wave 2+ migrates them. The shell
    regex MAY anticipate those future agents (the W1 regex already
    matches ``copilot-reviewer``, ``qa-*``) — that's fine; the registry
    is gradually catching up. But the regex MUST NOT match agents that
    are not reviewers at all (e.g., implementer agents, planner agents).
    The assertion here is a sanity check: a sample of clearly-unrelated
    agent paths is rejected by the regex.
    """
    shell_text = _LINT_STAGED_PATH.read_text(encoding="utf-8")
    match = re.search(r"^ENVELOPE_AGENTS=.*?-E\s+'([^']+)'", shell_text, re.MULTILINE)
    assert match, "ENVELOPE_AGENTS regex not found"
    shell_regex = re.compile(match.group(1))
    must_not_match = [
        ".claude/agents/orchestrator.md",
        ".claude/agents/planner.md",
        ".claude/agents/general-purpose.md",
        ".claude/agents/tdd-green.md",
        ".claude/agents/tdd-red.md",
        ".claude/agents/explore.md",
    ]
    matched = [path for path in must_not_match if shell_regex.match(path)]
    assert not matched, (
        f"ci/lint_staged.sh ENVELOPE_AGENTS regex unexpectedly matches non-reviewer agents: {matched}. "
        f"The regex must be reviewer-only — implementer / planner / explorer agents are not envelope-emitting."
    )


def test_lint_staged_regex_forward_compat_slack_pins_known_lookalikes() -> None:
    """[TODO-0146] Document the explicit forward-compat slack in the shell regex.

    The pair (``test_lint_router_regex_covers_every_registry_agent_id`` +
    ``test_lint_staged_regex_does_not_match_outside_registry``) is
    sufficient for CI drift detection but does NOT assert the regex
    matches *only* registry agent IDs. The shell regex
    ``qa-(standards|lint|test)(-(high|xhigh|max))?`` over-matches
    ``qa-lint-{high,xhigh,max}`` and ``qa-test-{high,xhigh,max}`` —
    which are not real registry agent IDs (qa-lint and qa-test are
    deterministic linters with no tiered variants). This is intentional
    forward-compat slack: if a future wave introduces tiered qa-lint or
    qa-test variants, the regex already covers them and only the
    registry needs updating.

    This test pins those known lookalikes so a future contributor who
    tightens the regex (removing the slack) sees this test fail and
    can intentionally also update the test list. Conversely, if any
    of these lookalikes graduate to a real registry agent_id, the
    coverage test ``test_lint_router_regex_covers_every_registry_agent_id``
    will continue to pass and this test should be updated to remove the
    graduated entries.
    """
    shell_text = _LINT_STAGED_PATH.read_text(encoding="utf-8")
    match = re.search(r"^ENVELOPE_AGENTS=.*?-E\s+'([^']+)'", shell_text, re.MULTILINE)
    assert match, "ENVELOPE_AGENTS regex not found"
    shell_regex = re.compile(match.group(1))
    registry_agent_ids = set(lint_router_agent_ids())
    forward_compat_lookalikes = [
        "qa-lint-high",
        "qa-lint-xhigh",
        "qa-lint-max",
        "qa-test-high",
        "qa-test-xhigh",
        "qa-test-max",
    ]
    for agent_id in forward_compat_lookalikes:
        assert agent_id not in registry_agent_ids, (
            f"Lookalike {agent_id!r} unexpectedly appears in the registry. "
            f"If it has graduated to a real agent, remove it from the "
            f"forward_compat_lookalikes list in this test."
        )
        assert shell_regex.match(f".claude/agents/{agent_id}.md"), (
            f"Lookalike {agent_id!r} no longer matches the ENVELOPE_AGENTS regex. "
            f"If the regex was intentionally tightened to remove forward-compat slack, "
            f"remove the entry from forward_compat_lookalikes."
        )


def test_migrated_families_view_includes_all_known_waves() -> None:
    """[Req-015] migrated_families_by_wave MUST emit one entry per known wave.

    Defensive: if a future contributor adds ``"W5"`` to ``KNOWN_WAVES``
    but no family carries that wave string, the result is an empty
    frozenset. That is still a valid (zero-coverage) wave; the test
    asserts the key is present so callers can rely on the dict shape.
    """
    view = migrated_families_by_wave()
    assert set(view.keys()) == set(KNOWN_WAVES), f"Wave coverage mismatch: {set(view.keys())} vs {set(KNOWN_WAVES)}"


def test_bridge_ceilings_view_excludes_no_cap_families() -> None:
    """[Req-005] bridge_ceilings MUST omit claude-native and qa-internal.

    These families have actual tier headroom up to ``max`` and are
    intentionally absent from the ceiling table — the parser's
    ``.get(family, "max")`` default and ``_reroute_at_ceiling``
    membership-guard handle them correctly. Adding them to the table
    would re-introduce the dead-code drift TODO-0144 closed.
    """
    ceilings = bridge_ceilings()
    no_cap_families = {name for name, family in AGENT_FAMILY_REGISTRY.items() if family.bridge_ceiling is None}
    overlap = no_cap_families & set(ceilings.keys())
    assert not overlap, (
        f"bridge_ceilings unexpectedly includes no-cap families: {overlap}. "
        f"Verify AGENT_FAMILY_REGISTRY entries — bridge_ceiling=None must be honored."
    )


def test_lint_scope_orders_by_registry_insertion() -> None:
    """[TODO-0146] lint_scope output ordering is deterministic and load-bearing.

    The pytest parametrize decorator on the lint tests displays test
    IDs in the order ``SCOPE`` declares them; deterministic ordering
    keeps test output stable across pytest invocations and Python
    versions. ``dict.values()`` preserves insertion order on
    Python ≥ 3.7, which is the contract this test pins.
    """
    scope = lint_scope()
    expected: list[str] = []
    for family in AGENT_FAMILY_REGISTRY.values():
        if family.waves:
            expected.extend(family.agent_ids)
    assert list(scope) == expected, (
        f"lint_scope ordering drift: scope={scope} vs expected={expected}. "
        f"Order is contract — the lint tests' parametrized IDs depend on it."
    )


def test_bridge_lint_scope_subset_of_lint_scope() -> None:
    """[TODO-0146] bridge_lint_scope MUST be a strict subset of lint_scope.

    Every agent in the bridge-only W2 lint scope MUST also be in the
    main lint scope. A bridge agent in BRIDGE_SCOPE but not SCOPE would
    skip the base envelope-token / canonical-doc / required-keys checks
    — defeating the per-wave scope-expansion contract.
    """
    bridges = set(bridge_lint_scope())
    full = set(lint_scope())
    missing = bridges - full
    assert not missing, f"BRIDGE_SCOPE entries not in SCOPE: {missing}. Every bridge agent must pass the base lint checks."


def test_registry_agent_files_exist() -> None:
    """[TODO-0146] Every realized registry agent_id MUST have an on-disk .md file.

    The registry is the architectural authority — but the agent files
    are the runtime authority. Adding an agent ID to the registry
    without creating the corresponding file leaves the lint to fail at
    runtime per agent; this test surfaces the problem at registry-edit
    time.
    """
    agents_dir = _REPO_ROOT / ".claude" / "agents"
    missing: list[str] = []
    for agent_id in lint_router_agent_ids():
        if not (agents_dir / f"{agent_id}.md").exists():
            missing.append(agent_id)
    assert not missing, (
        f"Registry references agent files that do not exist: {missing}. "
        f"Either create the agent file under .claude/agents/ or remove the agent_id from the registry."
    )
