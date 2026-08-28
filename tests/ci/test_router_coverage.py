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
"""

import re
import subprocess
import sys
from collections.abc import Callable
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

#: The only router target this guard covers. The other targets reach an
#: un-stubbed ``ci/resolve_downstream_tests.py``, which this walk would run once
#: per tracked path.
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

#: Sources the container-detection scan reads. This module is in the list
#: because a skip inside it is the repair an in-container red invites;
#: ``tests/ci/conftest.py`` is in it because that is the other place such a skip
#: fits — it supplies this module's route fixtures and takes additions freely.
CONTAINER_DETECTION_SCAN_SOURCES: tuple[str, ...] = (
    GUARD_MODULE,
    "tests/ci/conftest.py",
)

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
#: carries has no closure path. ``TODO-0333`` is the catch-all standing-holes
#: id, so a hole whose cause no other id names still gets an honest one.
#: Known limit: this is a hand-copied mirror of the ids filed in the ledger and
#: nothing checks it against one, so an id renamed or retired there keeps
#: passing here until a reader notices.
ENUMERATED_TODO_IDS: frozenset[str] = frozenset({
    "TODO-0307",
    "TODO-0313",
    "TODO-0329",
    "TODO-0330",
    "TODO-0331",
    "TODO-0332",
    "TODO-0333",
    "TODO-0334",
    "TODO-0335",
})

#: The two files that carry this guard's wiring: the CI step that runs it on
#: every PR, and the target that step invokes.
WORKFLOW_PATH = ".github/workflows/test.yml"
TASKFILE_PATH = "taskfiles/test.yml"

#: The workflow job the guard step belongs to. Every step lookup below is
#: scoped by this key rather than searched file-wide: ``Install uv`` appears in
#: two jobs and ``Install Task`` in three, so an unscoped search either matches
#: several steps or makes the ordering assertions depend on edits to a job this
#: guard has nothing to do with.
GUARD_JOB = "test-src-scripts"

#: The guard step, pinned by name **and** by the command it runs. Either alone
#: leaves a rename direction open: matching on the name only lets the command
#: be retargeted at some other target, and matching on the command only lets
#: the step be renamed into something a reader no longer recognises as this
#: guard.
GUARD_STEP_NAME = "Run Routing Coverage Guard"
GUARD_STEP_COMMAND = "task test:routing"

#: The command as a whole line rather than as a substring of ``run:``. A
#: substring test is satisfied by any command with this one as a prefix —
#: ``task test:routing:some-subset`` among them — which is a step that no
#: longer runs the guard while still matching the pin.
GUARD_STEP_COMMAND_LINE = re.compile(rf"^\s*{re.escape(GUARD_STEP_COMMAND)}\s*$", re.MULTILINE)

#: The key that leaves the guard step running, and red, while the job it sits
#: in still reports success.
GUARD_STEP_TOLERANCE_KEY = "continue-on-error"

#: The steps the guard step must sit between. After the uv install because that
#: step appends to ``$GITHUB_PATH`` and so affects only later steps; before the
#: script tests because a script-test failure would otherwise suppress a guard
#: whose whole point is that it always runs.
UV_INSTALL_STEP_NAME = "Install uv"
SCRIPT_TESTS_STEP_NAME = "Run Script Tests"

#: The uv package cache the guard's ``deps: [setup]`` venv build restores from.
#: The package cache, never ``.venv`` itself — a virtualenv is not relocatable.
CACHE_ACTION_PREFIX = "actions/cache@"
UV_CACHE_PATH = "~/.cache/uv"

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

#: This module as a whole pytest argument in the routing target's commands.
#: ``taskfiles/`` sits under no router prefix, so a target repointed at some
#: other file runs green in CI while the guard stops running at all — the
#: runner and the dependency say nothing about *what* is run. Matched
#: whitespace-delimited so a longer path with this one as a prefix cannot
#: satisfy the pin.
GUARD_MODULE_ARGUMENT = re.compile(rf"(?<!\S){re.escape(GUARD_MODULE)}(?!\S)")

#: Expressions that MUST NOT appear in the routing target's commands. The first
#: three would put a host-side guard back under the container path it was moved
#: off; the fourth would let a caller inject pytest arguments — including a
#: selection that deselects every case — into a target whose value is that it
#: always runs the same thing. Word-anchored where the expression ends in a
#: word character, so a path such as a test module named after a container file
#: does not read as a container invocation.
FORBIDDEN_ROUTING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bdocker\b"),
    re.compile(r"--entrypoint\b"),
    re.compile(r"\bPYTHON_GATE_DISABLED\b"),
    re.compile(re.escape("{{.CLI_ARGS}}")),
)

#: Target-level keys that retire the guard without touching its commands:
#: ``ignore_error`` swallows the pytest exit, ``status`` makes go-task skip a
#: satisfied target outright — which is exactly how ``setup`` skips — and
#: ``platforms`` narrows the target to matching hosts, which is not a property
#: an unconditional guard can have.
FORBIDDEN_ROUTING_TARGET_KEYS: tuple[str, ...] = ("ignore_error", "status", "platforms")

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
    ENOENT. ``-p no:cacheprovider`` keeps pytest from writing a cache directory
    into the mount, whose only writable subtree is ``tmp/``. ``--`` stops a
    tracked path beginning with a hyphen being read as a flag.

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
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "--", target],
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

        Args:
            target: Announced pytest target.

        Returns:
            ``True`` when pytest collected something.

        Raises:
            AssertionError: If the collector exited anything other than
                collected-or-empty.
        """
        if target not in self._collects:
            result = self._collect(target)
            assert result.returncode in (COLLECTED_EXIT, NO_TESTS_COLLECTED_EXIT), (
                f"collecting {target} exited {result.returncode}; only {COLLECTED_EXIT} (collected) and "
                f"{NO_TESTS_COLLECTED_EXIT} (no tests) classify, and reading any other exit as either "
                f"one files a wrong verdict\n--- stdout ---\n{result.stdout}--- stderr ---\n{result.stderr}"
            )
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
    run; a ``ValueError`` if it returns bytes the listing's declared encoding
    cannot decode, which is what a tracked path in another encoding produces;
    and a ``subprocess.TimeoutExpired`` if git does not return inside the
    listing's liveness ceiling. Any one left uncaught is exactly the collection
    error this degradation exists to avoid.

    Returns:
        The cases, and their pytest ids in the same order.
    """
    cases: list[RouterCase] = []
    ids: list[str] = []
    for router in TEST_ROUTERS:
        try:
            universe = changed_scripts_universe(router)
        except (AssertionError, re.error, OSError, ValueError, subprocess.TimeoutExpired) as failure:
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

    @pytest.mark.parametrize("case", ROUTER_CASES, ids=ROUTER_CASE_IDS)
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
        """Every exemption is tracked by an id that exists, so each one has a closure path."""
        assert EXEMPTIONS, "the registry is empty, which leaves this scan vacuous"
        assert ENUMERATED_TODO_IDS, "the enumerated-id set is empty, which leaves this scan vacuous"
        unknown = sorted({entry.todo_id for entry in EXEMPTIONS if entry.todo_id not in ENUMERATED_TODO_IDS})
        assert not unknown, (
            f"helpers.router_coverage_registry cites TODO ids {unknown} outside {sorted(ENUMERATED_TODO_IDS)}; "
            "use the id whose subject describes the hole, or the standing-holes catch-all"
        )

    def test_pinned_path_routing_outcome_is_unchanged(self, routing_probe: RoutingProbe) -> None:
        """Each router's announcement for the pinned path is asserted, not merely exempted.

        The pair is a registered hole in both routers, and the registry records
        only that it is one. The two routers arrive there by different branches
        and produce different shapes — a self-target that collects nothing on one
        side, no target at all on the other — and nothing else asserts either, so
        a change from one wrong outcome to another would leave the hole set
        balanced and pass.
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

        The registry is this guard's data, so an edit to it has to re-run the
        guard. That holds only while it sits under ``tests/helpers/``, whose
        fan-out reaches ``tests/ci/`` as well. Under ``tests/ci/`` it would route
        to itself and collect nothing, and under any other prefix it would route
        nowhere — either way the guard would never see its own data change.
        """
        assert REGISTRY_FANOUT_TARGETS, "the pinned fan-out is empty, which leaves this check vacuous"
        registry_source = router_coverage_registry.__file__
        assert registry_source and (REPO_ROOT / REGISTRY_MODULE).resolve() == Path(registry_source).resolve(), (
            f"{REGISTRY_MODULE} is not the module this guard reads its exemptions from ({registry_source}), so "
            "the fan-out below is measured for a path the guard does not actually depend on — repoint "
            "REGISTRY_MODULE at wherever the registry now lives"
        )
        # No existence check on the path: the assertion above already resolves it onto the ``__file__``
        # of a module this test imported, which cannot be a file that is missing.
        for router in TEST_ROUTERS:
            announced = frozenset(routing_probe.announced_targets(router, REGISTRY_MODULE))
            assert REGISTRY_FANOUT_TARGETS <= announced, (
                f"ci/{router} routes {REGISTRY_MODULE} to {sorted(announced)}, which omits "
                f"{sorted(REGISTRY_FANOUT_TARGETS - announced)}; the registry belongs under "
                "tests/helpers/ precisely so that editing it re-runs this guard"
            )

    def test_guard_sources_carry_no_container_detection(self) -> None:
        """Neither this module nor the conftest behind it branches on being containerised.

        Both routers route ``tests/ci/`` into ``pytest-cli``, so this guard runs
        in-container as a matter of course. A skip there would silence the very
        channel that detects an un-routed source; the repair for a red
        in-container run is the interpreter resolution in ``collect_target``.
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
        # No emptiness guard on the source itself: the assertion above already ties it to the module
        # currently executing, which cannot be an empty file and still be running this test.
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
        # Only the two variable-length collections are guarded. Emptying either would leave the loop
        # below running zero comparisons and still passing. TEST_ROUTERS is a fixed-length 2-tuple,
        # so its own type rules the empty case out and a non-empty assertion on it can never fire.
        assert CONTAMINATION_SAMPLES, "there are no samples to compare, which leaves the reuse check vacuous"
        assert CONTAMINATION_NOISE, "there is nothing to dirty the workspace with, which leaves the settling check vacuous"
        for router in TEST_ROUTERS:
            for sample in CONTAMINATION_SAMPLES:
                reused = session_route(router, [sample], target=ROUTE_TARGET)
                fresh = route_variant()(router, [sample], target=ROUTE_TARGET)
                assert reused.returncode == 0, diagnose(reused)
                assert fresh.returncode == 0, diagnose(fresh)
                assert routed_targets(reused) == routed_targets(fresh), (
                    f"ci/{router} announced {routed_targets(reused)} for {sample} in the reused session "
                    f"workspace and {routed_targets(fresh)} in a fresh one"
                )
            noise = session_route(router, list(CONTAMINATION_NOISE), target=ROUTE_TARGET)
            assert noise.returncode == 0, diagnose(noise)
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
        announcement, so an absent one kills the router under ``set -e``. The
        sample must route a target, since both routers return early on an empty
        one and never reach the gate at all.
        """
        probe = RoutingProbe(route_variant(shadow_security_gate=False), collect_target)
        for router in TEST_ROUTERS:
            with pytest.raises(AssertionError, match="a router that fails is a router defect"):
                probe.announced_targets(router, ROUTER_HEALTH_SAMPLE)

    def test_collector_exit_outside_the_classified_pair_fails(self, session_route: RouteFn) -> None:
        """An unclassifiable collector exit fails, rather than being read as either verdict.

        Read as collected it excuses a hole; read as empty it invents one. The
        injected collector is the only way to produce such an exit, since the
        real one is a pytest collection run.
        """
        probe = RoutingProbe(session_route, unclassified_collect)
        with pytest.raises(AssertionError, match=f"exited {UNCLASSIFIED_COLLECT_EXIT}"):
            probe.collects_tests(STUB_COLLECT_TARGET)


def _load_yaml_mapping(relative: str) -> dict[str, object]:
    """Parse one wiring file, failing loudly rather than yielding an empty mapping to read nothing off."""
    path = REPO_ROOT / relative
    assert path.is_file(), f"{relative} is missing, so the wiring it carries cannot be pinned"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{relative} did not parse as a mapping, so no wiring can be read off it"
    return document


def _guard_job() -> dict[str, object]:
    """Return the job the guard step belongs to, located by key.

    Scoping every later lookup by job is the whole safeguard. ``Install uv``
    appears in two jobs of this workflow and ``Install Task`` in three, so a
    file-wide search would either match several steps or make the ordering
    assertions turn on edits to a job this guard has nothing to do with.
    """
    workflow = _load_yaml_mapping(WORKFLOW_PATH)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict) and jobs, f"{WORKFLOW_PATH} declares no jobs, so the guard step cannot be located"
    assert GUARD_JOB in jobs, (
        f"{WORKFLOW_PATH} declares no {GUARD_JOB!r} job — it declares {sorted(jobs)}; every lookup below is "
        "scoped by job key because step names repeat across jobs, so a renamed job unwires the pin rather "
        "than relocating it"
    )
    job = jobs[GUARD_JOB]
    assert isinstance(job, dict), f"{WORKFLOW_PATH} job {GUARD_JOB} did not parse as a mapping"
    return job


def _guard_job_steps() -> list[dict[str, object]]:
    """Return the guard job's steps."""
    job = _guard_job()
    steps = job.get("steps")
    assert isinstance(steps, list) and steps, f"{WORKFLOW_PATH} job {GUARD_JOB} declares no steps"
    mistyped = [index for index, step in enumerate(steps) if not isinstance(step, dict)]
    assert not mistyped, f"{WORKFLOW_PATH} job {GUARD_JOB} has non-mapping steps at {mistyped}"
    return steps


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
    """Locate the guard step by name **and** by the command it runs.

    Both predicates are required. Matching the name alone would let the command
    be retargeted at some other task while the step keeps its label; matching
    the command alone would let the step be renamed into something no reader
    recognises as this guard. The command is matched as a whole line, so a
    command that merely starts with it does not satisfy the pin.
    """
    matches = [
        index
        for index, step in enumerate(steps)
        if step.get("name") == GUARD_STEP_NAME and GUARD_STEP_COMMAND_LINE.search(str(step.get("run", "")))
    ]
    assert len(matches) == 1, (
        f"{WORKFLOW_PATH} job {GUARD_JOB} carries {len(matches)} steps named {GUARD_STEP_NAME!r} whose `run:` "
        f"is exactly {GUARD_STEP_COMMAND!r}, not exactly 1; the guard is unwired until exactly one step "
        "satisfies both"
    )
    return matches[0]


def _uv_cache_step(steps: list[dict[str, object]]) -> tuple[int, dict[str, object]]:
    """Locate the single step restoring the uv package cache, and return its settings.

    Selected by cached path rather than by being the job's only cache step: an
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
    assert len(matches) == 1, (
        f"{WORKFLOW_PATH} job {GUARD_JOB} carries {len(matches)} {CACHE_ACTION_PREFIX} steps caching "
        f"{UV_CACHE_PATH!r}, not exactly 1; without one the guard's venv is rebuilt from an empty package "
        "cache on every run, and with two which one serves the build is arbitrary"
    )
    return matches[0]


def _declared_tasks() -> dict[str, object]:
    """Return every target declared in the taskfile."""
    taskfile = _load_yaml_mapping(TASKFILE_PATH)
    tasks = taskfile.get("tasks")
    assert isinstance(tasks, dict) and tasks, f"{TASKFILE_PATH} declares no tasks"
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
    """Return a target's literal commands, dropping the ``task:`` and ``defer:`` mapping entries."""
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


def _junit_destinations(target: object) -> frozenset[str]:
    """Read the junit paths a target writes to."""
    return frozenset(str(match) for command in _command_strings(target) for match in JUNIT_DESTINATION.findall(command))


def _setup_requirements_files() -> tuple[str, ...]:
    """Read the requirements files the venv-building target installs from."""
    tasks = _declared_tasks()
    assert SETUP_TASK_NAME in tasks, (
        f"{TASKFILE_PATH} declares no {SETUP_TASK_NAME!r} target, so the files the guard's venv is built "
        "from cannot be read and REQUIREMENTS_FILES has nothing to be pinned against"
    )
    files = tuple(str(match) for command in _command_strings(tasks[SETUP_TASK_NAME]) for match in REQUIREMENTS_FLAG.findall(command))
    assert files, (
        f"{TASKFILE_PATH} target {SETUP_TASK_NAME} names no {REQUIREMENTS_FLAG.pattern!r} file; either the "
        "install line changed shape, or the venv is no longer built from requirements files at all"
    )
    return files


class TestGuardWiring:
    """The CI step and the task target that make this guard unconditional.

    Everything above measures routing coverage; nothing above notices when the
    thing that runs it is deleted, renamed, made conditional, or pointed
    somewhere else. ``.github/`` and ``taskfiles/`` sit under no router prefix,
    so no diff-scoped job covers either file — this class is what makes a
    wiring regression fail in the run it happens in, wherever the guard is
    invoked from.
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

    def test_workflow_job_is_neither_gated_nor_forgiven(self) -> None:
        """The job holding the guard carries no ``if:`` and no ``continue-on-error``.

        The step-level pins above are worth nothing while the job around them
        can be skipped or forgiven wholesale — one key on the job retires every
        step it holds, this guard included, and costs less to write than either
        step-level equivalent.
        """
        job = _guard_job()
        gates = [key for key in ("if", GUARD_STEP_TOLERANCE_KEY) if key in job]
        assert not gates, (
            f"{WORKFLOW_PATH} job {GUARD_JOB} carries {gates}; the guard runs on every pull request only "
            "while the job carrying it does, and counts only while that job's conclusion follows from it"
        )

    def test_workflow_runs_the_guard_between_uv_install_and_script_tests(self) -> None:
        """The guard step sits after the uv install and before the script tests.

        The lower bound is mechanical: the uv install appends to
        ``$GITHUB_PATH``, which affects only subsequent steps, so a guard placed
        earlier finds no ``uv`` for its ``deps: [setup]`` venv build. The upper
        bound is the point of the guard: after the script tests, an ordinary
        script-test failure would suppress it.
        """
        steps = _guard_job_steps()
        guard_index = _guard_step_index(steps)
        uv_index = _sole_step_index(steps, UV_INSTALL_STEP_NAME)
        script_index = _sole_step_index(steps, SCRIPT_TESTS_STEP_NAME)
        assert uv_index < guard_index, (
            f"{WORKFLOW_PATH} job {GUARD_JOB} runs {GUARD_STEP_NAME!r} at step {guard_index}, before "
            f"{UV_INSTALL_STEP_NAME!r} at step {uv_index}; uv is on $PATH only for steps after its install"
        )
        assert guard_index < script_index, (
            f"{WORKFLOW_PATH} job {GUARD_JOB} runs {GUARD_STEP_NAME!r} at step {guard_index}, after "
            f"{SCRIPT_TESTS_STEP_NAME!r} at step {script_index}; a script-test failure would then suppress "
            "the one step that is meant to run unconditionally"
        )

    def test_workflow_caches_uv_packages_before_the_guard(self) -> None:
        """A uv package cache keyed on the requirements files precedes the guard step.

        The step is selected by the path it caches, which is the uv package
        cache and not ``.venv``: a virtualenv records absolute interpreter
        paths and does not survive relocation, so restoring one would be worse
        than rebuilding.
        """
        installed = _setup_requirements_files()
        assert frozenset(REQUIREMENTS_FILES) == frozenset(installed), (
            f"{TASKFILE_PATH} target {SETUP_TASK_NAME} installs from {sorted(set(installed))} while the key "
            f"check below is written against {sorted(REQUIREMENTS_FILES)}; the two have drifted, and the "
            "difference is a dependency change the cache key would not notice"
        )
        steps = _guard_job_steps()
        guard_index = _guard_step_index(steps)
        cache_index, settings = _uv_cache_step(steps)
        key = str(settings.get("key", ""))
        # Matched as the quoted `hashFiles` argument, not as a bare substring: `requirements.txt`
        # is a suffix of `tests/requirements.txt`, so a substring test would read a key naming only
        # the two nested files as covering the root one too.
        unkeyed = [name for name in REQUIREMENTS_FILES if f"'{name}'" not in key]
        assert not unkeyed, (
            f"{WORKFLOW_PATH} keys the uv cache on {key!r}, which ignores {unkeyed}; a change to an ignored "
            "requirements file would hit a cache the change invalidated"
        )
        assert cache_index < guard_index, (
            f"{WORKFLOW_PATH} restores the uv cache at step {cache_index}, after {GUARD_STEP_NAME!r} at step "
            f"{guard_index}; a cache restored afterwards saves the guard's venv build nothing"
        )

    def test_routing_target_runs_host_side_under_the_venv(self) -> None:
        """The target runs this module, under the host ``.venv`` pytest, and builds it first.

        ``deps: [setup]`` is what makes the target self-sufficient in CI, where
        no ``.venv`` exists until something creates one; without it the target
        fails on a fresh runner for a reason that has nothing to do with routing.

        The pytest argument is pinned alongside the runner because the runner
        alone says only *how* the target runs, not *what*: ``taskfiles/`` sits
        under no router prefix, so a target repointed at some other module
        passes every diff-scoped job while this guard stops running.
        """
        target = _routing_target()
        commands = _command_strings(target)
        assert commands, f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} declares no commands"
        joined = "\n".join(commands)
        assert ROUTING_TASK_RUNNER in joined, (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} does not run {ROUTING_TASK_RUNNER}; the guard is "
            "host-side by design and a runner outside the venv is a different execution environment"
        )
        assert GUARD_MODULE_ARGUMENT.search(joined), (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} passes no {GUARD_MODULE} argument; the target that "
            "CI invokes as the routing-coverage guard has to run this module — repoint it, or repoint "
            "GUARD_MODULE at wherever the guard now lives"
        )
        deps = target.get("deps")
        assert isinstance(deps, list), f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} declares no deps list"
        assert ROUTING_TASK_DEPENDENCY in deps, (
            f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} depends on {deps}, which omits "
            f"{ROUTING_TASK_DEPENDENCY!r}; the venv it runs under would then have to pre-exist"
        )

    def test_routing_target_is_part_of_the_full_suite(self) -> None:
        """The aggregate target invokes the routing target, first.

        The guard *module* is already collected by the containerised scripts
        suite. What needs aggregating is the *target* — its host-side venv
        wiring — which otherwise runs only in CI and so is only ever exercised
        where a failure is most expensive to diagnose.

        Position is asserted for the reason the workflow ordering is: go-task
        runs ``cmds`` sequentially and stops at the first failure, so any target
        listed ahead of the guard suppresses it exactly as a preceding CI step
        would.
        """
        tasks = _declared_tasks()
        assert AGGREGATE_TASK_NAME in tasks, f"{TASKFILE_PATH} declares no {AGGREGATE_TASK_NAME!r} target"
        aggregate = tasks[AGGREGATE_TASK_NAME]
        assert isinstance(aggregate, dict), f"{TASKFILE_PATH} target {AGGREGATE_TASK_NAME} did not parse as a mapping"
        cmds = aggregate.get("cmds")
        assert isinstance(cmds, list) and cmds, f"{TASKFILE_PATH} target {AGGREGATE_TASK_NAME} declares no commands"
        referenced = [entry.get("task") for entry in cmds if isinstance(entry, dict)]
        assert ROUTING_TASK_NAME in referenced, (
            f"{TASKFILE_PATH} target {AGGREGATE_TASK_NAME} runs {referenced}, which omits "
            f"{ROUTING_TASK_NAME!r}; the host-side wiring would then run only in CI"
        )
        # Positions are read off the raw cmds list rather than off `referenced`, which holds only the
        # mapping entries: a literal command inserted ahead of the guard suppresses it just as a nested
        # target does, and would not show up in an index over the mappings alone.
        positions = [index for index, entry in enumerate(cmds) if isinstance(entry, dict) and entry.get("task") == ROUTING_TASK_NAME]
        assert positions == [0], (
            f"{TASKFILE_PATH} target {AGGREGATE_TASK_NAME} runs {ROUTING_TASK_NAME!r} at command index "
            f"{positions}, not [0]; anything ahead of it that fails ends the aggregate run before the guard "
            "— which is the one target here that is meant to report on every change"
        )

    def test_routing_target_carries_no_container_or_tolerance_tokens(self) -> None:
        """The target neither reaches for a container nor tolerates a non-zero exit.

        A drift guard rather than an adversarial boundary — the boundary is the
        permission surface plus review. What it catches is the accidental
        reintroduction of the container path this target was deliberately moved
        off, and the or-true suffix an implementer reaches for when the guard
        reds.
        """
        assert FORBIDDEN_ROUTING_PATTERNS, "the forbidden-expression list is empty, which leaves this scan vacuous"
        commands = "\n".join(_command_strings(_routing_target()))
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
        """The target declares none of the keys that retire it in place.

        Each retires the guard without touching a command, so the command scan
        above sees none of them: ``ignore_error`` reports success for a target
        whose pytest run failed, a satisfied ``status`` makes go-task skip the
        target outright — which is how ``setup`` skips a venv it already built —
        and ``platforms`` limits it to hosts that match, while CI and the
        developers running the aggregate suite are not the same platform. Read
        off the target as written, since ``ignore_error`` also attaches to an
        individual ``cmd:`` mapping, and a scan over the string commands drops
        every mapping entry.
        """
        assert FORBIDDEN_ROUTING_TARGET_KEYS, "the forbidden-key list is empty, which leaves this scan vacuous"
        target = _routing_target()
        entries = _command_entries(target)
        assert entries, f"{TASKFILE_PATH} target {ROUTING_TASK_NAME} declares no commands to scan"
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
