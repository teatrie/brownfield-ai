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

Behavioural coverage alone is not enough, which is why this module also
compares the two routers' mirrored region directly. The behavioural assertions
enumerate their triggers, so a sixth trigger added to one router and not the
other satisfies every one of them while the mirror drifts — the same silent
divergence the routers themselves exist to close, reproduced one level up.

That comparison has two layers, because either one alone reproduces the
enumeration weakness a third time:

- Per-block byte-identity, driven by ``MIRRORED_BLOCK_MARKERS``. It renders a
  readable diff naming exactly what diverged, but its marker list is itself an
  enumeration: a third block added to one router only is not on the list, and
  every known block still matches.
- Set-equality of the task targets delegated below ``MIRROR_REGION_ANCHOR``,
  derived from the files rather than from any list. Adding or removing a block
  in one router changes that set and fails here whatever the markers say.

Lives under ``tests/helpers/`` for the same reason as ``router_harness``:
``pytest.ini`` sets ``--import-mode=importlib``, so a test's own directory is
not on ``sys.path``, while ``pythonpath = tests`` makes this package importable
as ``helpers.lint_router_harness``.
"""

import re
import subprocess
from collections.abc import Callable

import pytest

from helpers.router_harness import BLOCK_TERMINATOR, REPO_ROOT, assert_block_mirrored, diagnose

#: Every path the reviewer-template check reads: a reviewer prompt, the two
#: codex configs it scans for criteria that must live in the prompts instead,
#: the SKILL.md half of the mirrored rubric, and the checker itself. Each must
#: reach the check from either router.
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

#: Opening comment of each block the two routers must carry byte-identically,
#: matched as a line *prefix*. The cut at the em-dash buys a stable *locator*,
#: not tolerance: the header line sits inside the compared slice, so rewriting
#: its trailing prose in one router only still fails byte-identity, as it
#: should. What the short prefix avoids is the locator itself going stale on
#: that same edit and the marker resolving to nothing.
MIRRORED_BLOCK_MARKERS: tuple[str, ...] = (
    "# Reviewer template invariant check —",
    "# Reviewer Output Envelope compliance —",
)

#: Anchor for the mirrored region: the last check both routers carry *outside*
#: it. Everything after that block's closing ``fi`` is the tail the structural
#: assertion compares. The anchor is what keeps the comparison honest — the two
#: routers legitimately diverge above this line (different filters, different
#: block ordering, and lint_changed.sh carries a CI-scope preamble), so a
#: whole-file comparison would report drift that is not drift. A stale anchor
#: fails loudly rather than silently comparing nothing: extraction asserts it
#: appears exactly once.
MIRROR_REGION_ANCHOR = 'NON_PY_SQL_FILES=$(echo "$CHANGED_FILES"'

#: A delegation to ``task``, as both routers write it. The target names the
#: check, so the set of targets in the mirrored region *is* the set of checks
#: that region runs — read off the files, with no list to keep current.
#: Comment text cannot match, which is what stops lint_changed.sh's CI-scope
#: preamble from reading as a block a comment-header comparison would count.
TASK_DELEGATION = re.compile(r'"\$\{TASK_CMD\[@\]\}"\s+([^\s;]+)')

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


def mirrored_region_delegations(script: str) -> set[str]:
    """
    Collect the task targets a lint router delegates to below the anchor.

    Args:
        script: Router filename under ``ci/``.

    Returns:
        One entry per distinct task target delegated in the mirrored region.
    """
    lines = (REPO_ROOT / "ci" / script).read_text(encoding="utf-8").splitlines(keepends=True)
    anchors = [index for index, line in enumerate(lines) if line.startswith(MIRROR_REGION_ANCHOR)]
    assert len(anchors) == 1, f"ci/{script}: anchor {MIRROR_REGION_ANCHOR!r} found {len(anchors)} times, expected exactly 1"

    ends = [index for index in range(anchors[0], len(lines)) if lines[index].rstrip("\r\n") == BLOCK_TERMINATOR]
    assert ends, f"ci/{script}: anchor block has no closing {BLOCK_TERMINATOR!r}"

    targets = set(TASK_DELEGATION.findall("".join(lines[ends[0] + 1 :])))
    # Two empty sets compare equal, so a mis-anchored slice would pass
    # vacuously — the exact failure mode the region check exists to rule out.
    assert targets, f"ci/{script}: no task delegation found below the anchor block"
    return targets


def assert_mirrored_region_delegations_match() -> None:
    """Assert both lint routers run the same set of checks in the mirrored region."""
    left, right = LINT_ROUTERS
    left_targets = mirrored_region_delegations(left)
    right_targets = mirrored_region_delegations(right)
    assert left_targets == right_targets, (
        "the mirrored region of the two lint routers delegates to different task targets\n"
        f"only in ci/{left}: {sorted(left_targets - right_targets)}\n"
        f"only in ci/{right}: {sorted(right_targets - left_targets)}"
    )


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
        assert_block_mirrored(
            marker,
            routers=LINT_ROUTERS,
            boundaries=MIRRORED_BLOCK_MARKERS,
        )

    def test_mirrored_region_runs_the_same_checks(self) -> None:
        """Both routers delegate to the same task targets below the anchor.

        The check above can only compare blocks somebody remembered to name in
        ``MIRRORED_BLOCK_MARKERS``; this one reads the delegations straight out
        of the two files, so a block added to — or dropped from — one router
        alone fails without anyone updating a list. Reads both files and
        ignores ``SCRIPT`` for the same reason as its neighbour.
        """
        assert_mirrored_region_delegations_match()
