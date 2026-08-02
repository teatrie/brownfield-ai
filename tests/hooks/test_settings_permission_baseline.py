"""Baseline contract for ``.claude/settings.json`` ``permissions`` block.

Locks in the enumerated-allow + exclude-by-default permission surface
that TODO-0092 Phase C ships. The previous state was a single
``Bash(task *)`` wildcard: every ``task <anything>`` auto-approved at
Layer 0. Phase C replaces that wildcard with nine enumerated
namespaces and relies on exclusion (not deny) for all other
namespaces.

**Assertion layering rationale.** The ten assertions below separate
*intent pins* (exact-set equality — deliberately brittle against
accidental drift) from *security property pins* (negative-set,
composite-vulnerability, operator-authorization matrix — deliberately
permissive against legitimate additions to the allow set so long as
the security invariants hold). An intentional expansion of the allow
set requires updating the exact-set assertion, which surfaces the
change in review; a silent regression is caught by whichever property
pin it violates first.

**Scope.** This test reads ``.claude/settings.json`` only — the
committed baseline. ``.claude/settings.local.json`` is a per-developer
override that the Claude Code harness merges on top at runtime; this
test is concerned with the committed permission surface, not with the
effective runtime surface on any individual machine.

**Option F trust model** (per TODO-0092 Phase C R_C4). Destructive
task subtargets are kept out of the baseline by *excluding* the
enclosing namespace from allow (``repos:*``, ``aws:*``, ``ralph:*``,
``run:*``, etc.), not by adding task-level deny entries. The single
exception is ``ledger:check-reviews``: the enclosing ``ledger:*`` is
allowed because other ``ledger:*`` subtargets (``status``, ``set-prs``,
``create``, ``resume``, ``index``, ``checkpoint``) are routinely
invoked from Claude-session skills and agents. The ``check-reviews``
subtarget *is* reachable through the allow list — intentionally —
because the operator (ralph autonomous, user terminal, or user
supervising a Claude session) is the authorization boundary for the
PR-state sweep it performs, not the permission matcher.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_SETTINGS = REPO_ROOT / ".claude" / "settings.json"
LOCAL_SETTINGS = REPO_ROOT / ".claude" / "settings.local.json"

EXPECTED_ALLOW_SET: frozenset[str] = frozenset({
    "Bash(task agent:*)",
    "Bash(task findings:*)",
    "Bash(task gh:*)",
    "Bash(task git:*)",
    "Bash(task ledger:*)",
    "Bash(task lint:*)",
    "Bash(task test:*)",
    "Bash(task todo:*)",
})

_ALLOW_ENTRY_SHAPE = re.compile(r"^Bash\(task [a-z][a-z0-9-]*:\*\)$")

EXCLUDED_NAMESPACES: frozenset[str] = frozenset({
    "run",
    "repos",
    "aws",
    "ralph",
    "chromadb",
    "builders",
    "sh",
    "dashboard",
})

EXEC_NAMESPACES: frozenset[str] = frozenset({"run"})
"""Namespaces whose subtargets can execute arbitrary caller-supplied code.

Paired with a ``Write(tmp/**)`` grant, any of these would form a
silent code-execution path. Any future namespace that exposes a
``run``-shaped subtarget (``exec:*``, ``eval:*``, etc.) MUST be added
here so the composite-vulnerability assertion covers it.
"""

OPERATOR_AUTHORIZED_DESTRUCTIVE: frozenset[str] = frozenset({
    "task ledger:check-reviews",
})
"""Destructive task subtargets that are reachable via allow by design.

Each entry corresponds to a task where the caller's intent — not the
permission matcher — is the authorization boundary. The operator
(ralph loop runner, user in their terminal, or user asking a Claude
session to perform the sweep) is trusted to authorize the mutation.
Do not expand this set without an explicit trust-model review.
"""


def _load_committed_settings() -> dict[str, Any]:
    """Parse the committed ``.claude/settings.json`` into a dict.

    Fails loud on missing file or malformed JSON — both regressions
    would otherwise silently disable the permission matcher and fall
    back to interactive prompts for every call.
    """
    return cast(dict[str, Any], json.loads(COMMITTED_SETTINGS.read_text(encoding="utf-8")))


def _allow_list(settings: dict[str, Any]) -> list[str]:
    """Extract the ``permissions.allow`` list from a settings dict."""
    permissions = cast(dict[str, Any], settings.get("permissions", {}))
    return cast(list[str], permissions.get("allow", []))


def _deny_list(settings: dict[str, Any]) -> list[str]:
    """Extract the ``permissions.deny`` list from a settings dict."""
    permissions = cast(dict[str, Any], settings.get("permissions", {}))
    return cast(list[str], permissions.get("deny", []))


class TestPermissionBaseline:
    """Ten-assertion contract for the committed permission surface."""

    def test_allow_list_exact_set_equality(self) -> None:
        """Assertion #1 — intent pin: the allow set is exactly the eight entries.

        Deliberately brittle. An intentional addition must update this
        set alongside the change, surfacing the expansion in code
        review. A silent drift in either direction fails here.
        """
        settings = _load_committed_settings()
        actual = frozenset(_allow_list(settings))
        assert actual == EXPECTED_ALLOW_SET, f"allow-list drift — expected {sorted(EXPECTED_ALLOW_SET)}, got {sorted(actual)}"

    def test_allow_entries_match_structural_form(self) -> None:
        """Assertion #2 — every allow entry is ``Bash(task <ns>:*)`` shape.

        Catches any future entry that sneaks in as a bare wildcard, a
        non-task Bash pattern, or a non-Bash permission. Pairs with
        the no-blanket assertion to make the intended shape explicit.
        """
        settings = _load_committed_settings()
        violations = [entry for entry in _allow_list(settings) if not _ALLOW_ENTRY_SHAPE.match(entry)]
        assert not violations, f"allow entries must match ``Bash(task <ns>:*)`` — offenders: {violations}"

    def test_no_blanket_task_wildcard(self) -> None:
        """Assertion #3 — the pre-Phase-C ``Bash(task *)`` wildcard is absent.

        Protects against an accidental merge that reintroduces the
        blanket. The exact-set assertion already forbids it, but this
        assertion gives the regression a human-readable failure
        message pointing directly at the regressed entry.
        """
        settings = _load_committed_settings()
        assert "Bash(task *)" not in _allow_list(settings), (
            "blanket ``Bash(task *)`` reintroduced — every task auto-approves at Layer 0 again"
        )

    def test_excluded_namespaces_are_absent_from_allow(self) -> None:
        """Assertion #4 — no allow entry references an excluded namespace.

        Each namespace in ``EXCLUDED_NAMESPACES`` is excluded for a
        documented reason (destructive, interactive, operator-only, or
        composite-vuln paired). A future expansion that pulls one of
        them in must first update this set, which surfaces the
        decision in review.
        """
        settings = _load_committed_settings()
        allow = _allow_list(settings)
        violations = [entry for entry in allow for ns in EXCLUDED_NAMESPACES if entry == f"Bash(task {ns}:*)"]
        assert not violations, f"allow contains excluded-namespace entries: {violations}"

    def test_composite_vulnerability_not_latent(self) -> None:
        """Assertion #5 — no ``Write(tmp/**)`` × exec-namespace pair.

        ``task run:adhoc -- tmp/<anything>.py`` executes
        caller-supplied code. Paired with a ``Write(tmp/**)`` grant
        (or any permission that lets an attacker drop a Python file
        into ``tmp``), the pair forms a silent code-execution path.
        This assertion keeps the two sides disjoint: neither may
        appear on its own if the other is present; in the current
        state, both are absent.
        """
        settings = _load_committed_settings()
        allow = _allow_list(settings)
        has_tmp_write = any("Write(tmp/" in entry for entry in allow)
        exec_allows = [
            entry for entry in allow for ns in EXEC_NAMESPACES if entry.startswith(f"Bash(task {ns}:") or entry == f"Bash(task {ns}:*)"
        ]
        assert not (has_tmp_write and exec_allows), (
            f"composite vulnerability: Write(tmp/**) paired with exec-namespace allow — "
            f"tmp_write={has_tmp_write}, exec_allows={exec_allows}"
        )

    def test_operator_authorized_destructive_matrix(self) -> None:
        """Assertion #6 — destructive-by-allow targets match the trusted matrix.

        Any task that mutates shared state or performs remote-visible
        actions (PR close, branch delete, etc.) MUST either be denied
        at the matcher / hook layer, or appear in
        ``OPERATOR_AUTHORIZED_DESTRUCTIVE`` with a documented
        trust-boundary rationale. New destructive subtargets cannot
        slip in through a namespace blanket without tripping this
        assertion's maintenance.

        Today: ``ledger:check-reviews`` is the sole entry — trust
        boundary is the operator (ralph, user-terminal, or user
        asking a Claude session to sweep). The ``ledger:*`` allow
        covers it by design. See module docstring for the full
        rationale.
        """
        assert "task ledger:check-reviews" in OPERATOR_AUTHORIZED_DESTRUCTIVE, (
            "trust-matrix drift — ``task ledger:check-reviews`` must remain documented as operator-authorized or be denied explicitly."
        )

    def test_task_level_deny_entries_are_absent(self) -> None:
        """Assertion #7 — deny list contains no ``Bash(task ...)`` entries.

        Option F's trust model uses exclusion (not deny) for
        destructive namespaces and operator-authorization (not deny)
        for the single destructive-by-allow exception. Adding a
        task-level deny would be a shape change worth surfacing in
        review; this assertion forces that surfacing. Hook-based
        content denies (``block-container-escape.sh`` et al.) are the
        correct layer for per-target rules and are not affected.
        """
        settings = _load_committed_settings()
        task_denies = [entry for entry in _deny_list(settings) if entry.startswith("Bash(task ")]
        assert not task_denies, f"task-level deny entries introduced — expected exclusion-based model. Offenders: {task_denies}"

    def test_no_legacy_codex_reviewer_setup_references(self) -> None:
        """Assertion #8 — rename-regression guard for ``setup:codex-reviewer``.

        TODO-0092 Phase A migrated all callers off
        ``task setup:codex-reviewer`` to
        ``task agent:setup:codex-reviewer``. A re-introduction of the
        pre-migration name anywhere under ``.claude/``, ``workflows/``,
        ``docs/``, ``.github/instructions/``, or the repository root
        markdown would reintroduce the bridge-ambiguity class that
        Phase A resolved. Settings.json is the anchor here because
        the allow list no longer includes ``Bash(task setup:*)`` —
        so the old name would fail to match anything, silently
        breaking any caller that kept the old reference.
        """
        scan_roots: list[Path] = [
            REPO_ROOT / ".claude",
            REPO_ROOT / "workflows",
            REPO_ROOT / "docs",
            REPO_ROOT / ".github" / "instructions",
        ]
        offenders: list[str] = []
        for root in scan_roots:
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix not in {".md", ".json", ".yml", ".yaml", ".toml", ".sh", ".py"}:
                    continue
                try:
                    content = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                if "task setup:codex-reviewer" in content:
                    offenders.append(str(path.relative_to(REPO_ROOT)))
        for md_path in REPO_ROOT.glob("*.md"):
            content = md_path.read_text(encoding="utf-8")
            if "task setup:codex-reviewer" in content:
                offenders.append(str(md_path.relative_to(REPO_ROOT)))
        assert not offenders, f"pre-Phase-A ``task setup:codex-reviewer`` references reintroduced: {offenders}"

    def test_settings_local_json_is_not_consulted(self) -> None:
        """Assertion #9 — the loader reads only the committed settings file.

        Structural self-check: the committed baseline is the contract
        under review. ``settings.local.json`` is a per-developer
        override (gitignored) and MUST NOT influence any assertion
        above. The check inspects the AST of ``_load_committed_settings``
        only — looking at the whole module's source would match the
        marker strings declared in this assertion itself, a
        tautological failure.
        """
        tree = ast.parse(inspect.getsource(_load_committed_settings))
        forbidden_names = {"LOCAL_SETTINGS"}
        local_refs = [node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id in forbidden_names]
        assert not local_refs, f"_load_committed_settings must not reference {forbidden_names}; found {local_refs}"
        assert LOCAL_SETTINGS.name == "settings.local.json", "LOCAL_SETTINGS constant renamed — review the scope-pin above"

    def test_settings_json_self_edit_denies_present(self) -> None:
        """Assertion #10 — settings.json self-edit protection is preserved.

        Both ``Edit(.claude/settings.json)`` and
        ``Write(.claude/settings.json)`` MUST remain in the deny list.
        This protects against silent self-privilege-escalation: a
        compromised or prompt-injected agent that can Edit/Write the
        settings file can add arbitrary allow entries or disable hooks.

        The pin is deliberately narrow — it asserts the two literal
        deny entries and nothing more. If a maintainer needs to
        temporarily drop one (e.g., to let Claude itself apply a
        reviewed narrowing change in-session), this test forces the
        removal to appear in a review diff rather than slipping in
        unseen.
        """
        settings = _load_committed_settings()
        deny = set(_deny_list(settings))
        required = {"Edit(.claude/settings.json)", "Write(.claude/settings.json)"}
        missing = required - deny
        assert not missing, f"settings.json self-edit deny entries missing from deny list: {sorted(missing)}"
