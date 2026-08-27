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
from helpers.router_coverage_registry import EXEMPTIONS
from helpers.router_harness import (
    ANNOUNCE_PREFIX,
    CONTAINER_DETECTION_TOKENS,
    REPO_ROOT,
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

#: This module, as the container-detection scan below names it.
GUARD_MODULE = "tests/ci/test_router_coverage.py"

#: Sources the container-detection scan reads. This module is in the list
#: because a skip inside it is the repair an in-container red invites;
#: ``tests/ci/conftest.py`` is in it because that is the other place such a skip
#: fits — it supplies this module's route fixtures and takes additions freely.
CONTAINER_DETECTION_SCAN_SOURCES: tuple[str, ...] = (
    GUARD_MODULE,
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

#: Probes whether one announced target collects, returning the raw process so
#: the exit-code contract stays with the caller.
CollectFn = Callable[[str], subprocess.CompletedProcess[str]]

#: How many probes this session has built. One is the whole budget: the caches
#: below hold a route per pair and a collection per target, and a probe rebuilt
#: per case would re-route and re-collect for every one of them while still
#: reporting the same verdicts. Read by the last test in the walk, which is
#: also the one whose premise is that a single probe served everything before
#: it.
PROBE_CONSTRUCTIONS = 0


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
        global PROBE_CONSTRUCTIONS
        PROBE_CONSTRUCTIONS += 1
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

    Enumeration fails in three shapes, and all three are caught: the floor's
    ``AssertionError``; a ``re.error`` if a router's filter gains a nested
    alternation, since the reconstruction splits on the pipe and would then
    compile unbalanced fragments; and an ``OSError`` if the git listing cannot
    be run. Catching only the first would leave the other two as exactly the
    collection error this degradation exists to avoid.

    Returns:
        The cases, and their pytest ids in the same order.
    """
    cases: list[RouterCase] = []
    ids: list[str] = []
    for router in TEST_ROUTERS:
        try:
            universe = changed_scripts_universe(router)
        except (AssertionError, re.error, OSError) as failure:
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
        assert PROBE_CONSTRUCTIONS == 1, (
            f"{PROBE_CONSTRUCTIONS} routing probes were built this session, not 1; the walk shares one "
            "probe, so any more means it is no longer session-scoped and every case re-routed and "
            "re-collected from an empty cache"
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
