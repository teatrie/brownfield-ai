"""Shared pieces for the ``ci/`` changed-file lint router tests.

``ci/lint_staged.sh`` and ``ci/lint_changed.sh`` decide which lint tasks a diff
maps to, then hand each one to ``task``. The routing decision is the part worth
testing; the lint run is not. The ``lint_route`` fixture in
``tests/ci/conftest.py`` shadows ``git`` (to inject a synthetic changed-file
list) and ``task`` (to swallow the execution stage while echoing the target it
was handed), and the assertions here read both the router's announcement line
and that echoed delegation.

The routers run in a fake workspace rather than the repository. Both drop
changed paths that are absent from the working tree, so the fixture
materialises an empty placeholder for every synthetic path — created in place
rather than symlinked from the repository, so no assertion can be swayed by
real file contents.

Announcement *and* delegation are both asserted: the announcement alone would
pass for a router that printed the banner and then called the wrong task
target, and the delegation alone would pass for one that ran the check silently
under a different branch.

Behavioural coverage alone is not enough, which is why this module also asserts
byte-identity of the two mirrored blocks directly. The behavioural assertions
enumerate their triggers, so a sixth trigger added to one router and not the
other satisfies every one of them while the mirror drifts — the same silent
divergence the routers themselves exist to close, reproduced one level up. The
only enforcement that byte-identity ever had was
``tmp/apply_reviewer_template_ci_routing.py``, which is untracked and dies with
``tmp/``; nothing in the committed tree compared the files. The parity
assertion below is that enforcement, made durable.

Lives under ``tests/helpers/`` for the same reason as ``router_harness``:
``pytest.ini`` sets ``--import-mode=importlib``, so a test's own directory is
not on ``sys.path``, while ``pythonpath = tests`` makes this package importable
as ``helpers.lint_router_harness``.
"""

import difflib
import subprocess
from collections.abc import Callable

import pytest

from helpers.router_harness import REPO_ROOT, diagnose

#: Every source the reviewer-template parity guard is built from or compares:
#: the reviewer prompt and the two codex configs the bridge template is
#: rendered from, the mirrored rubric half in SKILL.md, and the checker that
#: compares the two halves. Each must reach the check from either router.
REVIEWER_TEMPLATE_TRIGGERS: tuple[str, ...] = (
    ".claude/prompts/reviewer/diff.md",
    ".codex/config.toml",
    "docker/agent-cli/codex-config.toml",
    ".claude/skills/diff-review/SKILL.md",
    "scripts/lint_reviewer_templates.py",
)

TEMPLATE_ANNOUNCEMENT = "Checking reviewer template invariants..."

TEMPLATE_TASK = "lint:reviewer-templates"

#: Files that must re-run the Reviewer Output Envelope gate: a reviewer agent
#: definition, the canonical doc, or the schema.
REVIEWER_ENVELOPE_TRIGGERS: tuple[str, ...] = (
    ".claude/agents/code-review.md",
    ".claude/agents/codex-reviewer.md",
    "docs/reviewer_envelope.md",
    "docs/schemas/reviewer_envelope.schema.json",
)

ENVELOPE_ANNOUNCEMENT = "Checking reviewer envelope compliance..."

ENVELOPE_TASK = "lint:reviewer-envelope"

#: A file no reviewer-facing lint branch should react to.
UNRELATED_FILE = "README.md"

#: Prefix the task stub prints for each delegation, chosen so the assertions
#: read one stream (stdout) and ``diagnose`` keeps reporting the whole run.
TASK_MARKER = "TASK-INVOKED: "

TASK_STUB = """#!/usr/bin/env bash
# Echo the delegation so an assertion can prove *which* task target ran rather
# than only that the router printed its announcement line.
echo "TASK-INVOKED: $*"
exit 0
"""

#: The two lint routers, in the order the parity diff labels them.
LINT_ROUTERS: tuple[str, str] = ("lint_staged.sh", "lint_changed.sh")

#: Opening comment of each block the two routers must carry byte-identically.
#: Matched as a line *prefix* and cut at the em-dash so the assertion survives
#: a rewrite of the trailing prose in either header; the prefix through the
#: em-dash is the part that names the block.
MIRRORED_BLOCK_MARKERS: tuple[str, ...] = (
    "# Reviewer template invariant check —",
    "# Reviewer Output Envelope compliance —",
)

#: Closing line of a mirrored block. Both blocks are a single top-level ``if``
#: whose terminator sits at column 0, while their inner ``fi`` is indented, so
#: an exact match on the unindented token ends the slice at the right place.
BLOCK_TERMINATOR = "fi"

LintRouteFn = Callable[..., subprocess.CompletedProcess[str]]


def delegated_targets(result: subprocess.CompletedProcess[str]) -> list[str]:
    """
    Extract the task targets the router delegated to.

    Args:
        result: Completed router process.

    Returns:
        One target name per ``task`` invocation, in invocation order.
    """
    targets = []
    for line in result.stdout.splitlines():
        if not line.startswith(TASK_MARKER):
            continue
        argv = line[len(TASK_MARKER) :].split()
        if argv:
            targets.append(argv[0])
    return targets


def assert_check_ran(
    result: subprocess.CompletedProcess[str],
    announcement: str,
    task_target: str,
) -> None:
    """
    Assert the router announced a check and delegated it to the right target.

    The exit-code check is what separates "did not run the check" from "died
    under ``set -e`` before reaching it" — both leave the announcement absent.
    Every stub exits 0, so a non-zero code here is always a real router
    failure.

    Args:
        result: Completed router process.
        announcement: The banner the router prints before delegating.
        task_target: The task target the check must be handed to.
    """
    assert result.returncode == 0, f"router failed\n{diagnose(result)}"
    assert announcement in result.stdout, f"missing announcement {announcement!r}\n{diagnose(result)}"
    assert task_target in delegated_targets(result), f"missing delegation to {task_target!r}\n{diagnose(result)}"


def assert_check_skipped(
    result: subprocess.CompletedProcess[str],
    announcement: str,
    task_target: str,
) -> None:
    """
    Assert the router ran successfully and deliberately skipped a check.

    Args:
        result: Completed router process.
        announcement: The banner that must be absent.
        task_target: The task target that must not have been invoked.
    """
    assert result.returncode == 0, f"router failed\n{diagnose(result)}"
    assert announcement not in result.stdout, f"unexpected announcement {announcement!r}\n{diagnose(result)}"
    assert task_target not in delegated_targets(result), f"unexpected delegation to {task_target!r}\n{diagnose(result)}"


def extract_mirrored_block(script: str, marker: str) -> str:
    """
    Slice a marked block out of a lint router, line endings preserved.

    Located by marker rather than by line number, which drifts with every edit
    above the block. A marker seen more or fewer than once fails here instead
    of silently slicing the wrong region.

    Args:
        script: Router filename under ``ci/``.
        marker: Opening comment of the block, matched as a line prefix.

    Returns:
        The block from its opening comment through its closing ``fi``.
    """
    lines = (REPO_ROOT / "ci" / script).read_text(encoding="utf-8").splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.startswith(marker)]
    assert len(starts) == 1, f"ci/{script}: marker {marker!r} found {len(starts)} times, expected exactly 1"

    start = starts[0]
    ends = [index for index in range(start, len(lines)) if lines[index].rstrip("\r\n") == BLOCK_TERMINATOR]
    assert ends, f"ci/{script}: no closing {BLOCK_TERMINATOR!r} after marker {marker!r}"
    return "".join(lines[start : ends[0] + 1])


def assert_block_mirrored(marker: str) -> None:
    """
    Assert a marked block is byte-identical in both lint routers.

    Args:
        marker: Opening comment of the block, matched as a line prefix.
    """
    left, right = LINT_ROUTERS
    left_block = extract_mirrored_block(left, marker)
    right_block = extract_mirrored_block(right, marker)
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
    assert left_block == right_block, f"mirrored block {marker!r} diverged between the lint routers\n{diff}"


class LintRouterContract:
    """Lint-routing contract both routers must satisfy identically.

    Subclassed once per script rather than duplicated, for the same reason
    ``RouterContract`` is: the defect these tests exist to catch is drift
    between the two files. Drift is not cosmetic: the CI ``lint`` job runs
    ``task lint:changed`` and nothing else, so ``lint_changed.sh`` is the
    router a pull request is gated on, and a check only ``lint_staged.sh``
    carries never fires on one.

    Subclasses set ``SCRIPT`` to the filename under ``ci/``.
    """

    SCRIPT: str

    @pytest.mark.parametrize("trigger", REVIEWER_TEMPLATE_TRIGGERS)
    def test_template_trigger_runs_template_check(self, lint_route: LintRouteFn, trigger: str) -> None:
        """Every source of the mirrored rubric triggers the invariant check."""
        result = lint_route(self.SCRIPT, [trigger])
        assert_check_ran(result, TEMPLATE_ANNOUNCEMENT, TEMPLATE_TASK)

    def test_unrelated_file_does_not_run_template_check(self, lint_route: LintRouteFn) -> None:
        """A file outside the trigger set leaves the template check alone."""
        result = lint_route(self.SCRIPT, [UNRELATED_FILE])
        assert_check_skipped(result, TEMPLATE_ANNOUNCEMENT, TEMPLATE_TASK)

    @pytest.mark.parametrize("trigger", REVIEWER_ENVELOPE_TRIGGERS)
    def test_envelope_trigger_runs_envelope_check(self, lint_route: LintRouteFn, trigger: str) -> None:
        """A reviewer agent definition, the envelope doc, or its schema triggers the gate."""
        result = lint_route(self.SCRIPT, [trigger])
        assert_check_ran(result, ENVELOPE_ANNOUNCEMENT, ENVELOPE_TASK)

    def test_unrelated_file_does_not_run_envelope_check(self, lint_route: LintRouteFn) -> None:
        """A file outside the envelope trigger set leaves that gate alone."""
        result = lint_route(self.SCRIPT, [UNRELATED_FILE])
        assert_check_skipped(result, ENVELOPE_ANNOUNCEMENT, ENVELOPE_TASK)

    @pytest.mark.parametrize("marker", MIRRORED_BLOCK_MARKERS)
    def test_mirrored_block_is_byte_identical(self, marker: str) -> None:
        """Both routers carry the block byte-identically, whitespace included.

        Ignores ``SCRIPT`` and reads both files, so it is redundant across the
        two subclasses by construction. That redundancy is the point: a
        cross-file invariant asserted in only one subclass would not run when
        the *other* router is edited, since ``lint_changed.sh`` routes solely
        to ``tests/ci/test_lint_changed.py`` and ``lint_staged.sh`` solely to
        ``tests/ci/test_lint_staged.py``. Living on the shared contract is what
        makes an edit to either file reach the check.
        """
        assert_block_mirrored(marker)
