"""Unconditional routing-coverage guard for the ``scripts`` router target.

Asserts that every git-tracked source path under a router prefix both routes to
at least one test target and that each announced target actually collects at
least one test — unless the ``(router, path)`` pair is registered as a known
exemption in ``helpers.router_coverage_registry``.

Both routers are executed for real, one changed path per call, and the announced
targets are read back off their own output. Nothing here re-derives a test
filename from a source path: a re-modelled dispatch chain agrees with a broken
router, which is the defect this guard exists to catch.

An announcement is only half of coverage. Both routers guard every derived name
with ``[ -f ]`` and treat a no-tests-collected pytest run as success, so a target
that collects nothing is as silent a hole as no target at all. Collection is
therefore probed per distinct announced target — once, over the deduplicated
union, rather than once per path.

Two assertions here run outside a case body, because a run narrowed enough to
retire this guard reaches no case body at all. One runs at **import** and leads
the module: it screens the channels it reads for the two pinned deselecting
spellings. The other is an execution floor — one counter incremented per walk
case, read from an ``atexit`` handler — which stands on how many cases ran
rather than on what the run was started with, so a narrowing that stops the
walk ends the process non-zero however it was delivered and whatever it was
spelled.

The floor's cost is unconditional: *any* run of this module that reaches fewer
cases than the walk holds ends at ``UNRUN_WALK_EXIT``, whatever narrowed it and
whether or not it was deliberate. A ``-k`` against this module ends there, and
so does ``task test:scripts`` under a filter that narrows collection, since that
target's command threads ``{{.CLI_ARGS}}`` and names ``tests/ci/``; passing
``--ignore=tests/ci/test_router_coverage.py`` alongside the filter is what
narrows the rest of that suite without ending on the floor.
``task test:routing`` runs the whole module.
"""

import ast
import atexit
import configparser
import io
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple

import pytest
import yaml
from helpers import router_coverage_registry
from helpers.router_coverage_registry import EXEMPTIONS
from helpers.router_harness import (
    ANNOUNCE_PREFIX,
    CONTAINER_DETECTION_TOKENS,
    REPO_ROOT,
    SOURCE_PATH_DERIVATION_TOKENS,
    TEST_ROUTERS,
    RouteFn,
    RouteVariantFn,
    changed_scripts_universe,
    diagnose,
    routed_targets,
    tracked_paths,
)

#: The environment variable pytest reads extra command-line options from, and
#: the ini file and key that do the same thing from disk. Neither appears in the
#: routing target's command, so the token whitelist over that command reads
#: past both.
AMBIENT_ADDOPTS_ENV_VAR = "PYTEST_ADDOPTS"
PYTEST_INI_PATH = "pytest.ini"
PYTEST_INI_SECTION = "pytest"
PYTEST_INI_ADDOPTS_KEY = "addopts"

#: The whole ``addopts`` value ``pytest.ini`` declares. Pinned by equality, in
#: a case body: the ini reaches every channel this guard runs in, and an option
#: added to it is an edit that has to be argued for whatever it is called. The
#: import-time scan below reads the same value for the narrower deselecting set
#: only, so a legitimate addition reds as a failing case rather than as a
#: collection error that takes the whole directory with it.
PYTEST_INI_ADDOPTS = "--import-mode=importlib"

#: The option measured to leave pytest reporting a collection count in place of
#: any pass or fail count, evaluating no assertion, and still exiting 0 — which
#: is the one exit the routing target forgives — and the short spelling pytest
#: documents for it, which was not separately measured.
#: Two spellings of one option rather than a list of the ways a run can be
#: narrowed: a run narrowed some other way is caught by the execution floor at
#: ``EXECUTED_ROUTER_CASES``, whenever the narrowing stops the walk.
DESELECTING_OPTIONS: tuple[str, ...] = ("--collect-only", "--co")

#: Every argument ``collect_target`` passes ahead of the target it probes. The
#: probe is itself a ``--collect-only`` run, so the import-time scan has to let
#: it through; comparing the whole argument vector against this tuple is what
#: separates the probe from a guard run started with a deselecting option.
#: ``collect_target`` builds its command line out of this, so the exemption
#: cannot drift away from the thing it exempts.
#: Known limit: a routing command spelled as exactly this vector followed by one
#: target is exempted by the same comparison. Every one of its five tokens is
#: outside ``ROUTING_COMMAND_TOKENS`` — but that whitelist is read by a case
#: body, which is precisely what a deselecting run never reaches. The execution
#: floor is exempted on this same comparison, so it does not close this either.
PROBE_ARGUMENTS: tuple[str, ...] = ("--collect-only", "-q", "-p", "no:cacheprovider", "--")


def _pytest_ini_addopts() -> str:
    """
    Read the whole ``addopts`` value ``pytest.ini`` declares.

    Returns:
        The declared value, empty where the file declares none.

    Raises:
        AssertionError: If the file is missing or carries no ``[pytest]``
            section, either of which leaves the scans reading nothing.
    """
    path = REPO_ROOT / PYTEST_INI_PATH
    assert path.is_file(), f"{PYTEST_INI_PATH} is missing, so the options it hands every pytest run cannot be read"
    parser = configparser.RawConfigParser()
    parser.read_string(path.read_text(encoding="utf-8"))
    assert parser.has_section(PYTEST_INI_SECTION), (
        f"{PYTEST_INI_PATH} carries no [{PYTEST_INI_SECTION}] section, so the options it hands every pytest run cannot be read"
    )
    return parser.get(PYTEST_INI_SECTION, PYTEST_INI_ADDOPTS_KEY, fallback="")


def _deselecting_options(arguments: Sequence[str]) -> tuple[str, ...]:
    """
    Return the pinned deselecting options one argument sequence carries.

    Args:
        arguments: Pytest arguments, already split on whitespace.

    Returns:
        The options carried, in the order they are pinned.
    """
    carried = frozenset(arguments)
    return tuple(option for option in DESELECTING_OPTIONS if option in carried)


def _is_collection_probe(arguments: Sequence[str]) -> bool:
    """
    Decide whether one argument vector is this module's own collection probe.

    Args:
        arguments: Pytest arguments, the interpreter and script dropped.

    Returns:
        Whether the vector is ``PROBE_ARGUMENTS`` followed by a single target.
    """
    return len(arguments) == len(PROBE_ARGUMENTS) + 1 and tuple(arguments[:-1]) == PROBE_ARGUMENTS


def assert_no_deselecting_option_is_in_effect(
    *,
    arguments: Sequence[str],
    ambient: str,
    ini_addopts: str,
) -> None:
    """
    Assert no pinned deselecting option arrives by the channels this scan reads.

    Called at import, which is where it has to run: under a deselecting option
    no case body executes, so an assertion inside one is unreachable exactly
    when it is needed. Import happens in every channel this guard runs in, and
    it reads the arriving effect rather than one file a key pin reads — the
    option reaches pytest identically whether a workflow ``env:``, an
    ``echo >> "$GITHUB_ENV"`` inside a step that already runs one, a go-task
    ``env:`` at any of its scopes, ``pytest.ini`` or the ambient shell put it
    there.

    Every channel is screened for the pinned options rather than required to be
    empty, the ambient variable included. That the variable is empty is pinned
    too, but in a case body: at import an unrelated value — a ``-q``, a
    ``--no-header`` — would raise during collection, and pytest abandons the
    session on a collection error, so it would take every other module in
    ``tests/ci/`` with it. The same split holds for ``pytest.ini``, one channel
    across.

    Args:
        arguments: Pytest arguments, the interpreter and script dropped.
        ambient: Value of the ambient add-options environment variable.
        ini_addopts: The ``addopts`` value ``pytest.ini`` declares.

    Raises:
        AssertionError: If a pinned deselecting option arrives by the ambient
            variable, the ini or the command line.
    """
    assert DESELECTING_OPTIONS, "the deselecting-option list is empty, which leaves the scan below vacuous"
    delivered = {
        f"${AMBIENT_ADDOPTS_ENV_VAR}": _deselecting_options(ambient.split()),
        PYTEST_INI_PATH: _deselecting_options(ini_addopts.split()),
        "the command line": () if _is_collection_probe(arguments) else _deselecting_options(arguments),
    }
    carried = sorted(f"{channel} carries {list(options)}" for channel, options in delivered.items() if options)
    assert not carried, (
        "; ".join(carried) + f"; {list(DESELECTING_OPTIONS)} make pytest report a collection count in place of "
        "any pass or fail count, evaluate no assertion and still exit 0 — which is the one exit the routing "
        "target forgives, so the guard would report success having asserted nothing"
    )


assert_no_deselecting_option_is_in_effect(
    arguments=sys.argv[1:],
    ambient=os.environ.get(AMBIENT_ADDOPTS_ENV_VAR, ""),
    ini_addopts=_pytest_ini_addopts(),
)

#: The only router target this guard covers, and the three it leaves alone for
#: three different reasons. ``brownfield_ai`` reaches an un-stubbed
#: ``python ci/resolve_downstream_tests.py``, so a walk over it would spawn an
#: interpreter once per tracked path. ``skills`` reaches ``run_pytest_venv``,
#: which exits 1 on ``[ ! -f .venv/bin/pytest ]`` — and the synthetic workspace
#: holds no venv — so a walk over it would report a router defect rather than a
#: routing decision. ``dashboard`` reaches only ``task`` and
#: ``docker compose``, both of which the router workspace shadows, so cost is
#: not what excludes it: its branch delegates rather than announcing, printing
#: no ``ANNOUNCE_PREFIX`` line for this walk to read a target off, so every path
#: under it would report as a hole for want of a routing model to measure.
ROUTE_TARGET = "scripts"

#: ``pytest --collect-only`` exit codes this guard can classify. Any other exit
#: is a broken probe: read as "collected" it excuses a hole, read as "empty" it
#: invents one.
COLLECTED_EXIT = 0
NO_TESTS_COLLECTED_EXIT = 5

#: Liveness ceiling on one collection probe, well above the per-probe budget
#: rather than close to it: this is not a performance assertion. A collector
#: that wedges must fail the run, since without it the whole walk stalls behind
#: a probe that will never return.
COLLECT_TIMEOUT_SECONDS = 60

#: A changed path that routes at least one target, used to drive a router into
#: the un-shadowed security gate. It has to route something: both routers return
#: early on an empty target list, so an un-routed path never reaches the gate
#: and the router exits 0 with nothing announced — which is the outcome the
#: health assertion exists to tell apart from a real hole.
ROUTER_HEALTH_SAMPLE = ".claude/hooks/block-stranded-agent.sh"

#: Exit reported by the stub collector, chosen outside the classified pair so
#: neither reading of it is available.
UNCLASSIFIED_COLLECT_EXIT = 2

#: Target handed to the stub collector. It never reaches pytest — the stub
#: ignores it — so it only has to be a string a failure message can name.
STUB_COLLECT_TARGET = "tests/ci/"

#: This module, as the source scans below and the task target that runs it name
#: it. Every use is asserted against ``__file__`` or against the target, so a
#: moved guard fails rather than leaving a scan reading nothing.
GUARD_MODULE = "tests/ci/test_router_coverage.py"

#: A registered hole whose *shape* is pinned as well as its existence. An
#: exemption records only that a pair reaches no test, so a router that started
#: announcing some other wrong target would keep the hole set balanced and pass.
PINNED_OUTCOME_PATH = "tests/ci/conftest.py"

#: What each router announces for PINNED_OUTCOME_PATH. The staged router admits
#: any existing ``*.py`` under ``tests/ci/`` and routes it to itself, which
#: announces a target that collects nothing; the changed router admits only a
#: ``test_*.py`` name, so it announces nothing at all.
PINNED_OUTCOME_TARGETS: dict[str, tuple[str, ...]] = {
    "test_staged.sh": (PINNED_OUTCOME_PATH,),
    "test_changed.sh": (),
}

#: The registry this guard reads, and the two directory targets a changed
#: helper module fans out to in both routers. The registry sits under
#: ``tests/helpers/`` so that an edit to it re-runs this suite; the fan-out is
#: pinned because relocating it under ``tests/ci/`` would route it to itself and
#: leave the guard blind to its own data changing. The literal is tied to the
#: module actually imported above, the way GUARD_MODULE is tied to this one, so
#: a moved registry cannot leave the fan-out measured for a stale path.
REGISTRY_MODULE = "tests/helpers/router_coverage_registry.py"
REGISTRY_FANOUT_TARGETS: frozenset[str] = frozenset({"tests/ci/", "tests/helpers/"})

#: Sources the container-detection scan reads. This module is in the list
#: because a skip inside it is the repair an in-container red invites;
#: ``tests/ci/conftest.py`` is in it because it supplies this module's route
#: fixtures and takes additions freely; the registry is in it because it is
#: this guard's data and declares none of the tokens, so scanning it costs
#: nothing.
#: Known limit: ``tests/helpers/router_harness.py`` is on this module's
#: import-time path as well — it supplies ``tracked_paths``,
#: ``changed_scripts_universe``, ``build_router_workspace`` and ``make_route`` —
#: and it is NOT scanned. It declares ``CONTAINER_DETECTION_TOKENS`` itself, so
#: a scan over it would match on the declaration whatever the surrounding code
#: did. Closing that would take a pin that tolerates the declaration itself —
#: an occurrence count over the harness source, or a token list living in a
#: module neither the guard nor the harness declares. Until one is added, a
#: module-level container-keyed skip in the harness silences the guard with
#: nothing here to notice.
#: ``tests/conftest.py`` sits in the same position and is likewise not scanned:
#: it is loaded for every session this module runs in — ``TestGuardWiring``
#: names it among the vectors it leaves open — and it already spells one of
#: ``CONTAINER_DETECTION_TOKENS``, for its ``docker_ip`` fixture, so a scan over
#: it would match on that read whatever the surrounding code did. Spelling the
#: token here rather than naming the list would red the scan over *this* module,
#: which is the same self-match one file across.
CONTAINER_DETECTION_SCAN_SOURCES: tuple[str, ...] = (
    GUARD_MODULE,
    REGISTRY_MODULE,
    "tests/ci/conftest.py",
)

#: Paths the contamination check routes through both a reused and a fresh
#: workspace. One per branch shape that yields a target: a whole-suite fan-out,
#: the helper fan-out, and a derived name.
CONTAMINATION_SAMPLES: tuple[str, ...] = (
    ".claude/hooks/block-stranded-agent.sh",
    "tests/helpers/router_harness.py",
    "docker/shared/python-security-gate.sh",
)

#: A changed-file list announcing several targets at once, used to dirty the
#: reused workspace between the two halves of the contamination check.
CONTAMINATION_NOISE: tuple[str, ...] = (
    ".claude/agents/code-review.md",
    ".claude/settings.json",
    "tests/helpers/eval_utils.py",
    "scripts/setup_codex_reviewer.sh",
)

#: A tracked path no branch of either router matches.
UNROUTED_SAMPLE = "README.md"

#: The TODO ids a registry entry may cite. An id outside this set is either
#: invented or points at work nobody tracks, and in both cases the exemption it
#: carries has no closure path. Held to the ids the registry actually cites
#: rather than to every id filed: ``TODO-0332`` for the agent-cli routing
#: divergence between the two routers, ``TODO-0333`` as the catch-all
#: standing-holes id, so a hole whose cause no other id names still gets an
#: honest one. The reverse direction is asserted alongside the forward one: an
#: id admitted here but cited by no exemption is a landing site a typo can hit
#: while still passing.
#: Known limit: this is a hand-copied mirror of the ids filed in the ledger and
#: nothing checks it against one, so an id renamed or retired there keeps
#: passing here until a reader notices.
ENUMERATED_TODO_IDS: frozenset[str] = frozenset({
    "TODO-0332",
    "TODO-0333",
})

#: The three files that carry this guard's wiring: the CI step that runs it on
#: every PR, the taskfile declaring the target that step invokes, and the root
#: taskfile whose own ``test`` aggregate runs that target through the included
#: namespace. The root file is read as well as the included one because an
#: aggregate that names the guard and is not ratcheted can drop it silently:
#: neither file sits under a router prefix, so no diff-scoped channel re-runs
#: anything on a change to either.
WORKFLOW_PATH = ".github/workflows/test.yml"
TASKFILE_PATH = "taskfiles/test.yml"
ROOT_TASKFILE_PATH = "Taskfile.yml"

#: The whole file-level ``env:`` each wiring taskfile declares, keys and values
#: both. A file-level ``env:`` is the file's own declaration of variables for
#: every target it holds — one scope above the target ``env:`` the forbidden-key
#: scan reads, and two above the per-command one, so both of those scans look
#: straight past it. ``taskfiles/test.yml`` declares ``PYTHONPATH`` there; the
#: root file declares nothing at all.
#: The values are pinned as well as the keys, because a key admitted with its
#: value left free is not closed: ``PYTHONPATH`` is an interpreter-level module
#: search path handed to every target the file declares, and a directory
#: prepended to it is searched before the rest of it. No exploit through it is
#: claimed as measured; what is claimed is that the value was unconstrained.
#: What is measured is that a ``PYTEST_ADDOPTS`` present in the environment the
#: guard's command inherits retires the run — a collection count in place of
#: any pass or fail count, no assertion evaluated, exit 0 — and that a
#: target-level ``env:`` populates that environment. That the file level
#: populates it too is **inferred** from it being the same mechanism one scope
#: out, not observed here.
TASKFILE_ENV: dict[str, dict[str, object]] = {
    TASKFILE_PATH: {"PYTHONPATH": "{{.ROOT_DIR}}:{{.ROOT_DIR}}/src"},
    ROOT_TASKFILE_PATH: {},
}

#: The two keys that put variables into a target's environment. ``env`` names
#: them in the file, so it is closed by whitelisting the names; ``dotenv`` names
#: a file whose contents nothing here reads, so it cannot be whitelisted by key
#: at all and is forbidden outright at the file level of both wiring taskfiles.
#: ``AMBIENT_ENV_KEY`` is read on the workflow side too, where GitHub Actions
#: defines a top-level ``env:`` as a map of variables available to the steps of
#: *all* jobs in the workflow — the guard's job included. There is no workflow
#: equivalent of ``dotenv``, so only the one key is read there.
#: Known limit: both spellings mirror go-task's schema, which nothing here
#: executes or reads, so a key renamed there leaves the scan for it looking past
#: whatever go-task now calls it. What each spelling *is* held to is a subject
#: inside this repository. ``AMBIENT_ENV_KEY`` has the file-level environment
#: pinned at ``TASKFILE_ENV``, non-empty in one of the two files, so renaming it
#: reds there. ``AMBIENT_DOTENV_KEY`` has no such subject — neither wiring
#: taskfile declares one, and an absence holds for any name — so it is held
#: against ``FORBIDDEN_ROUTING_TARGET_KEYS``, which forbids the same go-task key
#: one scope down and spells it as a literal of its own.
AMBIENT_ENV_KEY = "env"
AMBIENT_DOTENV_KEY = "dotenv"

#: The workflow job the guard step belongs to: a job of its own, holding only
#: the checkout, toolchain and cache steps the guard needs. Every step lookup
#: below is scoped by this key rather than searched file-wide, because the
#: toolchain step names repeat across the workflow's jobs, so an unscoped search
#: either matches several steps or makes the ordering assertions depend on edits
#: to a job this guard has nothing to do with.
GUARD_JOB = "routing-coverage"

#: The guard step, pinned by name **and** by the command it runs. Either alone
#: leaves a rename direction open: matching on the name only lets the command
#: be retargeted at some other target, and matching on the command only lets
#: the step be renamed into something a reader no longer recognises as this
#: guard. The command is compared against the whole ``run:`` scalar, stripped,
#: rather than being searched for inside it: a search is satisfied by any one
#: line of a multi-line block, so a ``run: |`` opening with an early ``exit 0``
#: would retire the guard while still matching.
GUARD_STEP_NAME = "Run Routing Coverage Guard"
GUARD_STEP_COMMAND = "task test:routing"

#: The key that leaves the guard step running, and red, while the job it sits
#: in still reports success.
GUARD_STEP_TOLERANCE_KEY = "continue-on-error"

#: Every key the guard step declares, as a whitelist. ``if`` and
#: ``continue-on-error`` are pinned individually below as well, because each
#: has a specific retirement worth naming in a failure; this closes the rest of
#: the step's key space by equality, so a key nobody enumerated reds too. The
#: one that matters most is ``env``: measured on this repository, a
#: ``PYTEST_ADDOPTS=--collect-only`` present in the environment
#: ``task test:routing`` inherits reaches pytest through go-task, and the run
#: then printed a collection count in place of any pass or fail count,
#: evaluated no assertion and still exited 0. A step-level ``env:`` is one of
#: the ways to put it there.
GUARD_STEP_KEYS: frozenset[str] = frozenset({"name", "run"})

#: Three job-level keys that retire every step the guard's job holds, named for
#: the diagnostic rather than for the closure: ``GUARD_JOB_KEYS`` below is what
#: closes the job's key space, by equality, and it covers these three together
#: with the ones nobody enumerated — a ``strategy:`` resolving to an empty
#: matrix, which runs the job zero times, and an ``env:``, which reaches pytest
#: by the route measured above. These three stay listed so that a failure names
#: the specific retirement rather than only reporting an unexpected key.
#: ``if`` skips every step, ``continue-on-error`` forgives their failures, and
#: ``needs`` sequences the job behind another one — a guard sequenced behind a
#: test job never starts when that job reds, so an ordinary test failure
#: suppresses the one signal meant to survive it.
GUARD_JOB_FORBIDDEN_KEYS: tuple[str, ...] = ("if", GUARD_STEP_TOLERANCE_KEY, "needs")

#: The step the guard must follow, because the uv install appends to
#: ``$GITHUB_PATH`` and so affects only later steps.
UV_INSTALL_STEP_NAME = "Install uv"

#: The remaining toolchain steps the guard's job holds, named so the ordered
#: step-name pin below is written in constants rather than in bare literals.
TASK_INSTALL_STEP_NAME = "Install Task"
UV_CACHE_STEP_NAME = "Cache uv packages"

#: Expressions that start a test run. Steps within a job run in sequence and a
#: failing one ends the job, so any step carrying one of these ahead of the
#: guard suppresses it — which is the outcome a job of the guard's own exists to
#: rule out, and which does not depend on what that step is called. Pinning a
#: forbidden step *name* covers the one test step that happened to be named;
#: this covers the property instead, so a package, dashboard or skills step
#: added later is caught under whatever name it arrives with.
#: Held to the three shapes this repository's workflows use to start tests, not
#: claimed exhaustive: the ordered step-name pin below is what closes the
#: direction an unlisted shape would come in by.
#: Known limit: these are matched against ``run:`` text only, so a step that
#: starts a test run through an action carries nothing for them to match at
#: all; ``GUARD_JOB_STEP_ACTIONS`` closes that axis instead, by pinning which
#: action each step of the job may run.
TEST_INVOCATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<!\S)task\s+test:"),
    re.compile(r"(?<!\S)\S*ci/test_\w+\.sh(?!\S)"),
    re.compile(r"(?<!\S)\S*pytest(?!\S)"),
)

#: The step uploading the guard's junit, and the action it must use. Located by
#: step name rather than by the path it uploads: a search by path would stop
#: matching exactly when the path drifted, which is the drift being checked.
JUNIT_UPLOAD_STEP_NAME = "Publish Routing Coverage Guard Results"
UPLOAD_ACTION_PREFIX = "actions/upload-artifact@"

#: The two keys the junit upload's value rests on. ``if: always()`` is what
#: makes the upload fire on the run where the guard red — the only run whose
#: artifact is worth anything, since a step following a failed one is otherwise
#: skipped and the per-case list of unrouted paths is lost to a truncated log.
#: ``if-no-files-found: ignore`` is what keeps a venv build that fails ahead of
#: pytest from turning a legitimately absent file into a second, misleading
#: complaint.
JUNIT_UPLOAD_CONDITION = "always()"
JUNIT_MISSING_FILE_KEY = "if-no-files-found"
JUNIT_MISSING_FILE_POLICY = "ignore"

#: The guard job's steps, in order, as a whitelist. Every other pin here says
#: what a step must *not* be, and each such pin is escaped by the next thing
#: nobody listed; this says what the job *is*, so any step added to it — a test
#: step under any name, a gate, a second guard — fails and has to be argued for
#: rather than merged with the other pins still green. ``None`` is the unnamed
#: checkout, which declares only ``uses:``.
GUARD_JOB_STEP_NAMES: tuple[str | None, ...] = (
    None,
    TASK_INSTALL_STEP_NAME,
    UV_INSTALL_STEP_NAME,
    UV_CACHE_STEP_NAME,
    GUARD_STEP_NAME,
    JUNIT_UPLOAD_STEP_NAME,
)

#: The job's own aggregate liveness ceiling, and the largest value that counts
#: as one. The guard bounds each router call and each collection probe
#: individually; a wedge anywhere outside those ceilings is bounded only by
#: the job's, and absent that by GitHub's 360-minute default. Asserted as a
#: bound rather than as an exact value, so raising it within reason is not a
#: test edit.
GUARD_JOB_TIMEOUT_KEY = "timeout-minutes"
GUARD_JOB_TIMEOUT_CEILING = 60

#: Every key the guard's job declares, as a whitelist. The forbidden-key list
#: above enumerates three members of GitHub Actions' job schema, which is far
#: larger than three and not closed by anything a reader here can check;
#: asserting the key set by equality closes it from the other side, so a
#: ``strategy:`` resolving to an empty matrix, an ``env:`` reaching pytest
#: through go-task, and any key nobody has thought of all red without having
#: been named. The job is the guard's own and holds three keys, so this reds on
#: edits to the guard's wiring rather than on ordinary workflow maintenance.
GUARD_JOB_RUNNER_KEY = "runs-on"
GUARD_JOB_KEYS: frozenset[str] = frozenset({GUARD_JOB_RUNNER_KEY, GUARD_JOB_TIMEOUT_KEY, "steps"})

#: The runner label the guard's job requests. The key set above admits the key
#: and says nothing about its value, and no other assertion here reads it, so
#: the label is the one slot in a three-key job that nothing constrains. Pinned
#: for that reason rather than for a demonstrated outcome: what a runner label
#: naming no provisioned runner does to a queued job has not been measured here.
GUARD_JOB_RUNNER = "ubuntu-latest"

#: The key a job declares in place of ``steps:`` when it calls a reusable
#: workflow. Such a job holds no steps of its own, so the file-wide scans below
#: skip it rather than reporting it as a job that declares none.
#: Known limit: a toolchain install or a uv cache *inside* the called workflow
#: is then outside both scans, and neither the parity check nor the cache-key
#: check has anything to say about it.
REUSABLE_WORKFLOW_KEY = "uses"

#: Directory the scanned workflows live in, and the suffixes GitHub reads there.
#: Both are listed because a workflow file is picked up under either one, so a
#: scan written for a single suffix leaves the other unread.
WORKFLOW_DIR = ".github/workflows"
WORKFLOW_SUFFIXES: tuple[str, ...] = ("*.yml", "*.yaml")


def _workflow_scan_paths() -> tuple[str, ...]:
    """
    Enumerate the workflow files the file-wide scans read.

    Discovered by glob rather than listed. A hand-kept list is a whitelist over
    the wrong axis: it pins which *files* are compared while the property being
    checked is that every copy of a duplicated step agrees with every other, so
    a workflow added later carries its copies outside the comparison entirely.
    Both scans reading this run on the same argument: the toolchain parity check
    over the install steps, and the cache-key check over every job restoring the
    uv package cache.

    Each path is rendered by relativising the file against the repository root
    rather than by joining the directory to a filename read off it: the result
    is the same string, and the relativised form cannot disagree with where the
    file actually is.

    Returns:
        Repository-relative workflow paths, sorted.
    """
    directory = REPO_ROOT / WORKFLOW_DIR
    found = {path.relative_to(REPO_ROOT).as_posix() for suffix in WORKFLOW_SUFFIXES for path in directory.glob(suffix)}
    return tuple(sorted(found))


#: Workflow files the file-wide scans read. Each install step below is
#: duplicated across jobs, and across files, and every copy of one of them
#: fetches the same artifact and checks it against the same checksum — so two
#: copies of the same step carrying different values is a drift whichever one
#: moved. Some copies carry a comment telling the author to keep the pair in
#: sync with the others and some carry none; the scan stands on the values
#: rather than on that instruction, which has no mechanism either way. The uv
#: cache-key check reads the same set, for the same reason: a cache keyed on
#: fewer than every requirements file serves a stale one in whichever job keys
#: it that way, and which file that job sits in is not the property.
#: Measured membership: the glob resolves to ``.github/workflows/ci.yml`` and
#: ``.github/workflows/test.yml``, and to nothing else. Recorded rather than
#: pinned — a workflow added later is meant to be compared, and a pin over the
#: set would red on the addition instead of reading it.
WORKFLOW_SCAN_PATHS: tuple[str, ...] = _workflow_scan_paths()

#: Step names whose pinned toolchain values must agree across every copy, and
#: the ``env:`` keys carrying them.
TOOLCHAIN_STEP_PINS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (TASK_INSTALL_STEP_NAME, ("TASK_VERSION", "TASK_CHECKSUM")),
    (UV_INSTALL_STEP_NAME, ("UV_VERSION", "UV_CHECKSUM")),
)

#: ``yaml.safe_load`` resolves a bare ``on`` key as the YAML 1.1 boolean, so the
#: workflow's trigger block is read under ``True`` rather than under the string.
WORKFLOW_TRIGGER_KEY = True

#: Every key the guard's workflow declares at the top level, as a whitelist.
#: This level reaches every step of every job in the file, so a key added here
#: sits two levels above the step-key pin and one above the job-key pin, both of
#: which stay green through it — which is why the level is closed by equality
#: rather than by naming the one key that was thought of. ``env`` is checked
#: again beneath, for the message.
#: The key with a named retirement besides ``env`` is ``defaults``: GitHub
#: Actions applies a workflow-level ``defaults.run.shell`` to every ``run:``
#: step of every job, so a shell that prints its script instead of executing it
#: leaves the guard's step declared, its command byte-identical and its pins
#: green while nothing runs. That reading is off the workflow schema; it is not
#: measured here.
#: ``on`` is a member as the boolean ``WORKFLOW_TRIGGER_KEY``, not as the
#: string, for the reason recorded above it.
WORKFLOW_KEYS: frozenset[object] = frozenset({"name", WORKFLOW_TRIGGER_KEY, "permissions", "jobs"})

#: The trigger the guard's whole purpose depends on. Without it the guard never
#: runs on a pull request at all, which makes the filter check below vacuous.
GUARD_TRIGGER_EVENT = "pull_request"

#: Trigger-level filters that skip a workflow run the guard has to report on.
#: That reading is off the trigger's documented filter semantics; it is not
#: measured here. ``paths`` and ``paths-ignore`` skip the run outright for a diff
#: touching nothing they list, which retires the guard on exactly the pull
#: requests it exists for. ``types`` is the same one-line shape one key across:
#: the ``pull_request`` default is ``[opened, synchronize, reopened]``, so
#: ``types: [labeled]`` leaves the workflow declaring the trigger while running
#: on none of the pushes that carry the change. ``branches-ignore`` narrows by
#: base branch. Each costs one line, one level above the ``if:`` the step-level
#: pin already forbids.
#: ``branches`` is absent from this list because it cannot be in it: the
#: workflow declares it, and it is load-bearing. It is closed by its *value*
#: instead — see ``GUARD_TRIGGER_BASE_BRANCH``.
#: At the two events ``BASE_BRANCH_SCOPED_EVENTS`` names this list is the
#: diagnostic rather than the closure, the way ``GUARD_JOB_FORBIDDEN_KEYS`` sits
#: beneath ``GUARD_JOB_KEYS``: ``GUARD_TRIGGER_KEYS`` closes their key space, and
#: this list is what makes a failure name the retirement rather than only report
#: an unlisted key. At any other event the workflow declares it is not a
#: diagnostic but the whole check — no key set is pinned there.
FORBIDDEN_TRIGGER_FILTER_KEYS: tuple[str, ...] = ("paths", "paths-ignore", "types", "branches-ignore")

#: The base branch the guard reports into, and the trigger key scoping a run to
#: it. Declining to forbid a key is not the same as closing it: editing the
#: declared ``branches: [main]`` to name a branch that does not exist stops the
#: whole workflow — and with it the guard's job — on every pull request into
#: ``main``, for one word, with every other pin in this class green. So the
#: value is asserted where the key is declared.
#: An absent ``branches`` widens the trigger rather than narrowing it, so it is
#: not asserted into existence: a check with no subject is the safe state here,
#: not a blind one.
GUARD_TRIGGER_BASE_BRANCH = "main"
GUARD_TRIGGER_BRANCH_KEY = "branches"

#: The whole branch list each of those events must declare where it declares
#: one. Compared by equality, because membership does not close the key:
#: ``branches: [main, '!main']`` names ``main`` and matches no pull request,
#: since GitHub's filter admits ``!``-prefixed exclusions and applies them in
#: the order written — ``['!*']`` is the same shape one pattern across. That
#: reading is off the filter's documented syntax, not measured here.
GUARD_TRIGGER_BRANCHES: tuple[str, ...] = (GUARD_TRIGGER_BASE_BRANCH,)

#: The events whose base-branch scoping the guard's claim rests on.
#: ``pull_request`` carries "on every pull request"; ``push`` is what runs the
#: guard on ``main`` once one merges. Both are asserted present, not only
#: scoped: deleting ``on.push`` retires the post-merge run outright, and a check
#: that skipped an absent event would pass through the deletion. An event added
#: later and scoped to some other branch retires neither claim, so both checks
#: are held to these two rather than applied to every event the workflow
#: declares.
BASE_BRANCH_SCOPED_EVENTS: tuple[str, ...] = (GUARD_TRIGGER_EVENT, "push")

#: Every key those two events may declare, as a whitelist. The forbidden list
#: above closes only what somebody thought to name, and it is read by a bare
#: membership test — so renaming its members, or renaming
#: ``GUARD_TRIGGER_BRANCH_KEY``, leaves a real ``paths:`` invisible and the
#: branch value unread. This is the level that closes both: a key outside it
#: reds whether or not anybody listed it, and the branch key has to be spelled
#: the way the workflow spells it for the set to admit the trigger at all.
#: Read as "no key beside these" rather than as equality, so that an event
#: declaring none is not red: while this set holds one key the two readings
#: differ only on the empty mapping, which is the widening
#: ``GUARD_TRIGGER_BASE_BRANCH`` gives the reason for declining to assert
#: against.
#: Held to ``BASE_BRANCH_SCOPED_EVENTS`` rather than to every event the workflow
#: declares. ``merge_group:`` carries no mapping to read keys off, and an event
#: added later carries neither of the claims these two do.
GUARD_TRIGGER_KEYS: frozenset[str] = frozenset({GUARD_TRIGGER_BRANCH_KEY})

#: The uv package cache the guard's ``deps: [setup]`` venv build restores from.
#: The package cache, never ``.venv`` itself — a virtualenv is not relocatable.
CACHE_ACTION_PREFIX = "actions/cache@"
UV_CACHE_PATH = "~/.cache/uv"

#: The action the guard job's unnamed first step must run.
CHECKOUT_ACTION_PREFIX = "actions/checkout@"

#: Every step of the guard's job that runs an action, and the action prefix it
#: must run, as a whitelist keyed by step name. The test-invocation scan reads
#: ``run:`` text and so cannot see this axis at all: a step starting a
#: test run through an action — the shape ``ci.github-actions.md`` §1 pushes
#: this file towards — matches none of its patterns. The ordered name list
#: closes the direction a *new* step arrives by; this closes the direction
#: where a step already on that list is repointed at a different action, and it
#: pins the checkout, which is otherwise the one step in the job whose ``uses:``
#: nothing reads.
GUARD_JOB_STEP_ACTIONS: dict[str | None, str] = {
    None: CHECKOUT_ACTION_PREFIX,
    UV_CACHE_STEP_NAME: CACHE_ACTION_PREFIX,
    JUNIT_UPLOAD_STEP_NAME: UPLOAD_ACTION_PREFIX,
}

#: Every key each step of the guard's job declares, as a whitelist per step.
#: ``GUARD_STEP_KEYS`` closed the guard step's own key space and left the other
#: five open, and the checkout is the one that matters most: it is pinned to an
#: action by the mapping above, and a ``with:`` under that same action chooses
#: which tree the job checks out. A checkout pointed at the pull request's base
#: commit leaves every pin in this class green while the walk reads a tree that
#: does not contain the change — so the guard finds no un-routed source on
#: exactly the pull request introducing one. ``repository:`` and
#: ``sparse-checkout:`` are the same key one value across.
#: Closing all six by equality also closes ``working-directory:``, ``shell:``
#: and a per-step ``continue-on-error:`` on the five steps that admitted them.
#: The two install steps declare an ``env:`` of their own, and it is admitted:
#: it carries the pinned version and checksum, and a step-level ``env:`` reaches
#: that step alone rather than the guard's.
GUARD_JOB_STEP_KEYS: dict[str | None, frozenset[str]] = {
    None: frozenset({"uses"}),
    TASK_INSTALL_STEP_NAME: frozenset({"name", "run", AMBIENT_ENV_KEY}),
    UV_INSTALL_STEP_NAME: frozenset({"name", "run", AMBIENT_ENV_KEY}),
    UV_CACHE_STEP_NAME: frozenset({"name", "uses", "with"}),
    GUARD_STEP_NAME: GUARD_STEP_KEYS,
    JUNIT_UPLOAD_STEP_NAME: frozenset({"name", "uses", "if", "with"}),
}

#: The requirements files ``task test:setup`` installs from, and therefore the
#: files the cache key must track: a key that ignores one serves a stale cache
#: across the dependency change that invalidated it. Pinned against the target
#: it mirrors rather than hand-maintained, the way every other cross-file
#: constant here is: a requirements file added to the install line and not to
#: this list would otherwise leave the key silently short of it.
REQUIREMENTS_FILES: tuple[str, ...] = (
    "requirements.txt",
    "tests/requirements.txt",
    "services/dashboard/requirements.txt",
)

#: The target whose install line REQUIREMENTS_FILES mirrors, and the flag the
#: files are read off. The lookbehind keeps the flag from matching the tail of
#: a longer one.
SETUP_TASK_NAME = "setup"
REQUIREMENTS_FLAG = re.compile(r"(?<!\S)-r\s+(\S+)")

#: The task target the guard step invokes, and the aggregate that must include
#: it so the same wiring runs in a full local suite rather than only in CI.
ROUTING_TASK_NAME = "routing"
AGGREGATE_TASK_NAME = "all"
ROUTING_TASK_RUNNER = ".venv/bin/pytest"
ROUTING_TASK_DEPENDENCY = "setup"

#: The included aggregate's sole dependency. go-task completes every ``deps:``
#: entry before ``cmds[0]``, so the guard's command index buys nothing against
#: them: a target added here runs, and can fail, ahead of the guard whatever its
#: index says. Pinned as the whole list rather than screened for members that
#: run tests, because a target's name does not say whether it does.
AGGREGATE_DEPENDENCY = "purge-envs"

#: The root taskfile's aggregate, and the name it refers to the guard by. The
#: include namespace makes it ``test:routing`` there and a bare ``routing``
#: inside ``taskfiles/test.yml``.
ROOT_AGGREGATE_TASK_NAME = "test"
ROOT_ROUTING_ENTRY_NAME = "test:routing"


class AggregateSite(NamedTuple):
    """One aggregate that runs the guard, and the ratchets that hold it first."""

    #: Taskfile declaring the aggregate.
    taskfile: str
    #: Aggregate target name within that file.
    aggregate: str
    #: Name the aggregate refers to the guard by.
    entry: str
    #: The aggregate's whole ``deps:`` list, or ``None`` where it declares none.
    deps: list[str] | None


#: Every aggregate that runs the guard, with the ``deps:`` each may declare.
#: Both ratchets — command index 0 and the whole ``deps:`` list — apply wherever
#: the guard is aggregated, so both are asserted per site: an aggregate that
#: names the guard and carries neither can be demoted or emptied with every
#: other pin in this class still green, and neither taskfile sits under a router
#: prefix, so nothing else re-runs on the change that does it. The expected
#: ``deps:`` differs per site: the included aggregate declares ``purge-envs``,
#: the root one declares none at all, and ``None`` is asserted as strictly as a
#: list would be.
AGGREGATE_SITES: tuple[AggregateSite, ...] = (
    AggregateSite(TASKFILE_PATH, AGGREGATE_TASK_NAME, ROUTING_TASK_NAME, [AGGREGATE_DEPENDENCY]),
    AggregateSite(ROOT_TASKFILE_PATH, ROOT_AGGREGATE_TASK_NAME, ROOT_ROUTING_ENTRY_NAME, None),
)

#: The parametrize argument the aggregate-site cases bind. Named rather than
#: spelled twice, because the walk-case predicate's negative case is driven on
#: this parametrize: a literal there would be a hand-copy that keeps passing
#: after the parametrize it claims to mirror is renamed.
AGGREGATE_SITE_PARAM = "site"

#: Directory holding the included taskfiles, and the suffixes an included one
#: may carry. Both are globbed for the reason ``WORKFLOW_SUFFIXES`` lists both:
#: an ``includes:`` entry names an explicit path, so the extension is the
#: author's choice and a scan written for one of them leaves the other unread.
TASKFILE_DIR = "taskfiles"
TASKFILE_SUFFIXES: tuple[str, ...] = ("*.yml", "*.yaml")


def _aggregate_scan_paths() -> tuple[str, ...]:
    """
    Enumerate the taskfiles the aggregate discovery opens.

    Globbed rather than listed. ``AGGREGATE_SITES`` is a whitelist over
    aggregates, and a discovery loop that only ever opens the files those sites
    name moves the whitelist one level out, onto the *files* — so an aggregate
    running the guard from a third taskfile is outside the comparison entirely
    rather than caught by it.

    Rendered the way ``_workflow_scan_paths`` renders its own, by relativising
    each file against the repository root.

    Returns:
        The root taskfile, followed by every file under ``TASKFILE_DIR``
        carrying one of ``TASKFILE_SUFFIXES``, sorted. That set is neither a
        subset nor a superset of the ``includes:`` graph, and reaching an
        aggregate in a taskfile nothing includes is why it is globbed.
    """
    directory = REPO_ROOT / TASKFILE_DIR
    included = {path.relative_to(REPO_ROOT).as_posix() for suffix in TASKFILE_SUFFIXES for path in directory.glob(suffix)}
    return (ROOT_TASKFILE_PATH, *sorted(included))


#: Every taskfile the aggregate discovery reads.
#: Measured membership: the root taskfile plus the sixteen files under
#: ``taskfiles/``, every one of them ``*.yml``. Recorded rather than pinned, for
#: the reason ``WORKFLOW_SCAN_PATHS`` records its own.
AGGREGATE_SCAN_PATHS: tuple[str, ...] = _aggregate_scan_paths()

#: The command a target runs to reach another target through a shell rather
#: than through go-task's own ``task:`` key. ``_runs_task`` matches it as a
#: whole word followed by the target name, so a longer name carrying one of the
#: pinned entries as a prefix does not read as running it.
#: That search is not what holds the word, in either direction: it reaches only
#: a shell command spelling it, and a search reaching none passes for any word
#: at all. So the word is held against the first one of ``GUARD_STEP_COMMAND``,
#: which is itself pinned against the guard step's whole ``run:`` — what the
#: search looks for is then what the workflow runs.
TASK_INVOCATION = "task"

#: A ``cmds:`` entry in the mapping form, used to drive ``_command_entries``
#: past the shape the routing target has. That target's ``cmds`` is a single
#: folded string, so every entry of it fails ``isinstance(entry, dict)`` and the
#: per-command scan below would pass just as well reading only the string
#: commands. The mapping-form test overrides its ``cmd:`` with a template
#: expression, so the same synthetic entry drives the expression scan's seam as
#: well as the key scan's.
TOLERATED_COMMAND_ENTRY: dict[str, object] = {"cmd": "true", "ignore_error": True}

#: Keys of a ``cmds:`` mapping entry that carry text a command scan has to
#: read. A scan over the string entries alone drops every mapping entry
#: wholesale, so a mapping carrying ``docker``, ``--entrypoint``, a template
#: expression or an or-true suffix is invisible to it — the same fail-open
#: shape the per-command key scan exists to close, at the sibling scan that
#: reads command text rather than keys. A ``defer:`` whose value is itself
#: a ``{task: …}`` mapping carries no text and is not descended into.
COMMAND_TEXT_KEYS: tuple[str, ...] = ("cmd", "task", "defer")

#: This module as a whole pytest argument in the routing target's commands.
#: ``taskfiles/`` sits under no router prefix, so a target repointed at some
#: other file runs green in CI while the guard stops running at all — the
#: runner and the dependency say nothing about *what* is run. Matched
#: whitespace-delimited so a longer path with this one as a prefix cannot
#: satisfy the pin.
GUARD_MODULE_ARGUMENT = re.compile(rf"(?<!\S){re.escape(GUARD_MODULE)}(?!\S)")

#: Expressions that MUST NOT appear in the routing target's commands. The first
#: three would put a target that runs host-side under the venv onto a container
#: path instead. The fourth is the whole go-task template opener rather than the
#: ``{{.CLI_ARGS}}`` literal alone: ``{{.CLI_ARGS}}`` lets a caller inject
#: pytest arguments, and ``{{.ANY_VAR}}`` fed from the target's own ``vars:``
#: does the same thing with nobody supplying anything — one defect in two
#: spellings, in a target whose value is that it always runs the same thing, and
#: only the opener covers both. Word-anchored where the expression ends in a
#: word character, so a path such as a test module named after a container file
#: does not read as a container invocation.
FORBIDDEN_ROUTING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bdocker\b"),
    re.compile(r"--entrypoint\b"),
    re.compile(r"\bPYTHON_GATE_DISABLED\b"),
    re.compile(r"\{\{"),
)

#: Every whitespace-separated token the routing target's commands may carry.
#: A whitelist, because each forbidden list above closes only what somebody
#: thought to name: a deselecting pytest flag written as a plain literal —
#: ``-k``, ``-m``, ``--deselect``, ``--collect-only`` — retires the guard
#: exactly as ``{{.CLI_ARGS}}`` does and matches none of them. Listing what the
#: target *does* run inverts that, since the set is six tokens and closed by
#: inspection while the set of ways to retire a pytest run is not.
ROUTING_COMMAND_TOKENS: frozenset[str] = frozenset({
    ROUTING_TASK_RUNNER,
    GUARD_MODULE,
    "-v",
    "-o",
    "cache_dir=tmp/.pytest_cache",
    "--junitxml=tmp/junit_routing.xml",
})

#: Every key the routing target declares, as a whitelist. The target holds
#: three, which is as small and as closed by inspection as the guard step's two,
#: so the same equality that closes the step's key space closes this one — and
#: it closes it against a schema no reader here can enumerate, where the
#: forbidden list below closes only what somebody thought to name.
ROUTING_TARGET_KEYS: frozenset[str] = frozenset({"desc", "deps", "cmds"})

#: Target-level keys that retire the guard without touching its commands —
#: five of them measured end to end, and ``dotenv`` measured only as far as the
#: delivery, as each entry below says.
#: Named for the diagnostic rather than for the closure, the way
#: ``GUARD_JOB_FORBIDDEN_KEYS`` sits beneath ``GUARD_JOB_KEYS``:
#: ``ROUTING_TARGET_KEYS`` closes the target's key space by equality, and this
#: list is what makes a failure name the retirement rather than only report an
#: unexpected key.
#: ``ignore_error`` swallows the pytest exit. ``status`` makes go-task skip a
#: satisfied target outright, which is exactly how ``setup`` skips.
#: ``platforms`` narrows the target to matching hosts, which is not a property
#: an unconditional guard can have. ``sources`` puts the target under go-task's
#: checksum comparison: measured, ``sources:`` on its own reports the target up
#: to date and runs nothing on a later invocation whose listed sources are
#: unchanged, while ``sources:`` paired with ``generates:`` did not reproduce
#: that — the retirement is the ``sources:``-alone shape rather than every shape
#: carrying the key. ``env`` is measured end to end on go-task 3.52.0: against a
#: control printing ``13 passed, 355 deselected``, an otherwise identical target
#: carrying ``env: PYTEST_ADDOPTS: "--collect-only"`` printed
#: ``13/368 tests collected``, no pass or fail counts at all, and still exited 0
#: — no assertion was evaluated. ``dotenv`` is measured only as far as the
#: delivery: a variable set through it reaches the ``cmds:`` shell identically,
#: and that pytest then honours it is **inferred**, from pytest reading
#: ``PYTEST_ADDOPTS`` off the process environment whichever key populated it.
#: The target needs none of the six.
FORBIDDEN_ROUTING_TARGET_KEYS: tuple[str, ...] = ("ignore_error", "status", "platforms", "sources", "env", "dotenv")

#: The or-true suffix, matched as a pattern rather than a literal so both
#: spacings are caught. Tolerating a non-zero pytest exit here would fail open
#: in exactly the class this guard exists to close.
OR_TRUE_SUFFIX = re.compile(r"\|\|\s*true")

#: Reads the junit destination back off a target's commands, so the routing
#: target's artifact can be checked against every other target's.
JUNIT_DESTINATION = re.compile(r"--junitxml=(\S+)")

#: Probes whether one announced target collects, returning the raw process so
#: the exit-code contract stays with the caller.
CollectFn = Callable[[str], subprocess.CompletedProcess[str]]

#: How many times the shared-probe fixture has been built. One is the whole
#: budget: the caches below hold a route per pair and a collection per target,
#: and a probe rebuilt per case would re-route and re-collect for every one of
#: them while still reporting the same verdicts. Read by the last test in the
#: walk, which is also the one whose premise is that a single probe served
#: everything before it. Counted in the fixture rather than in the constructor
#: because the property is that *the walk* shares one probe: the health tests
#: below build their own on purpose, and counting those would make the reading
#: depend on which tests a selection happens to include.
PROBE_FIXTURE_BUILDS = 0


def collect_target(target: str, *, root: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    """
    Ask pytest to collect one routing target without running anything.

    ``sys.executable -m pytest`` rather than a ``.venv/bin/pytest`` path: the
    repository is bind-mounted into ``pytest-cli``, so that file exists in the
    container but its shebang names a host interpreter and the exec fails with
    ENOENT. The arguments ahead of the target are ``PROBE_ARGUMENTS``, which the
    import-time scan reads as its own exemption: ``-p no:cacheprovider`` keeps
    pytest from writing a cache directory into the mount, whose only writable
    subtree is ``tmp/``, and ``--`` stops a tracked path beginning with a hyphen
    being read as a flag.

    The probe rests on an explicit path argument overriding ``pytest.ini``'s
    ``norecursedirs``, which lists ``tests/ci`` among others: pytest applies
    that filter while recursing rather than to the paths it is handed, so a
    directory named on the command line is collected even where a walk from
    ``testpaths`` would skip it. Recorded rather than pinned on its own — the
    walk already asserts that every announced target collects, so were the
    behaviour to change, every directory target in the announcement set would
    report as an empty hole rather than pass.

    Args:
        target: Announced pytest target, repository-relative.
        root: Directory the probe runs from.

    Returns:
        The completed collection process, unclassified.

    Raises:
        subprocess.TimeoutExpired: If the collector has not returned within
            ``COLLECT_TIMEOUT_SECONDS``.
    """
    return subprocess.run(
        [sys.executable, "-m", "pytest", *PROBE_ARGUMENTS, target],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=COLLECT_TIMEOUT_SECONDS,
    )


class RoutingProbe:
    """Session cache of router announcements and per-target collection outcomes.

    The walk is one case per ``(router, tracked path)`` — several hundred — while
    the announced targets deduplicate to far fewer, so a route runs once per pair
    and a collection once per distinct target. Both callables are injected, so a
    test can substitute a router that dies or a collector that breaks.
    """

    def __init__(self, route: RouteFn, collect: CollectFn) -> None:
        """
        Hold the injected callables and their caches.

        Args:
            route: Runs a router against a changed-file list.
            collect: Probes whether one target collects any tests.
        """
        self._route = route
        self._collect = collect
        self._announced: dict[tuple[str, str], tuple[str, ...]] = {}
        self._collects: dict[str, bool] = {}
        self._collect_failures: dict[str, Exception] = {}

    @property
    def cached_routes(self) -> int:
        """
        How many ``(router, path)`` pairs this probe has routed and held.

        Returns:
            The number of cached announcements.
        """
        return len(self._announced)

    @property
    def cached_collections(self) -> int:
        """
        How many distinct announced targets this probe has probed for collection.

        Returns:
            The number of cached collection outcomes.
        """
        return len(self._collects)

    def announced_targets(self, router: str, path: str) -> tuple[str, ...]:
        """
        Route one changed path and return the targets the router announced.

        A non-zero exit is a router defect, never a routing hole: a router that
        dies before announcing produces the same empty target list as one that
        deliberately selected nothing.

        ``routed_targets`` reads the first announcement line only, so a second
        one is rejected rather than silently dropped.

        Args:
            router: Router filename under ``ci/``.
            path: Single changed path to route.

        Returns:
            The announced targets, empty when the router selected none.

        Raises:
            AssertionError: If the router exited non-zero or announced twice.
        """
        key = (router, path)
        if key not in self._announced:
            result = self._route(router, [path], target=ROUTE_TARGET)
            assert result.returncode == 0, (
                f"ci/{router} exited {result.returncode} on {path}; a router that fails is a router "
                f"defect and MUST NOT be recorded as a routing hole\n{diagnose(result)}"
            )
            announcements = [line for line in result.stdout.splitlines() if line.startswith(ANNOUNCE_PREFIX)]
            assert len(announcements) <= 1, (
                f"ci/{router} announced {len(announcements)} target lists for {path}; only the first "
                f"is read, so every later one would go uncovered in silence\n{diagnose(result)}"
            )
            self._announced[key] = tuple(routed_targets(result))
        return self._announced[key]

    def collects_tests(self, target: str) -> bool:
        """
        Probe whether an announced target collects at least one test.

        A failed probe is cached alongside the successful ones. Several hundred
        cases reference the same handful of targets, so a collector that wedges
        or exits unclassifiably would otherwise be re-run once per referencing
        case — each one paying the full liveness ceiling before failing the same
        way, with the job's own timeout as the only bound.

        The cached failure is reported rather than re-raised as the original
        object: re-raising one exception several hundred times appends a frame
        to its traceback on every raise, so the last case rendered would carry
        a traceback the length of the walk.

        Args:
            target: Announced pytest target.

        Returns:
            ``True`` when pytest collected something.

        Raises:
            AssertionError: If the collector exited anything other than
                collected-or-empty, or if an earlier probe of this target
                already failed.
            subprocess.TimeoutExpired: If the collector has not returned within
                ``COLLECT_TIMEOUT_SECONDS``, on the first probe of a target.
        """
        cached_failure = self._collect_failures.get(target)
        if cached_failure is not None:
            raise AssertionError(f"collecting {target} already failed once this run with {type(cached_failure).__name__}: {cached_failure}")
        if target not in self._collects:
            try:
                result = self._collect(target)
                assert result.returncode in (COLLECTED_EXIT, NO_TESTS_COLLECTED_EXIT), (
                    f"collecting {target} exited {result.returncode}; only {COLLECTED_EXIT} (collected) and "
                    f"{NO_TESTS_COLLECTED_EXIT} (no tests) classify, and reading any other exit as either "
                    f"one files a wrong verdict\n--- stdout ---\n{result.stdout}--- stderr ---\n{result.stderr}"
                )
            except (AssertionError, subprocess.TimeoutExpired) as failure:
                self._collect_failures[target] = failure
                raise
            self._collects[target] = result.returncode == COLLECTED_EXIT
        return self._collects[target]


def uncovered_reason(router: str, path: str, *, probe: RoutingProbe) -> str | None:
    """
    Decide whether one ``(router, path)`` pair reaches a test that exists, registry aside.

    Args:
        router: Router filename under ``ci/``.
        path: Tracked repository-relative path.
        probe: Cache supplying announcements and collection outcomes.

    Returns:
        Why the pair reaches no test, or ``None`` when it reaches one.
    """
    announced = probe.announced_targets(router, path)
    if not announced:
        return (
            f"ci/{router} announced no pytest target for {path}, so a change to it runs no test — "
            "route it, or register the pair in helpers.router_coverage_registry"
        )
    distinct = sorted(set(announced))
    empty = [target for target in distinct if not probe.collects_tests(target)]
    if empty:
        return (
            f"ci/{router} routed {path} to {distinct}, of which {empty} collect no tests — a target "
            "that collects nothing is as silent as no target at all"
        )
    return None


def routing_hole_reason(
    router: str,
    path: str,
    *,
    probe: RoutingProbe,
    exempt_pairs: frozenset[tuple[str, str]],
) -> str | None:
    """
    Decide whether one ``(router, path)`` pair is a routing hole the guard reports.

    The registry is applied last, not first: short-circuiting on an exemption
    would leave the exempt pair's router unrun, so a router that dies on one of
    them would never be noticed, and nothing would record whether the exemption
    is still earning its place.

    Args:
        router: Router filename under ``ci/``.
        path: Tracked repository-relative path.
        probe: Cache supplying announcements and collection outcomes.
        exempt_pairs: Pairs the registry excuses.

    Returns:
        Why the pair is a hole, or ``None`` when it is covered or exempt.
    """
    reason = uncovered_reason(router, path, probe=probe)
    if reason is None or (router, path) in exempt_pairs:
        return None
    return reason


class RouterCase(NamedTuple):
    """One unit of the walk: a router and one of the tracked paths it filters in."""

    #: Router filename under ``ci/``.
    router: str
    #: Tracked repository-relative path; empty when enumeration failed.
    path: str
    #: Why the universe could not be enumerated, or ``None``.
    enumeration_failure: str | None


def _build_router_cases() -> tuple[tuple[RouterCase, ...], tuple[str, ...]]:
    """
    Enumerate one case per router and tracked path, at import time.

    ``changed_scripts_universe`` shells out to git and rescans the whole listing
    once per filter alternative, so it is called once per router and its result
    held; a per-case call would multiply that by the size of the universe.

    Its floor is asserted inline, so a broken enumeration raises here, while the
    parametrize arguments are being built. Letting that propagate would be a
    collection error, which takes the module with it and reports as an error
    rather than as a failing test, so it is turned into a single always-failing
    case per router instead. An empty router list degrades the same way.

    Enumeration fails in five shapes, and all five are caught: the floor's
    ``AssertionError``; a ``re.error`` if a router's filter gains a nested
    alternation, since the reconstruction splits on the pipe and would then
    compile unbalanced fragments; an ``OSError`` if the git listing cannot be
    run; a ``UnicodeDecodeError`` if it returns bytes the listing's declared
    encoding cannot decode, which is what a tracked path in another encoding
    produces; and a ``subprocess.TimeoutExpired`` if git does not return inside
    the listing's liveness ceiling. Any one left uncaught is exactly the
    collection error this degradation exists to avoid.

    Returns:
        The cases, and their pytest ids in the same order.
    """
    cases: list[RouterCase] = []
    ids: list[str] = []
    for router in TEST_ROUTERS:
        try:
            universe = changed_scripts_universe(router)
        except (AssertionError, re.error, OSError, UnicodeDecodeError, subprocess.TimeoutExpired) as failure:
            cases.append(RouterCase(router, "", f"{type(failure).__name__}: {failure}"))
            ids.append(f"{router}-enumeration-failed")
            continue
        for path in universe:
            cases.append(RouterCase(router, path, None))
            ids.append(f"{router}-{path}")
    if not cases:
        cases.append(RouterCase("", "", f"there are no routers to walk: TEST_ROUTERS is {TEST_ROUTERS!r}"))
        ids.append("no-routers")
    return tuple(cases), tuple(ids)


ROUTER_CASES, ROUTER_CASE_IDS = _build_router_cases()

#: Walk cases this process has executed. The import-time scan above reads what
#: the run was *started with*, over three channels and two spellings; this reads
#: what it *ran*. A run narrowed by a channel that scan does not read, or by an
#: option spelled some other way, leaves the count short of the walk.
EXECUTED_ROUTER_CASES = 0

#: The parametrize argument carrying a walk case. Read off the executing node so
#: that the count is over the walk rather than over every test in the module:
#: what the floor asserts is that every tracked path was routed, and the wiring
#: pins are a different claim, held by their own cases.
#: Bound by the walk's own parametrize as well as read off the node, for the
#: reason ``AGGREGATE_SITE_PARAM`` is: spelled as a literal on the binding side,
#: it would be a hand-copy that keeps the reading side passing after the
#: parametrize it claims to mirror is renamed.
ROUTER_CASE_PARAM = "case"

#: Status the floor ends the process with. Outside pytest's own exit codes, so a
#: run ending this way cannot be read as one of pytest's verdicts — including
#: the no-tests-collected 5 that both routers forgive.
UNRUN_WALK_EXIT = 70


def _is_walk_case(callspec: object) -> bool:
    """
    Decide whether one node's ``callspec`` binds a walk case.

    Named rather than written inline in the fixture below, so that the
    discriminator the floor's count rests on has a subject an assertion can
    reach. ``TestWalkCasePredicate`` is what reaches it, and why nothing else
    in this module does is recorded there.

    Args:
        callspec: The ``callspec`` pytest hangs on a parametrized node, or
            ``None`` for a node it did not parametrize.

    Returns:
        Whether the node is one case of the walk.
    """
    params = getattr(callspec, "params", None)
    return isinstance(params, dict) and isinstance(params.get(ROUTER_CASE_PARAM), RouterCase)


@pytest.fixture(autouse=True)
def _count_executed_router_case(request: pytest.FixtureRequest) -> None:
    """Record that one walk case is about to run, for the floor below to read."""
    global EXECUTED_ROUTER_CASES
    if _is_walk_case(getattr(request.node, "callspec", None)):
        EXECUTED_ROUTER_CASES += 1


def exit_when_the_walk_did_not_run() -> None:
    """
    End the process non-zero when fewer cases ran than the walk holds.

    Registered with ``atexit`` at import, so it is reached however the run ends,
    including one that evaluated no assertion at all and would otherwise exit 0.

    What it observes is the count, and only the count — never a cause. A
    narrowing is one way to leave the count short; a collection error in any
    module the session collects is another, since pytest abandons the session
    on one; so is a failing session-scoped fixture, because the counter is
    function-scoped and ``session_route`` is built ahead of the first case that
    would increment it. So is ``-x`` after a genuine routing hole, and that one
    inverts the report: the hole's own exit 1 is replaced by
    ``UNRUN_WALK_EXIT``, which names a run that did not finish rather than the
    hole it found. The message below therefore states the count rather than a
    diagnosis of it.

    ``os._exit`` rather than a raised ``SystemExit``: raising
    ``SystemExit(UNRUN_WALK_EXIT)`` here instead printed
    ``Exception ignored in atexit callback ...: SystemExit: 70`` and the process
    still exited 1. So the exception is reported rather than swallowed, and it
    does not replace the status already chosen — which is the whole property
    ``os._exit`` is here for. The streams are flushed
    first because ``os._exit`` skips that, and pytest's own output is
    block-buffered whenever it is piped.
    """
    if EXECUTED_ROUTER_CASES >= len(ROUTER_CASES):
        return
    print(
        f"{GUARD_MODULE}: {EXECUTED_ROUTER_CASES} of {len(ROUTER_CASES)} routing cases ran, so the guard "
        "reached none of the tracked paths it did not run a case for, and a run that asserted nothing about "
        "them MUST NOT report success. `task test:routing` runs the whole module.",
        file=sys.stderr,
    )
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(UNRUN_WALK_EXIT)


# Registered except in this module's own collection probe, which runs
# `--collect-only` against an announced target and so runs no case by design.
# The exemption is the argument vector the probe is built from, which is what
# the import-time scan above exempts, rather than a second channel of its own.
if not _is_collection_probe(sys.argv[1:]):
    atexit.register(exit_when_the_walk_did_not_run)


@pytest.fixture(scope="session")
def exempt_pairs() -> frozenset[tuple[str, str]]:
    """
    The ``(router, path)`` pairs the registry excuses.

    Returns:
        One entry per registry exemption, projected onto its identity pair.
    """
    return frozenset((entry.router, entry.path) for entry in EXEMPTIONS)


@pytest.fixture(scope="session")
def routing_probe(session_route: RouteFn) -> RoutingProbe:
    """
    One probe, and so one cache, shared by every case in the walk.

    Args:
        session_route: Session-scoped route callable over one reused workspace.

    Returns:
        The probe the whole walk shares.
    """
    global PROBE_FIXTURE_BUILDS
    PROBE_FIXTURE_BUILDS += 1
    return RoutingProbe(session_route, collect_target)


class TestRouterCoverage:
    """Every tracked path a router filters in reaches a test that exists."""

    @pytest.mark.parametrize(ROUTER_CASE_PARAM, ROUTER_CASES, ids=ROUTER_CASE_IDS)
    def test_tracked_path_reaches_a_collecting_target(
        self,
        case: RouterCase,
        routing_probe: RoutingProbe,
        exempt_pairs: frozenset[tuple[str, str]],
    ) -> None:
        """One case per router and path, so two holes report as two failures."""
        assert case.enumeration_failure is None, (
            f"ci/{case.router}: the CHANGED_SCRIPTS universe could not be enumerated, so this run "
            f"covers none of its tracked paths\n{case.enumeration_failure}"
        )
        reason = routing_hole_reason(case.router, case.path, probe=routing_probe, exempt_pairs=exempt_pairs)
        assert reason is None, reason

    def test_registry_is_exactly_the_measured_hole_set(
        self,
        routing_probe: RoutingProbe,
        exempt_pairs: frozenset[tuple[str, str]],
    ) -> None:
        """The registry equals the holes, so an exemption that stops being needed fails here.

        Uniqueness is asserted before the comparison rather than after it.
        ``EXEMPTIONS`` is a tuple, so two entries sharing a ``(router, path)``
        while differing in ``reason`` or ``todo_id`` are structurally possible,
        and the projection this comparison runs on would collapse them into one
        member — excusing a pair while the two sides still balanced. Declaring
        the container a ``frozenset`` would not close that: ``reason`` and
        ``todo_id`` are part of the entry's identity, so such a pair stays two
        distinct members and still collapses under the projection.

        The probe is the session-scoped one the walk shares, so each pair costs a
        route once per run whichever of the two reaches it first.
        """
        pairs = [(entry.router, entry.path) for entry in EXEMPTIONS]
        duplicated = sorted({pair for pair in pairs if pairs.count(pair) > 1})
        assert len(pairs) == len(set(pairs)), (
            f"helpers.router_coverage_registry lists {len(pairs)} exemptions covering only "
            f"{len(set(pairs))} distinct (router, path) pairs; duplicates {duplicated} collapse in the "
            "comparison below, which would then balance while a pair went silently excused"
        )
        unenumerable = [case for case in ROUTER_CASES if case.enumeration_failure is not None]
        assert not unenumerable, (
            "the universe could not be enumerated, so the measured set below is a subset of the real "
            f"one and MUST NOT be compared against the registry\n{unenumerable[0].enumeration_failure}"
        )
        measured = frozenset(
            (case.router, case.path) for case in ROUTER_CASES if uncovered_reason(case.router, case.path, probe=routing_probe) is not None
        )
        assert measured == exempt_pairs, (
            "the registry and the measured hole set disagree\n"
            f"exempt but no longer a hole (delete these): {sorted(exempt_pairs - measured)}\n"
            f"a hole but not exempt (route these, or register them): {sorted(measured - exempt_pairs)}"
        )

    def test_registry_names_only_tracked_paths(self) -> None:
        """A registry path git does not track excuses nothing and reads as if it did.

        Such an entry is a typo or a stale path: no case in the walk ever carries
        it. The comparison above already reds on it, as an unexplained set
        difference; this names the cause instead, which is the difference between
        a one-line fix and a re-derivation of the hole set.
        """
        assert EXEMPTIONS, "the registry is empty, which leaves this scan vacuous"
        tracked = frozenset(tracked_paths())
        unknown = sorted({entry.path for entry in EXEMPTIONS if entry.path not in tracked})
        assert not unknown, (
            f"helpers.router_coverage_registry exempts untracked paths {unknown}; a path git does not "
            "track is a path no router ever routes, so the entry excuses nothing"
        )

    def test_registry_cites_only_enumerated_todo_ids(self) -> None:
        """Every exemption cites an enumerated id, and every enumerated id is cited.

        Why the reverse direction is asserted alongside the forward one is
        recorded at ``ENUMERATED_TODO_IDS``.
        """
        assert EXEMPTIONS, "the registry is empty, which leaves this scan vacuous"
        assert ENUMERATED_TODO_IDS, "the enumerated-id set is empty, which leaves this scan vacuous"
        cited = {entry.todo_id for entry in EXEMPTIONS}
        unknown = sorted(cited - ENUMERATED_TODO_IDS)
        assert not unknown, (
            f"helpers.router_coverage_registry cites TODO ids {unknown} outside {sorted(ENUMERATED_TODO_IDS)}; "
            "use the id whose subject describes the hole, or the standing-holes catch-all"
        )
        uncited = sorted(ENUMERATED_TODO_IDS - cited)
        assert not uncited, (
            f"ENUMERATED_TODO_IDS admits {uncited}, which no exemption cites; an admitted id nothing uses is "
            "a landing site a typo can hit while still passing the check above — drop it, or add the "
            "exemption it was admitted for"
        )

    def test_pinned_path_routing_outcome_is_unchanged(self, routing_probe: RoutingProbe) -> None:
        """Each router's announcement for the pinned path is asserted, not merely exempted.

        Why the pair's shape is pinned as well as its existence is recorded at
        ``PINNED_OUTCOME_PATH``, and the shape each router produces at
        ``PINNED_OUTCOME_TARGETS``.
        """
        assert frozenset(PINNED_OUTCOME_TARGETS) == frozenset(TEST_ROUTERS), (
            f"the pinned outcomes cover {sorted(PINNED_OUTCOME_TARGETS)} while the routers are "
            f"{sorted(TEST_ROUTERS)}; a router with no pinned outcome is not asserted here at all"
        )
        for router in TEST_ROUTERS:
            announced = routing_probe.announced_targets(router, PINNED_OUTCOME_PATH)
            assert announced == PINNED_OUTCOME_TARGETS[router], (
                f"ci/{router} announces {list(announced)} for {PINNED_OUTCOME_PATH}, not "
                f"{list(PINNED_OUTCOME_TARGETS[router])}; if the routing was fixed, drop the registry "
                "exemption for the pair and repoint this pin"
            )
            for target in announced:
                assert not routing_probe.collects_tests(target), (
                    f"ci/{router} routes {PINNED_OUTCOME_PATH} to {target}, which now collects tests; "
                    "the pair is no longer a hole and its registry exemption has to go"
                )

    def test_registry_edits_route_back_into_this_suite(self, routing_probe: RoutingProbe) -> None:
        """A changed registry module reaches the helpers suite and this one, in both routers.

        Why the registry's location is what makes that hold, and why the
        fan-out is pinned, is recorded at ``REGISTRY_MODULE``.
        """
        assert REGISTRY_FANOUT_TARGETS, "the pinned fan-out is empty, which leaves this check vacuous"
        registry_source = router_coverage_registry.__file__
        assert registry_source and (REPO_ROOT / REGISTRY_MODULE).resolve() == Path(registry_source).resolve(), (
            f"{REGISTRY_MODULE} is not the module this guard reads its exemptions from ({registry_source}), so "
            "the fan-out below is measured for a path the guard does not actually depend on — repoint "
            "REGISTRY_MODULE at wherever the registry now lives"
        )
        for router in TEST_ROUTERS:
            announced = frozenset(routing_probe.announced_targets(router, REGISTRY_MODULE))
            assert REGISTRY_FANOUT_TARGETS <= announced, (
                f"ci/{router} routes {REGISTRY_MODULE} to {sorted(announced)}, which omits "
                f"{sorted(REGISTRY_FANOUT_TARGETS - announced)}; the registry belongs under "
                "tests/helpers/ precisely so that editing it re-runs this guard"
            )

    def test_guard_sources_carry_no_container_detection(self) -> None:
        """No scanned source behind this guard branches on being containerised.

        Both routers run their announced targets in ``pytest-cli``, and they
        reach this module on a pull request changing a non-test module under
        ``tests/helpers/`` or the guard module itself — not on every pull
        request under a router prefix. A skip inside that channel would silence
        the one run that detects an un-routed source there; the repair for a red
        in-container run is the interpreter resolution in ``collect_target``.

        ``tests/helpers/router_harness.py`` is on the same import path and is
        not scanned; see ``CONTAINER_DETECTION_SCAN_SOURCES`` for why, and for
        what closing it would take.
        """
        assert CONTAINER_DETECTION_TOKENS, "the forbidden-token list is empty, which leaves this scan vacuous"
        assert CONTAINER_DETECTION_SCAN_SOURCES, "the scanned-source list is empty, which leaves this scan vacuous"
        assert (REPO_ROOT / GUARD_MODULE).resolve() == Path(__file__).resolve(), (
            f"{GUARD_MODULE} is not this module, so the scan below reads the wrong source — repoint "
            "GUARD_MODULE at wherever this guard now lives"
        )
        for relative in CONTAINER_DETECTION_SCAN_SOURCES:
            source_path = REPO_ROOT / relative
            assert source_path.is_file(), f"{relative} is missing, which leaves this scan vacuous"
            source = source_path.read_text(encoding="utf-8")
            present = [token for token in CONTAINER_DETECTION_TOKENS if token in source]
            assert not present, (
                f"{relative} references container detectors {present}; this guard MUST NOT skip "
                "in-container, because in-container is where an un-routed source is detected"
            )

    def test_guard_source_rebuilds_no_routing_target(self) -> None:
        """This module re-models no part of either dispatch chain.

        The guard's whole value is that it executes the routers: a target
        rebuilt from a source path agrees with a broken router by construction,
        which is the defect being guarded against. The scan reads this module
        only — ``helpers.router_harness`` spells the same expressions on purpose,
        in the negative tests that prove the routers do not derive.
        """
        assert SOURCE_PATH_DERIVATION_TOKENS, "the derivation-token list is empty, which leaves this scan vacuous"
        source_path = REPO_ROOT / GUARD_MODULE
        assert source_path.resolve() == Path(__file__).resolve(), (
            f"{GUARD_MODULE} is not this module, so the scan below reads the wrong source — repoint "
            "GUARD_MODULE at wherever this guard now lives"
        )
        source = source_path.read_text(encoding="utf-8")
        present = [token for token in SOURCE_PATH_DERIVATION_TOKENS if token in source]
        assert not present, (
            f"{GUARD_MODULE} builds a routing target with {present}; run the router and read its "
            "announcement instead, because a rebuilt target agrees with a router that is broken"
        )

    def test_session_workspace_survives_prior_calls(
        self,
        session_route: RouteFn,
        route_variant: RouteVariantFn,
        routing_probe: RoutingProbe,
    ) -> None:
        """A reused workspace announces exactly what a fresh one does.

        The premise — that the session workspace has already served every case
        above — is asserted rather than assumed. This test reads the same probe
        the walk shares, and a single probe holding a filled cache is what makes
        the premise true; under a selection that reaches this test first, or a
        probe that stops being session-scoped, the assertions below fail rather
        than pass against a workspace nothing has touched.

        Each comparison builds its own control workspace: one control shared
        across the loop would itself have served the earlier samples by the
        second comparison, so only the first would compare against a genuinely
        fresh one.

        Both sides of every comparison are asserted non-empty, and so is the
        noise call. A sample that goes stale — a renamed agent file, a moved
        script — routes nothing in *both* workspaces, and the equality then
        holds between two empty lists while proving nothing about reuse; a
        noise call that routes nothing leaves the settling assertion below
        checking that an untouched workspace stayed untouched.
        """
        assert PROBE_FIXTURE_BUILDS == 1, (
            f"the shared-probe fixture was built {PROBE_FIXTURE_BUILDS} times this session, not 1; the walk "
            "shares one probe, so any more means the fixture is no longer session-scoped and every case "
            "re-routed and re-collected from an empty cache"
        )
        assert routing_probe.cached_routes and routing_probe.cached_collections, (
            f"the shared probe holds {routing_probe.cached_routes} routes and "
            f"{routing_probe.cached_collections} collection outcomes, so the walk has not run through this "
            "workspace yet and the comparison below would prove nothing about reuse"
        )
        assert CONTAMINATION_SAMPLES, "there are no samples to compare, which leaves the reuse check vacuous"
        assert CONTAMINATION_NOISE, "there is nothing to dirty the workspace with, which leaves the settling check vacuous"
        for router in TEST_ROUTERS:
            for sample in CONTAMINATION_SAMPLES:
                reused = session_route(router, [sample], target=ROUTE_TARGET)
                fresh = route_variant()(router, [sample], target=ROUTE_TARGET)
                assert reused.returncode == 0, diagnose(reused)
                assert fresh.returncode == 0, diagnose(fresh)
                assert routed_targets(reused), (
                    f"ci/{router} announced nothing for {sample} in the reused session workspace; the sample "
                    "has to route something, or the comparison below holds between two empty lists and "
                    "leaves this scan vacuous — repoint CONTAMINATION_SAMPLES at a path that still routes\n"
                    f"{diagnose(reused)}"
                )
                assert routed_targets(reused) == routed_targets(fresh), (
                    f"ci/{router} announced {routed_targets(reused)} for {sample} in the reused session "
                    f"workspace and {routed_targets(fresh)} in a fresh one"
                )
            noise = session_route(router, list(CONTAMINATION_NOISE), target=ROUTE_TARGET)
            assert noise.returncode == 0, diagnose(noise)
            assert routed_targets(noise), (
                f"ci/{router} announced nothing for {list(CONTAMINATION_NOISE)}; the noise call has to dirty "
                "the workspace, or the settling assertion below only shows that an untouched workspace stayed "
                f"untouched — repoint CONTAMINATION_NOISE at paths that still route\n{diagnose(noise)}"
            )
            settled = session_route(router, [UNROUTED_SAMPLE], target=ROUTE_TARGET)
            assert settled.returncode == 0, diagnose(settled)
            assert routed_targets(settled) == [], (
                f"ci/{router} announced {routed_targets(settled)} for {UNROUTED_SAMPLE} after a call that "
                f"routed {list(CONTAMINATION_NOISE)}: the earlier list survived into the later call"
            )


def unclassified_collect(target: str) -> subprocess.CompletedProcess[str]:
    """
    Stand in for a collector that neither collected nor reported an empty run.

    Args:
        target: Target the real collector would have been asked about.

    Returns:
        A completed process carrying an exit outside the classified pair.
    """
    return subprocess.CompletedProcess(args=[target], returncode=UNCLASSIFIED_COLLECT_EXIT, stdout="", stderr="")


def unroutable(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    """
    Fill a probe's route slot for a test that must never route.

    Args:
        args: Whatever the caller would have routed.
        kwargs: Whatever the caller would have routed.

    Returns:
        Never returns.

    Raises:
        AssertionError: Always, since reaching it means the probe routed.
    """
    raise AssertionError(f"the probe routed {args!r} {kwargs!r}; this test exercises the collector only")


class TestProbeHealthChecks:
    """The probe's two health assertions fire on the failures they describe.

    Neither can fail anywhere else in this module: every case above routes
    through a shadowed security gate and probes with the real collector, so
    both assertions hold on every input the walk supplies, and deleting either
    leaves the rest of the suite green. The seams that drive them off those
    defaults — ``route_variant``'s ``shadow_security_gate`` argument and the
    probe's injected collector — have no other non-default caller.
    """

    def test_router_that_dies_is_not_read_as_a_routing_hole(self, route_variant: RouteVariantFn) -> None:
        """A router killed before it announces fails here, rather than reporting no targets.

        Withholding the gate shadow reproduces the death on demand: both
        routers invoke the security gate by a relative path *before* the
        announcement, so an absent one kills the router under ``set -e``. Why
        the sample has to route a target is recorded at
        ``ROUTER_HEALTH_SAMPLE``.
        """
        probe = RoutingProbe(route_variant(shadow_security_gate=False), collect_target)
        for router in TEST_ROUTERS:
            with pytest.raises(AssertionError, match="a router that fails is a router defect"):
                probe.announced_targets(router, ROUTER_HEALTH_SAMPLE)

    def test_collector_exit_outside_the_classified_pair_fails(self) -> None:
        """An unclassifiable collector exit fails, rather than being read as either verdict.

        What each reading of such an exit costs is recorded at
        ``COLLECTED_EXIT``. The injected collector is the only way to produce
        such an exit, since the real one is a pytest collection run.

        The route slot is filled by a callable that fails if it is ever called,
        so the assertion covers the collector alone and no workspace is built to
        serve a probe that never routes.

        The second call asserts the failure is cached like a success. Several
        hundred cases reference the same handful of targets, so a collector
        that fails un-cached is re-run once per referencing case — each one
        paying the full liveness ceiling to fail the same way — with nothing
        but the job's own timeout to end it.
        """
        probed: list[str] = []

        def counting_collect(target: str) -> subprocess.CompletedProcess[str]:
            probed.append(target)
            return unclassified_collect(target)

        probe = RoutingProbe(unroutable, counting_collect)
        with pytest.raises(AssertionError, match=f"exited {UNCLASSIFIED_COLLECT_EXIT}"):
            probe.collects_tests(STUB_COLLECT_TARGET)
        with pytest.raises(AssertionError, match="already failed once this run"):
            probe.collects_tests(STUB_COLLECT_TARGET)
        assert probed == [STUB_COLLECT_TARGET], (
            f"the collector ran {len(probed)} times for one target; a failed probe has to be held the way a "
            "successful one is, or one wedging target is paid for once per case that names it"
        )


#: The case a narrowed child run below selects. Held against the method itself
#: rather than written as a literal: a selection matching nothing narrows the
#: child to zero cases, which trips the floor too, so a stale literal would keep
#: the pin passing while it stopped selecting the thing it names. This one
#: routes nothing and probes nothing, which is why it is the one chosen.
NARROWING_SELECTION = TestRouterCoverage.test_registry_names_only_tracked_paths.__name__

#: Two ways of narrowing a run that the import-time scan does not see. ``-k`` is
#: outside ``DESELECTING_OPTIONS`` and leaves one case selected. ``-o``
#: overrides the ini and is prepended to the arguments as two tokens, of which
#: neither is a pinned spelling. ``-p no:cacheprovider`` keeps a child from writing a cache
#: directory into a mount whose only writable subtree is ``tmp/``, and ``--``
#: stops the module path being read as a flag.
NARROWING_ARGUMENTS: tuple[tuple[str, ...], ...] = (
    ("-p", "no:cacheprovider", "-k", NARROWING_SELECTION, "--"),
    ("-p", "no:cacheprovider", "-o", f"addopts={DESELECTING_OPTIONS[0]}", "--"),
)

#: Ids for the cases driving those arguments. Written out rather than rendered
#: from the arguments themselves: ``-k`` matches a substring of the whole node
#: id, parametrize ids included, so an id echoing the selection is matched by
#: it — the child would then select the case that spawned it, spawn a child of
#: its own, and every generation would run to ``COLLECT_TIMEOUT_SECONDS`` before
#: the one above it gave up.
NARROWING_IDS: tuple[str, ...] = ("selection-flag", "ini-override")


def run_this_module(arguments: Sequence[str], *, ambient: str) -> subprocess.CompletedProcess[str]:
    """
    Run this module in a child pytest process, with the ambient variable pinned.

    ``sys.executable -m pytest`` for the reason ``collect_target`` uses it: the
    repository is bind-mounted into ``pytest-cli``, so ``.venv/bin/pytest``
    exists in the container but its shebang names a host interpreter.

    The ambient variable is written rather than inherited, so a child's outcome
    turns on the arguments under test rather than on what the parent's shell
    happened to export.

    Args:
        arguments: Pytest arguments to run ahead of this module's path.
        ambient: Value to give the ambient add-options variable in the child.

    Returns:
        The completed child process, unclassified.

    Raises:
        subprocess.TimeoutExpired: If the child has not returned within
            ``COLLECT_TIMEOUT_SECONDS``.
    """
    return subprocess.run(
        [sys.executable, "-m", "pytest", *arguments, GUARD_MODULE],
        cwd=REPO_ROOT,
        env={**os.environ, AMBIENT_ADDOPTS_ENV_VAR: ambient},
        capture_output=True,
        text=True,
        check=False,
        timeout=COLLECT_TIMEOUT_SECONDS,
    )


class TestOutOfCaseAssertionsAreCalled:
    """The two assertions that run outside a case body are wired into this module.

    Their bodies are exercised elsewhere — the scan on synthetic arguments, the
    floor on the count it reads — and neither exercise reads a *call site*.
    Deleting the module-level call to the scan, or the ``atexit`` registration
    below it, leaves every other case in this module green — which is the shape
    of an assertion that has stopped existing without anything failing.

    Each case here runs a child pytest process that can only red because the
    call site it pins is still there.
    """

    @pytest.mark.parametrize("arguments", NARROWING_ARGUMENTS, ids=NARROWING_IDS)
    def test_a_narrowed_run_of_this_module_ends_on_the_floor(self, arguments: tuple[str, ...]) -> None:
        """A child reaching fewer cases than the walk holds exits ``UNRUN_WALK_EXIT``.

        Both narrowings leave pytest reporting success on its own account: one
        runs a single cheap case and one collects without running anything, and
        the import-time scan reads neither as a deselecting option. The status
        asserted is ``UNRUN_WALK_EXIT``, so the pin cannot be satisfied by the
        child failing for some other reason.
        """
        result = run_this_module(arguments, ambient="")
        assert result.returncode == UNRUN_WALK_EXIT, (
            f"a child running {list(arguments)} against {GUARD_MODULE} exited {result.returncode}, not "
            f"{UNRUN_WALK_EXIT}; the run reached fewer cases than the walk holds, so the floor registered at "
            f"import has to end it non-zero\n--- stdout ---\n{result.stdout}--- stderr ---\n{result.stderr}"
        )

    def test_importing_this_module_runs_the_import_time_scan(self) -> None:
        """A child importing this module with a poisoned ambient variable reds at collection.

        The child is handed the collection probe's own argument vector, so the
        command line is exempt and no case runs — which leaves the floor
        unregistered and the ambient channel the only thing that can red it. A
        child that collects cleanly means the module-level call is gone.
        """
        result = run_this_module(PROBE_ARGUMENTS, ambient=DESELECTING_OPTIONS[0])
        rendered = result.stdout + result.stderr
        assert result.returncode not in (COLLECTED_EXIT, NO_TESTS_COLLECTED_EXIT), (
            f"a child collecting {GUARD_MODULE} with ${AMBIENT_ADDOPTS_ENV_VAR}={DESELECTING_OPTIONS[0]!r} "
            f"exited {result.returncode}; importing this module has to run the scan, not merely define it\n{rendered}"
        )
        assert result.returncode != UNRUN_WALK_EXIT, (
            f"the child exited on the floor rather than on the import-time scan; the probe's own argument "
            f"vector is exempt from the floor, so this pin would stop reading the scan at all\n{rendered}"
        )
        assert AMBIENT_ADDOPTS_ENV_VAR in rendered, (
            f"the child failed without naming ${AMBIENT_ADDOPTS_ENV_VAR}, so what red it is not the channel this pin reads\n{rendered}"
        )


class TestExecutionFloorThreshold:
    """The floor's predicate fires one case short of the walk, and not at it.

    The children above pin the floor's *call site*, and both of them drive the
    count to zero: ``-k`` selects a case whose name appears in no walk id, and
    ``--collect-only`` runs nothing. So ``0 >= len(ROUTER_CASES)`` is the only
    state they observe, and a predicate rewritten to forgive any count above
    zero — ``> 0`` — passes every one of them while permitting a run that
    executed a single walk case. That is the deselect-all-but-one narrowing,
    whose exit-0 behaviour is why the floor stands on the whole walk rather
    than on any run at all.

    Driven on the module global rather than in a third child process: the
    threshold is a property of the predicate, and a child would pay a second
    import of this module and a second ``_build_router_cases()`` to observe one
    comparison.
    """

    def test_the_floor_fires_one_case_short_of_the_walk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One case short of the walk ends the process; the whole walk does not."""
        module = sys.modules.get(__name__)
        assert module is not None and getattr(module, "exit_when_the_walk_did_not_run", None) is exit_when_the_walk_did_not_run, (
            f"{__name__} does not resolve in sys.modules to the module holding the floor, so the count "
            "patched below is not the one the floor reads and this pin would assert nothing"
        )
        assert len(ROUTER_CASES) > 1, (
            f"the walk holds {len(ROUTER_CASES)} case(s), so one short of it is zero — the same state the "
            "children above already drive, which leaves the threshold untested here"
        )
        statuses: list[int] = []
        rendered = io.StringIO()
        monkeypatch.setattr(os, "_exit", statuses.append)
        # The floor's own stream, held rather than let through: the containerised
        # scripts suite runs with capture off, where the real thing would print an
        # unrun-walk banner in the middle of a passing run.
        monkeypatch.setattr(sys, "stderr", rendered)

        monkeypatch.setattr(module, "EXECUTED_ROUTER_CASES", len(ROUTER_CASES) - 1)
        exit_when_the_walk_did_not_run()
        assert statuses == [UNRUN_WALK_EXIT], (
            f"with {len(ROUTER_CASES) - 1} of {len(ROUTER_CASES)} cases run the floor ended the process with "
            f"{statuses}, not [{UNRUN_WALK_EXIT}]; a threshold anywhere below the whole walk forgives the "
            "narrowing that leaves one case running"
        )
        assert f"{len(ROUTER_CASES) - 1} of {len(ROUTER_CASES)}" in rendered.getvalue(), (
            f"the floor ended the process without naming the count it stands on, printing "
            f"{rendered.getvalue()!r}; the status alone says a run was short, not by how much"
        )

        monkeypatch.setattr(module, "EXECUTED_ROUTER_CASES", len(ROUTER_CASES))
        exit_when_the_walk_did_not_run()
        assert statuses == [UNRUN_WALK_EXIT], (
            f"with the whole walk run the floor ended the process with {statuses[1:]}; a threshold above the "
            "walk reds every complete run, this one included"
        )


def _counter_fixture_source() -> str:
    """
    Slice the counting fixture's own block out of this module's source.

    Read off the source rather than off the name the fixture decorator leaves
    behind, which is a wrapper object rather than the function whose body pytest
    runs. The source is located the way the two scans above locate it, by
    resolving ``GUARD_MODULE`` against ``__file__``.

    Returns:
        The fixture's ``def`` line and every line indented under it.

    Raises:
        AssertionError: If ``GUARD_MODULE`` is not this module, or the source
            does not carry exactly one module-level ``def`` of that name.
    """
    source_path = REPO_ROOT / GUARD_MODULE
    assert source_path.resolve() == Path(__file__).resolve(), (
        f"{GUARD_MODULE} is not this module, so the slice below reads the wrong source — repoint "
        "GUARD_MODULE at wherever this guard now lives"
    )
    opening = f"def {_count_executed_router_case.__name__}("
    lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.startswith(opening)]
    assert len(starts) == 1, (
        f"{GUARD_MODULE} carries {len(starts)} module-level {opening!r} lines, not exactly 1; the pin below "
        "has no single block to read, so it would report on whichever one it happened to slice"
    )
    start = starts[0]
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].strip() and not lines[index].startswith((" ", "\t"))),
        len(lines),
    )
    return "".join(lines[start:end]).rstrip("\n") + "\n"


class NodeCallspec(NamedTuple):
    """A parametrized node's ``callspec``, as the walk-case predicate reads it.

    pytest's own object carries far more than this. Standing in for it is what
    lets the predicate be driven on a chosen parametrize rather than on
    whichever one pytest happens to be executing.
    """

    #: Parametrize argument names to the values bound for one case.
    params: dict[str, object]


class TestWalkCasePredicate:
    """The counter's discriminator selects the walk, and no other parametrize.

    Its twin — the floor's threshold, which reads the count this predicate
    keeps — is pinned by ``TestExecutionFloorThreshold``. This one is observed
    by nothing else here: weakened to ``callspec is not None`` the counter
    picks up the ``arguments`` and ``site`` parametrizations too, and every
    other test in this module stays green. The parent run then reaches the
    floor on the walk plus that slack, and both narrowed children drive the
    count to zero either way, so neither observes the difference. The slack
    grows with every non-walk parametrize added.

    The predicate is a conjunction of an argument *name* and the type bound to
    it, and the two halves need a negative case each: negatives that all differ
    in the name leave the type half carrying nothing.

    The counter's one call to the predicate is pinned here as well. Everything
    below can hold while the fixture stops consulting it — testing the node's
    ``callspec`` inline instead — and nothing else in this module reads that
    call site.

    Driven on stand-in callspecs rather than in a third child process, for the
    reason ``TestExecutionFloorThreshold`` gives.
    """

    def test_only_a_walk_parameter_is_counted(self) -> None:
        """A walk case counts; an aggregate-site case, a wrongly typed binding of the walk's own argument, and an unparametrized node do not."""
        assert ROUTER_CASES, "the walk is empty, which leaves the positive case below vacuous"
        assert AGGREGATE_SITES, "no aggregate sites are pinned, which leaves the negative cases below vacuous"
        assert _is_walk_case(NodeCallspec({ROUTER_CASE_PARAM: ROUTER_CASES[0]})), (
            f"a node binding {ROUTER_CASE_PARAM!r} to a {RouterCase.__name__} does not count as a walk case, "
            "so the count stays at zero through the whole walk and the floor reds every complete run"
        )
        assert not _is_walk_case(NodeCallspec({AGGREGATE_SITE_PARAM: AGGREGATE_SITES[0]})), (
            f"a node binding {AGGREGATE_SITE_PARAM!r} counts as a walk case; the floor's count then takes in "
            "this module's other parametrizations, so it stops standing on the walk and the slack grows with "
            "every one added"
        )
        assert not _is_walk_case(NodeCallspec({ROUTER_CASE_PARAM: AGGREGATE_SITES[0]})), (
            f"a node binding {ROUTER_CASE_PARAM!r} to {type(AGGREGATE_SITES[0]).__name__} counts as a walk "
            f"case; the other negatives here differ in the argument name, so the predicate's type half would "
            f"carry nothing and a later parametrize reusing {ROUTER_CASE_PARAM!r} — a name generic enough to "
            "be reached for — would be counted into the floor's tally"
        )
        assert not _is_walk_case(None), (
            "a node pytest did not parametrize counts as a walk case; the wiring pins here are such nodes, so "
            "the floor's count would take in cases that assert nothing about routing"
        )

    def test_the_counter_reaches_the_predicate(self) -> None:
        """The counting fixture's body calls the predicate the cases above hold.

        A body testing the node's ``callspec`` directly counts every
        parametrized node in this module, and every case above stays green
        while it does: the predicate keeps each property asserted of it and is
        simply no longer consulted. That is the same gap
        ``TestOutOfCaseAssertionsAreCalled`` names for the two assertions that
        run outside a case body, one seam across.

        Read as source text and *parsed*, rather than searched. A substring
        search over that block is satisfied by the predicate's name written
        inside the fixture's own docstring or a comment, so a body that tests
        the ``callspec`` inline and mentions the predicate in prose passes one.
        What is required here is a call node.

        Known limit: what is required is that the call node exist in the block,
        not that it is reached or that its result is read. A call under an
        ``if False:``, or one whose return value is discarded, passes here
        beside an inline ``callspec`` test, and the rest of this module stays
        green through it: the predicate's own cases drive it directly, the
        threshold cases patch the count, and the floor's ``>=`` absorbs a count
        that ran wide. Named rather than closed — reaching it takes an inert
        call written deliberately past the pin, where the rewrite this pin
        exists for carries no call node at all.
        """
        body = _counter_fixture_source()
        called = {node.func.id for node in ast.walk(ast.parse(body)) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert _is_walk_case.__name__ in called, (
            f"the {_count_executed_router_case.__name__} block calls {sorted(called)}, which does not include "
            f"{_is_walk_case.__name__}:\n{body}\n"
            "the floor's count then rests on whatever that body tests instead, which nothing here reads — "
            "count through the predicate the cases above do read"
        )


#: A long option pytest does not define, written into the ambient add-options
#: variable to observe pytest reading that variable at all. Nothing is assumed
#: about the spelling: were pytest to define it, the child below would collect
#: cleanly and the case would red rather than pass.
UNRECOGNISED_PYTEST_OPTION = "--not-a-pytest-option"


class TestConstantSafetyProperties:
    """Properties a constant's own comment states about its value, asserted rather than described.

    A comment saying what makes a constant load-bearing — that a status is
    outside pytest's own, that a word is the one some other tool reads — is a
    claim about the *value*, and a value nothing holds to its claim can be
    edited with every other case in this module green. Each case here is that
    claim for one constant, and a comment making such a claim needs one.

    What belongs here is a claim about a value. A claim about the code that
    reads a constant is held where that code is exercised.

    Taken literally that criterion admits more than the cases below cover, and
    the difference is deliberate: a claim whose *consequence* is already closed
    one level out needs no case of its own — what needs one is a claim nothing
    else reds. ``GUARD_STEP_TOLERANCE_KEY`` and ``GUARD_JOB_FORBIDDEN_KEYS`` are
    both read by bare membership tests and are both renameable with every case
    in this module green; both are cleared because the key-set equalities beside
    them, ``GUARD_STEP_KEYS`` and ``GUARD_JOB_KEYS``, red on the very key such a
    rename would hide. ``FORBIDDEN_ROUTING_TARGET_KEYS`` is cleared the same way
    at the target level, where ``ROUTING_TARGET_KEYS`` closes the key space, and
    two of its members are held besides: ``dotenv`` by the case below, and
    ``ignore_error`` by the synthetic entry ``TOLERATED_COMMAND_ENTRY`` carries
    into the mapping-form case.

    ``COLLECT_TIMEOUT_SECONDS`` is a borderline member cleared on other grounds,
    recorded so a later reader does not derive it again. Its comment says the
    ceiling sits well above the per-probe budget, which nothing asserts, so it
    fits the criterion literally — but every mis-setting of it fails loudly
    rather than quietly: too small errors the walk on a raised
    ``TimeoutExpired``, and too large costs liveness rather than silence. It has
    no retirement to close.

    Known limit: nothing enforces any of this. A constant whose comment states a
    property of its value and carries no case here passes like any other, and
    the sweep behind these cases was reasoned per constant rather than driven —
    so the constants named above are what that reading surfaced, not every one
    that qualifies.
    """

    def test_the_floors_exit_status_is_none_of_pytests_own(self) -> None:
        """``UNRUN_WALK_EXIT`` is outside pytest's exit codes, the forgiven one included.

        Both routers map a no-tests-collected pytest exit to success, so a
        status set to that one retires the floor outright in the containerised
        channel: the process still ends on it, and the router reads the result
        as a run that collected nothing and reports success. Every other pin on
        the status compares it against itself — the children assert the exit
        they were told to expect, the threshold case compares a list of it — so
        none of them observes the value at all.

        The premise the case opens on is an identity rather than a membership.
        Every one of pytest's verdicts is in the set, so a membership test is
        satisfied by a ``NO_TESTS_COLLECTED_EXIT`` naming any of them — a usage
        error, say — while the prose beside it calls the value the forgiven one.
        """
        verdicts = {int(code) for code in pytest.ExitCode}
        assert NO_TESTS_COLLECTED_EXIT == int(pytest.ExitCode.NO_TESTS_COLLECTED), (
            f"pytest reads {NO_TESTS_COLLECTED_EXIT} as something other than the no-tests-collected status "
            f"both routers forgive, which is {int(pytest.ExitCode.NO_TESTS_COLLECTED)}; a membership test over "
            "pytest's own verdicts admits any one of them, so the premise this case rests on has to name the "
            "one it means"
        )
        assert UNRUN_WALK_EXIT not in verdicts, (
            f"UNRUN_WALK_EXIT is {UNRUN_WALK_EXIT}, which is pytest's own {pytest.ExitCode(UNRUN_WALK_EXIT)!r}; "
            "a run ended by the floor is then indistinguishable from one of pytest's own verdicts, and at the "
            "no-tests-collected status both routers forgive it outright"
        )

    def test_pytest_reads_options_from_the_ambient_variable(self) -> None:
        """Pytest takes command-line options from the variable ``AMBIENT_ADDOPTS_ENV_VAR`` names.

        The import-time scan, the emptiness pin and the child that drives the
        scan all read or write whatever this constant says, so all three hold
        for a variable pytest ignores — while a real ``PYTEST_ADDOPTS`` reaches
        every channel unscreened. This drives the name against pytest itself:
        the child is handed an option pytest does not define, by that variable
        and by nothing else, and has to fail on it.

        The child's command line is the collection probe's own argument vector,
        which the scan and the floor both exempt, so the variable is the only
        thing that can end it.
        """
        result = run_this_module(PROBE_ARGUMENTS, ambient=UNRECOGNISED_PYTEST_OPTION)
        rendered = result.stdout + result.stderr
        assert result.returncode not in (COLLECTED_EXIT, NO_TESTS_COLLECTED_EXIT), (
            f"a child handed {UNRECOGNISED_PYTEST_OPTION!r} through ${AMBIENT_ADDOPTS_ENV_VAR} exited "
            f"{result.returncode}, which is a collection that went through; pytest reads its extra options "
            f"from some other variable, so every channel screened through this one screens nothing\n{rendered}"
        )
        assert result.returncode != UNRUN_WALK_EXIT, (
            "the child exited on the floor rather than on the option; the probe's own argument vector is "
            f"exempt from the floor, so this pin would stop reading the variable at all\n{rendered}"
        )
        assert UNRECOGNISED_PYTEST_OPTION in rendered, (
            f"the child failed without naming {UNRECOGNISED_PYTEST_OPTION!r}, so what red it is not the "
            f"option ${AMBIENT_ADDOPTS_ENV_VAR} carried\n{rendered}"
        )

    def test_the_forbidden_dotenv_key_is_spelled_the_same_at_both_scopes(self) -> None:
        """``AMBIENT_DOTENV_KEY`` is the key the target-level forbidden list carries too.

        The file-level check is a bare absence, and a key nothing declares is
        absent whatever it is called, so the constant renamed on its own leaves
        that check passing over a real ``dotenv:``. What that rename has to red
        against is recorded at ``AMBIENT_DOTENV_KEY``, along with what neither
        spelling is held against.
        """
        assert FORBIDDEN_ROUTING_TARGET_KEYS, "the forbidden-key list is empty, which leaves this check vacuous"
        assert AMBIENT_DOTENV_KEY in FORBIDDEN_ROUTING_TARGET_KEYS, (
            f"the file-level scan forbids {AMBIENT_DOTENV_KEY!r} while the target-level list forbids "
            f"{list(FORBIDDEN_ROUTING_TARGET_KEYS)}; those screen one go-task key at two scopes, and a "
            "spelling only one of them carries is a scope screening a key nothing can declare"
        )

    def test_the_shell_task_invocation_is_the_one_the_workflow_runs(self) -> None:
        """``TASK_INVOCATION`` is the word the guard's own CI step invokes go-task by.

        Why the word needs a subject outside ``_runs_task``, and why this is the
        subject it gets, is recorded at ``TASK_INVOCATION``.
        """
        invoked = GUARD_STEP_COMMAND.split()[:1]
        assert invoked == [TASK_INVOCATION], (
            f"_runs_task searches command text for {TASK_INVOCATION!r} while the guard step runs go-task as "
            f"{invoked}; an aggregate reaching the guard through a shell command would then be invisible to "
            "the discovery that holds every such aggregate to the position and deps ratchets"
        )


def _load_yaml_mapping(relative: str) -> dict[object, object]:
    """Parse one wiring file, failing loudly rather than yielding an empty mapping to read nothing off.

    The key type is left open because a workflow's top-level ``on:`` resolves to
    the YAML 1.1 boolean rather than to a string, so the mapping genuinely
    carries keys of more than one type.
    """
    path = REPO_ROOT / relative
    assert path.is_file(), f"{relative} is missing, so the wiring it carries cannot be pinned"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{relative} did not parse as a mapping, so no wiring can be read off it"
    return document


def _workflow_jobs(relative: str) -> dict[str, dict[str, object]]:
    """Return every job one workflow declares, rejecting a mistyped one rather than skipping it."""
    workflow = _load_yaml_mapping(relative)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict) and jobs, f"{relative} declares no jobs, so nothing here can be located in it"
    mistyped = sorted(str(name) for name, job in jobs.items() if not isinstance(job, dict))
    assert not mistyped, f"{relative} jobs {mistyped} did not parse as mappings"
    return {str(name): job for name, job in jobs.items()}


def _job_steps(relative: str, name: str, job: dict[str, object]) -> list[dict[str, object]]:
    """Return one job's steps, rejecting a mistyped entry rather than skipping it."""
    steps = job.get("steps")
    assert isinstance(steps, list) and steps, f"{relative} job {name} declares no steps"
    mistyped = [index for index, step in enumerate(steps) if not isinstance(step, dict)]
    assert not mistyped, f"{relative} job {name} has non-mapping steps at {mistyped}"
    return steps


def _scanned_job_steps(relative: str, name: str, job: dict[str, object]) -> list[dict[str, object]] | None:
    """Return one job's steps, or ``None`` for a job that calls a reusable workflow.

    Only the file-wide scans use this. A job declaring ``uses:`` and no
    ``steps:`` is a reusable-workflow call and holds no steps of its own, so
    requiring steps of it would red this guard on a job added for reasons
    unrelated to routing — including in ``ci.yml``, which this module reads only
    for toolchain parity. A job declaring neither still fails, in ``_job_steps``.

    Args:
        relative: Workflow file the job was read from.
        name: Job key.
        job: The job mapping.

    Returns:
        The job's steps, or ``None`` where it calls a reusable workflow.
    """
    if REUSABLE_WORKFLOW_KEY in job and "steps" not in job:
        return None
    return _job_steps(relative, name, job)


def _guard_job() -> dict[str, object]:
    """Return the job the guard step belongs to, located by key.

    Scoping every later lookup by job is the whole safeguard. The checkout,
    toolchain and cache step names repeat across this workflow's jobs, so a
    file-wide search would either match several steps or make the ordering
    assertions turn on edits to a job this guard has nothing to do with.
    """
    jobs = _workflow_jobs(WORKFLOW_PATH)
    assert GUARD_JOB in jobs, (
        f"{WORKFLOW_PATH} declares no {GUARD_JOB!r} job — it declares {sorted(jobs)}; every lookup below is "
        "scoped by job key because step names repeat across jobs, so a renamed job unwires the pin rather "
        "than relocating it"
    )
    return jobs[GUARD_JOB]


def _guard_job_steps() -> list[dict[str, object]]:
    """Return the guard job's steps."""
    return _job_steps(WORKFLOW_PATH, GUARD_JOB, _guard_job())


def _sole_step_index(steps: list[dict[str, object]], name: str) -> int:
    """Locate exactly one step by name, so neither absence nor duplication passes silently."""
    matches = [index for index, step in enumerate(steps) if step.get("name") == name]
    assert len(matches) == 1, (
        f"{WORKFLOW_PATH} job {GUARD_JOB} carries {len(matches)} steps named {name!r}, not exactly 1; an "
        "absent step leaves the ordering assertion nothing to anchor on, and a duplicated one makes which "
        "step it anchors on arbitrary"
    )
    return matches[0]


def _guard_step_index(steps: list[dict[str, object]]) -> int:
    """Locate the guard step by name **and** by the whole command it runs.

    Both predicates are required. Matching the name alone would let the command
    be retargeted at some other task while the step keeps its label; matching
    the command alone would let the step be renamed into something no reader
    recognises as this guard.

    The whole ``run:`` scalar is compared, stripped, rather than searched. A
    search matches any single line of a multi-line block, so a ``run: |``
    opening with ``if [ … ]; then exit 0; fi`` above the command satisfies it
    while retiring the guard — the same diff-scoped condition an ``if:`` would
    carry, relocated one key across. Equality also rules out a command that
    merely starts with this one, such as a narrower ``task test:routing:…``.
    """
    matches = [
        index
        for index, step in enumerate(steps)
        if step.get("name") == GUARD_STEP_NAME and str(step.get("run", "")).strip() == GUARD_STEP_COMMAND
    ]
    assert len(matches) == 1, (
        f"{WORKFLOW_PATH} job {GUARD_JOB} carries {len(matches)} steps named {GUARD_STEP_NAME!r} whose whole "
        f"`run:` is exactly {GUARD_STEP_COMMAND!r}, not exactly 1; the guard is unwired until exactly one "
        "step satisfies both, and a `run:` carrying anything besides that command satisfies neither"
    )
    return matches[0]


def _uv_cache_settings(steps: list[dict[str, object]]) -> list[tuple[int, dict[str, object]]]:
    """Return every step restoring the uv package cache, with its index and ``with:`` mapping.

    Selected by cached path rather than by being a job's only cache step: an
    unrelated cache added later is not this guard's business, and a count over
    every ``actions/cache@`` step would red on one while reporting that the uv
    cache was missing.
    """
    matches: list[tuple[int, dict[str, object]]] = []
    for index, step in enumerate(steps):
        if not str(step.get("uses", "")).startswith(CACHE_ACTION_PREFIX):
            continue
        settings = step.get("with")
        if isinstance(settings, dict) and settings.get("path") == UV_CACHE_PATH:
            matches.append((index, settings))
    return matches


def _uv_cache_step(steps: list[dict[str, object]]) -> tuple[int, dict[str, object]]:
    """Locate the guard job's single uv cache step, for the ordering assertion."""
    matches = _uv_cache_settings(steps)
    assert len(matches) == 1, (
        f"{WORKFLOW_PATH} job {GUARD_JOB} carries {len(matches)} {CACHE_ACTION_PREFIX} steps caching "
        f"{UV_CACHE_PATH!r}, not exactly 1; without one the guard's venv is rebuilt from an empty package "
        "cache on every run, and with two which one serves the build is arbitrary"
    )
    return matches[0]


def _uv_cache_jobs() -> list[tuple[str, str, dict[str, object]]]:
    """Return the uv cache settings of every job in every scanned workflow that restores one.

    Neither scoped to the guard's job nor to its file: the same eight-line cache
    step, keyed on the same three files, is duplicated across jobs, and a key
    check scoped to one of them leaves the others serving a cache that a
    dependency change invalidated. The files are globbed for the reason the
    toolchain parity check globs them — the property is that every copy of the
    step is keyed on every requirements file, and which workflow a copy sits in
    is not part of it.

    Returns:
        One entry per restoring job, as workflow path, job key and ``with:``
        mapping.
    """
    found: list[tuple[str, str, dict[str, object]]] = []
    for relative in WORKFLOW_SCAN_PATHS:
        for name, job in _workflow_jobs(relative).items():
            steps = _scanned_job_steps(relative, name, job)
            if steps is None:
                continue
            for _, settings in _uv_cache_settings(steps):
                found.append((relative, name, settings))
    return found


def _named_steps(name: str) -> list[tuple[str, str, dict[str, object]]]:
    """Return every step carrying one name across the scanned workflows, with its file and job."""
    found: list[tuple[str, str, dict[str, object]]] = []
    for relative in WORKFLOW_SCAN_PATHS:
        for job_name, job in _workflow_jobs(relative).items():
            steps = _scanned_job_steps(relative, job_name, job)
            if steps is None:
                continue
            for step in steps:
                if step.get("name") == name:
                    found.append((relative, job_name, step))
    return found


def _declared_tasks(relative: str = TASKFILE_PATH) -> dict[str, object]:
    """Return every target declared in one taskfile."""
    taskfile = _load_yaml_mapping(relative)
    tasks = taskfile.get("tasks")
    assert isinstance(tasks, dict) and tasks, f"{relative} declares no tasks"
    return tasks


def _routing_target() -> dict[str, object]:
    """Return the target the CI step invokes."""
    tasks = _declared_tasks()
    assert ROUTING_TASK_NAME in tasks, (
        f"{TASKFILE_PATH} declares no {ROUTING_TASK_NAME!r} target, so the CI step pinned above invokes nothing that exists"
    )
    target = tasks[ROUTING_TASK_NAME]
    assert isinstance(target, dict), f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} did not parse as a mapping"
    return target


def _command_strings(target: object) -> tuple[str, ...]:
    """Return a target's literal commands, dropping every mapping entry.

    Kept as the negative control the mapping-form test compares
    ``_command_texts`` against; no scan reads it, because dropping the mapping
    entries is exactly what makes a scan fail open.
    """
    if not isinstance(target, dict):
        return ()
    cmds = target.get("cmds")
    if not isinstance(cmds, list):
        return ()
    return tuple(entry for entry in cmds if isinstance(entry, str))


def _command_entries(target: object) -> tuple[object, ...]:
    """Return a target's ``cmds`` entries as written, mapping forms included.

    ``_command_strings`` drops every mapping entry, so a key carried by one —
    ``ignore_error`` on a ``cmd:`` mapping — is invisible to any scan that
    reads only the strings.
    """
    if not isinstance(target, dict):
        return ()
    cmds = target.get("cmds")
    if not isinstance(cmds, list):
        return ()
    return tuple(cmds)


def _command_texts(target: object) -> tuple[str, ...]:
    """Return every command text a target declares, mapping entries flattened in.

    The seam every text-reading scan in this module goes through. Substituting
    ``_command_strings`` here re-opens all of them at once, which is what
    ``test_per_command_scan_reads_the_mapping_form`` drives out.
    """
    texts: list[str] = []
    for entry in _command_entries(target):
        if isinstance(entry, str):
            texts.append(entry)
            continue
        if not isinstance(entry, dict):
            continue
        for key in COMMAND_TEXT_KEYS:
            value = entry.get(key)
            if isinstance(value, str):
                texts.append(value)
    return tuple(texts)


def _joined_commands(target: object) -> str:
    """Return a target's command texts as one block, for the expression scans."""
    return "\n".join(_command_texts(target))


def _shorthand_command_entries(target: object) -> tuple[object, ...]:
    """Return a target's command entries under every shape go-task admits for one.

    ``_command_entries`` reads the mapping form, where the commands live under
    ``cmds:``. go-task also takes a target written as a bare string or as a bare
    list, and for either of those ``_command_entries`` returns nothing at all —
    so a discovery built on it alone reads an aggregate written in shorthand as
    running nothing.

    Args:
        target: A target as the taskfile declares it.

    Returns:
        The target's command entries.
    """
    if isinstance(target, str):
        return (target,)
    if isinstance(target, list):
        return tuple(target)
    return _command_entries(target)


def _dependency_entries(target: object) -> tuple[object, ...]:
    """Return a target's ``deps:`` entries as written, mapping forms included.

    Args:
        target: A target as the taskfile declares it.

    Returns:
        The target's dependency entries, empty where it declares none.
    """
    if not isinstance(target, dict):
        return ()
    deps = target.get("deps")
    if not isinstance(deps, list):
        return ()
    return tuple(deps)


def _runs_task(target: object, entry: str) -> bool:
    """
    Decide whether one target runs a named task, under every spelling discovered.

    A ``cmds:`` mapping carrying ``task:`` is one shape among several that reach
    the same target: a ``deps:`` entry runs it *before* ``cmds[0]``, a ``deps:``
    mapping is the same one key across, and a plain shell command invoking
    ``task`` runs it without any structure to read. They are matched here so the
    discovery is over what a taskfile can express rather than over the one form
    the pinned sites happen to use — which is also why each shape is driven on a
    literal, at ``test_the_aggregate_discovery_reads_every_shape_it_claims``.

    Args:
        target: A target as the taskfile declares it.
        entry: Task name to look for, with or without a leading ``:``.

    Returns:
        Whether the target runs that task.
    """
    wanted = entry.lstrip(":")
    invocation = re.compile(rf"(?<!\S){re.escape(TASK_INVOCATION)}\s+:?{re.escape(wanted)}(?!\S)")
    for dependency in _dependency_entries(target):
        if isinstance(dependency, str) and dependency.lstrip(":") == wanted:
            return True
        named = dependency.get("task") if isinstance(dependency, dict) else None
        if isinstance(named, str) and named.lstrip(":") == wanted:
            return True
    for command in _shorthand_command_entries(target):
        if isinstance(command, str):
            if invocation.search(command):
                return True
            continue
        if not isinstance(command, dict):
            continue
        named = command.get("task")
        if isinstance(named, str) and named.lstrip(":") == wanted:
            return True
        for key in COMMAND_TEXT_KEYS:
            text = command.get(key)
            if isinstance(text, str) and invocation.search(text):
                return True
    return False


def _junit_destinations(target: object) -> frozenset[str]:
    """Read the junit paths a target writes to."""
    return frozenset(str(match) for command in _command_texts(target) for match in JUNIT_DESTINATION.findall(command))


def _setup_requirements_files() -> tuple[str, ...]:
    """Read the requirements files the venv-building target installs from."""
    tasks = _declared_tasks()
    assert SETUP_TASK_NAME in tasks, (
        f"{TASKFILE_PATH} declares no {SETUP_TASK_NAME!r} target, so the files the guard's venv is built "
        "from cannot be read and REQUIREMENTS_FILES has nothing to be pinned against"
    )
    files = tuple(str(match) for command in _command_texts(tasks[SETUP_TASK_NAME]) for match in REQUIREMENTS_FLAG.findall(command))
    assert files, (
        f"{TASKFILE_PATH} target {SETUP_TASK_NAME} names no {REQUIREMENTS_FLAG.pattern!r} file; either the "
        "install line changed shape, or the venv is no longer built from requirements files at all"
    )
    return files


class TestGuardWiring:
    """The CI step and the task target that make this guard unconditional.

    Everything above measures routing coverage; nothing above notices when the
    thing that runs it is made conditional, forgiven, skipped, sequenced behind
    another job, filtered out of its trigger, or pointed somewhere else. These
    pins are what notice.

    Their limit is *when* they run, not what they assert. This module runs in
    the guard's own job, on every pull request, and in the containerised scripts
    suite, on every pull request changing a non-test module under
    ``tests/helpers/`` or this module itself. A wiring change lands in
    ``.github/``, ``taskfiles/`` or the root ``Taskfile.yml``, none of which sits
    under a router prefix, so on the pull request making that change only the
    first channel is live — and that channel is the wiring being edited.

    A retirement that leaves this module running, and its failure counting,
    therefore fails in the run that introduces it. One that removes either
    property does not: a deleted job or step, a ``continue-on-error`` around the
    red these assertions produce, a target repointed at another module. Those
    are left to review. Widening the router filters so that a wiring diff routes
    here is out of scope.

    Four vectors are known, named and left open. The name ``task test:routing``
    resolves through a binding nothing here pins — a root target keyed on it, or
    a repointed ``includes:`` — so the pins below can be read off a target the
    CI step no longer reaches. ``deps: [setup]`` is pinned by name, while
    ``setup`` is what builds the ``.venv/bin/pytest`` this guard runs under and
    its commands are unpinned beyond the ``-r`` requirements files
    ``_setup_requirements_files`` reads off them for the cache-key check —
    nothing pins that the target actually produces a working
    ``.venv/bin/pytest``. The ``run:`` bodies of the two install steps that put
    ``task`` and ``uv`` on the runner are unpinned too. ``tests/conftest.py``
    configures every session this module runs in and no pin here reads it; the
    execution floor observes the effect of one hook it can carry, not the file.
    Every one of them takes an edit to the guard's own wiring, and every file
    such an edit lands in routes to no test in either router, so the only job
    that would notice the diff is the one being retired. The control that does
    cover them is human review of that diff plus branch protection on the branch
    it lands in, and nothing here is claimed to close them.
    A measured set, not a closed one: these are the vectors review has surfaced,
    and nothing here enumerates the ones it has not.

    The ``route`` fixture's parity assertion is not among them. It covers the
    two workspace builders' stub sets rather than the rest of their layout, but
    that fixture is not on this guard's execution path — the walk routes through
    ``session_route``, which the ``route_variant`` factory builds on
    ``build_router_workspace`` — and the layout divergences that would change
    what the routers announce red
    ``test_registry_is_exactly_the_measured_hole_set`` in one direction or the
    other: a lost ``tests/`` symlink makes every ``[ -f ]`` probe miss, so pairs
    become holes that are not exempt, while a gained file makes a registered
    hole stop being one. It is an incomplete parity assertion, not a retirement
    vector.

    Convention for the cases below: record a pin's rationale once, beside the
    constant the case reads, and point at it from the docstring rather than
    restating it. A rationale kept in two places drifts, and the constant is
    the copy the failure message is written next to.
    Known limit: nothing enforces it. A case restating a rationale its constant
    already carries, and a case reading a constant that carries none, both pass
    like any other.
    """

    def test_workflow_runs_the_guard_unconditionally(self) -> None:
        """The guard step carries no ``if:``.

        A condition is how this guard gets quietly retired: any diff-scoped
        predicate skips it on exactly the pull requests that add a source
        reaching no test, which is the case it exists for.
        """
        steps = _guard_job_steps()
        guard = steps[_guard_step_index(steps)]
        assert "if" not in guard, (
            f"{WORKFLOW_PATH} step {GUARD_STEP_NAME!r} carries `if: {guard['if']}`; the guard must run on "
            "every pull request, including the ones touching no router-prefixed path"
        )

    def test_workflow_does_not_tolerate_a_red_guard(self) -> None:
        """The guard step carries no ``continue-on-error``.

        The cheaper retirement of the two the step allows: unlike an ``if:``, it
        leaves the step running and reporting its failure, while the job around
        it still concludes success — so the guard reds in a log nobody is
        prompted to read.
        """
        steps = _guard_job_steps()
        guard = steps[_guard_step_index(steps)]
        assert GUARD_STEP_TOLERANCE_KEY not in guard, (
            f"{WORKFLOW_PATH} step {GUARD_STEP_NAME!r} carries "
            f"`{GUARD_STEP_TOLERANCE_KEY}: {guard[GUARD_STEP_TOLERANCE_KEY]}`; a routing hole would then be "
            "reported by a job that still passes"
        )

    def test_workflow_guard_step_declares_only_the_keys_it_needs(self) -> None:
        """The guard step declares a name and a command, and nothing else.

        The two pins above forbid the two step keys with a named retirement
        each. Every other key in GitHub Actions' step schema is unforbidden, and
        one of them — ``env:`` — is a measured retirement; see
        ``GUARD_STEP_KEYS``. Asserting the key set instead closes that key together with the ones
        nobody has enumerated, so an addition here has to be argued for rather
        than merged.
        """
        assert GUARD_STEP_KEYS, "the pinned step-key set is empty, which would admit any step at all"
        steps = _guard_job_steps()
        guard = steps[_guard_step_index(steps)]
        declared = frozenset(str(key) for key in guard)
        assert declared == GUARD_STEP_KEYS, (
            f"{WORKFLOW_PATH} step {GUARD_STEP_NAME!r} declares {sorted(declared)}, not "
            f"{sorted(GUARD_STEP_KEYS)}; the guard's step runs one command unconditionally, and a key added "
            "to it — an `env:` above all, which reaches pytest through go-task — has to be argued for here too"
        )

    def test_workflow_guard_job_steps_declare_only_the_keys_they_need(self) -> None:
        """Every step of the guard's job declares exactly the keys pinned for it.

        The pin above closes the guard step's key space and leaves the other
        five open. Which key on which step matters, and what closing all six by
        equality buys, is recorded at ``GUARD_JOB_STEP_KEYS``.
        """
        assert GUARD_JOB_STEP_KEYS, "no step key sets are pinned, which leaves this check vacuous"
        found: list[tuple[str | None, frozenset[str]]] = []
        for step in _guard_job_steps():
            name = step.get("name")
            found.append((name if isinstance(name, str) else None, frozenset(str(key) for key in step)))
        declared = sorted((name for name, _ in found), key=str)
        assert declared == sorted(GUARD_JOB_STEP_KEYS, key=str), (
            f"{WORKFLOW_PATH} job {GUARD_JOB} holds steps {declared}, while key sets are pinned for "
            f"{sorted(GUARD_JOB_STEP_KEYS, key=str)}; a step with no pinned set declares whatever it likes"
        )
        wrong = sorted(
            f"{name!r} declares {sorted(keys)}, not {sorted(GUARD_JOB_STEP_KEYS[name])}"
            for name, keys in found
            if keys != GUARD_JOB_STEP_KEYS[name]
        )
        assert not wrong, (
            f"{WORKFLOW_PATH} job {GUARD_JOB}: " + "; ".join(wrong) + " — every step in the guard's job runs "
            "ahead of or alongside the guard, so a key added to any of them has to be argued for here"
        )

    def test_workflow_job_declares_only_the_keys_the_guard_needs(self) -> None:
        """The job holding the guard declares a runner, a timeout and its steps, and nothing else.

        The step-level pins above are worth nothing while the job around them
        can be skipped or forgiven wholesale — one key on the job retires every
        step it holds, this guard included, and costs less to write than either
        step-level equivalent.

        Asserted as the key set rather than as the absence of three named keys,
        which are checked afterwards for the message. What the set closes that
        the list does not is recorded at ``GUARD_JOB_KEYS``; what each of the
        three retires, at ``GUARD_JOB_FORBIDDEN_KEYS``.

        The runner label is asserted alongside the key set; why that value
        needs a pin of its own is recorded at ``GUARD_JOB_RUNNER``.
        """
        assert GUARD_JOB_KEYS, "the pinned job-key set is empty, which would admit any job at all"
        assert GUARD_JOB_FORBIDDEN_KEYS, "the forbidden job-key list is empty, which leaves the check below vacuous"
        job = _guard_job()
        declared = frozenset(str(key) for key in job)
        assert declared == GUARD_JOB_KEYS, (
            f"{WORKFLOW_PATH} job {GUARD_JOB} declares {sorted(declared)}, not {sorted(GUARD_JOB_KEYS)}; the "
            "guard holds a job of its own precisely so that its wiring is this short — a key added here can "
            "skip it, forgive it, sequence it, run it zero times or hand it an environment, and has to be "
            "argued for rather than merged"
        )
        gates = [key for key in GUARD_JOB_FORBIDDEN_KEYS if key in job]
        assert not gates, (
            f"{WORKFLOW_PATH} job {GUARD_JOB} carries {gates}; the guard runs on every pull request only "
            "while the job carrying it starts unconditionally, and counts only while that job's conclusion "
            "follows from it"
        )
        assert job.get(GUARD_JOB_RUNNER_KEY) == GUARD_JOB_RUNNER, (
            f"{WORKFLOW_PATH} job {GUARD_JOB} declares {GUARD_JOB_RUNNER_KEY}={job.get(GUARD_JOB_RUNNER_KEY)!r}, "
            f"not {GUARD_JOB_RUNNER!r}; the key set above admits the key and leaves its value free, and no "
            "other assertion here reads it"
        )

    def test_workflow_declares_only_the_keys_the_guard_needs(self) -> None:
        """The workflow declares a name, a trigger, permissions and jobs, and nothing else.

        The job- and step-key pins are worth nothing while the file around them
        can hand every job a shell, an environment or a concurrency group. Why
        this level is closed by equality, and which of its members carry a named
        retirement, is recorded at ``WORKFLOW_KEYS``; the trigger key is
        compared as the boolean ``WORKFLOW_TRIGGER_KEY`` rather than as the
        string ``on``, for the reason recorded beside that constant.
        """
        assert WORKFLOW_KEYS, "the pinned workflow-key set is empty, which would admit any workflow at all"
        workflow = _load_yaml_mapping(WORKFLOW_PATH)
        declared = frozenset(workflow)
        assert declared == WORKFLOW_KEYS, (
            f"{WORKFLOW_PATH} declares {sorted(declared, key=str)}, not {sorted(WORKFLOW_KEYS, key=str)}; a "
            "top-level key reaches every step of every job in the file, the guard's included, so an addition "
            "here has to be argued for rather than merged"
        )

    def test_workflow_declares_no_ambient_environment(self) -> None:
        """The workflow hands the guard's job no environment from above it.

        A top-level ``env:`` reaches the guard's step whatever the job and the
        step themselves declare — two levels above the step-key pin and one
        above the job-key pin, both of which would stay green. The scope GitHub
        Actions gives that key is recorded at ``AMBIENT_ENV_KEY``.

        What it buys is measured; see ``GUARD_STEP_KEYS``.
        """
        workflow = _load_yaml_mapping(WORKFLOW_PATH)
        assert AMBIENT_ENV_KEY not in workflow, (
            f"{WORKFLOW_PATH} declares a top-level `{AMBIENT_ENV_KEY}: {workflow[AMBIENT_ENV_KEY]}`; that "
            "reaches every step of every job in the file, the guard's included, and a PYTEST_ADDOPTS in it "
            "retires the guard while the job- and step-level pins above stay green"
        )

    def test_workflow_guard_job_runs_only_the_actions_it_needs(self) -> None:
        """Every step of the guard's job that runs an action runs the pinned one.

        Which axis this closes, and why the ``run:`` scan cannot see it, is
        recorded at ``GUARD_JOB_STEP_ACTIONS``.

        The checkout is the reason it is a whitelist rather than a scan. It is
        the job's unnamed first step, and no other assertion in this class reads
        it, so without this pin its ``uses:`` is the one slot in the job nothing
        constrains — and whatever is named there runs ahead of every other step
        in a job the guard depends on.
        """
        assert GUARD_JOB_STEP_ACTIONS, "no step actions are pinned, which leaves this check vacuous"
        found: list[tuple[str | None, str]] = []
        for step in _guard_job_steps():
            if "uses" not in step:
                continue
            name = step.get("name")
            found.append((name if isinstance(name, str) else None, str(step["uses"])))
        declared = sorted((name for name, _ in found), key=str)
        assert declared == sorted(GUARD_JOB_STEP_ACTIONS, key=str), (
            f"{WORKFLOW_PATH} job {GUARD_JOB} runs actions at steps {declared}, while "
            f"{sorted(GUARD_JOB_STEP_ACTIONS, key=str)} are pinned; a step that starts running one is "
            "invisible to the `run:` scan below, and one that stops is no longer pinned to anything"
        )
        wrong = sorted(
            f"{name!r} uses {uses!r}, not {GUARD_JOB_STEP_ACTIONS[name]!r}"
            for name, uses in found
            if not uses.startswith(GUARD_JOB_STEP_ACTIONS[name])
        )
        assert not wrong, (
            f"{WORKFLOW_PATH} job {GUARD_JOB}: " + "; ".join(wrong) + " — the guard's job holds only the "
            "steps it needs, and each of them is pinned to the action it needs rather than to running one"
        )

    def test_workflow_bounds_the_guard_job(self) -> None:
        """The job declares its own ``timeout-minutes``, under a ceiling well below the default.

        What the ceiling stands between, and why it is asserted as a bound
        rather than as an exact value, is recorded at ``GUARD_JOB_TIMEOUT_KEY``.
        """
        job = _guard_job()
        timeout = job.get(GUARD_JOB_TIMEOUT_KEY)
        assert isinstance(timeout, int) and not isinstance(timeout, bool), (
            f"{WORKFLOW_PATH} job {GUARD_JOB} declares {GUARD_JOB_TIMEOUT_KEY}={timeout!r}, not a whole number "
            f"of minutes; without one the job runs to GitHub's 360-minute default before anything ends it"
        )
        assert 0 < timeout <= GUARD_JOB_TIMEOUT_CEILING, (
            f"{WORKFLOW_PATH} job {GUARD_JOB} allows {timeout} minutes, outside 1..{GUARD_JOB_TIMEOUT_CEILING}; "
            "a ceiling this far above the guard's own per-unit ceilings stops being one"
        )

    def test_workflow_runs_the_guard_after_the_uv_install(self) -> None:
        """The guard step sits after the uv install.

        Mechanical: the uv install appends to ``$GITHUB_PATH``, which affects
        only subsequent steps, so a guard placed earlier finds no ``uv`` for its
        ``deps: [setup]`` venv build.
        """
        steps = _guard_job_steps()
        guard_index = _guard_step_index(steps)
        uv_index = _sole_step_index(steps, UV_INSTALL_STEP_NAME)
        assert uv_index < guard_index, (
            f"{WORKFLOW_PATH} job {GUARD_JOB} runs {GUARD_STEP_NAME!r} at step {guard_index}, before "
            f"{UV_INSTALL_STEP_NAME!r} at step {uv_index}; uv is on $PATH only for steps after its install"
        )

    def test_workflow_runs_no_test_beside_the_guard(self) -> None:
        """The guard's job holds exactly its own steps, and no other one starts a test run.

        What a step running tests ahead of the guard does to it, and why the
        scan below covers the property rather than a forbidden step name, is
        recorded at ``TEST_INVOCATION_PATTERNS``.

        The property is asserted twice, in the two directions a step can arrive
        by. The ordered step-name list is a whitelist over the job, so *any*
        added step fails whatever it runs. The command scan covers the other
        direction, where a test invocation is appended to a step already on the
        list — which the name list alone would not see.
        """
        assert GUARD_JOB_STEP_NAMES, "the pinned step-name list is empty, which leaves this check vacuous"
        assert TEST_INVOCATION_PATTERNS, "the test-invocation list is empty, which leaves the scan below vacuous"
        steps = _guard_job_steps()
        declared = tuple(step.get("name") for step in steps)
        assert declared == GUARD_JOB_STEP_NAMES, (
            f"{WORKFLOW_PATH} job {GUARD_JOB} runs steps {list(declared)}, not {list(GUARD_JOB_STEP_NAMES)}; the "
            "guard holds a job of its own so that nothing else in it can fail ahead of the guard and end the "
            "run before it reports — add a step here only by arguing for it in GUARD_JOB_STEP_NAMES too"
        )
        guard_index = _guard_step_index(steps)
        running_tests = sorted(
            f"{index}:{step.get('name')}"
            for index, step in enumerate(steps)
            if index != guard_index
            for pattern in TEST_INVOCATION_PATTERNS
            if pattern.search(str(step.get("run", "")))
        )
        assert not running_tests, (
            f"{WORKFLOW_PATH} job {GUARD_JOB} starts a test run at step(s) {running_tests} besides "
            f"{GUARD_STEP_NAME!r}; a step that runs tests can fail, and a failing step ahead of the guard "
            "ends the job before it reports"
        )

    def test_workflow_triggers_the_guard_on_every_pull_request(self) -> None:
        """The workflow is triggered by pull requests, and by none of the filters ``FORBIDDEN_TRIGGER_FILTER_KEYS`` names.

        Which trigger-level filters skip a run the guard has to report on, and
        how each of them does it, is recorded at
        ``FORBIDDEN_TRIGGER_FILTER_KEYS``. The step-level and job-level pins
        above sit underneath all of them and would still pass.

        That list is read by a membership test, which closes only the keys it
        spells; the key space of the two events carrying the guard's claim is
        closed beside it, against ``GUARD_TRIGGER_KEYS``. Why that closure is
        written as "no key beside the pinned one" rather than as an equality,
        and why it is held to those two events, is recorded there.

        ``branches`` cannot be forbidden the way those four are — it is
        declared, and it is what scopes the run to the branch the guard reports
        into — so it is closed by its value instead: wherever one of the two
        events carrying the guard's claim declares it, the list has to be
        exactly the pinned one. Why equality rather than membership is recorded
        at ``GUARD_TRIGGER_BRANCHES``.

        Why an absent ``branches`` is not asserted into existence is recorded
        at ``GUARD_TRIGGER_BASE_BRANCH``; why both events are, at
        ``BASE_BRANCH_SCOPED_EVENTS``.

        The ``pull_request`` trigger is asserted first because without it the
        filter check has no subject: a workflow that no longer runs on pull
        requests carries no path filter either, and would pass a check written
        only in the negative.
        """
        assert FORBIDDEN_TRIGGER_FILTER_KEYS, "the forbidden-filter list is empty, which leaves this check vacuous"
        assert BASE_BRANCH_SCOPED_EVENTS, "no events are base-branch scoped, which leaves the value check below vacuous"
        workflow = _load_yaml_mapping(WORKFLOW_PATH)
        triggers = workflow.get(WORKFLOW_TRIGGER_KEY)
        assert isinstance(triggers, dict) and triggers, (
            f"{WORKFLOW_PATH} declares no trigger mapping under the `on:` key, so nothing here says when the guard runs"
        )
        assert GUARD_TRIGGER_EVENT in triggers, (
            f"{WORKFLOW_PATH} triggers on {sorted(str(event) for event in triggers)}, which omits "
            f"{GUARD_TRIGGER_EVENT!r}; the guard's whole claim is that it runs on every pull request"
        )
        undeclared = [event for event in BASE_BRANCH_SCOPED_EVENTS if event not in triggers]
        assert not undeclared, (
            f"{WORKFLOW_PATH} triggers on {sorted(str(event) for event in triggers)}, which omits "
            f"{undeclared}; the scoping check below skips an event it cannot find, so deleting one retires "
            "the run it carries with nothing here to notice"
        )
        filtered = sorted(
            f"{event}.{key}"
            for event, settings in triggers.items()
            if isinstance(settings, dict)
            for key in FORBIDDEN_TRIGGER_FILTER_KEYS
            if key in settings
        )
        assert not filtered, (
            f"{WORKFLOW_PATH} filters its triggers by {filtered}; a path filter skips the whole run for a "
            "diff it does not list, so the guard would stop reporting on the changes it exists to report on"
        )
        unpinned: list[str] = []
        misscoped: list[str] = []
        for event in BASE_BRANCH_SCOPED_EVENTS:
            settings = triggers.get(event)
            if not isinstance(settings, dict):
                continue
            unpinned.extend(f"{event}.{key}" for key in sorted(str(name) for name in settings) if key not in GUARD_TRIGGER_KEYS)
            if GUARD_TRIGGER_BRANCH_KEY not in settings:
                continue
            declared = settings[GUARD_TRIGGER_BRANCH_KEY]
            branches = [declared] if isinstance(declared, str) else declared
            if not isinstance(branches, list) or tuple(branches) != GUARD_TRIGGER_BRANCHES:
                misscoped.append(f"{event}.{GUARD_TRIGGER_BRANCH_KEY} is {declared!r}")
        assert not unpinned, (
            f"{WORKFLOW_PATH} declares {unpinned}, which is outside {sorted(GUARD_TRIGGER_KEYS)}; the "
            "forbidden list above reaches only the keys it names, so a filter spelled any other way — or "
            "the pinned branch key renamed out from under it — narrows the trigger with every membership "
            "check here still passing"
        )
        assert not misscoped, (
            f"{WORKFLOW_PATH}: " + "; ".join(misscoped) + f", not {list(GUARD_TRIGGER_BRANCHES)}; a branch "
            "filter that omits the branch the guard reports into — or that names it and then excludes it — "
            "stops the whole workflow on every pull request into that branch, and every step- and job-level "
            "pin above stays green while it does"
        )

    def test_workflow_uploads_the_junit_the_target_writes(self) -> None:
        """The upload path is read off the taskfile, and the two keys it rests on are pinned.

        The upload carries ``if-no-files-found: ignore``, so a path that drifts
        from the one the target writes uploads nothing and still reports
        success. Neither end fails on its own, and the junit is what the guard
        leaves behind to read when it reds.

        Both of those keys are asserted rather than described; what each of
        them buys is recorded at ``JUNIT_UPLOAD_CONDITION``.
        """
        destinations = _junit_destinations(_routing_target())
        assert len(destinations) == 1, (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} writes junit to {sorted(destinations)}, not to "
            "exactly one path; the upload below can only be tied to a single destination"
        )
        expected = next(iter(destinations))
        steps = _guard_job_steps()
        upload = steps[_sole_step_index(steps, JUNIT_UPLOAD_STEP_NAME)]
        uses = str(upload.get("uses", ""))
        assert uses.startswith(UPLOAD_ACTION_PREFIX), (
            f"{WORKFLOW_PATH} step {JUNIT_UPLOAD_STEP_NAME!r} uses {uses!r}, not a {UPLOAD_ACTION_PREFIX} "
            "action; the step named as the junit upload has to be one"
        )
        settings = upload.get("with")
        assert isinstance(settings, dict), (
            f"{WORKFLOW_PATH} step {JUNIT_UPLOAD_STEP_NAME!r} declares no `with:` mapping, so it names no path to upload"
        )
        assert settings.get("path") == expected, (
            f"{WORKFLOW_PATH} step {JUNIT_UPLOAD_STEP_NAME!r} uploads {settings.get('path')!r} while "
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} writes {expected!r}; the step ignores a missing "
            "file, so the drift uploads nothing and reports success"
        )
        assert str(upload.get("if", "")).strip() == JUNIT_UPLOAD_CONDITION, (
            f"{WORKFLOW_PATH} step {JUNIT_UPLOAD_STEP_NAME!r} carries `if: {upload.get('if')}`, not "
            f"{JUNIT_UPLOAD_CONDITION!r}; a step following a failed one is skipped, so without it the upload "
            "runs on exactly the runs whose artifact is worth having and not on the one that reds"
        )
        assert settings.get(JUNIT_MISSING_FILE_KEY) == JUNIT_MISSING_FILE_POLICY, (
            f"{WORKFLOW_PATH} step {JUNIT_UPLOAD_STEP_NAME!r} sets "
            f"{JUNIT_MISSING_FILE_KEY}={settings.get(JUNIT_MISSING_FILE_KEY)!r}, not "
            f"{JUNIT_MISSING_FILE_POLICY!r}; the file is legitimately absent when the venv build fails ahead "
            "of pytest, and the drift check above is written on the premise that this is tolerated"
        )

    def test_workflow_caches_uv_packages_before_the_guard(self) -> None:
        """Every uv cache in the workflow is keyed on the install line, and the guard's precedes it.

        The step is selected by the path it caches, which is the uv package
        cache and not ``.venv``: a virtualenv records absolute interpreter
        paths and does not survive relocation, so restoring one would be worse
        than rebuilding.

        The key check runs over every job restoring that cache in every scanned
        workflow, not only the guard's job in this one; why it reads the
        globbed set rather than the guard's file alone is recorded at
        ``WORKFLOW_SCAN_PATHS``. The ordering assertion stays scoped to the
        guard's job, because that is the only job whose step order this guard
        has anything to say about.
        """
        installed = _setup_requirements_files()
        assert frozenset(REQUIREMENTS_FILES) == frozenset(installed), (
            f"{TASKFILE_PATH} target {SETUP_TASK_NAME} installs from {sorted(set(installed))} while the key "
            f"check below is written against {sorted(REQUIREMENTS_FILES)}; the two have drifted, and the "
            "difference is a dependency change the cache key would not notice"
        )
        cached = _uv_cache_jobs()
        assert cached, (
            f"{list(WORKFLOW_SCAN_PATHS)} declare no {CACHE_ACTION_PREFIX} step caching {UV_CACHE_PATH!r} in "
            "any job, which leaves this scan vacuous and every venv build restoring from an empty package cache"
        )
        # Matched as the quoted `hashFiles` argument, not as a bare substring: `requirements.txt`
        # is a suffix of `tests/requirements.txt`, so a substring test would read a key naming only
        # the two nested files as covering the root one too.
        unkeyed: list[str] = []
        for relative, job, settings in cached:
            key = str(settings.get("key", ""))
            missing = [required for required in REQUIREMENTS_FILES if f"'{required}'" not in key]
            if missing:
                unkeyed.append(f"{relative} job {job} keys the uv cache on {key!r}, which ignores {missing}")
        assert not unkeyed, (
            "\n".join(sorted(unkeyed)) + "\na change to an ignored requirements file would hit a cache the "
            "change invalidated, in whichever job ignores it"
        )
        steps = _guard_job_steps()
        guard_index = _guard_step_index(steps)
        cache_index, _ = _uv_cache_step(steps)
        assert cache_index < guard_index, (
            f"{WORKFLOW_PATH} restores the uv cache at step {cache_index}, after {GUARD_STEP_NAME!r} at step "
            f"{guard_index}; a cache restored afterwards saves the guard's venv build nothing"
        )

    def test_workflow_toolchain_pins_agree_across_every_copy(self) -> None:
        """Every copy of a toolchain install step pins the same version and checksum.

        Both install steps are duplicated across jobs, and ``Install Task``
        across files as well. A copy left on an older version, or on a checksum
        that stops matching the artifact it names, fails the job it sits in
        rather than the one that drifted away from it.

        Why the check stands on the values rather than on the sync comments
        some copies carry is recorded at ``WORKFLOW_SCAN_PATHS``.

        The files are globbed rather than listed, so a workflow added later is
        compared too; the workflow the guard runs in is asserted to be among
        them, because a rename that took it out of the glob would leave the
        parity check running over the files that are left.

        Globbing makes the set discovered rather than pinned, so the copies
        compared are held to the ones that install by running a script: a step
        carrying no ``run:`` installs the toolchain some other way, carries no
        ``env:`` for these values to live in, and reding the routing guard over
        it would be a failure about a workflow this guard has no claim on.
        """
        assert WORKFLOW_SCAN_PATHS, "no workflow files are scanned, which leaves this check vacuous"
        assert WORKFLOW_PATH in WORKFLOW_SCAN_PATHS, (
            f"{WORKFLOW_PATH} is not among the globbed workflows {list(WORKFLOW_SCAN_PATHS)}; the guard's own "
            f"workflow has to be scanned, so either it moved out of {WORKFLOW_DIR}/ or it took a suffix outside "
            f"{list(WORKFLOW_SUFFIXES)}"
        )
        assert TOOLCHAIN_STEP_PINS, "no toolchain steps are pinned, which leaves this check vacuous"
        for name, keys in TOOLCHAIN_STEP_PINS:
            found = [(relative, job, step) for relative, job, step in _named_steps(name) if "run" in step]
            assert len(found) > 1, (
                f"step {name!r} runs a script in {len(found)} place(s) across {list(WORKFLOW_SCAN_PATHS)}; a "
                "parity check over fewer than two copies compares nothing — drop the pin if the duplication is gone"
            )
            for key in keys:
                sites: dict[str, list[str]] = {}
                for relative, job, step in found:
                    env = step.get("env")
                    assert isinstance(env, dict) and key in env, (
                        f"{relative} job {job} step {name!r} declares no `env: {key}`; that value is what "
                        "every other copy of the step is compared against"
                    )
                    sites.setdefault(str(env[key]), []).append(f"{relative}:{job}")
                assert len(sites) == 1, (
                    f"step {name!r} pins {key} to {len(sites)} different values: "
                    + "; ".join(f"{value!r} in {where}" for value, where in sorted(sites.items()))
                    + " — every copy fetches the same artifact and checks it against the same checksum, and "
                    "nothing but this compares one copy's values against another's"
                )

    def test_routing_target_runs_host_side_under_the_venv(self) -> None:
        """The target runs this module, under the host ``.venv`` pytest, and builds it first.

        ``deps: [setup]`` is what makes the target self-sufficient in CI, where
        no ``.venv`` exists until something creates one; without it the target
        fails on a fresh runner for a reason that has nothing to do with routing.

        Why the pytest argument is pinned alongside the runner is recorded at
        ``GUARD_MODULE_ARGUMENT``.

        Every token of the command is pinned as well, against a whitelist. What
        that whitelist closes that the forbidden-expression scan below does not
        is recorded at ``ROUTING_COMMAND_TOKENS``.

        ``deps:`` is pinned as the whole list, for the reason recorded at
        ``AGGREGATE_DEPENDENCY``.
        """
        target = _routing_target()
        commands = _command_texts(target)
        assert commands, f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} declares no commands"
        joined = _joined_commands(target)
        assert ROUTING_TASK_RUNNER in joined, (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} does not run {ROUTING_TASK_RUNNER}; the guard is "
            "host-side by design and a runner outside the venv is a different execution environment"
        )
        assert GUARD_MODULE_ARGUMENT.search(joined), (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} passes no {GUARD_MODULE} argument; the target that "
            "CI invokes as the routing-coverage guard has to run this module — repoint it, or repoint "
            "GUARD_MODULE at wherever the guard now lives"
        )
        assert ROUTING_COMMAND_TOKENS, "the allowed-token list is empty, which leaves the scan below vacuous"
        unlisted = sorted(set(joined.split()) - ROUTING_COMMAND_TOKENS)
        assert not unlisted, (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} runs {unlisted}, which ROUTING_COMMAND_TOKENS does "
            "not allow; the guard's value is that it always runs the same thing, so a token added here has "
            "to be argued for rather than merged — a pytest selection flag among them deselects the run"
        )
        deps = target.get("deps")
        assert deps == [ROUTING_TASK_DEPENDENCY], (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} declares deps {deps}, not "
            f"[{ROUTING_TASK_DEPENDENCY!r}]; go-task completes deps before cmds[0], so anything added here "
            "runs — and can fail — before pytest starts, with every wiring pin in this class still green"
        )

    @pytest.mark.parametrize(AGGREGATE_SITE_PARAM, AGGREGATE_SITES, ids=[f"{site.taskfile}:{site.aggregate}" for site in AGGREGATE_SITES])
    def test_routing_target_is_part_of_the_full_suite(self, site: AggregateSite) -> None:
        """Each aggregate that runs the guard runs it first, and declares only the deps it may.

        The guard *module* is already collected by the containerised scripts
        suite. What needs aggregating is the *target* — its host-side venv
        wiring — which otherwise runs only in CI and so is only ever exercised
        where a failure is most expensive to diagnose.

        Position is asserted for the reason the workflow ordering is: go-task
        runs ``cmds`` sequentially and stops at the first failure, so any target
        listed ahead of the guard suppresses it exactly as a preceding CI step
        would.

        ``deps:`` is a second channel the command index says nothing about; why
        it is pinned as the whole list is recorded at ``AGGREGATE_DEPENDENCY``.

        Run per site; why both ratchets apply wherever the guard is aggregated
        is recorded at ``AGGREGATE_SITES``.
        """
        tasks = _declared_tasks(site.taskfile)
        assert site.aggregate in tasks, f"{site.taskfile} declares no {site.aggregate!r} target"
        aggregate = tasks[site.aggregate]
        assert isinstance(aggregate, dict), f"{site.taskfile} target {site.aggregate} did not parse as a mapping"
        cmds = aggregate.get("cmds")
        assert isinstance(cmds, list) and cmds, f"{site.taskfile} target {site.aggregate} declares no commands"
        referenced = [entry.get("task") for entry in cmds if isinstance(entry, dict)]
        assert site.entry in referenced, (
            f"{site.taskfile} target {site.aggregate} runs {referenced}, which omits "
            f"{site.entry!r}; the host-side wiring would then run only in CI"
        )
        # Positions are read off the raw cmds list rather than off `referenced`, which holds only the
        # mapping entries: a literal command inserted ahead of the guard suppresses it just as a nested
        # target does, and would not show up in an index over the mappings alone.
        positions = [index for index, entry in enumerate(cmds) if isinstance(entry, dict) and entry.get("task") == site.entry]
        assert positions == [0], (
            f"{site.taskfile} target {site.aggregate} runs {site.entry!r} at command index "
            f"{positions}, not [0]; anything ahead of it that fails ends the aggregate run before the guard "
            "— which is the one target here that is meant to report on every change"
        )
        deps = aggregate.get("deps")
        assert deps == site.deps, (
            f"{site.taskfile} target {site.aggregate} declares deps {deps}, not {site.deps}; go-task "
            f"completes deps before cmds[0], so anything added here runs — and can fail — ahead of "
            f"{site.entry!r} while its command index stays 0"
        )

    def test_every_aggregate_running_the_guard_carries_the_ratchets(self) -> None:
        """No aggregate anywhere in the taskfiles runs the guard without being pinned above.

        The site list is a whitelist, so it can go stale in the direction that
        matters: an aggregate that starts running the guard and is not added to
        it gets neither the position ratchet nor the deps ratchet, and a comment
        restating the argument beside it enforces nothing.

        Two axes have to be discovered for that comparison to mean anything, and
        a whitelist on either one moves the hole rather than closing it. The
        *files* are globbed, so an aggregate in a third taskfile is compared
        instead of never being opened. The *shapes* are read through
        ``_runs_task``, so a ``deps:`` entry — which go-task completes before
        ``cmds[0]`` — a shell command invoking ``task``, or a target written in
        go-task's string or list shorthand all count as running the guard, where
        a scan for a ``cmds:`` mapping carrying ``task:`` sees none of them.

        Every file is checked against every pinned entry name, not only against
        the one its own site names: the root file refers to the guard as
        ``test:routing`` and the included file as ``routing``, and a shell
        command in either file spells it the way the root does.

        Known limits: a taskfile outside ``AGGREGATE_SCAN_PATHS``; a reference
        built from a variable; and a name that is neither pinned entry, such as
        an alias. Those are named rather than claimed closed — the comparison is
        over what this discovery can see.
        """
        assert AGGREGATE_SITES, "no aggregate sites are pinned, which leaves the ratchets above running on nothing"
        assert AGGREGATE_SCAN_PATHS, "no taskfiles are scanned, which leaves this discovery reading nothing"
        unscanned = sorted({site.taskfile for site in AGGREGATE_SITES} - set(AGGREGATE_SCAN_PATHS))
        assert not unscanned, (
            f"AGGREGATE_SITES pins aggregates in {unscanned}, which the glob {list(AGGREGATE_SCAN_PATHS)} does "
            f"not reach; a pinned taskfile outside the scan is compared against nothing, so repoint it under "
            f"{TASKFILE_DIR}/ or add its location to the glob"
        )
        pinned: dict[tuple[str, str], set[str]] = {}
        for site in AGGREGATE_SITES:
            pinned.setdefault((site.taskfile, site.entry), set()).add(site.aggregate)
        entries = sorted({site.entry for site in AGGREGATE_SITES})
        for taskfile in AGGREGATE_SCAN_PATHS:
            tasks = _declared_tasks(taskfile)
            for entry in entries:
                expected = pinned.get((taskfile, entry), set())
                declared = {str(name) for name, target in tasks.items() if _runs_task(target, entry)}
                assert declared == expected, (
                    f"{taskfile} targets running {entry!r} are {sorted(declared)}, while AGGREGATE_SITES pins "
                    f"{sorted(expected)}; a target running the guard without the position and deps ratchets "
                    "above can demote or drop it with nothing here to notice — add it to AGGREGATE_SITES"
                )

    def test_the_aggregate_discovery_reads_every_shape_it_claims(self) -> None:
        """``_runs_task`` matches each shape it says it does, driven on literals rather than on the taskfiles.

        Both pinned sites write the guard as a ``cmds:`` mapping carrying
        ``task:``, and no target in the scanned taskfiles reaches it any other
        way — read off those files rather than asserted here. So on the tree as
        it stands that one arm is the only one the discovery above ever sees
        return true, and every other arm could be broken with it still green: a
        typo in the invocation pattern, a dropped ``:``-strip, a shorthand
        reader that returns nothing for the list form. The shapes the helper
        exists for are the ones a *future* aggregate might be written in, which
        is exactly the case the discovery is there to catch.

        Driven on synthetic targets for the reason
        ``test_per_command_scan_reads_the_mapping_form`` gives for its own: a
        helper is held to the shapes it claims to read, not to the shape the
        tree happens to hold. Each shape is checked under both spellings of the
        entry, because the helper's contract admits a leading ``:`` on either
        side of the comparison and a strip dropped from one side reds nothing
        otherwise.
        """
        name = ROUTING_TASK_NAME
        shell = f"{TASK_INVOCATION} {name}"
        shapes: dict[str, object] = {
            "a deps entry": {"deps": [name]},
            "a deps entry with a leading colon": {"deps": [f":{name}"]},
            "a deps mapping": {"deps": [{"task": name}]},
            "a deps mapping with a leading colon": {"deps": [{"task": f":{name}"}]},
            "a cmds mapping": {"cmds": [{"task": name}]},
            "a cmds mapping with a leading colon": {"cmds": [{"task": f":{name}"}]},
            "a cmds mapping carrying command text": {"cmds": [{"cmd": shell}]},
            "a cmds shell command": {"cmds": [shell]},
            "the list shorthand": [shell],
            "the string shorthand": shell,
        }
        for entry in (name, f":{name}"):
            unread = sorted(shape for shape, target in shapes.items() if not _runs_task(target, entry))
            assert not unread, (
                f"_runs_task reads a target written as {unread} as running nothing, while every one of them "
                f"runs {entry!r}; an aggregate written in one of those shapes reaches the guard without the "
                "position and deps ratchets above, and the discovery beside this compares it against nothing"
            )
        prefixes: dict[str, object] = {
            "a shell command invoking a longer name": {"cmds": [f"{shell}:extra"]},
            "a deps entry naming a longer name": {"deps": [f"{name}:extra"]},
        }
        matched = sorted(shape for shape, target in prefixes.items() if _runs_task(target, name))
        assert not matched, (
            f"_runs_task reads {matched} as running {name!r}; a target carrying the pinned name only as a "
            "prefix would then be pulled into AGGREGATE_SITES' comparison, which is what the whole-word "
            "rationale at TASK_INVOCATION rests on"
        )

    def test_wiring_taskfiles_declare_no_ambient_environment(self) -> None:
        """Neither wiring taskfile hands the guard an environment from the file level.

        The forbidden-key scan below reads the routing target and its command
        mappings. A file-level ``env:`` sits above both, declared once for every
        target the file holds, so a ``PYTEST_ADDOPTS`` written there retires the
        guard with that scan green. The retirement is measured, and that a
        file-level ``env:`` is one of the ways to deliver it is inferred rather
        than observed; see ``TASKFILE_ENV``.

        Whitelisted rather than forbidden, because ``taskfiles/test.yml``
        legitimately declares one. Keys *and values*: why the one key admitted
        here is pinned by value rather than by key alone is recorded there too.
        The two mappings are read straight off the two files and are a single
        entry wide between them, so an addition to either has to be argued for
        rather than merged. ``dotenv:`` takes no whitelist of that kind — it
        names a file whose keys appear nowhere in the taskfile — so it is
        forbidden outright at this level.
        """
        assert TASKFILE_ENV, "no taskfile environments are pinned, which leaves this check vacuous"
        for relative, expected in sorted(TASKFILE_ENV.items()):
            document = _load_yaml_mapping(relative)
            environment = document.get(AMBIENT_ENV_KEY, {})
            assert isinstance(environment, dict), (
                f"{relative} declares a file-level `{AMBIENT_ENV_KEY}:` that did not parse as a mapping "
                f"({environment!r}), so the keys it exports to every target cannot be read off it"
            )
            declared = {str(key): value for key, value in environment.items()}
            assert declared == expected, (
                f"{relative} declares file-level environment {declared}, not {expected}; every target in the "
                "file runs with it, the guard included — a PYTEST_ADDOPTS among the keys retires the guard "
                "with the target-level scan below still green, and a value edited under a pinned key is as "
                "free as a key nobody pinned"
            )
            assert AMBIENT_DOTENV_KEY not in document, (
                f"{relative} declares a file-level `{AMBIENT_DOTENV_KEY}: {document[AMBIENT_DOTENV_KEY]}`; the "
                "keys it loads are named in that file rather than in this one, so no whitelist here can say "
                "what it exports to the guard's command"
            )

    def test_pytest_ini_hands_the_guard_no_options_it_was_not_measured_under(self) -> None:
        """``pytest.ini`` declares exactly the ``addopts`` value this guard runs under.

        The ini is a delivery channel no key pin in this class reads and no
        router prefix covers. It sits at the repository root, so an edit to it
        routes to zero tests: only the unconditional guard job runs, and if the
        word added deselects the run, that job goes green having asserted
        nothing. The import-time scan closes the words measured to do that; this
        closes every other one by equality, because an option here reaches every
        channel the guard runs in and the set of options that quietly narrow a
        run is not one this module can enumerate.

        Why it is asserted in a case body rather than at import, unlike the
        scan, is recorded at ``PYTEST_INI_ADDOPTS``.

        ``collect_target`` already rests on this file's ``norecursedirs``, so it
        is a file the guard reads and would otherwise leave unpinned.
        """
        declared = _pytest_ini_addopts()
        assert declared == PYTEST_INI_ADDOPTS, (
            f"{PYTEST_INI_PATH} declares `{PYTEST_INI_ADDOPTS_KEY} = {declared}`, not {PYTEST_INI_ADDOPTS!r}; "
            "every pytest run in this repository starts with that value, the guard's included, and nothing "
            "else here reads it"
        )

    def test_the_ambient_add_options_variable_hands_the_guard_nothing(self) -> None:
        """``$PYTEST_ADDOPTS`` is empty in the process this guard runs in.

        The variable reaches every channel the guard runs in and no key pin in
        this class reads it, so equality is what closes the options nobody
        enumerated: the wiring pins leave it declared nowhere that reaches the
        guard's process, and a value arriving at runtime is unaccounted for by
        construction.

        Asserted in a case body rather than at import, the way the ini value is:
        a variable set for an unrelated reason should red as a failing case
        naming it, not as a collection error that takes every module in the
        directory with it. The import-time scan reads the same value for the
        narrower deselecting set.
        """
        ambient = os.environ.get(AMBIENT_ADDOPTS_ENV_VAR, "")
        assert not ambient.strip(), (
            f"${AMBIENT_ADDOPTS_ENV_VAR} is {ambient!r}; it hands pytest arguments the routing target's command "
            "never names, so a deselecting option in it retires this guard with every wiring pin in this class "
            "still green — unset it, and if CI set it, take out the line that did"
        )

    def test_the_import_time_scan_fires_on_every_channel_it_reads(self) -> None:
        """The scan run at import raises on each channel, and lets its own probe through.

        The scan cannot fire on a healthy tree, which is what it is for and also
        what leaves it unexercised: deleting its body leaves every other case
        here green. Driving it on synthetic inputs is the only way to hold its
        three channels and its one exemption, and the exemption is the half that
        has to be re-checked — widening it is how the scan would be defeated
        without any assertion here being deleted.

        The ambient channel is driven in both directions. It screens for the
        pinned options rather than requiring emptiness, so an ordinary value has
        to pass here: were it to raise, every module in ``tests/ci/`` would stop
        collecting alongside this one, on a variable set for a reason that has
        nothing to do with the guard.
        """
        assert DESELECTING_OPTIONS, "the deselecting-option list is empty, which leaves this check vacuous"
        deselecting = DESELECTING_OPTIONS[0]
        assert_no_deselecting_option_is_in_effect(arguments=[GUARD_MODULE, "-v"], ambient="", ini_addopts=PYTEST_INI_ADDOPTS)
        assert_no_deselecting_option_is_in_effect(arguments=[GUARD_MODULE, "-v"], ambient="-q", ini_addopts=PYTEST_INI_ADDOPTS)
        assert_no_deselecting_option_is_in_effect(arguments=[*PROBE_ARGUMENTS, "tests/ci/"], ambient="", ini_addopts=PYTEST_INI_ADDOPTS)
        with pytest.raises(AssertionError, match=re.escape(AMBIENT_ADDOPTS_ENV_VAR)):
            assert_no_deselecting_option_is_in_effect(arguments=[GUARD_MODULE], ambient=f" {deselecting} ", ini_addopts=PYTEST_INI_ADDOPTS)
        with pytest.raises(AssertionError, match=re.escape(PYTEST_INI_PATH)):
            assert_no_deselecting_option_is_in_effect(
                arguments=[GUARD_MODULE],
                ambient="",
                ini_addopts=f"{PYTEST_INI_ADDOPTS} {deselecting}",
            )
        with pytest.raises(AssertionError, match="the command line"):
            assert_no_deselecting_option_is_in_effect(arguments=[GUARD_MODULE, deselecting], ambient="", ini_addopts=PYTEST_INI_ADDOPTS)
        with pytest.raises(AssertionError, match="the command line"):
            assert_no_deselecting_option_is_in_effect(
                arguments=[*PROBE_ARGUMENTS, "tests/ci/", "-v"],
                ambient="",
                ini_addopts=PYTEST_INI_ADDOPTS,
            )

    def test_routing_target_carries_no_container_or_tolerance_tokens(self) -> None:
        """The target neither reaches for a container nor tolerates a non-zero exit.

        A drift guard rather than an adversarial boundary — the boundary is the
        permission surface plus review. What it catches is a container path
        introduced into a target that runs host-side under the venv, and the
        or-true suffix an implementer reaches for when the guard reds.

        Read through ``_command_texts``, not off the string commands; what a
        scan over the strings alone would miss is recorded at
        ``COMMAND_TEXT_KEYS``.
        """
        assert FORBIDDEN_ROUTING_PATTERNS, "the forbidden-expression list is empty, which leaves this scan vacuous"
        commands = _joined_commands(_routing_target())
        assert commands, f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} declares no commands to scan"
        present = [pattern.pattern for pattern in FORBIDDEN_ROUTING_PATTERNS if pattern.search(commands)]
        assert not present, (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} matches {present}; the guard runs host-side "
            "under the venv, and its commands take no caller-supplied arguments"
        )
        tolerated = OR_TRUE_SUFFIX.findall(commands)
        assert not tolerated, (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} suffixes a command with {tolerated}; a swallowed "
            "pytest exit reports green for a guard that never asserted anything"
        )

    def test_routing_target_can_be_neither_skipped_nor_forgiven(self) -> None:
        """The target declares only the keys it needs, and every command it holds is a plain string.

        Two assertions close the target's whole surface.

        The key set closes go-task's target schema by equality. That schema is
        large and not one a reader here can enumerate, so the six named below
        are what has been driven and observed rather than a claim to have found
        every retirement; the equality is what covers the ones nobody found.

        The entry type closes the level a key whitelist cannot reach. go-task
        takes a ``cmds:`` entry as a mapping, and a ``for:`` on one of those
        retires the target with the pinned command byte-identical on the page.
        Measured on go-task 3.52.0: a byte-identical ``exit 3`` exits 201
        unwrapped, reporting ``Failed to run task``, and exits 0 with no output
        at all wrapped in ``for: []``; iterating an unset variable behaves the
        same; execution continues into the following entry; and go-task prints
        not even its usual ``task: [target] <command>`` echo line, so the skip
        leaves no trace in a CI log to read it off. Every text scan in this
        module reads such an entry through its ``cmd:`` value, so the runner
        check, the module argument, the token whitelist, the expression scan,
        the or-true scan and the junit pin all pass while pytest never starts. A
        key whitelist over the entry would not close it either, since ``for:``
        and ``cmd:`` live in the same mapping; requiring a plain string does,
        and closes every other per-entry key with it.

        Each of the six retires the guard without touching a command, so the
        command scan above sees none of them; what each one does, and how far
        each was measured, is recorded at ``FORBIDDEN_ROUTING_TARGET_KEYS``.

        The per-command scan at the end reads the entries as written, since
        ``ignore_error`` also attaches to an individual ``cmd:`` mapping. On
        this target it now has nothing to find, because the entry-type
        assertion has already rejected every mapping; it is kept as the
        diagnostic for the seam ``test_per_command_scan_reads_the_mapping_form``
        drives on a literal.
        """
        assert ROUTING_TARGET_KEYS, "the pinned target-key set is empty, which would admit any target at all"
        assert FORBIDDEN_ROUTING_TARGET_KEYS, "the forbidden-key list is empty, which leaves this scan vacuous"
        target = _routing_target()
        keys = frozenset(str(key) for key in target)
        assert keys == ROUTING_TARGET_KEYS, (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} declares {sorted(keys)}, not "
            f"{sorted(ROUTING_TARGET_KEYS)}; the guard's target is this short precisely so that its key space "
            "can be closed by equality — a key added here can skip it, forgive it, hand it an environment or "
            "hand it a checksum, and has to be argued for rather than merged"
        )
        entries = _command_entries(target)
        assert entries, f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} declares no commands to scan"
        mapped = [index for index, entry in enumerate(entries) if not isinstance(entry, str)]
        assert not mapped, (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} writes command(s) {mapped} as something other than a "
            "plain string; a `cmds:` mapping carries keys of its own, and a `for:` iterating zero times skips "
            "the command it wraps while go-task prints nothing and reports the target successful — the pinned "
            "command text stays byte-identical through it and every scan here still passes"
        )
        declared = [key for key in FORBIDDEN_ROUTING_TARGET_KEYS if key in target]
        assert not declared, (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} declares {declared}; the guard is unconditional, so "
            "neither a skipped run nor a forgiven failure is an outcome it can have"
        )
        per_command = sorted({key for entry in entries if isinstance(entry, dict) for key in FORBIDDEN_ROUTING_TARGET_KEYS if key in entry})
        assert not per_command, (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} carries {per_command} on a command mapping; that "
            "swallows the same exit the target-level key would, one command at a time"
        )

    def test_per_command_scan_reads_the_mapping_form(self) -> None:
        """The two seams the scans above read keep the mapping entries the string commands drop.

        Both scans meet no mapping on the real target — its ``cmds`` is a single
        folded string — so both pass identically with ``_command_strings``
        substituted, and neither would notice. This drives that substitution out
        on a literal rather than on whatever shape the target happens to have.

        It locks the *seams*, which is more than the helper: ``_joined_commands``
        is the one call the expression scan makes, so the ``{{`` match below
        fails the moment that call reads the strings alone, and the key scan
        reads ``_command_entries`` the same way. What it does not lock is a scan
        rewritten to call neither — that stays a review matter.
        """
        assert FORBIDDEN_ROUTING_TARGET_KEYS, "the forbidden-key list is empty, which leaves this scan vacuous"
        assert FORBIDDEN_ROUTING_PATTERNS, "the forbidden-expression list is empty, which leaves this scan vacuous"
        command = f"{ROUTING_TASK_RUNNER} {GUARD_MODULE}"
        injected = dict(TOLERATED_COMMAND_ENTRY, cmd=f"{ROUTING_TASK_RUNNER} {{{{.CLI_ARGS}}}}")
        target = {"cmds": [command, injected]}
        assert _command_strings(target) == (command,), (
            "_command_strings kept the mapping entry, so the two helpers no longer differ and the scans' "
            "reliance on the flattening seams stops being load-bearing"
        )
        matched = [pattern.pattern for pattern in FORBIDDEN_ROUTING_PATTERNS if pattern.search(_joined_commands(target))]
        assert matched, (
            f"_joined_commands surfaced none of {[pattern.pattern for pattern in FORBIDDEN_ROUTING_PATTERNS]} "
            f"from a cmds mapping whose command is {injected['cmd']!r}; the expression scan reading it would "
            "then miss a caller-injected argument written one command at a time"
        )
        entries = _command_entries(target)
        surfaced = sorted({key for entry in entries if isinstance(entry, dict) for key in FORBIDDEN_ROUTING_TARGET_KEYS if key in entry})
        assert surfaced == sorted(set(injected) & set(FORBIDDEN_ROUTING_TARGET_KEYS)), (
            f"_command_entries surfaced {surfaced} from a cmds mapping carrying {sorted(injected)}; "
            "a scan reading it would then miss an exit swallowed one command at a time"
        )
        assert surfaced, (
            f"the synthetic entry {injected!r} carries none of {list(FORBIDDEN_ROUTING_TARGET_KEYS)}, "
            "so the comparison above holds for a helper that drops every mapping too"
        )

    def test_routing_target_junit_artifact_is_its_own(self) -> None:
        """No other target writes to the routing target's junit path.

        Scoped to this target rather than asserted globally: two pre-existing
        targets already share a junit path, and repairing that is out of scope
        here. What matters is that the aggregate suite, which runs several
        targets in one pass, cannot have one of them clobber this guard's
        results file.
        """
        destinations = _junit_destinations(_routing_target())
        assert destinations, (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} writes no junit file, so there is no artifact to "
            "keep distinct and nothing here to assert"
        )
        others = frozenset(
            destination
            for name, target in _declared_tasks().items()
            if name != ROUTING_TASK_NAME
            for destination in _junit_destinations(target)
        )
        assert others, f"{TASKFILE_PATH} declares no other junit destination, which leaves this comparison vacuous"
        shared = sorted(destinations & others)
        assert not shared, (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} writes {shared}, which another target also writes; "
            "under the aggregate suite whichever runs last silently replaces the other's results"
        )
