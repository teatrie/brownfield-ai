"""Shared pieces for the ``ci/`` changed-file lint router tests.

``ci/lint_staged.sh`` and ``ci/lint_changed.sh`` decide which lint tasks a diff
maps to. The routing decision is what is under test; the lint run is not. The
``lint_route`` fixture in ``tests/ci/conftest.py`` shadows ``git`` (to inject a
synthetic changed-file list) and ``task`` (to swallow the execution stage while
echoing the target it was handed).

Announcement *and* delegation are both asserted: the announcement alone would
pass for a router that printed the banner and then called the wrong task
target, and the delegation alone would pass for one that ran the check silently
under a different branch.

Behavioural assertions enumerate their triggers, so a trigger added to one
router and not the other satisfies every one of them while the mirror drifts.
This module therefore also compares the two routers' mirrored region directly,
in two layers: per-block byte-identity driven by ``MIRRORED_BLOCK_MARKERS``,
which renders a readable diff but is itself an enumeration; and
multiset-equality of the task targets delegated below ``MIRROR_REGION_ANCHOR``,
which is derived from the files and needs no list. The second layer compares
``"${TASK_CMD[@]}" <target>`` delegations and nothing else, so text below the
anchor that is neither a delegation nor inside a markered block — such as
``lint_changed.sh``'s CI-scope preamble — is compared by nothing here.

Lives under ``tests/helpers/`` for the same reason as ``router_harness``:
``pytest.ini`` sets ``--import-mode=importlib``, so a test's own directory is
not on ``sys.path``, while ``pythonpath = tests`` makes this package importable
as ``helpers.lint_router_harness``.
"""

import re
import subprocess
from collections import Counter
from collections.abc import Callable
from typing import Any

import pytest
import yaml

from helpers.router_harness import BLOCK_TERMINATOR, REPO_ROOT, assert_block_mirrored, diagnose
from scripts.orchestrator.agent_family_registry import lint_router_agent_ids

#: Paths that must reach the reviewer-template check from either router.
REVIEWER_TEMPLATE_TRIGGERS: tuple[str, ...] = (
    ".claude/prompts/reviewer/diff.md",
    ".codex/config.toml",
    "docker/agent-cli/codex-config.toml",
    ".claude/skills/diff-review/SKILL.md",
    "scripts/lint_reviewer_templates.py",
)

TEMPLATE_ANNOUNCEMENT = "Checking reviewer template invariants..."

TEMPLATE_TASK = "lint:reviewer-templates"

#: Files that must re-run the Reviewer Output Envelope gate. The agent paths
#: are derived from the same registry the routers' ``ENVELOPE_AGENTS`` regex is
#: cross-checked against in
#: ``tests/scripts/orchestrator/test_agent_family_registry.py``, so an agent ID
#: added there is exercised here without a second list to keep current. The doc
#: and schema paths are selected by the routers' separate ``ENVELOPE_DOCS``
#: pattern and have no registry counterpart.
REVIEWER_ENVELOPE_TRIGGERS: tuple[str, ...] = (
    *(f".claude/agents/{agent_id}.md" for agent_id in lint_router_agent_ids()),
    "docs/reviewer_envelope.md",
    "docs/schemas/reviewer_envelope.schema.json",
)

ENVELOPE_ANNOUNCEMENT = "Checking reviewer envelope compliance..."

ENVELOPE_TASK = "lint:reviewer-envelope"

#: A file no reviewer-facing lint branch should react to.
UNRELATED_FILE = "README.md"

#: Paths that share a prefix with a template trigger but must not reach the
#: check. ``UNRELATED_FILE`` shares no prefix with any trigger, so it passes
#: against an unanchored or extension-blind rewrite of the trigger regex as
#: readily as against the current one; each entry here is a near miss on a
#: different part of that regex — file extension, exact filename, and the
#: leading ``^`` — so relaxing any of the three fails.
TEMPLATE_NEAR_MISSES: tuple[str, ...] = (
    ".claude/prompts/reviewer/diff.txt",
    ".claude/skills/diff-review/README.md",
    "docs/notes/.claude/skills/diff-review/SKILL.md",
)

#: An agent definition under the directory the envelope trigger matches, whose
#: ID is outside the reviewer alternation. The gate is deliberately broader
#: than the registry, so this pins the outer edge of that slack rather than the
#: registry's own boundary.
ENVELOPE_NEAR_MISSES: tuple[str, ...] = (".claude/agents/orchestrator.md",)

#: Template triggers asserted to reach the check on a diff that *deletes*
#: them. Both routers narrow their changed-file list to paths present in the
#: working tree before the per-language lint dispatch, since linting a file
#: that is no longer there is meaningless. The reviewer gates select on path
#: alone and re-run a whole check rather than lint the named file, so they read
#: the list from before that filter — a removed reviewer prompt changes what
#: the check concludes just as much as an edited one does. One trigger suffices
#: here: a single grep, ``TEMPLATE_FILES``, feeds this gate.
DELETED_TEMPLATE_TRIGGERS: tuple[str, ...] = (".claude/prompts/reviewer/diff.md",)

#: Envelope triggers asserted to reach the gate on a diff that deletes them,
#: for the reason given above. Two entries because two greps feed this gate —
#: ``ENVELOPE_AGENTS`` and ``ENVELOPE_DOCS`` — and either reading the filtered
#: list must fail on its own.
DELETED_ENVELOPE_TRIGGERS: tuple[str, ...] = (
    ".claude/agents/code-review.md",
    "docs/reviewer_envelope.md",
)

#: A template trigger that is also an ordinary Markdown file, used to pin the
#: other side of the pre-filter boundary: the reviewer gates read the
#: unfiltered list, every per-filetype lint stage reads the filtered one.
MARKDOWN_TEMPLATE_TRIGGER = ".claude/prompts/reviewer/diff.md"

#: The per-filetype stage ``MARKDOWN_TEMPLATE_TRIGGER`` reaches when it exists.
MARKDOWN_TASK = "lint:markdown"

#: Prefix the task stub prints for each delegation.
TASK_MARKER = "TASK-INVOKED: "

#: Interpolates TASK_MARKER rather than repeating the literal: the stub writes
#: the prefix and ``delegated_targets`` strips it, so hand-kept copies would
#: drift.
TASK_STUB = f"""#!/usr/bin/env bash
# Report the delegation so an assertion can prove *which* task target ran
# rather than only that the router printed its announcement line.
printf '%s%s\\n' "{TASK_MARKER}" "$*"
exit 0
"""

#: The two lint routers, in the order the parity diff labels them.
LINT_ROUTERS: tuple[str, str] = ("lint_staged.sh", "lint_changed.sh")

#: Opening comment of each block the two routers must carry byte-identically,
#: matched as a line *prefix*. The cut at the em-dash buys a stable locator,
#: not tolerance: the header line sits inside the compared slice, so rewording
#: its trailing prose in one router only still fails byte-identity.
MIRRORED_BLOCK_MARKERS: tuple[str, ...] = (
    "# Reviewer template invariant check —",
    "# Reviewer Output Envelope compliance —",
)

#: Anchor bounding the region ``mirrored_region_delegations`` tallies: the last
#: check both routers carry *outside* the mirrored tail. Everything after that
#: block's closing ``fi`` is compared. The comparison is an order-insensitive
#: multiset of task targets, not a byte comparison, so it already tolerates the
#: two routers running the same checks in a different order; what the anchor
#: buys is scope — each router's own dispatch chain above this line is under no
#: parity contract here.
MIRROR_REGION_ANCHOR = 'NON_PY_SQL_FILES=$(echo "$CHANGED_FILES"'

#: A delegation to ``task``, as both routers write it. The target names the
#: check, so the multiset of matches in the mirrored region *is* the tally of
#: checks that region runs — read off the files, with no list to keep current.
TASK_DELEGATION = re.compile(r'"\$\{TASK_CMD\[@\]\}"\s+([^\s;]+)')

#: Home of the aggregate ``lint`` task, the full-sweep counterpart to the
#: routers' incremental dispatch.
TASKFILE_PATH = REPO_ROOT / "Taskfile.yml"

#: Task targets the aggregate ``lint`` task must invoke. Each is wired into the
#: two routers incrementally as well, so a target dropped from the aggregate
#: leaves the check firing only on a diff that happens to touch its triggers.
AGGREGATE_LINT_REQUIRED_TASKS: tuple[str, ...] = (TEMPLATE_TASK, ENVELOPE_TASK)

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


def mirrored_region_delegations(script: str) -> Counter[str]:
    """
    Count the task targets a lint router delegates to below the anchor.

    The region opens at the *first* column-zero terminator at or after the
    anchor, which maximises the compared text: opening at a later one would
    drop the leading blocks of the mirrored region and let them diverge unseen.
    Matching ``BLOCK_TERMINATOR`` at column zero rather than with indentation
    stripped is what makes that scan stop at the anchor block's *outer* ``fi``:
    the block wraps a nested ``if`` whose own ``fi`` is indented.

    Args:
        script: Router filename under ``ci/``.

    Returns:
        One count per task target delegated in the mirrored region, so a
        repeated delegation is distinguishable from a single one.
    """
    lines = (REPO_ROOT / "ci" / script).read_text(encoding="utf-8").splitlines(keepends=True)
    anchors = [index for index, line in enumerate(lines) if line.startswith(MIRROR_REGION_ANCHOR)]
    assert len(anchors) == 1, f"ci/{script}: anchor {MIRROR_REGION_ANCHOR!r} found {len(anchors)} times, expected exactly 1"

    ends = [index for index in range(anchors[0], len(lines)) if lines[index].rstrip("\r\n") == BLOCK_TERMINATOR]
    assert ends, f"ci/{script}: anchor block has no closing {BLOCK_TERMINATOR!r} at column zero"

    targets = Counter(TASK_DELEGATION.findall("".join(lines[ends[0] + 1 :])))
    # Two empty counters compare equal, so a mis-anchored slice would pass
    # vacuously — the exact failure mode the region check exists to rule out.
    assert targets, f"ci/{script}: no task delegation found below the anchor block"
    return targets


def assert_mirrored_region_delegations_match() -> None:
    """Assert both lint routers run the same checks, as many times each, below the anchor.

    Order-insensitive: reordering the mirrored blocks in both routers in step
    is legitimate and must not fail here.
    """
    left, right = LINT_ROUTERS
    left_targets = mirrored_region_delegations(left)
    right_targets = mirrored_region_delegations(right)
    assert left_targets == right_targets, (
        "the mirrored region of the two lint routers delegates to different task targets\n"
        f"surplus in ci/{left}: {sorted((left_targets - right_targets).elements())}\n"
        f"surplus in ci/{right}: {sorted((right_targets - left_targets).elements())}"
    )


def aggregate_lint_subtasks() -> list[str]:
    """
    Read the sub-tasks the aggregate ``lint`` task in ``Taskfile.yml`` runs.

    Parsed as YAML rather than matched as text: a substring search would be
    satisfied by the target's name appearing in a ``desc:`` block or in a
    neighbouring task, so a removed ``cmds:`` entry would slip through.

    Returns:
        The ``task:`` value of every mapping entry in the aggregate task's
        ``cmds`` list, in file order. Plain-string ``cmds`` entries are shell
        commands, not sub-task invocations, and are skipped.
    """
    document: Any = yaml.safe_load(TASKFILE_PATH.read_text(encoding="utf-8"))
    cmds = document["tasks"]["lint"]["cmds"]
    return [entry["task"] for entry in cmds if isinstance(entry, dict) and "task" in entry]


def assert_aggregate_lint_runs_reviewer_checks() -> None:
    """
    Assert the aggregate ``lint`` task still invokes both reviewer checks.

    Coverage is partial by construction: ``Taskfile.yml`` matches no routing
    branch in either test router, so an edit to the aggregate task on its own
    selects no tests and this assertion does not run. Hanging it off
    ``LintRouterContract`` buys the reachable half, since any edit to either
    lint router routes to ``tests/ci/``. Routing ``Taskfile.yml`` itself is the
    remaining gap, filed as a TODO rather than closed here.
    """
    subtasks = aggregate_lint_subtasks()
    missing = [target for target in AGGREGATE_LINT_REQUIRED_TASKS if target not in subtasks]
    assert not missing, (
        f"the aggregate `lint` task in {TASKFILE_PATH.name} no longer runs {missing} — "
        f"a full `task lint` would skip {'those checks' if len(missing) > 1 else 'that check'}, "
        f"leaving them to fire only when a diff happens to touch their triggers. Found: {subtasks}"
    )


class LintRouterContract:
    """Lint-routing contract both routers must satisfy identically.

    Subclassed once per script rather than duplicated, for the same reason
    ``RouterContract`` is: the defect these tests exist to catch is drift
    between the two files. The CI ``lint`` job runs ``task lint:changed`` and
    nothing else, so a check only ``lint_staged.sh`` carries never fires on a
    pull request.

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

    @pytest.mark.parametrize("near_miss", TEMPLATE_NEAR_MISSES)
    def test_near_miss_path_does_not_run_template_check(self, lint_route: LintRouteFn, near_miss: str) -> None:
        """A path that near-misses a template trigger leaves the check alone."""
        result = lint_route(self.SCRIPT, [near_miss])
        assert_check_skipped(result, TEMPLATE_ANNOUNCEMENT, TEMPLATE_TASK)

    @pytest.mark.parametrize("trigger", DELETED_TEMPLATE_TRIGGERS)
    def test_deleted_template_trigger_runs_template_check(self, lint_route: LintRouteFn, trigger: str) -> None:
        """A template trigger the diff removes still reaches the invariant check.

        The path is listed as changed but withheld from the working tree, so it
        is dropped by the routers' existence filter and survives only in the
        pre-filter list the trigger grep reads.
        """
        result = lint_route(self.SCRIPT, [trigger], absent=[trigger])
        assert_check_ran(result, TEMPLATE_ANNOUNCEMENT, TEMPLATE_TASK)

    def test_deleted_template_trigger_does_not_reach_markdown_lint(self, lint_route: LintRouteFn) -> None:
        """A deleted trigger reaches the reviewer gate but not the Markdown stage.

        The pre-filter list is read by the three reviewer-gate triggers and by
        nothing else; handing a path that is no longer on disk to a stage that
        opens the file would break it. Only the reviewer gate's own trigger may
        widen, so the same route is asserted from both sides at once.

        The control route establishes that the path does reach the Markdown
        stage when it exists, without which the negative assertion would hold
        for a path that never routed there in the first place.
        """
        control = lint_route(self.SCRIPT, [MARKDOWN_TEMPLATE_TRIGGER])
        assert MARKDOWN_TASK in delegated_targets(control), (
            f"{MARKDOWN_TEMPLATE_TRIGGER!r} no longer reaches {MARKDOWN_TASK!r} when present, "
            f"so the deletion assertion below would prove nothing\n{diagnose(control)}"
        )

        result = lint_route(self.SCRIPT, [MARKDOWN_TEMPLATE_TRIGGER], absent=[MARKDOWN_TEMPLATE_TRIGGER])
        assert_check_ran(result, TEMPLATE_ANNOUNCEMENT, TEMPLATE_TASK)
        assert MARKDOWN_TASK not in delegated_targets(result), (
            f"deleted {MARKDOWN_TEMPLATE_TRIGGER!r} was handed to {MARKDOWN_TASK!r} — "
            f"the Markdown stage must read the existence-filtered list\n{diagnose(result)}"
        )

    @pytest.mark.parametrize("trigger", REVIEWER_ENVELOPE_TRIGGERS)
    def test_envelope_trigger_runs_envelope_check(self, lint_route: LintRouteFn, trigger: str) -> None:
        """A reviewer agent definition, the envelope doc, or its schema triggers the gate."""
        result = lint_route(self.SCRIPT, [trigger])
        assert_check_ran(result, ENVELOPE_ANNOUNCEMENT, ENVELOPE_TASK)

    def test_unrelated_file_does_not_run_envelope_check(self, lint_route: LintRouteFn) -> None:
        """A file outside the envelope trigger set leaves that gate alone."""
        result = lint_route(self.SCRIPT, [UNRELATED_FILE])
        assert_check_skipped(result, ENVELOPE_ANNOUNCEMENT, ENVELOPE_TASK)

    @pytest.mark.parametrize("near_miss", ENVELOPE_NEAR_MISSES)
    def test_near_miss_path_does_not_run_envelope_check(self, lint_route: LintRouteFn, near_miss: str) -> None:
        """An agent definition outside the reviewer alternation leaves the gate alone."""
        result = lint_route(self.SCRIPT, [near_miss])
        assert_check_skipped(result, ENVELOPE_ANNOUNCEMENT, ENVELOPE_TASK)

    @pytest.mark.parametrize("trigger", DELETED_ENVELOPE_TRIGGERS)
    def test_deleted_envelope_trigger_runs_envelope_check(self, lint_route: LintRouteFn, trigger: str) -> None:
        """An envelope trigger the diff removes still reaches the gate.

        Parametrized across an agent definition and the canonical doc because
        the gate fires off two separate greps, either of which could be pointed
        back at the post-filter list on its own.
        """
        result = lint_route(self.SCRIPT, [trigger], absent=[trigger])
        assert_check_ran(result, ENVELOPE_ANNOUNCEMENT, ENVELOPE_TASK)

    @pytest.mark.parametrize("marker", MIRRORED_BLOCK_MARKERS)
    def test_mirrored_block_is_byte_identical(self, marker: str) -> None:
        """Both routers carry the block byte-identically, whitespace included.

        Ignores ``SCRIPT`` and reads both files, so it is redundant across the
        two subclasses by construction. That redundancy is the point: each
        router routes only to its own test file, so a cross-file invariant
        asserted in one subclass would not run when the other router is edited.
        """
        assert_block_mirrored(
            marker,
            routers=LINT_ROUTERS,
            boundaries=MIRRORED_BLOCK_MARKERS,
        )

    def test_mirrored_region_runs_the_same_checks(self) -> None:
        """Both routers delegate to the same task targets, as often, below the anchor.

        The check above can only compare blocks somebody remembered to name in
        ``MIRRORED_BLOCK_MARKERS``; this one reads the delegations straight out
        of the two files, so a block added to — or dropped from — one router
        alone fails without anyone updating a list. Reads both files and
        ignores ``SCRIPT`` for the same reason as its neighbour.
        """
        assert_mirrored_region_delegations_match()

    def test_aggregate_lint_task_runs_both_reviewer_checks(self) -> None:
        """The aggregate ``task lint`` still invokes both reviewer checks.

        Reads ``Taskfile.yml``, not ``SCRIPT``. Partial coverage by design: see
        ``assert_aggregate_lint_runs_reviewer_checks``.
        """
        assert_aggregate_lint_runs_reviewer_checks()
