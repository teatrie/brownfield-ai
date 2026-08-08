"""Shared pieces for the ``ci/`` changed-file router tests.

``ci/test_staged.sh`` and ``ci/test_changed.sh`` decide which pytest targets a
diff maps to, then hand those targets to Docker. The routing decision is the
part worth testing; the container run is not. The ``route`` fixture in
``tests/ci/conftest.py`` shadows ``git`` (to inject a synthetic changed-file
list), plus ``docker`` and ``task`` (to swallow the execution stage), and the
assertions here read the targets back off the router's own announcement line.

The routers run in a fake workspace rather than the repository, which is what
lets the security gate be shadowed — it is invoked by a path relative to the
working directory, not through ``PATH``. Nothing here touches the real
repository state, so these tests assert on routing alone and nothing else.

Two deliberate limits:

- The security gate is stubbed, so its path-containment and tracked-file
  checks are **not** covered here. They belong to
  ``tests/scripts/test_python_security_gate.py``. Running the real gate was
  tried and abandoned: it writes ``tmp/.python-gate-pass``, which in CI is
  already owned by the outer gate run's uid, so the nested write failed with
  EACCES and ``set -e`` killed the router before it announced anything.
- Assertions read the announced targets rather than the exit code, because the
  code reports on the stubbed execution stage. It is not meaningless, though:
  the stubs exit 0, so a non-zero code means the router itself failed, and
  ``assert_routed_nothing`` checks it — otherwise a router that crashed before
  announcing would be indistinguishable from one that deliberately selected
  nothing.

Two assertions here deliberately read the repository instead of the fixture,
because each closes a hole the fixture cannot see:

- ``assert_reviewer_template_suite_pinned``. The fixture symlinks the real
  ``tests/`` into its fake workspace so the routers' ``[ -f "$test_file" ]``
  probes resolve, which means a behavioural assertion cannot distinguish "the
  router names a live suite" from "the router names a path that no longer
  exists". The literal is unpinned everywhere else, so a rename would leave
  both routers guarding a dead path and silently selecting zero tests.
- ``assert_block_mirrored``. Behavioural assertions enumerate their triggers,
  so a trigger added to one router and not the other satisfies every one of
  them while the two branches drift apart — the enumeration can only cover the
  triggers already known. Comparing the branch text itself needs no trigger
  list. ``helpers.lint_router_harness`` reuses the same extractor over the two
  lint routers.

The two test routers get per-block byte-identity only, with no region-level
delegation comparison of the kind ``helpers.lint_router_harness`` runs over the
lint pair, because outside the mirrored branch they legitimately diverge —
``test_changed.sh`` carries a ``docker/agent-cli/`` branch and a host-side
container-integration re-run that ``test_staged.sh`` has no counterpart for, and
the two dispatch chains open on different first-branch conditions — so an
anchored region comparison would report that intended divergence as drift.

Lives under ``tests/helpers/`` rather than beside the tests because
``pytest.ini`` sets ``--import-mode=importlib``, which does not put a test's
own directory on ``sys.path``; ``pythonpath = tests`` makes this package
importable as ``helpers.router_harness``.
"""

import difflib
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every hook registered in .claude/settings.json. None resolves under a
#: derive-the-test-filename scheme, which is why the router targets the
#: directory; see RouterContract.test_no_filename_derivation.
HOOKS: tuple[str, ...] = (
    ".claude/hooks/block-container-escape.sh",
    ".claude/hooks/block-docker-build-escape.sh",
    ".claude/hooks/block-sandbox-prompt-patterns.sh",
    ".claude/hooks/block-stranded-agent.sh",
    ".claude/hooks/block-terraform-escape.sh",
)

SETTINGS_FILES: tuple[str, ...] = (
    ".claude/settings.json",
    ".claude/settings.local.json",
)

#: The directory target both the hook and settings branches produce.
HOOKS_SUITE = "tests/hooks/"

#: Helper modules under tests/helpers/ that are imported by other suites rather
#: than exercised in place. Only the first two have a test file of their own,
#: which is why the branch routes to directories instead of deriving a name;
#: see RouterContract.test_no_helper_filename_derivation.
HELPER_MODULES: tuple[str, ...] = (
    "tests/helpers/eval_utils.py",
    "tests/helpers/runners.py",
    "tests/helpers/router_harness.py",
    "tests/helpers/lint_router_harness.py",
    "tests/helpers/aws_env.py",
)

#: The two directory targets a changed helper module produces. tests/ci/ is in
#: the pair because its router contracts import helpers.router_harness.
HELPER_SUITES = ("tests/ci/", "tests/helpers/")

#: A representative sample of the sources whose only automated gate is the
#: reviewer-template parity test, not a closed enumeration of what that test
#: reads. _invariants.md holds the canonical INVARIANT: blocks every reviewer
#: prompt under .claude/prompts/reviewer/ must reproduce verbatim; diff.md is
#: sampled as one such prompt, but scripts/lint_reviewer_templates.py discovers
#: the templates by glob (_discover_template_names), so its siblings in that
#: directory are checked too and reach the suite through the same branch. The
#: diff-review SKILL.md holds the SHARED: regions the bridge template diff.md
#: mirrors, and lint_reviewer_templates.py is the checker over both.
#:
#: The checker's Codex-TOML relationship (_check_codex_toml over TOML_PATHS) is
#: deliberately unrepresented: those two files are named by the *lint* routers'
#: trigger regex, but neither reaches this suite from a test router.
#: .codex/config.toml matches neither router's CHANGED_SCRIPTS filter, and
#: docker/agent-cli/codex-config.toml is claimed by the earlier agent-cli branch
#: in test_changed.sh before the reviewer-template branch is reached (and by no
#: branch at all in test_staged.sh, whose filter omits that prefix).
REVIEWER_TEMPLATE_SOURCES: tuple[str, ...] = (
    ".claude/prompts/reviewer/diff.md",
    ".claude/prompts/reviewer/_invariants.md",
    ".claude/skills/diff-review/SKILL.md",
    "scripts/lint_reviewer_templates.py",
)

#: The single target every reviewer-template source produces. The checker
#: cannot reach it through the scripts/* filename-derivation branch, which
#: builds tests/scripts/test_lint_reviewer_templates.py — a file that does not
#: exist, so editing the checker routes to nothing.
REVIEWER_TEMPLATE_SUITE = "tests/scripts/test_reviewer_templates.py"

#: The routers that hard-code REVIEWER_TEMPLATE_SUITE as a literal.
TEST_ROUTERS: tuple[str, str] = ("test_staged.sh", "test_changed.sh")

#: Opening line of the reviewer-template branch both test routers must carry
#: byte-identically. REVIEWER_TEMPLATE_SOURCES catches a trigger *dropped* from
#: one router — every source it lists must still route. It cannot catch one
#: *added* to a single router, because it can only enumerate triggers that
#: already exist; comparing the branch text needs no enumeration at all.
REVIEWER_TEMPLATE_BRANCH_MARKER = 'elif [[ "$file" == .claude/prompts/reviewer/* ]]'

#: Opening prefix shared by every branch of the changed-file dispatch chain.
#: A block slice ends at the next sibling branch rather than at the end of the
#: enclosing loop, which is the nearest closing ``fi`` these routers otherwise
#: offer — the whole rest of the dispatch chain would be swallowed without it.
BRANCH_BOUNDARY_MARKERS: tuple[str, ...] = ('elif [[ "$file" == ',)

#: Closing line of a block, matched against the line with **indentation
#: stripped** — so an indented ``fi`` matches. This is the ``elif`` branch's
#: inner ``if`` in the test routers, and the top-level ``if`` of each mirrored
#: block in the lint routers. Used by ``extract_marked_block``.
BLOCK_TERMINATOR = "fi"

#: Closing line of a block, matched at **column zero** — only the line ending is
#: stripped, so a nested ``fi`` does not match. Not interchangeable with
#: ``BLOCK_TERMINATOR``: the anchor block ``mirrored_region_delegations`` scans
#: forward from wraps a nested ``if`` whose own ``fi`` is indented, and
#: column-zero matching is what makes that scan stop at the *outer* ``fi``
#: instead of the inner one. Relaxing this to the indentation-stripped form
#: would silently move the region boundary, so the two semantics are carried as
#: separate constants rather than reconciled into one.
COLUMN_ZERO_BLOCK_TERMINATOR = "fi"

ANNOUNCE_PREFIX = "Running pytest (Docker) with "

GIT_STUB = """#!/usr/bin/env bash
# Fully synthetic git — nothing here reaches the real binary, so no assertion
# can be swayed by the state of the developer's or the runner's checkout.
#
# Matching on the subcommand rather than on flag positions keeps a router that
# reorders its flags (`git diff --cached --name-only`) from falling through
# unnoticed.
case "$1" in
    diff)
        # Every `git diff` in these routers is a changed-file query.
        cat "$ROUTER_TEST_CHANGED_FILES"
        ;;
    ls-files)
        shift
        case "${1:-}" in
            # Root-commit branch of test_changed.sh: "all tracked files".
            "") cat "$ROUTER_TEST_CHANGED_FILES" ;;
            # --others --exclude-standard: report no untracked files.
            *) ;;
        esac
        ;;
    rev-parse)
        # HEAD^ must resolve, or test_changed.sh takes its root-commit branch.
        echo "0000000000000000000000000000000000000000"
        ;;
    *)
        ;;
esac
exit 0
"""

NOOP_STUB = """#!/usr/bin/env bash
exit 0
"""

RouteFn = Callable[..., subprocess.CompletedProcess[str]]


def routed_targets(result: subprocess.CompletedProcess[str]) -> list[str]:
    """
    Extract the pytest targets the router announced.

    Args:
        result: Completed router process.

    Returns:
        The announced targets, or an empty list when the router routed nothing.
    """
    for line in result.stdout.splitlines():
        if line.startswith(ANNOUNCE_PREFIX):
            return line[len(ANNOUNCE_PREFIX) :].split()
    return []


def diagnose(result: subprocess.CompletedProcess[str]) -> str:
    """
    Render a router run for an assertion message.

    stderr carries as much as stdout here: under ``set -e`` a router that dies
    early prints nothing to stdout, so a stdout-only message reports that the
    target list was empty without saying why.

    Args:
        result: Completed router process.

    Returns:
        Exit code, stdout, and stderr, labelled.
    """
    return f"exit={result.returncode}\n--- stdout ---\n{result.stdout}--- stderr ---\n{result.stderr}"


def assert_routed_nothing(result: subprocess.CompletedProcess[str]) -> None:
    """
    Assert the router ran successfully and deliberately selected no targets.

    The exit-code check is what separates "chose nothing" from "died before it
    could announce anything" — both produce an empty target list. Nothing
    downstream of the stubs runs on this path, so a non-zero code here is
    always a real router failure.

    Args:
        result: Completed router process.
    """
    assert result.returncode == 0, f"router failed\n{diagnose(result)}"
    assert routed_targets(result) == [], f"expected no targets\n{diagnose(result)}"


def assert_reviewer_template_suite_pinned() -> None:
    """
    Assert both routers still name the reviewer-template suite, and that it exists.

    The branch in each router guards its literal with ``[ -f "$test_file" ]``,
    so a renamed or deleted suite makes both routers route *nothing* and report
    success — the silent zero-tests outcome that whole branch exists to
    prevent. Nothing else pins the literal, so the rename is invisible until a
    reviewer-prompt change ships unchecked.

    Reads the repository rather than the fixture's fake workspace: the fixture
    symlinks the real ``tests/`` in, so the router's own existence probe is
    satisfied by whatever the tree happens to contain, which is exactly the
    fact under test here.

    ``tests/scripts/test_reviewer_templates.py`` carries an inlined copy of
    this assertion rather than importing it. That duplication is deliberate:
    the helper fan-out in both routers sends a changed module under
    ``tests/helpers/`` to ``tests/helpers/`` and ``tests/ci/`` only, so an
    import from ``tests/scripts/`` would be a dependency no router covers and a
    rename here would break that file at collection time with nothing running
    to report it. Widening the fan-out is the alternative and costs the whole
    ``tests/scripts/`` suite on every helper edit. Do not merge the two copies.
    """
    suite = REPO_ROOT / REVIEWER_TEMPLATE_SUITE
    assert suite.is_file(), (
        f"{REVIEWER_TEMPLATE_SUITE} is missing; both routers guard it with `[ -f ]` "
        "and will route nothing — update the literal in "
        f"{', '.join(f'ci/{script}' for script in TEST_ROUTERS)} alongside the rename"
    )
    for script in TEST_ROUTERS:
        source = (REPO_ROOT / "ci" / script).read_text(encoding="utf-8")
        assert REVIEWER_TEMPLATE_SUITE in source, f"ci/{script} no longer routes to {REVIEWER_TEMPLATE_SUITE}"


def extract_marked_block(
    script: str,
    marker: str,
    *,
    boundaries: Sequence[str],
    terminator: str = BLOCK_TERMINATOR,
) -> str:
    """
    Slice a marked block out of a router script, line endings preserved.

    Located by marker rather than by line number, which drifts with every edit
    above the block. A marker seen more or fewer than once fails here instead
    of silently slicing the wrong region.

    The block ends at the *last* terminator inside the window running from the
    marker to the next sibling boundary — not the first. Stopping at the first
    is correct only while a block holds exactly one top-level statement: give
    it a second and the slice truncates, the un-compared tail is free to
    diverge, and the assertion still passes. Over-slicing is the safe
    direction, since it drags unrelated lines into a byte-identity comparison
    that then fails loudly; under-slicing fails silently, which is the one
    outcome a parity guard must not produce.

    Args:
        script: Router filename under ``ci/``.
        marker: Opening line of the block, matched as a prefix of the
            indentation-stripped line.
        boundaries: Opening-line prefixes of the sibling blocks that bound the
            search window.
        terminator: Line content, indentation stripped, that closes the block.

    Returns:
        The block from its opening line through its closing terminator.
    """
    lines = (REPO_ROOT / "ci" / script).read_text(encoding="utf-8").splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.lstrip().startswith(marker)]
    assert len(starts) == 1, f"ci/{script}: marker {marker!r} found {len(starts)} times, expected exactly 1"

    start = starts[0]
    window_end = next(
        (index for index in range(start + 1, len(lines)) if any(lines[index].lstrip().startswith(boundary) for boundary in boundaries)),
        len(lines),
    )
    ends = [index for index in range(start, window_end) if lines[index].strip() == terminator]
    assert ends, f"ci/{script}: no closing {terminator!r} between marker {marker!r} and the next block boundary"
    return "".join(lines[start : ends[-1] + 1])


def assert_block_mirrored(
    marker: str,
    *,
    routers: tuple[str, str],
    boundaries: Sequence[str],
    terminator: str = BLOCK_TERMINATOR,
) -> None:
    """
    Assert a marked block is byte-identical across a pair of routers.

    Args:
        marker: Opening line of the block, matched as a prefix of the
            indentation-stripped line.
        routers: The two router filenames under ``ci/``, in the order the
            rendered diff labels them.
        boundaries: Opening-line prefixes of the sibling blocks that bound the
            search window.
        terminator: Line content, indentation stripped, that closes the block.
    """
    left, right = routers
    left_block = extract_marked_block(left, marker, boundaries=boundaries, terminator=terminator)
    right_block = extract_marked_block(right, marker, boundaries=boundaries, terminator=terminator)
    # Rendered eagerly so the message names *what* diverged — indentation and
    # trailing whitespace included. A parity failure that reports only
    # "not equal" leaves the reader to diff two shell scripts by hand.
    diff = "".join(
        difflib.unified_diff(
            left_block.splitlines(keepends=True),
            right_block.splitlines(keepends=True),
            fromfile=f"ci/{left}",
            tofile=f"ci/{right}",
        )
    )
    assert left_block == right_block, f"mirrored block {marker!r} diverged between ci/{left} and ci/{right}\n{diff}"


class RouterContract:
    """Routing contract both routers must satisfy identically.

    Subclassed once per script rather than duplicated, because the defect these
    tests exist to catch was drift between the two files: ``test_changed.sh``
    carried a byte-identical copy of the broken branch in ``test_staged.sh``,
    so fixing one without the other would leave the pre-push gate blind.

    Subclasses set ``SCRIPT`` to the filename under ``ci/``.
    """

    SCRIPT: str

    @pytest.mark.parametrize("hook", HOOKS)
    def test_hook_alone_routes_to_suite(self, route: RouteFn, hook: str) -> None:
        """A hook edited on its own routes to the whole hooks suite."""
        result = route(self.SCRIPT, [hook])
        assert routed_targets(result) == [HOOKS_SUITE], f"{hook}\n{diagnose(result)}"

    @pytest.mark.parametrize("settings", SETTINGS_FILES)
    def test_settings_alone_routes_to_suite(self, route: RouteFn, settings: str) -> None:
        """A settings change routes to the suite holding its two guard tests."""
        result = route(self.SCRIPT, [settings])
        assert routed_targets(result) == [HOOKS_SUITE], f"{settings}\n{diagnose(result)}"

    def test_many_hooks_collapse_to_one_target(self, route: RouteFn) -> None:
        """Several changed hooks deduplicate to a single directory target."""
        result = route(self.SCRIPT, list(HOOKS))
        assert routed_targets(result) == [HOOKS_SUITE], diagnose(result)

    def test_hook_and_settings_collapse_to_one_target(self, route: RouteFn) -> None:
        """The hook and settings branches share one target without duplicating it."""
        result = route(self.SCRIPT, [HOOKS[0], SETTINGS_FILES[0]])
        assert routed_targets(result) == [HOOKS_SUITE], diagnose(result)

    @pytest.mark.parametrize("hook", HOOKS)
    def test_no_filename_derivation(self, route: RouteFn, hook: str) -> None:
        """No per-hook test filename is derived.

        Guards the reason for directory routing: hooks are dash-named, their
        tests underscore-named with a ``_hook`` suffix, and one pair shares no
        stem, so any derived name silently resolves to nothing.
        """
        derived = f"tests/hooks/test_{Path(hook).stem.replace('-', '_')}.py"
        result = route(self.SCRIPT, [hook])
        assert derived not in routed_targets(result), diagnose(result)

    def test_hook_test_file_still_routes_directly(self, route: RouteFn) -> None:
        """A changed test under tests/hooks/ is still added as itself."""
        test_file = "tests/hooks/test_block_stranded_agent_hook.py"
        result = route(self.SCRIPT, [test_file])
        assert routed_targets(result) == [test_file], diagnose(result)

    def test_unrelated_file_routes_nothing(self, route: RouteFn) -> None:
        """A file outside every branch selects no targets."""
        assert_routed_nothing(route(self.SCRIPT, ["README.md"]))

    def test_agent_definition_routes_to_variant_parity(self, route: RouteFn) -> None:
        """An agent .md change routes to the parity contract."""
        result = route(self.SCRIPT, [".claude/agents/code-review.md"])
        assert routed_targets(result) == ["tests/agents/test_variant_parity.py"], diagnose(result)

    def test_shared_docker_script_routes_by_derived_name(self, route: RouteFn) -> None:
        """docker/shared/ keeps filename derivation, which resolves for it."""
        result = route(self.SCRIPT, ["docker/shared/python-security-gate.sh"])
        assert routed_targets(result) == ["tests/scripts/test_python_security_gate.py"], diagnose(result)

    def test_independent_branches_accumulate(self, route: RouteFn) -> None:
        """Separate branches add targets rather than shadowing each other."""
        result = route(self.SCRIPT, [HOOKS[4], ".claude/agents/code-review.md"])
        expected = sorted([HOOKS_SUITE, "tests/agents/test_variant_parity.py"])
        assert sorted(routed_targets(result)) == expected, diagnose(result)

    def test_hook_alone_is_not_reported_as_untestable(self, route: RouteFn) -> None:
        """The original defect: a lone hook printed 'No testable scripts found'."""
        result = route(self.SCRIPT, [HOOKS[3]])
        assert "No testable scripts found." not in result.stdout, diagnose(result)

    @pytest.mark.parametrize("module", HELPER_MODULES)
    def test_helper_module_routes_to_helpers_and_ci(self, route: RouteFn, module: str) -> None:
        """A changed helper module routes to its own suite and to tests/ci/."""
        result = route(self.SCRIPT, [module])
        assert sorted(routed_targets(result)) == sorted(HELPER_SUITES), f"{module}\n{diagnose(result)}"

    @pytest.mark.parametrize("module", HELPER_MODULES)
    def test_no_helper_filename_derivation(self, route: RouteFn, module: str) -> None:
        """No per-module test filename is derived.

        Guards the reason for directory routing: some of these modules have no
        test file of their own, so a derivation rule resolves them to nothing —
        the silent un-routing this branch exists to close.
        """
        derived = f"tests/helpers/test_{Path(module).stem}.py"
        result = route(self.SCRIPT, [module])
        assert derived not in routed_targets(result), diagnose(result)

    def test_many_helper_modules_collapse_to_one_pair(self, route: RouteFn) -> None:
        """Several changed helper modules deduplicate to the same two targets."""
        result = route(self.SCRIPT, list(HELPER_MODULES))
        assert sorted(routed_targets(result)) == sorted(HELPER_SUITES), diagnose(result)

    def test_helper_test_file_still_routes_directly(self, route: RouteFn) -> None:
        """A changed test under tests/helpers/ is added as itself."""
        test_file = "tests/helpers/test_eval_utils.py"
        result = route(self.SCRIPT, [test_file])
        assert routed_targets(result) == [test_file], diagnose(result)

    def test_helper_module_alone_is_not_reported_as_untestable(self, route: RouteFn) -> None:
        """The defect: a lone helper module selected no targets at all."""
        result = route(self.SCRIPT, ["tests/helpers/router_harness.py"])
        assert "No scripts or script tests changed." not in result.stdout, diagnose(result)
        assert "No testable scripts found." not in result.stdout, diagnose(result)

    @pytest.mark.parametrize("source", REVIEWER_TEMPLATE_SOURCES)
    def test_reviewer_template_source_routes_to_parity_test(self, route: RouteFn, source: str) -> None:
        """Each mirrored rubric half, and the checker itself, routes to the parity test."""
        result = route(self.SCRIPT, [source])
        assert routed_targets(result) == [REVIEWER_TEMPLATE_SUITE], f"{source}\n{diagnose(result)}"

    def test_many_reviewer_template_sources_collapse_to_one_target(self, route: RouteFn) -> None:
        """Several changed reviewer-template sources deduplicate to a single target."""
        result = route(self.SCRIPT, list(REVIEWER_TEMPLATE_SOURCES))
        assert routed_targets(result) == [REVIEWER_TEMPLATE_SUITE], diagnose(result)

    def test_reviewer_template_branch_accumulates_with_agent_branch(self, route: RouteFn) -> None:
        """The reviewer-template branch adds a target rather than shadowing the agent branch."""
        result = route(self.SCRIPT, [".claude/skills/diff-review/SKILL.md", ".claude/agents/code-review.md"])
        expected = sorted([REVIEWER_TEMPLATE_SUITE, "tests/agents/test_variant_parity.py"])
        assert sorted(routed_targets(result)) == expected, diagnose(result)

    @pytest.mark.parametrize("source", REVIEWER_TEMPLATE_SOURCES)
    def test_reviewer_template_source_alone_is_not_reported_as_untestable(
        self,
        route: RouteFn,
        source: str,
    ) -> None:
        """The defect: the parity guard's own sources selected no targets at all."""
        result = route(self.SCRIPT, [source])
        assert "No scripts or script tests changed." not in result.stdout, f"{source}\n{diagnose(result)}"
        assert "No testable scripts found." not in result.stdout, f"{source}\n{diagnose(result)}"

    def test_reviewer_template_suite_path_is_pinned(self) -> None:
        """Both routers name the reviewer-template suite, and it exists on disk.

        Ignores ``SCRIPT`` and reads both routers, so it is redundant across
        the two subclasses by construction — the same trade the lint-router
        parity check makes. Each router routes only to its own test file, so a
        cross-file invariant asserted in one subclass would not run when the
        other router is edited. ``tests/scripts/test_reviewer_templates.py``
        carries the second entry point, covering the rename direction this
        module cannot see.
        """
        assert_reviewer_template_suite_pinned()

    def test_reviewer_template_branch_is_byte_identical(self) -> None:
        """Both routers carry the reviewer-template branch byte-identically.

        The behavioural assertions above enumerate ``REVIEWER_TEMPLATE_SOURCES``
        and so catch a trigger *dropped* from one router; a trigger *added* to
        one router only passes all of them, because an enumeration cannot list
        a trigger that does not exist yet. Comparing the branch text closes
        that direction without any list to maintain.

        Ignores ``SCRIPT`` and reads both routers, so it is redundant across
        the two subclasses by construction — the same trade
        ``test_reviewer_template_suite_path_is_pinned`` makes, and for the same
        reason: each router routes only to its own test file.
        """
        assert_block_mirrored(
            REVIEWER_TEMPLATE_BRANCH_MARKER,
            routers=TEST_ROUTERS,
            boundaries=BRANCH_BOUNDARY_MARKERS,
        )
