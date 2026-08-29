"""Shared pieces for the ``ci/`` changed-file router tests.

``ci/test_staged.sh`` and ``ci/test_changed.sh`` decide which pytest targets a
diff maps to. The routing decision is what is under test; the container run is
not. The ``route`` fixture in ``tests/ci/conftest.py`` shadows ``git`` (to
inject a synthetic changed-file list) plus ``docker`` and ``task`` (to swallow
the execution stage), and the assertions here read the targets back off the
router's own announcement line.

The security gate is stubbed rather than run: it writes
``tmp/.python-gate-pass``, which in CI is already owned by the outer gate run's
uid, so a nested invocation fails with EACCES and ``set -e`` kills the router
before it announces anything. Its path-containment and tracked-file checks
therefore belong to ``tests/scripts/test_python_security_gate.py``, not here.

The test routers get per-block byte-identity only, with no region-level
delegation comparison of the kind ``helpers.lint_router_harness`` runs over the
lint pair: outside the mirrored branch they legitimately diverge —
``test_changed.sh`` carries a ``docker/agent-cli/`` branch and a host-side
container-integration re-run that ``test_staged.sh`` has no counterpart for —
so an anchored region comparison would report intended divergence as drift.
The one derived comparison that does apply across the pair is over the
``CHANGED_SCRIPTS`` path filters, whose two prefix lists are compared against a
pinned divergence rather than byte-for-byte.

Lives under ``tests/helpers/`` because ``pytest.ini`` sets
``--import-mode=importlib``, which keeps a test's own directory off
``sys.path``; ``pythonpath = tests`` makes this package importable as
``helpers.router_harness``.
"""

import difflib
import os
import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple

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
#: than exercised in place. The two router harnesses and aws_env.py have no test
#: file at all, which is why the branch routes to directories instead of
#: deriving a name; see RouterContract.test_no_helper_filename_derivation.
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

#: The only test under tests/lint/, and the entire enforcement body of
#: ``task lint:reviewer-envelope``. Both routers guard it with ``[ -f ]``, so a
#: rename that misses this constant surfaces as an empty target list rather
#: than as a missing file.
LINT_SUITE_TEST = "tests/lint/test_reviewer_envelope_required.py"

#: A representative sample of the sources that must route to
#: REVIEWER_TEMPLATE_SUITE, not a closed enumeration: the branch matches the
#: reviewer-prompt and diff-review directories wholesale, so unlisted siblings
#: route here too.
REVIEWER_TEMPLATE_SOURCES: tuple[str, ...] = (
    ".claude/prompts/reviewer/diff.md",
    ".claude/prompts/reviewer/_invariants.md",
    ".codex/config.toml",
    ".claude/skills/diff-review/SKILL.md",
    "scripts/lint_reviewer_templates.py",
)

#: A path named in both routers' reviewer-template branch condition that
#: reaches that branch in neither, for two unrelated reasons.
#: ``ci/test_staged.sh`` carries no ``docker/agent-cli/`` prefix in its
#: ``CHANGED_SCRIPTS`` filter, so the path is dropped before the dispatch chain
#: sees it and the router selects nothing at all. ``ci/test_changed.sh`` carries
#: the prefix but places its ``docker/agent-cli/`` branch ahead of the
#: reviewer-template branch, and first match wins, so the path is handled there
#: instead — and neither of the two test names that branch derives from it
#: exists, so no pytest target is announced. Announcing nothing is not the same
#: as doing nothing there: the prefix also matches ``AGENT_CLI_RELEVANT`` after
#: the dispatch loop, which delegates to ``task test:container-integration``
#: outside the announced target list. The reviewer-template invariants are
#: still gated on this path through ``task lint:reviewer-templates``, which both
#: lint routers trigger on it.
INERT_REVIEWER_TEMPLATE_SOURCE = "docker/agent-cli/codex-config.toml"

#: Substring of the line ``ci/test_changed.sh`` prints before delegating to the
#: host-side container-integration re-run. ``ci/test_staged.sh`` has no such
#: stage, so its absence there is as much a pinned outcome as its presence here.
CONTAINER_INTEGRATION_RERUN_MARKER = "running task test:container-integration"

#: The only router carrying the container-integration re-run.
CONTAINER_INTEGRATION_RERUN_ROUTER = "test_changed.sh"

#: The single target every reviewer-template source produces.
REVIEWER_TEMPLATE_SUITE = "tests/scripts/test_reviewer_templates.py"

#: A source whose test target both routers *derive* rather than name: it falls
#: through to the ``scripts/*`` branch, which builds the target out of the
#: changed path's own basename and directory.
DERIVED_TARGET_SOURCE = "scripts/setup_codex_reviewer.sh"

#: The target DERIVED_TARGET_SOURCE derives to. Unlike REVIEWER_TEMPLATE_SUITE
#: this string appears in neither router, so a source-text search for it there
#: finds nothing and would fail; ``tests/scripts/test_setup_codex_reviewer.py``
#: pins the derivation that produces it instead of the name it produces.
DERIVED_TARGET_SUITE = "tests/scripts/test_setup_codex_reviewer.py"

#: The routers that hard-code REVIEWER_TEMPLATE_SUITE as a literal.
TEST_ROUTERS: tuple[str, str] = ("test_staged.sh", "test_changed.sh")

#: Lifts the alternation body out of a router's ``CHANGED_SCRIPTS=`` filter,
#: written as ``CHANGED_SCRIPTS=$(... grep -E "^(<alternation>)" ...)``. The
#: closing ``)"`` is an unambiguous stop: the only nested group either filter
#: contains, ``(\.local)?``, closes onto its quantifier rather than the quote.
CHANGED_SCRIPTS_PATTERN = re.compile(r'^[ \t]*CHANGED_SCRIPTS=.*?-E\s+"\^\((.+?)\)"', re.MULTILINE)

#: Prefixes ``ci/test_changed.sh`` legitimately carries that
#: ``ci/test_staged.sh`` does not. ``docker/agent-cli/`` has a dispatch branch
#: and a host-side container-integration re-run in ``test_changed.sh`` only, so
#: in ``test_staged.sh`` the prefix would admit paths that then match no branch.
KNOWN_ROUTER_DIVERGENCE: frozenset[str] = frozenset({"docker/agent-cli/"})

#: Tracked paths every router's ``CHANGED_SCRIPTS`` universe must contain. Each
#: sits under an alternative written without regex escapes, deliberately: a
#: universe built with ``str.startswith`` over the escaped alternatives still
#: holds them, so this pin fails only when an alternative is *dropped* and the
#: dot-prefixed alternatives are left to the per-alternative coverage check.
#: Adding a ``.claude/`` path here would collapse the two into one check.
#: ``tests/agents/`` and ``tests/scripts/`` are listed because no behavioural
#: assertion below feeds a path under either *into* a router. Each appears
#: below only on the expected-target side of an assertion — ``tests/agents/``
#: as what a changed ``.claude/agents/`` definition routes to,
#: ``tests/scripts/`` as REVIEWER_TEMPLATE_SUITE, DERIVED_TARGET_SUITE, and the
#: name the ``docker/shared/`` case derives — and a target names no prefix the
#: filter has to admit. The sibling test prefixes are not in that position:
#: ``tests/hooks/``, ``tests/helpers/`` and ``tests/lint/`` each have a case
#: routing a file under them to itself. So for these two this pin is the only
#: check that the filter still admits the prefix, and dropping it from both
#: routers leaves a change to a file underneath routing nothing at all — with
#: the prefix-parity check agreeing, because both dropped it. The list is
#: maintained rather than derived: a prefix added to the routers later can sit
#: in the same position and carry nothing here. The ``tests/scripts/`` entry is
#: spelled out rather than reused from REVIEWER_TEMPLATE_SUITE: bound to that
#: constant, a repoint of the suite out of ``tests/scripts/`` would carry the
#: sentinel out of the prefix with it and drop the cover silently.
UNIVERSE_SENTINELS: tuple[str, ...] = (
    "ci/test_staged.sh",
    "ci/test_changed.sh",
    "scripts/setup_codex_reviewer.sh",
    "tests/ci/conftest.py",
    "tests/helpers/router_harness.py",
    "docker/shared/python-security-gate.sh",
    "tests/agents/test_variant_parity.py",
    "tests/scripts/test_reviewer_templates.py",
)

#: A tracked path that *contains* a ``CHANGED_SCRIPTS`` alternative without
#: starting with one. A lower bound is satisfied by an over-matching pattern
#: too, so only a path that must stay *out* of the universe can catch a lost
#: ``^`` anchor or a substring match. It must stay tracked to mean anything —
#: an untracked negative sentinel can never appear, and the check goes vacuous.
UNIVERSE_NEGATIVE_SENTINEL = "workflows/agent-memory/skills/execution-ledger/scripts/todo_cli.py"

#: Opening line of the reviewer-template branch both test routers must carry
#: byte-identically.
REVIEWER_TEMPLATE_BRANCH_MARKER = 'elif [[ "$file" == .claude/prompts/reviewer/* ]]'

#: Opening line of the ``scripts/*`` dispatch branch both test routers must
#: carry byte-identically. Pinned as the whole condition line rather than a
#: prefix of it: ``ci/test_changed.sh`` opens its agent-cli branch with
#: ``elif [[ "$file" == scripts/`` as well, and a marker matching two blocks
#: fails extraction outright instead of comparing either one.
SCRIPTS_BRANCH_MARKER = 'elif [[ "$file" == scripts/* ]] || [[ "$file" == ci/* ]]; then'

#: Opening prefix shared by every branch of the changed-file dispatch chain.
#: Bounding a block slice at the next sibling branch is what keeps it from
#: running on to the enclosing loop's ``fi`` and swallowing the rest of the
#: dispatch chain.
BRANCH_BOUNDARY_MARKERS: tuple[str, ...] = ('elif [[ "$file" == ',)

#: The line that closes a block. How strictly it is matched belongs to the
#: caller, not to this value: ``extract_marked_block`` compares the
#: indentation-stripped line, so a nested ``fi`` matches, while the region scan
#: in ``helpers.lint_router_harness`` compares the raw line, so only a
#: column-zero ``fi`` does.
BLOCK_TERMINATOR = "fi"

ANNOUNCE_PREFIX = "Running pytest (Docker) with "

#: Liveness ceiling on the tracked-file listing. Its callers run it at import
#: time, so a git that never returns wedges collection itself rather than
#: failing a test: there is no case left to report the stall against, and the
#: run reports nothing at all.
TRACKED_PATHS_TIMEOUT_SECONDS = 60

#: Liveness ceiling on one router run. Well above the per-run cost rather than
#: close to it: this is not a performance assertion, it is what stops a router
#: that wedges from stalling the walk that calls it several hundred times.
#: Named rather than written inline at the call, like the listing ceiling
#: above, so the value can be read and cited without opening ``run_router``.
ROUTER_TIMEOUT_SECONDS = 180

#: Container-detection expressions the routing-coverage guard and the fixtures
#: it consumes must not carry. Both routers run their announced targets in
#: ``pytest-cli``, and they reach the guard module on a pull request changing a
#: non-test module under ``tests/helpers/`` or the guard module itself, so a
#: skip keyed on one of these would silence the guard in the containerised
#: channel. The list lives here rather than beside the scan that reads it: a
#: module scanning its own source for a literal it also declares always matches
#: itself — which is also why this module is outside the scan that reads the
#: list; see ``CONTAINER_DETECTION_SCAN_SOURCES`` in the guard.
#: A measured set, not a closed one: these are the expressions this repository's
#: own container detection is written with, and a skip keyed on anything else
#: carries nothing here to match. Known uncovered members: ``/run/.containerenv``,
#: which identifies a Podman container; a predicate on ``CI`` or
#: ``GITHUB_ACTIONS``, which reaches the same skip without naming a container at
#: all; a hostname read compared against a container's; and a read of the
#: process mount table. The paragraph above states the property the list serves,
#: which is not the same as the reach of the list.
CONTAINER_DETECTION_TOKENS: tuple[str, ...] = (
    "/.dockerenv",
    "INSIDE_CONTAINER",
    "/proc/1/cgroup",
    "/proc/self/cgroup",
)

#: Expressions that rebuild a routing target out of a source path. The
#: routing-coverage guard runs the routers instead of re-modelling them, because
#: a reconstructed dispatch chain agrees with a broken router, so its own source
#: must carry none of these. The list lives here for the reason
#: CONTAINER_DETECTION_TOKENS does: a module scanning its own source for a
#: literal it also declares always matches itself. It is deliberately scoped to
#: that one module — RouterContract's negative derivation tests below spell some
#: of these on purpose, to prove the routers do not derive.
#: The ``.replace`` entries stop before their second argument, so a derivation
#: written without the interior space is caught by the same token.
#: Known limits include: a test-path literal used as an expected target, which
#: cannot be tokenised at all, since the guard's outcome pins are required to
#: name ``tests/ci/`` and ``tests/helpers/``; a target rebuilt by f-string or
#: concatenation, which carries no token to match; ``basename`` imported by
#: name and then called bare, which none of the dotted spellings reach; and
#: ``.parent`` or ``.parts``, which are left out because a path split on either
#: of them is not by itself a rebuilt target. The list is a drift guard over one
#: module's source, not a closed enumeration of every way to derive a path.
SOURCE_PATH_DERIVATION_TOKENS: tuple[str, ...] = (
    "os.path.basename",
    "os.path.dirname",
    "os.path.splitext",
    ".stem",
    ".name",
    '.replace("-"',
    ".replace('-'",
)

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

#: Builds a ``RouteFn`` over a fresh workspace whose stub set and security-gate
#: shadow the caller chooses.
RouteVariantFn = Callable[..., RouteFn]

#: Executables a router workspace shadows on PATH, and the stub body each gets.
#: ``task`` is stubbed alongside ``docker`` so a changed-file list reaching the
#: agent-cli branch of ``ci/test_changed.sh`` cannot launch the real
#: container-integration suite from a unit test.
ROUTER_PATH_STUBS: tuple[tuple[str, str], ...] = (
    ("git", GIT_STUB),
    ("docker", NOOP_STUB),
    ("task", NOOP_STUB),
)


class RouterWorkspace(NamedTuple):
    """A synthetic workspace and stub PATH, ready to run a router against."""

    #: Working directory the router runs from.
    workspace: Path
    #: Directory prepended to PATH, holding the executable stubs.
    bin_dir: Path
    #: File each run rewrites with its changed-file list.
    listing: Path
    #: Value pinned into ``GITHUB_EVENT_NAME`` on every run.
    event_name: str


def build_router_workspace(
    root: Path,
    event_name: str,
    *,
    stubs: Sequence[tuple[str, str]] = ROUTER_PATH_STUBS,
    shadow_security_gate: bool = True,
) -> RouterWorkspace:
    """
    Lay out a synthetic workspace a test router can be run against.

    The routers invoke the security gate by a path relative to the working
    directory, so shadowing it means placing a stub at that relative path.
    Shadowing is the normal case: the real gate writes
    ``tmp/.python-gate-pass``, which in CI is already owned by the outer gate
    run's uid, so a nested invocation fails with EACCES and ``set -e`` kills the
    router before it announces anything. Withholding the shadow reproduces that
    death on demand, which is how a caller can tell a router that *failed* apart
    from one that deliberately selected nothing — but only for a changed-file
    list that reaches ``run_pytest_docker``, since both routers return early on
    an empty target list and never touch the gate.

    ``tests/`` is symlinked in rather than copied, so the routers' ``[ -f ]``
    probes see the repository's real test files.

    Args:
        root: Directory to build under.
        event_name: Value to pin into ``GITHUB_EVENT_NAME`` on every run.
        stubs: ``(executable name, script body)`` pairs to shadow on PATH.
        shadow_security_gate: Whether to place the security-gate stub.

    Returns:
        The workspace, its stub bin directory, the changed-file listing path,
        and the pinned event name.
    """
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    for name, body in stubs:
        stub = bin_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)

    workspace = root / "workspace"
    (workspace / "docker" / "shared").mkdir(parents=True)
    if shadow_security_gate:
        gate = workspace / "docker" / "shared" / "python-security-gate.sh"
        gate.write_text(NOOP_STUB, encoding="utf-8")
        gate.chmod(0o755)
    (workspace / "tmp").mkdir()
    (workspace / "tests").symlink_to(REPO_ROOT / "tests")

    return RouterWorkspace(
        workspace=workspace,
        bin_dir=bin_dir,
        listing=root / "changed-files.txt",
        event_name=event_name,
    )


def run_router(
    space: RouterWorkspace,
    script: str,
    changed_files: Sequence[str],
    *,
    target: str = "scripts",
) -> subprocess.CompletedProcess[str]:
    """
    Run a router script in a prepared workspace against a changed-file list.

    The listing is rewritten in full on every call, so no earlier call's paths
    survive into a later one. That is what makes one workspace safe to reuse for
    a whole session rather than rebuilding it per test.

    The exit status is returned rather than checked: the caller decides whether
    a non-zero router is a failure or the outcome under test.

    Args:
        space: Prepared workspace to run in.
        script: Router filename under ``ci/``.
        changed_files: Paths the stubbed ``git`` reports as changed.
        target: Router target argument.

    Returns:
        The completed router process.
    """
    space.listing.write_text("".join(f"{path}\n" for path in changed_files), encoding="utf-8")

    env = os.environ.copy()
    env["PATH"] = f"{space.bin_dir}{os.pathsep}{env['PATH']}"
    env["ROUTER_TEST_CHANGED_FILES"] = str(space.listing)
    env["GITHUB_EVENT_NAME"] = space.event_name

    return subprocess.run(
        ["bash", str(REPO_ROOT / "ci" / script), target],
        cwd=space.workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=ROUTER_TIMEOUT_SECONDS,
    )


def make_route(space: RouterWorkspace) -> RouteFn:
    """
    Bind a workspace into a ``RouteFn``, so callers pass only script and paths.

    The closure lives here rather than in the fixture that returns it because
    only this module resolves under mypy: ``tests/`` is not a package base, so
    an importer of ``helpers.router_harness`` sees every name as ``Any`` and a
    call to ``run_router`` there checks nothing.

    Args:
        space: Prepared workspace every routed call runs in.

    Returns:
        Callable taking the script filename under ``ci/`` and the changed-file
        list, plus an optional keyword-only ``target``.
    """

    def _route(
        script: str,
        changed_files: Sequence[str],
        *,
        target: str = "scripts",
    ) -> subprocess.CompletedProcess[str]:
        return run_router(space, script, changed_files, target=target)

    return _route


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

    stderr is included because under ``set -e`` a router that dies early prints
    nothing to stdout.

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
    could announce anything" — both produce an empty target list.

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
    prevent.

    ``tests/scripts/test_reviewer_templates.py`` inlines the same assertion
    rather than importing it, for routing reasons: the helper fan-out in both
    routers sends a changed module under ``tests/helpers/`` to
    ``tests/helpers/`` and ``tests/ci/`` only, so an import from
    ``tests/scripts/`` would be a dependency no router covers. Do not merge the
    two copies.
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


def changed_scripts_prefixes(script: str) -> frozenset[str]:
    """
    Read the path prefixes a test router's ``CHANGED_SCRIPTS`` filter admits.

    Args:
        script: Router filename under ``ci/``.

    Returns:
        One entry per alternative of the filter, exactly as written — regex
        escaping included, since the result is only ever compared against the
        other router's.
    """
    source = (REPO_ROOT / "ci" / script).read_text(encoding="utf-8")
    alternations = CHANGED_SCRIPTS_PATTERN.findall(source)
    assert len(alternations) == 1, (
        f"ci/{script}: found {len(alternations)} CHANGED_SCRIPTS filters, expected exactly 1 — "
        'this guard reads the line shape `CHANGED_SCRIPTS=$(... grep -E "^(<alternation>)" ...)`'
    )
    return frozenset(alternations[0].split("|"))


def assert_changed_scripts_prefixes_agree() -> None:
    """
    Assert the two test routers admit the same path prefixes, bar a pinned divergence.

    The filter decides whether a changed path reaches the dispatch chain at
    all, and it is hand-maintained in both files. A prefix *dropped* from one
    router fails the behavioural assertions, which enumerate paths that must
    route; a prefix *added* to one router only passes every one of them,
    because an enumeration cannot list a prefix that does not exist yet.
    Byte-identity cannot close that direction here — the two filters differ by
    design — so the prefix sets are compared instead.

    Splitting the alternation on ``|`` would mis-split a nested alternation
    such as ``(a|b)``. Both routers would split it the same way, so the
    comparison stays sound; only the rendered failure message would read
    oddly.
    """
    staged_script, changed_script = TEST_ROUTERS
    staged = changed_scripts_prefixes(staged_script)
    changed = changed_scripts_prefixes(changed_script)
    surplus = changed - staged
    missing = staged - changed
    assert surplus == KNOWN_ROUTER_DIVERGENCE and not missing, (
        "the CHANGED_SCRIPTS prefix filters of the two test routers disagree\n"
        f"in ci/{changed_script} only: {sorted(surplus)} (pinned: {sorted(KNOWN_ROUTER_DIVERGENCE)})\n"
        f"in ci/{staged_script} only: {sorted(missing)} (pinned: none)\n"
        "add the prefix to both routers, or pin the divergence in KNOWN_ROUTER_DIVERGENCE"
    )


def split_nul_records(payload: str) -> tuple[str, ...]:
    """
    Split a NUL-delimited git payload into records.

    ``git ls-files -z`` *terminates* every record rather than separating them,
    so the split leaves a trailing empty fragment; discarding empties keeps a
    zero-length path out of the universe. NUL delimiting is also what holds a
    path containing a space or a newline together, which line splitting would
    not.

    Args:
        payload: Raw NUL-delimited stdout.

    Returns:
        One entry per record, empty fragments discarded.
    """
    return tuple(record for record in payload.split("\0") if record)


def tracked_paths() -> tuple[str, ...]:
    """
    Enumerate every path git tracks in this repository.

    Shells out on each call, so a caller that needs the listing more than once
    should hold the result rather than re-enumerate per case.

    ``safe.directory`` is set for the directory being listed, and derived from
    the same constant the call runs in so the two cannot drift. Both routers fan
    a changed module under ``tests/helpers/`` into ``tests/ci/``, which runs in
    ``pytest-cli`` as ``--user agent`` against a read-only bind mount of the
    repository.

    The failure this guards against is reasoned rather than observed: ``agent``
    is a system account the image creates with ``useradd -r``, so nothing ties
    its uid to the uid owning the mounted tree on a Linux runner, and git's
    ownership check refuses to read a repository owned by another user — exit
    128 before a single path is listed, taking every caller of this function
    with it. It has not been reproduced here, and has never run on a Linux
    runner: Docker Desktop remaps bind-mount ownership, so on this host the
    mounted tree already reports the container uid as its owner and the check
    passes whatever the image does. What is confirmed is that the option is
    accepted where it is set — ``git help config`` §SCOPES counts ``-c`` as
    protected command scope, which is the scope ``safe.directory`` requires.
    Where the uid already matches, the option changes nothing.

    Returns:
        Repository-relative tracked paths, in ``git ls-files`` order.

    Raises:
        AssertionError: If git exits non-zero, or reports nothing at all. A
            partial listing is the dangerous case — it shrinks the universe
            silently, and every downstream comparison then passes on a subset.
        subprocess.TimeoutExpired: If git has not returned within
            ``TRACKED_PATHS_TIMEOUT_SECONDS``.
    """
    result = subprocess.run(
        ["git", "-c", f"safe.directory={REPO_ROOT}", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        check=False,
        timeout=TRACKED_PATHS_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, (
        f"`git ls-files -z` failed in {REPO_ROOT} with exit {result.returncode}; whatever "
        f"reached stdout is a partial listing and is not usable\n{result.stderr}"
    )
    paths = split_nul_records(result.stdout)
    assert paths, f"`git ls-files -z` reported no tracked files in {REPO_ROOT}"
    return paths


def changed_scripts_universe(script: str) -> tuple[str, ...]:
    """
    Enumerate the tracked paths a test router's ``CHANGED_SCRIPTS`` filter admits.

    The filter is reconstructed from the router's own source rather than
    restated here, so the universe follows a prefix added to or dropped from
    the router with no list to maintain. ``changed_scripts_prefixes`` returns
    its alternatives regex-escaped, so the reconstruction has to stay a regex
    *and* has to stay anchored: a ``str.startswith`` equivalent drops every
    dot-prefixed alternative, and an unanchored match admits any path that
    merely contains one.

    The floor below is asserted here rather than in a test of its own, so it
    runs on every call — a caller that never happens to run that test would
    otherwise consume a silently narrowed universe.

    Args:
        script: Router filename under ``ci/``.

    Returns:
        Tracked repository-relative paths the filter admits, in
        ``git ls-files`` order.

    Raises:
        AssertionError: If the universe is empty, omits a pinned sentinel,
            leaves an alternative with no member, or if the negative sentinel
            has stopped being tracked or has entered the universe.
            Also if ``UNIVERSE_SENTINELS`` is itself empty, which would leave
            the floor asserting nothing about the universe it admits.
    """
    alternatives = changed_scripts_prefixes(script)
    pattern = re.compile("^(" + "|".join(sorted(alternatives)) + ")")
    tracked = tracked_paths()
    universe = tuple(path for path in tracked if pattern.search(path))

    assert universe, (
        f"ci/{script}: the reconstructed CHANGED_SCRIPTS filter {pattern.pattern!r} admitted none of the {len(tracked)} tracked paths"
    )
    assert UNIVERSE_SENTINELS, "the pinned sentinel list is empty, which leaves the universe floor vacuous"
    absent = [sentinel for sentinel in UNIVERSE_SENTINELS if sentinel not in universe]
    assert not absent, (
        f"ci/{script}: pinned universe sentinels are missing: {absent} — either the router dropped "
        "a CHANGED_SCRIPTS prefix, or those paths moved and UNIVERSE_SENTINELS needs repointing"
    )
    uncovered: list[str] = []
    for alternative in sorted(alternatives):
        admits = re.compile("^(" + alternative + ")")
        if not any(admits.search(path) for path in universe):
            uncovered.append(alternative)
    assert not uncovered, (
        f"ci/{script}: CHANGED_SCRIPTS alternatives with no tracked member: {uncovered} — an "
        "alternative that matches nothing means the reconstruction stopped being a regex, or the "
        "prefix is dead and belongs out of the router"
    )
    assert UNIVERSE_NEGATIVE_SENTINEL in tracked, (
        f"{UNIVERSE_NEGATIVE_SENTINEL} is no longer tracked, which leaves the over-match check "
        "below vacuous — repoint UNIVERSE_NEGATIVE_SENTINEL at another tracked path that contains "
        "a CHANGED_SCRIPTS alternative without starting with one"
    )
    assert UNIVERSE_NEGATIVE_SENTINEL not in universe, (
        f"ci/{script}: {pattern.pattern!r} admitted {UNIVERSE_NEGATIVE_SENTINEL}, which only "
        "contains an alternative rather than starting with one — the pattern lost its `^` anchor, "
        "or it is being applied in a way that ignores the anchor, so the universe over-matches"
    )
    return universe


def extract_marked_block(
    script: str,
    marker: str,
    *,
    boundaries: Sequence[str],
) -> str:
    """
    Slice a marked block out of a router script, line endings preserved.

    A marker seen more or fewer than once fails here instead of silently
    slicing the wrong region.

    The block ends at the *last* ``BLOCK_TERMINATOR`` inside the window running
    from the marker to the next sibling boundary, not the first: stopping at
    the first truncates any block holding more than one top-level statement,
    leaving the un-compared tail free to diverge while the assertion still
    passes. Over-slicing fails loudly instead, which is the safe direction for
    a parity guard.

    Args:
        script: Router filename under ``ci/``.
        marker: Opening line of the block, matched as a prefix of the
            indentation-stripped line.
        boundaries: Opening-line prefixes of the sibling blocks that bound the
            search window.

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
    ends = [index for index in range(start, window_end) if lines[index].strip() == BLOCK_TERMINATOR]
    assert ends, f"ci/{script}: no closing {BLOCK_TERMINATOR!r} between marker {marker!r} and the next block boundary"
    return "".join(lines[start : ends[-1] + 1])


def assert_block_mirrored(
    marker: str,
    *,
    routers: tuple[str, str],
    boundaries: Sequence[str],
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
    """
    left, right = routers
    left_block = extract_marked_block(left, marker, boundaries=boundaries)
    right_block = extract_marked_block(right, marker, boundaries=boundaries)
    # Rendered eagerly so the message names *what* diverged — indentation and
    # trailing whitespace included.
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
    tests exist to catch is drift between the two files.

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

    def test_lint_suite_test_file_routes_directly(self, route: RouteFn) -> None:
        """A changed test under tests/lint/ is added as itself.

        tests/lint/ is the whole enforcement body of
        ``task lint:reviewer-envelope``, and no other branch reaches it: no
        source directory fans out to it and no derivation rule produces its
        name, so un-routing leaves it running only in a full
        ``task test:scripts``.
        """
        result = route(self.SCRIPT, [LINT_SUITE_TEST])
        assert routed_targets(result) == [LINT_SUITE_TEST], diagnose(result)

    def test_lint_suite_test_file_alone_is_not_reported_as_untestable(self, route: RouteFn) -> None:
        """Guards the silent-zero outcome for a lone test under tests/lint/.

        Separates the two ways the routing is lost, which the assertion above
        cannot tell apart: dropping ``tests/lint/`` from the ``CHANGED_SCRIPTS``
        grep filters the path out before any branch sees it and prints "No
        scripts or script tests changed.", while dropping it from the branch
        condition lets the path through to a dispatch chain that matches
        nothing and prints "No testable scripts found."
        """
        result = route(self.SCRIPT, [LINT_SUITE_TEST])
        assert "No scripts or script tests changed." not in result.stdout, diagnose(result)
        assert "No testable scripts found." not in result.stdout, diagnose(result)

    @pytest.mark.parametrize("source", REVIEWER_TEMPLATE_SOURCES)
    def test_reviewer_template_source_routes_to_parity_test(self, route: RouteFn, source: str) -> None:
        """Each mirrored rubric half, and the checker itself, routes to the parity test."""
        result = route(self.SCRIPT, [source])
        assert routed_targets(result) == [REVIEWER_TEMPLATE_SUITE], f"{source}\n{diagnose(result)}"

    def test_inert_reviewer_template_source_selects_no_pytest_target(self, route: RouteFn) -> None:
        """The agent-cli codex config announces no pytest target in either router.

        Pins the outcome, not an intent: both routers name this path in their
        reviewer-template branch condition, and in both it is unreachable — see
        ``INERT_REVIEWER_TEMPLATE_SOURCE`` for the two mechanisms. Asserting it
        keeps the branch condition from reading as coverage that exists.

        The empty target list is only half the outcome, and the half the
        announcement line can show: in ``ci/test_changed.sh`` the path also
        triggers the host-side container-integration re-run, which delegates to
        ``task`` rather than to pytest. That leg is asserted off the router's
        own stdout, in both directions, so the path cannot quietly gain or lose
        it in either router.
        """
        result = route(self.SCRIPT, [INERT_REVIEWER_TEMPLATE_SOURCE])
        assert_routed_nothing(result)
        rerun_announced = CONTAINER_INTEGRATION_RERUN_MARKER in result.stdout
        rerun_expected = self.SCRIPT == CONTAINER_INTEGRATION_RERUN_ROUTER
        assert rerun_announced == rerun_expected, (
            f"ci/{self.SCRIPT}: container-integration re-run announced={rerun_announced}, expected={rerun_expected}\n{diagnose(result)}"
        )

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
        """Neither silent-zero message is printed for a lone reviewer-template source."""
        result = route(self.SCRIPT, [source])
        assert "No scripts or script tests changed." not in result.stdout, f"{source}\n{diagnose(result)}"
        assert "No testable scripts found." not in result.stdout, f"{source}\n{diagnose(result)}"

    def test_derived_target_source_routes_to_its_derived_suite(self, route: RouteFn) -> None:
        """A script routed by derivation reaches the suite the derivation names.

        The ``scripts/*`` branch guards its derived name with
        ``[ -f "$test_file" ]``, so a name that resolves to nothing is not an
        error anywhere downstream: the router appends no target, announces
        none, and exits 0 — and a no-tests-collected pytest exit is treated as
        success too.
        """
        result = route(self.SCRIPT, [DERIVED_TARGET_SOURCE])
        assert result.returncode == 0, f"ci/{self.SCRIPT} failed on {DERIVED_TARGET_SOURCE}\n{diagnose(result)}"
        assert routed_targets(result) == [DERIVED_TARGET_SUITE], (
            f"ci/{self.SCRIPT} no longer routes {DERIVED_TARGET_SOURCE} to {DERIVED_TARGET_SUITE} — restore the "
            "`scripts/*` branch's derivation of `tests/${dirname}/test_${basename}.py`, or point "
            f"DERIVED_TARGET_SUITE at wherever the suite now lives\n{diagnose(result)}"
        )

    def test_derived_target_source_alone_is_not_reported_as_untestable(self, route: RouteFn) -> None:
        """Neither silent-zero message is printed for a lone derivation-routed script.

        The two messages separate the two ways the routing is lost: dropping
        ``scripts/`` from the ``CHANGED_SCRIPTS`` filter drops the path before
        any branch sees it, while dropping the branch itself lets the path
        through to a dispatch chain that matches nothing. The ``is_file()``
        check names the third — a suite renamed or deleted out from under the
        derivation, which the ``[ -f ]`` guard turns into a zero exit.
        """
        result = route(self.SCRIPT, [DERIVED_TARGET_SOURCE])
        assert "No scripts or script tests changed." not in result.stdout, (
            f"ci/{self.SCRIPT} filtered {DERIVED_TARGET_SOURCE} out before any branch saw it — restore the "
            f"`scripts/` prefix in the CHANGED_SCRIPTS grep\n{diagnose(result)}"
        )
        assert "No testable scripts found." not in result.stdout, (
            f"ci/{self.SCRIPT} let {DERIVED_TARGET_SOURCE} reach the dispatch chain and matched no branch — restore "
            f"the `scripts/*` branch\n{diagnose(result)}"
        )
        assert (REPO_ROOT / DERIVED_TARGET_SUITE).is_file(), (
            f"{DERIVED_TARGET_SUITE} is missing; the `scripts/*` branch of both routers guards its derived name "
            f"with `[ -f ]`, so {DERIVED_TARGET_SOURCE} would route nothing and the router would still exit 0 — "
            "restore the suite at the derived path, or rename it and point DERIVED_TARGET_SUITE at the new one"
        )

    def test_reviewer_template_suite_path_is_pinned(self) -> None:
        """Both routers name the reviewer-template suite, and it exists on disk.

        Ignores ``SCRIPT`` and reads both routers, so it is redundant across
        the two subclasses by construction. Each router routes only to its own
        test file, so a cross-file invariant asserted in one subclass would not
        run when the other router is edited.
        """
        assert_reviewer_template_suite_pinned()

    def test_reviewer_template_branch_is_byte_identical(self) -> None:
        """Both routers carry the reviewer-template branch byte-identically.

        The behavioural assertions above enumerate ``REVIEWER_TEMPLATE_SOURCES``
        and so catch a trigger *dropped* from one router; a trigger *added* to
        one router only passes all of them, because an enumeration cannot list
        a trigger that does not exist yet. Comparing the branch text closes
        that direction without any list to maintain.

        Ignores ``SCRIPT`` and reads both routers, for the same reason as
        ``test_reviewer_template_suite_path_is_pinned``.
        """
        assert_block_mirrored(
            REVIEWER_TEMPLATE_BRANCH_MARKER,
            routers=TEST_ROUTERS,
            boundaries=BRANCH_BOUNDARY_MARKERS,
        )

    def test_scripts_branch_is_byte_identical(self) -> None:
        """Both routers carry the ``scripts/*`` dispatch branch byte-identically.

        ``test_derived_target_source_routes_to_its_derived_suite`` drives the
        branch through one source, which catches a trigger *dropped* from a
        router; comparing the branch text closes the other direction, where a
        trigger is added to one router only.

        What byte-identity here does **not** pin is routing parity for
        ``scripts/agent-cli/``. ``ci/test_changed.sh`` matches those paths in an
        earlier branch, so they never reach this block at all, and the two
        routers genuinely resolve them to different targets while this block
        stays identical. Closing that gap is tracked separately.

        Ignores ``SCRIPT`` and reads both routers, for the same reason as
        ``test_reviewer_template_suite_path_is_pinned``.
        """
        assert_block_mirrored(
            SCRIPTS_BRANCH_MARKER,
            routers=TEST_ROUTERS,
            boundaries=BRANCH_BOUNDARY_MARKERS,
        )

    def test_changed_scripts_prefix_filters_agree(self) -> None:
        """Both routers admit the same path prefixes, bar the pinned divergence.

        The byte-identity check above covers one branch of the dispatch chain;
        this covers the filter that gates entry to the chain, which is not
        byte-comparable. See ``assert_changed_scripts_prefixes_agree``.

        Ignores ``SCRIPT`` and reads both routers, for the same reason as
        ``test_reviewer_template_suite_path_is_pinned``.
        """
        assert_changed_scripts_prefixes_agree()
