"""Tests for ``scripts/agent-cli/gemini-review.sh`` (TODO-0092 Phase A contract).

Covers the EFFORT/model composition and error-handling behaviors that remain
after the wrapper contract migrated from caller-supplied prompt files to
``REVIEW_TYPE=<enum>`` + ``DIFF_FILE=<tmp-or-agent-review-path>``:

- Req-005: EFFORT alias composition (Pro + Flash tiers + fallback rewrite).
- Req-005: EFFORT enum strictness — ``low`` and ``minimal`` are rejected.
- Req-005: MEDIUM effort -> HIGH internal thinking; xhigh/max collapse to HIGH.
- Req-019: Pro-tier 429/503 -> flash-high single-shot retry.
- New contract: REVIEW_TYPE / DIFF_FILE argument validation.
- Auth-failure cache invalidation and missing-binary handling.

Every wrapper run is spawned from a throwaway root under the test's
``tmp_path``. The wrapper resolves its exit signal, review output and default
preflight cache against the CWD, and ``_review-common.sh`` resolves the
sanitized subject against the git toplevel it discovers from that CWD — so a
spawn inheriting the pytest process CWD writes the artifacts a live review
uses. The autouse ``_no_live_checkout_artifacts`` fixture watches those paths
in the real checkout, so an escape is reported on the test that caused it.

Two kinds of root exist because ``_review-common.sh`` branches on ``git
rev-parse --show-toplevel``: ``_anchored_root`` IS its own git toplevel and
drives the absolute-path branch, ``_unanchored_root`` has no ``.git`` ancestor
and drives the CWD-relative branch. ``_run_review`` requires every root to
resolve strictly inside the test's own ``tmp_path`` and puts it through
``_verify_partition`` before spawning the wrapper.

Both kinds therefore require a ``git`` binary on the closed ``PATH`` these
tests build — ``docker/pytest-cli/Dockerfile`` apt-installs one at
``/usr/bin/git``. ``_verify_partition`` settles both branches by running
``git rev-parse`` under that same ``PATH``, and raises rather than letting a
run drop onto the branch it did not declare.

Tests install a PATH-prepended fake ``gemini`` shim that logs argv and
stdin for each invocation. ``DIFF_FILE``-level path-containment tests live
in ``tests/scripts/test_wrapper_sanitation.py`` and are not duplicated
here.
"""

from __future__ import annotations

import inspect
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple, TypedDict

import pytest
from helpers.wrapper_sources import wrapper_tmp_paths

WORKSPACE: Path = Path(__file__).resolve().parents[2]
REVIEW_SCRIPT: str = str(WORKSPACE / "scripts" / "agent-cli" / "gemini-review.sh")
# Sourced by the wrapper; it owns the sanitized-subject and template paths.
REVIEW_COMMON: Path = WORKSPACE / "scripts" / "agent-cli" / "_review-common.sh"
# Canonical reviewer templates. Read-only: each scratch root gets its own copy
# so ``_review_template_path`` resolves, and the wrapper only concatenates the
# template it finds there.
REAL_TEMPLATES_DIR: Path = WORKSPACE / ".claude" / "prompts" / "reviewer"

# Standard diff-subject filenames used across tests. The wrapper's
# _review_validate_diff_file helper only accepts files realpath-contained
# under the run's own ``tmp/`` or ``agent-review/`` directories, so each
# subject lives in the scratch root the run works from. It imposes no
# basename constraint, so these names are test-owned.
SUBJECT_ARTIFACT: str = "gemini-test-subject.txt"
EMPTY_SUBJECT_ARTIFACT: str = "empty-subject-for-gemini-test.txt"
_SUBJECT_TEXT: str = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@\n-a\n+b\n"

# The live-checkout paths a root escaping ``tmp_path`` would land in, as globs
# relative to ``WORKSPACE``. ``_no_live_checkout_artifacts`` watches them.
#
# The dotted pattern is separate because a leading dot is not matched by the
# undotted one, and the single live-checkout path the wrapper DELETES — the
# preflight cache at ``gemini-review.sh``:348 — carries one. That line's
# ``PREFLIGHT_CACHE_FILE`` override can name any path at all and is therefore
# outside the watch set by construction; the two tests that set it point it into
# their own ``tmp_path``, so what is watched is the default the rest of the
# module leaves in place.
# ``agent-review/`` is watched unfiltered even though a pattern would bound it:
# the container branch builds both of its names around the hardcoded
# ``-gemini-review-`` literal at ``gemini-review.sh``:134-135, with only the
# ``${WORKSPACE}`` prefix and the ``${REVIEW_SESSION_ID}`` suffix supplied by the
# caller. The breadth is chosen so the guard also reports a name no pattern
# derived from THIS wrapper would predict; the cost is a false positive from a
# concurrent operator or sibling-bridge write, which the fixture's message
# already declines to attribute. The pattern is non-recursive, so the wrapper's
# own ``mkdir -p`` creating an empty ``agent-review/`` contributes no entry.
# The empty subject is test-owned rather than wrapper-written and shares a
# prefix with neither ``gemini-`` pattern, so it is named outright.
_LIVE_ARTIFACT_GLOBS: tuple[str, ...] = (
    "tmp/gemini-*",
    "tmp/.gemini-*",
    f"tmp/{EMPTY_SUBJECT_ARTIFACT}",
    "agent-review/*",
)

# The round ``_default_env`` binds. Every run that does not override it on argv
# executes there, so assertions can name tmp/gemini-review-output-<ROUND>.md and
# observe the resolved round end to end rather than restating the env entry that
# set it; the two ``--round`` tests pass a value that wins over it and assert on
# the rejection instead. The value itself carries no meaning — it is pinned only
# to be distinct from the wrapper's own default.
_ROUND: str = "999"


@pytest.fixture(autouse=True)
def _no_live_checkout_artifacts() -> Iterator[None]:
    """Fail the test across which a watched live-checkout artifact changed.

    Every root this module spawns the wrapper from resolves inside the test's
    own ``tmp_path``, so nothing here may write where a real review's artifacts
    live. A regression that lets one escape otherwise surfaces as an unrelated
    assertion failure — or as no failure at all, having merely corrupted a
    developer's review output.

    What the comparison establishes is that the artifacts changed, not why: a
    review running against this checkout at the same time produces the same
    report, and the message says so rather than naming the run as the cause.
    """
    before = _live_artifact_snapshot()
    yield
    after = _live_artifact_snapshot()
    assert after == before, (
        f"watched artifacts under {WORKSPACE} differ across this test: {sorted(set(after.items()) ^ set(before.items()))}. "
        "A scratch root that escaped tmp_path is what this guard exists for; a review running against this checkout "
        "concurrently reports identically."
    )


def _live_artifact_snapshot() -> dict[str, tuple[int, int]]:
    """Map each watched live-checkout path to the size and mtime that identify it.

    Returns:
        Keys are POSIX paths relative to ``WORKSPACE``, so a ``tmp/`` entry and
        an ``agent-review/`` entry sharing a basename stay distinct. Empty when
        the checkout has neither directory — a fresh clone is the state with
        nothing to protect, not an error.

    Size accompanies the mtime because a rewrite landing inside one mtime tick
    is otherwise indistinguishable from no write at all. A same-tick rewrite
    that also preserves the length still reads as unchanged; that residue is
    left open rather than closed by hashing every artifact on every test.

    An entry that vanishes between the glob and the ``stat`` is recorded as
    absent instead of raising: a concurrent delete is one of the differences
    this snapshot exists to report, and letting ``FileNotFoundError`` out of a
    teardown would replace the named assertion with a fixture error.
    """
    snapshot: dict[str, tuple[int, int]] = {}
    for pattern in _LIVE_ARTIFACT_GLOBS:
        for entry in WORKSPACE.glob(pattern):
            try:
                info = entry.stat()
            except FileNotFoundError:
                continue
            snapshot[entry.relative_to(WORKSPACE).as_posix()] = (info.st_size, info.st_mtime_ns)
    return snapshot


_SHIM_HELPER: str = """import json
import sys

log_path = sys.argv[1]
argv = sys.argv[2:]
try:
    if not sys.stdin.isatty():
        stdin_content = sys.stdin.read()
    else:
        stdin_content = ""
except (OSError, ValueError):
    stdin_content = ""
record = {"argv": argv, "stdin": stdin_content}
with open(log_path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(record) + "\\n")
"""


def _install_shim(
    tmp_path: Path,
    *,
    exit_code: int = 0,
    stderr_text: str = "",
    log_path: Path | None = None,
) -> Path:
    """Install a fake ``gemini`` shim at ``tmp_path/bin/gemini``.

    Delegates JSON-lines logging to a sibling python helper. Writes one
    record per invocation capturing argv and stdin, then exits ``exit_code``
    after optionally emitting ``stderr_text`` on stderr.

    Two mechanisms keep Python values out of the generated shell *syntax*.
    Paths and ``stderr_text`` pass through ``shlex.quote``, so a quote,
    backtick or ``$(...)`` in one of them is carried rather than parsed.
    ``exit_code`` is not quoted at all: ``:d`` renders the annotated ``int`` and
    raises ``ValueError`` on the ``str`` an untyped call site would hand it, so a
    value carrying shell syntax is refused while the body is being built rather
    than interpolated into it. The refusal runs through the value's own
    ``__format__``, so it binds the types callers actually pass rather than every
    type an ``int`` annotation admits.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    helper_path = bin_dir / "_shim_helper.py"
    helper_path.write_text(_SHIM_HELPER)
    log_file = log_path if log_path is not None else (tmp_path / "gemini-calls.log")
    stderr_line = ""
    if stderr_text:
        stderr_line = f"printf '%s\\n' {shlex.quote(stderr_text)} >&2\n"
    shim_body = (
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'python3 {shlex.quote(str(helper_path))} {shlex.quote(str(log_file))} "$@"\n'
        f"{stderr_line}exit {exit_code:d}\n"
    )
    shim = bin_dir / "gemini"
    shim.write_text(shim_body)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


class ShimRecord(TypedDict):
    """One fake-``gemini`` invocation as ``_SHIM_HELPER`` records it."""

    argv: list[str]
    stdin: str


def _read_shim_log(log_path: Path) -> list[ShimRecord]:
    """Parse the shim's JSON-lines log."""
    if not log_path.exists():
        return []
    records: list[ShimRecord] = []
    for line in log_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        records.append(json.loads(stripped))
    return records


class ScratchRoot(NamedTuple):
    """A throwaway workspace root plus the ``_review-common.sh`` branch it selects.

    ``_review_sanitize_subject`` and ``_review_template_path`` both branch on
    ``git rev-parse --show-toplevel``: inside a worktree they emit ABSOLUTE
    paths under the toplevel, and the former additionally cds there to write;
    outside one they emit CWD-RELATIVE paths. A root declares which branch it
    selects and ``_verify_partition`` holds it to that declaration. For a root
    whose CWD already IS its toplevel the two branches name the same file, so
    landing on the wrong one there costs the coverage without costing an
    assertion.
    """

    path: Path
    anchored: bool


def _anchored_root(tmp_path: Path) -> ScratchRoot:
    """Return a scratch root that is a git toplevel in its own right.

    Returns:
        The root to spawn the wrapper from, seeded with ``tmp/<subject>`` and
        the reviewer templates.
    """
    root = _provision_root(tmp_path, "anchored_ws")
    _write_git_skeleton(root)
    return ScratchRoot(root, anchored=True)


def _unanchored_root(tmp_path: Path) -> ScratchRoot:
    """Return a scratch root with no ``.git`` at or above it.

    Returns:
        The root to spawn the wrapper from, seeded with ``tmp/<subject>`` and
        the reviewer templates. ``agent-review/`` is deliberately not seeded: no
        test here needs it, and
        ``TestOutputRouting.test_container_context_writes_to_agent_review`` reads
        its existence as evidence of the wrapper's own ``mkdir -p`` at
        ``gemini-review.sh``:142.
    """
    return ScratchRoot(_provision_root(tmp_path, "unanchored_ws"), anchored=False)


def _provision_root(parent: Path, name: str) -> Path:
    """Create a scratch root carrying the file structure gemini-review.sh needs.

    Args:
        parent: directory to create the root under — the test's own ``tmp_path``
            for every root the wrapper is actually run from.
        name: leaf directory name. ``parent`` and ``name`` together address the
            root, so two calls sharing both address the same one — which is
            what ``_uncontained_root``, whose parent is the basetemp every test
            in the session shares, has to keep apart.

    Returns:
        The created root.

    The root is a child of ``parent`` rather than ``parent`` itself so the mock
    bin dir, the scratch ``HOME`` and the explicitly-passed cache files — all of
    which sit directly under the test's ``tmp_path`` — stay outside the tree a
    wrapper can reach through a CWD-relative write.
    """
    root = parent / name
    (root / "tmp").mkdir(parents=True, exist_ok=True)
    (root / "tmp" / SUBJECT_ARTIFACT).write_text(_SUBJECT_TEXT)
    _copy_reviewer_templates(root)
    return root


def _copy_reviewer_templates(root: Path) -> None:
    """Copy the canonical reviewer templates into a scratch root.

    Raises:
        RuntimeError: ``REAL_TEMPLATES_DIR`` is not a directory. ``copytree``
            would fail on that too, but as an errno several frames inside
            ``shutil``; naming the missing repository invariant at the
            provisioning site is what makes the failure legible.

    ``_review_template_path`` yields ``.claude/prompts/reviewer/<type>.md``
    under the run's toplevel or CWD, so the root has to resolve that path. The
    copy is taken from the canonical source, so a scratch root carries the
    templates a live review would load.

    ``copytree`` refuses a destination that already exists, so the early return
    is what makes a repeat call for an already-provisioned root a no-op rather
    than a ``FileExistsError``. That is reachable because ``_uncontained_root``
    provisions into the basetemp every test in the session shares, where a name
    outlives the test that created it.

    ``copytree`` rather than ``symlink_to``: a link resolves the same reads, but
    it also leaves a writable path from the scratch root back into the live
    checkout, which is the thing every root here exists to sever.
    """
    if not REAL_TEMPLATES_DIR.is_dir():
        raise RuntimeError(f"reviewer templates are missing at {REAL_TEMPLATES_DIR}; a scratch root would have nothing to copy")
    claude_dir = root / ".claude" / "prompts" / "reviewer"
    if claude_dir.exists():
        return
    claude_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REAL_TEMPLATES_DIR, claude_dir)


def _write_git_skeleton(root: Path) -> None:
    """Make ``root`` a repository git accepts as a worktree toplevel.

    An empty ``.git`` directory does NOT qualify: ``git rev-parse
    --show-toplevel`` rejects it and discovery continues UP. Where ``tmp_path``
    sits inside a real checkout — a ``TMPDIR`` pointed into the working tree —
    that walk returns the enclosing checkout at exit 0, silently re-anchoring
    the wrapper onto the live repository; where it does not, the walk
    terminates at ``/`` and git exits 128. ``HEAD`` naming a ref plus the
    ``objects/`` and ``refs/`` directories is enough for git to accept it.
    """
    git_dir = root / ".git"
    (git_dir / "objects").mkdir(parents=True, exist_ok=True)
    (git_dir / "refs").mkdir(exist_ok=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")


def _verify_partition(root: ScratchRoot, env: dict[str, str]) -> None:
    """Hold the filesystem to the anchoring branch ``root`` declares.

    Raises:
        RuntimeError: the declared branch is not the branch git actually
            selects from this root under this environment, or the probe could
            not be started / did not answer — an undetermined branch fails
            closed exactly as a contradicted one does. Start failures that
            ``_probe_git_toplevel`` does not translate propagate as the
            ``OSError`` subclass they are.

    Both sides settle on git's own verdict, mirroring the two-part test
    ``_review-common.sh`` applies — ``git rev-parse --show-toplevel`` exiting 0
    AND naming a non-empty path — so an environment entry that re-anchors the
    run fails the guard whichever branch was declared.

    On the unanchored side the ancestor walk and the probe are an implicit AND,
    both of which must pass. Suppression-resistance follows from that alone: the
    walk is a pure filesystem check no environment entry can silence, whereas
    the probe can be (``GIT_CEILING_DIRECTORIES``, an ownership refusal), so a
    silenced probe cannot buy a pass for a root that plainly sits in a worktree
    whichever order the two run in. Ordering the walk first buys the
    diagnostic, not the verdict — such a root is reported by the worktree that
    contains it rather than by whatever the probe managed to answer.
    """
    if root.anchored:
        _require_own_git_toplevel(root.path, env)
    else:
        _reject_git_ancestor(root.path)
        _require_no_git_toplevel(root.path, env)


def _require_own_git_toplevel(root: Path, env: dict[str, str]) -> None:
    """Fail unless ``git rev-parse --show-toplevel`` from ``root`` returns ``root``.

    Args:
        env: git is resolved through this mapping's own ``PATH``, so an
            environment in which the wrapper itself could not reach git fails
            here rather than silently demoting the run to the unanchored
            branch.

    Raises:
        RuntimeError: git reports no worktree, or reports one that is not
            ``root`` — in which case ``_review_sanitize_subject`` would cd
            there and write the sanitized subject into that tree instead.

    ``stdout`` is trimmed with ``rstrip("\\n")`` to track the ``top=$(git
    rev-parse --show-toplevel)`` command substitution at
    ``_review-common.sh``:136, which strips trailing newlines and nothing else.
    ``.strip()`` would also drop surrounding spaces the shell keeps, which
    rejects a toplevel path that legitimately ends in one, and — in
    ``_require_no_git_toplevel`` — reads a whitespace-only answer the shell
    calls non-empty as blank.

    The trim operates on a string ``_probe_git_toplevel`` decoded without
    universal-newline translation, so it still sees every byte git wrote. A
    directory name may end in CR — git accepts it and ``rev-parse`` prints it
    verbatim — and reading through a text wrapper would rewrite the trailing
    ``\\r\\n`` to ``\\n`` before ``rstrip`` saw it, leaving the compare below to
    reject a root the wrapper handles correctly.
    """
    probe = _probe_git_toplevel(root, env)
    reported = probe.stdout.rstrip("\n")
    if probe.returncode != 0 or not reported:
        raise RuntimeError(
            f"scratch root {root} is not a git toplevel: git rev-parse exited {probe.returncode} reporting {reported!r}: {probe.stderr.strip()}"
        )
    if Path(reported).resolve() != root.resolve():
        raise RuntimeError(f"scratch root {root} anchors to {reported}, not to itself; wrapper writes would land there")


def _require_no_git_toplevel(root: Path, env: dict[str, str]) -> None:
    """Fail when git, run from ``root`` under ``env``, selects any worktree at all.

    Raises:
        RuntimeError: git selected a worktree, so ``_review-common.sh`` would
            take its anchored branch from a root declared unanchored.

    ``_reject_git_ancestor`` answers this question off the filesystem, which is
    a proxy for git's decision and can disagree with it: a ``GIT_DIR`` in
    ``env`` makes a directory with no ``.git`` anywhere above it answer as a
    worktree, and the walk cannot see that. Asking git directly, under the
    mapping the spawn receives, is what makes this side of the partition as
    fail-closed as the anchored one.

    ``stdout`` is trimmed as command substitution trims it, for the reason
    ``_require_own_git_toplevel`` records. This is the direction whose trim
    choice decides between failing closed and failing open: a whitespace-only
    answer is ``-n``-true in the shell, so the wrapper anchors while a
    ``.strip()``-based guard sees blank and clears the root. Real git does not
    emit that payload — it is a stub construct, see ``_stub_probe`` — so what
    the trim rule buys is resistance to a future edit, not coverage of an
    answer git produces.
    """
    probe = _probe_git_toplevel(root, env)
    reported = probe.stdout.rstrip("\n")
    if probe.returncode == 0 and reported:
        raise RuntimeError(f"scratch root {root} is declared unanchored but git selects the worktree at {reported} under this environment")


def _reject_git_ancestor(root: Path) -> None:
    """Fail when ``root`` or any ancestor of it is a git worktree.

    Raises:
        RuntimeError: a ``.git`` entry exists at or above ``root``, which would
            route wrapper writes to that worktree instead of the scratch root.

    The lexical chain and the symlink-resolved chain are both walked because
    git discovers a worktree along the PHYSICAL path. For a plain child of
    ``tmp_path`` the two chains coincide — pytest resolves its basetemp before
    handing it out — so what earns the second walk is a root reached through a
    planted symlink. ``.exists()`` resolves every component, so the lexical walk
    does see the target's own ``.git``; what it cannot see is the target's
    ANCESTORS, because the lexical chain climbs the LINK's parents instead — and
    a worktree above the target is exactly where this case puts it.
    """
    resolved = root.resolve()
    seen: set[Path] = set()
    for candidate in (root, *root.parents, resolved, *resolved.parents):
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / ".git").exists():
            raise RuntimeError(f"scratch root {root} lies inside the git worktree at {candidate}")


def _probe_git_toplevel(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Ask git, from ``root`` under ``env``, which worktree toplevel it selects.

    Returns:
        The completed ``git rev-parse --show-toplevel`` run, with the bytes git
        wrote decoded into ``stdout``/``stderr``. Return code 0 together with a
        non-empty stdout means git selected the worktree stdout names.

    Raises:
        RuntimeError: no git was found on ``env``'s ``PATH`` (or ``root`` no
            longer exists), or the probe did not answer within its timeout.
            Other start failures — a non-executable git, a ``root`` that is not
            a directory — propagate as the ``OSError`` subclass they are.

    Decoding by hand rather than passing ``text=True`` is what keeps the payload
    byte-identical to what command substitution hands ``_review-common.sh``: a
    text wrapper applies universal-newline translation, which erases a trailing
    CR the shell keeps on the path. ``os.fsdecode`` is the decode because it
    applies ``surrogateescape``, so a path byte the filesystem encoding cannot
    represent round-trips back out through ``Path(...).resolve()`` instead of
    raising — a strict ``bytes.decode()`` would reject a directory name git and
    the shell both carry, which is neither byte-identical nor a failure this
    helper is documented to produce. The wait is bounded because a git that
    never answers would otherwise hang the suite instead of failing it.

    ``lang.python.md`` routes git operations through GitPython; this helper is a
    narrow exception. The question is not "what does git say" but "what will git
    say to the wrapper spawn this root is being vetted for", which depends on
    the ``PATH`` and ``GIT_*`` entries of the exact mapping the spawn receives —
    a library call would answer against this interpreter's ambient environment
    instead. One read-only ``rev-parse``, no repository mutation.
    """
    try:
        raw = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(root),
            env=env,
            capture_output=True,
            timeout=15,
        )
    except FileNotFoundError as exc:
        # Raised for a git that is not on the PATH AND for a cwd that does not
        # exist; the cause is only in ``exc``, so carry it rather than name one.
        raise RuntimeError(
            f"git rev-parse could not be started from {root} on PATH {env.get('PATH', '')} ({exc}); the anchoring branch cannot be established"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"git rev-parse from {root} did not answer within {exc.timeout}s; the anchoring branch cannot be established"
        ) from exc
    return subprocess.CompletedProcess(raw.args, raw.returncode, os.fsdecode(raw.stdout), os.fsdecode(raw.stderr))


def _default_env(bin_dir: Path, root: ScratchRoot, *, review_type: str = "diff") -> dict[str, str]:
    """Build the minimal env the wrapper needs to reach the shim.

    Supplies ``REVIEW_TYPE``/``DIFF_FILE`` for the new contract, the host
    execution context (so the token guard + OAuth path is exercised), a token
    so the token-missing guard does not short-circuit, and the pinned round.
    ``DIFF_FILE`` names the subject inside ``root``'s own ``tmp/`` for the
    containment reason ``SUBJECT_ARTIFACT`` records. ``--round`` on argv still
    wins: the wrapper's parse loop assigns after the ``ROUND`` default is read.
    """
    return {
        "REVIEW_TYPE": review_type,
        "DIFF_FILE": str(root.path / "tmp" / SUBJECT_ARTIFACT),
        "ROUND": _ROUND,
        "GEMINI_EXECUTION_CONTEXT": "host",
        "GEMINI_API_KEY": "test",
        "PATH": f"{bin_dir}:/usr/bin:/bin",
    }


def _require_scratch_containment(root: ScratchRoot, tmp_path: Path) -> None:
    """Fail unless ``root`` resolves strictly inside the test's own ``tmp_path``.

    Raises:
        RuntimeError: ``root`` resolves onto ``tmp_path`` itself or outside it.

    ``_verify_partition`` cannot stand in for this. The live checkout IS its own
    git toplevel, so a ``ScratchRoot`` naming it with ``anchored=True`` satisfies
    the partition and then spawns the wrapper into the tree whose ``tmp/`` a real
    review reads — the artifact race this module's scratch roots exist to remove.
    Comparison is on the resolved paths because a symlink planted under
    ``tmp_path`` reaches the same tree while looking contained; resolution is the
    chain the spawn's writes actually follow. Equality with ``tmp_path`` is
    rejected too, for the reason ``_provision_root`` records.
    """
    resolved = root.path.resolve()
    scratch = tmp_path.resolve()
    if resolved == scratch or not resolved.is_relative_to(scratch):
        raise RuntimeError(f"scratch root {root.path} resolves to {resolved}, which is not strictly inside the test's tmp_path {scratch}")


def _run_review(
    tmp_path: Path,
    env_overrides: dict[str, str],
    *,
    root: ScratchRoot,
    args: list[str] | None = None,
    timeout: int = 15,
) -> subprocess.CompletedProcess[str]:
    """Execute the gemini review script from ``root`` with a controlled env.

    Args:
        tmp_path: test temp dir supplying the scratch ``HOME``.
        env_overrides: entries merged over the closed base env.
        root: the throwaway workspace to run from. Required, with no default:
            the wrapper resolves every artifact it writes against its CWD.
        args: extra argv for the wrapper.
        timeout: seconds to wait for the wrapper.

    Returns:
        The completed process with captured stdout/stderr.

    Raises:
        RuntimeError: ``root`` does not resolve strictly inside ``tmp_path``,
            ``env_overrides`` carries a ``HOME`` that would displace the scratch
            one, or ``_verify_partition`` rejected ``root`` under the assembled
            env. The wrapper is never spawned in any of the three cases.

    Scratch containment — ``root`` under this test's ``tmp_path``, a different
    question from the wrapper's own DIFF_FILE containment check — is verified
    FIRST, before the partition probe: the probe is itself a subprocess run with
    ``cwd=root``, so ordering it ahead would spawn git inside whatever tree an
    out-of-``tmp_path`` root names.

    ``HOME`` is a scratch directory because ``run_gemini`` calls ``mkdir -p
    "$HOME/.gemini"`` unconditionally; it sits beside the scratch root rather
    than inside it, and ``env_overrides`` may not replace it — an override would
    put ``.gemini`` and git's global config back wherever it pointed, and would
    silently invert the discriminator
    ``test_run_review_probes_under_the_assembled_env_not_the_overrides`` turns
    on. The env mapping is closed — nothing is inherited from
    ``os.environ`` — and the ``GIT_*`` family stays out in particular, since an
    entry like ``GIT_WORK_TREE`` or ``GIT_DIR`` moves a run onto the branch it
    did not declare. Exclusion cannot cover everything that does that: git's
    system and repository-local config re-anchor a run without touching the env
    at all. What holds the partition is therefore the guard itself —
    ``_verify_partition`` probes git under this exact assembled mapping, from
    this exact root, before the wrapper is spawned.
    """
    _require_scratch_containment(root, tmp_path)
    if "HOME" in env_overrides:
        raise RuntimeError(f"env_overrides may not carry HOME (got {env_overrides['HOME']!r}); the scratch HOME is not overridable")
    home = tmp_path / "home"
    (home / ".gemini").mkdir(parents=True, exist_ok=True)
    env: dict[str, str] = {
        "PATH": env_overrides.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
        "HOME": str(home),
    }
    for key, value in env_overrides.items():
        env[key] = value
    _verify_partition(root, env)
    return subprocess.run(
        ["bash", REVIEW_SCRIPT, *(args or [])],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=str(root.path),
    )


# ---------------------------------------------------------------------------
# Req-005: EFFORT alias composition
# ---------------------------------------------------------------------------


class TestEffortAliasComposition:
    """EFFORT threads into the -m flag as <tier-shortname>-<effort>."""

    def _run_with_effort(
        self,
        tmp_path: Path,
        *,
        effort: str,
        model: str,
        root: ScratchRoot | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[ShimRecord]]:
        """Invoke the wrapper with the given EFFORT/model under the new contract.

        Args:
            root: the root to run from; a fresh anchored one by default.
                Callers that assert on the artifacts a run wrote have to pass
                their own, since the run resolves them against this root.
        """
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        run_root = root if root is not None else _anchored_root(tmp_path)
        env = _default_env(bin_dir, run_root)
        env["EFFORT"] = effort
        env["GEMINI_MODEL"] = model
        result = _run_review(tmp_path, env_overrides=env, root=run_root)
        return result, _read_shim_log(log)

    def test_pro_plus_high_composes_pro_alias(self, tmp_path: Path) -> None:
        """Pro tier + EFFORT=high -> -m gemini-3.1-pro-high."""
        result, records = self._run_with_effort(tmp_path, effort="high", model="gemini-3.1-pro-preview")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert "-m" in argv
        assert argv[argv.index("-m") + 1] == "gemini-3.1-pro-high"

    def test_flash_plus_medium_composes_flash_high(self, tmp_path: Path) -> None:
        """Flash tier + EFFORT=medium -> -m gemini-3-flash-high.

        MEDIUM tier collapses to HIGH internal thinking (model selection is
        what differs across tiers, not the internal effort setting).
        """
        result, records = self._run_with_effort(tmp_path, effort="medium", model="gemini-3-flash-preview")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert argv[argv.index("-m") + 1] == "gemini-3-flash-high"

    def test_pro_plus_xhigh_collapses_to_pro_high(self, tmp_path: Path) -> None:
        """Pro tier + EFFORT=xhigh collapses to -m gemini-3.1-pro-high."""
        result, records = self._run_with_effort(tmp_path, effort="xhigh", model="gemini-3.1-pro-preview")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert argv[argv.index("-m") + 1] == "gemini-3.1-pro-high"

    def test_pro_plus_max_collapses_to_pro_high(self, tmp_path: Path) -> None:
        """Pro tier + EFFORT=max collapses to -m gemini-3.1-pro-high."""
        result, records = self._run_with_effort(tmp_path, effort="max", model="gemini-3.1-pro-preview")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert argv[argv.index("-m") + 1] == "gemini-3.1-pro-high"

    def test_fallback_transition_flash_plus_high(self, tmp_path: Path) -> None:
        """Caller invokes with GEMINI_MODEL=gemini-3-flash-preview (post-fallback).

        Exercises the Pro->Flash capacity fallback (Req-N03): the shortname
        lookup must recognize the Flash full name post-rewrite and produce
        ``gemini-3-flash-high``.
        """
        result, records = self._run_with_effort(tmp_path, effort="high", model="gemini-3-flash-preview")
        assert result.returncode == 0, result.stderr
        assert records
        argv = records[0]["argv"]
        assert argv[argv.index("-m") + 1] == "gemini-3-flash-high"

    def test_minimal_rejected_at_enum(self, tmp_path: Path) -> None:
        """``minimal`` is rejected at the EFFORT enum gate."""
        root = _anchored_root(tmp_path)
        result, records = self._run_with_effort(tmp_path, effort="minimal", model="gemini-3-flash-preview", root=root)
        assert result.returncode != 0
        assert "EFFORT must be one of {medium,high,xhigh,max}" in result.stderr
        assert records == []
        _assert_arg_validation_rejection(root, "EFFORT enum rejected")

    def test_low_rejected_at_enum(self, tmp_path: Path) -> None:
        """``low`` is rejected upfront — reviewer floor is MEDIUM tier (HIGH internal)."""
        root = _anchored_root(tmp_path)
        result, records = self._run_with_effort(tmp_path, effort="low", model="gemini-3.1-pro-preview", root=root)
        assert result.returncode != 0
        assert "EFFORT must be one of {medium,high,xhigh,max}" in result.stderr
        assert records == []
        _assert_arg_validation_rejection(root, "EFFORT enum rejected")


# ---------------------------------------------------------------------------
# New-contract argument validation: REVIEW_TYPE / DIFF_FILE.
#
# DIFF_FILE path-containment (realpath, absolute-outside-tmp/, symlink
# escape, traversal, zero-byte) is covered exhaustively by
# tests/scripts/test_wrapper_sanitation.py against the shared
# _review_validate_diff_file helper. These tests focus on the wrapper's
# arg_validation JSON exit shape — i.e. that the validation failure
# surfaces as GEMINI_ERROR + error_class=arg_validation, not as a crash.
# ---------------------------------------------------------------------------


def _read_exit_json(root: ScratchRoot) -> dict[str, object]:
    """Read and parse the ``tmp/gemini-exit.json`` the wrapper wrote under ``root``."""
    path = root.path / "tmp" / "gemini-exit.json"
    if not path.exists():
        return {}
    parsed: dict[str, object] = json.loads(path.read_text())
    return parsed


def _assert_arg_validation_rejection(root: ScratchRoot, stderr_excerpt: str) -> None:
    """Assert the exit JSON under ``root`` names the gate ``stderr_excerpt`` identifies.

    ``signal`` and ``error_class`` are identical across every argument gate, so
    the excerpt is the only field that separates a REVIEW_TYPE rejection from a
    DIFF_FILE, EFFORT or ``--round`` one — which is why one parameterised
    assertion covers all four rather than a helper per gate.

    Reading the file back from ``root`` also witnesses two things the stderr
    message cannot: that the run left a machine-readable signal at all, and that
    it landed under the scratch root rather than under the CWD the pytest
    process was started from.
    """
    exit_json = _read_exit_json(root)
    assert exit_json.get("signal") == "GEMINI_ERROR"
    assert exit_json.get("error_class") == "arg_validation"
    assert exit_json.get("stderr_excerpt") == stderr_excerpt


class TestReviewTypeValidation:
    """Wrapper rejects missing / invalid REVIEW_TYPE before invoking gemini."""

    def test_missing_review_type_rejected(self, tmp_path: Path) -> None:
        """Unset REVIEW_TYPE -> arg_validation JSON, non-zero exit, no shim call."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        root = _anchored_root(tmp_path)
        env = _default_env(bin_dir, root)
        env.pop("REVIEW_TYPE")
        result = _run_review(tmp_path, env_overrides=env, root=root)
        assert result.returncode != 0
        assert _read_shim_log(log) == []
        _assert_arg_validation_rejection(root, "REVIEW_TYPE invalid or missing")

    def test_invalid_review_type_enum_rejected(self, tmp_path: Path) -> None:
        """REVIEW_TYPE=foo (not in enum) -> arg_validation rejection."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        root = _anchored_root(tmp_path)
        env = _default_env(bin_dir, root, review_type="foo")
        result = _run_review(tmp_path, env_overrides=env, root=root)
        assert result.returncode != 0
        assert _read_shim_log(log) == []
        _assert_arg_validation_rejection(root, "REVIEW_TYPE invalid or missing")


class TestDiffFileValidation:
    """Wrapper rejects missing / empty / out-of-root DIFF_FILE."""

    def test_missing_diff_file_rejected(self, tmp_path: Path) -> None:
        """Unset DIFF_FILE -> arg_validation rejection, shim never called."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        root = _anchored_root(tmp_path)
        env = _default_env(bin_dir, root)
        env.pop("DIFF_FILE")
        result = _run_review(tmp_path, env_overrides=env, root=root)
        assert result.returncode != 0
        assert _read_shim_log(log) == []
        _assert_arg_validation_rejection(root, "DIFF_FILE invalid or missing")

    def test_nonexistent_diff_file_rejected(self, tmp_path: Path) -> None:
        """DIFF_FILE pointing at a missing path -> arg_validation rejection."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        root = _anchored_root(tmp_path)
        env = _default_env(bin_dir, root)
        env["DIFF_FILE"] = "tmp/does-not-exist.txt"
        result = _run_review(tmp_path, env_overrides=env, root=root)
        assert result.returncode != 0
        assert _read_shim_log(log) == []
        _assert_arg_validation_rejection(root, "DIFF_FILE invalid or missing")

    def test_zero_byte_diff_file_rejected(self, tmp_path: Path) -> None:
        """Zero-byte DIFF_FILE -> arg_validation rejection."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        root = _anchored_root(tmp_path)
        empty_subject = root.path / "tmp" / EMPTY_SUBJECT_ARTIFACT
        empty_subject.touch()
        env = _default_env(bin_dir, root)
        env["DIFF_FILE"] = str(empty_subject)
        result = _run_review(tmp_path, env_overrides=env, root=root)
        assert result.returncode != 0
        assert _read_shim_log(log) == []
        _assert_arg_validation_rejection(root, "DIFF_FILE invalid or missing")

    def test_diff_file_outside_tmp_rejected(self, tmp_path: Path) -> None:
        """DIFF_FILE outside tmp/ or agent-review/ -> arg_validation rejection.

        The subject sits at the root itself — a sibling of ``tmp/``, not a child
        of it — which is the placement the wrapper's own DIFF_FILE containment
        check rejects. That check and ``_require_scratch_containment`` share a
        word and no criterion: this one bounds the SUBJECT to the run's ``tmp/``
        or ``agent-review/``, the other bounds the scratch ROOT to the test's
        ``tmp_path``, and this root passes the second while failing the first.
        """
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        root = _unanchored_root(tmp_path)
        outside = root.path / "evil.txt"
        outside.write_text("evil\n")
        env = _default_env(bin_dir, root)
        env["DIFF_FILE"] = str(outside)
        result = _run_review(tmp_path, env_overrides=env, root=root)
        assert result.returncode != 0
        assert _read_shim_log(log) == []
        _assert_arg_validation_rejection(root, "DIFF_FILE invalid or missing")


class TestTemplateIsHardcoded:
    """The reviewer template path is derived solely from REVIEW_TYPE.

    The wrapper ignores any caller-supplied prompt text; the template comes
    from ``.claude/prompts/reviewer/<REVIEW_TYPE>.md``. We observe this by
    asserting that a substring of the on-disk ``diff.md`` preamble appears
    in the stdin payload the shim received.
    """

    _TEMPLATE_MARKER: str = "The subject artifact follows immediately after this preamble"

    def test_stdin_contains_template_preamble(self, tmp_path: Path) -> None:
        """Shim stdin must include the hardcoded ``diff.md`` preamble text.

        Doubles as this module's check that the run executes at ``_ROUND``: the
        wrapper names the review output and the sanitized subject after the round
        it resolved, so the filenames report the round end to end rather than
        restating the env entry that set it. The two path assertions are
        branch-insensitive —
        the CWD here IS the toplevel, so the absolute and CWD-relative branches
        resolve to the same file.
        """
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        root = _anchored_root(tmp_path)
        env = _default_env(bin_dir, root)
        env["EFFORT"] = "high"
        env["GEMINI_MODEL"] = "gemini-3.1-pro-preview"
        result = _run_review(tmp_path, env_overrides=env, root=root)
        assert result.returncode == 0, result.stderr
        records = _read_shim_log(log)
        assert records, "shim was never invoked"
        # Template loaded from .claude/prompts/reviewer/diff.md and
        # concatenated with the sanitized subject.
        assert self._TEMPLATE_MARKER in records[0]["stdin"]
        # Subject data also present (the subject seeded in the scratch root).
        assert "diff --git" in records[0]["stdin"]
        # Round-suffixed artifacts land under the scratch root's own tmp/. The
        # wrapper defaults ROUND to 1, so a run that ignored the env entry
        # would produce the ...-1 pair instead of these.
        assert (root.path / "tmp" / f"gemini-review-output-{_ROUND}.md").is_file()
        assert (root.path / "tmp" / f"gemini-subject-sanitized-{_ROUND}.txt").is_file()


class TestRoundValidation:
    """Wrapper rejects non-positive-integer ROUND values before gemini."""

    def test_round_zero_rejected(self, tmp_path: Path) -> None:
        """``--round 0`` -> arg_validation JSON, non-zero exit."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        root = _anchored_root(tmp_path)
        env = _default_env(bin_dir, root)
        result = _run_review(tmp_path, env_overrides=env, root=root, args=["--round", "0"])
        assert result.returncode != 0
        assert "--round must be a positive integer >= 1, got '0'" in result.stderr
        assert _read_shim_log(log) == []
        _assert_arg_validation_rejection(root, "--round must be a positive integer >= 1")

    def test_round_negative_rejected(self, tmp_path: Path) -> None:
        """``--round -1`` -> arg_validation JSON, non-zero exit."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        root = _anchored_root(tmp_path)
        env = _default_env(bin_dir, root)
        # A leading-dash value is consumed by the while loop as --round's
        # argument rather than matching the usage branch, so the numeric regex
        # gate is what rejects it — assert that reason, not just the exit code.
        result = _run_review(tmp_path, env_overrides=env, root=root, args=["--round", "-1"])
        assert result.returncode != 0
        assert "--round must be a positive integer >= 1, got '-1'" in result.stderr
        assert _read_shim_log(log) == []
        _assert_arg_validation_rejection(root, "--round must be a positive integer >= 1")


class TestTokenAndSecretGuards:
    """Token-missing / secrets-guard behaviors.

    The ``/app/.env`` FATAL guard only trips inside a container and is
    covered by a separate integration test; we verify the token-missing
    signal here.

    Keeping ``_default_env``'s ``GEMINI_EXECUTION_CONTEXT=host`` +
    ``GEMINI_API_KEY=test`` is not by itself enough to exercise the host OAuth
    path: the guard sits at ``gemini-review.sh``:118, below the ``--round``
    (:51), ``REVIEW_TYPE`` (:69), ``DIFF_FILE`` (:73) and ``EFFORT`` (:93) gates,
    so a test that keeps the entries in order to observe a rejection at one of
    those never reaches it. The runs that clear all four are
    ``TestEffortAliasComposition``'s five composition cases,
    ``TestTemplateIsHardcoded``,
    ``TestOutputRouting.test_host_context_writes_to_tmp`` and every test in
    ``TestProTier429_503Fallback``.
    ``TestOutputRouting.test_container_context_writes_to_agent_review`` reaches
    the guard too, but clears it on the key rather than the host marker — that
    is the arm it drops the marker to reach.
    """

    def test_token_missing_emits_unavailable_signal(self, tmp_path: Path) -> None:
        """Non-host context without GEMINI_API_KEY -> GEMINI_UNAVAILABLE, exit 0."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        root = _anchored_root(tmp_path)
        env = _default_env(bin_dir, root)
        env.pop("GEMINI_API_KEY")
        env.pop("GEMINI_EXECUTION_CONTEXT")
        result = _run_review(tmp_path, env_overrides=env, root=root)
        assert result.returncode == 0, result.stderr
        assert _read_shim_log(log) == []
        exit_json = _read_exit_json(root)
        assert exit_json.get("signal") == "GEMINI_UNAVAILABLE"
        assert exit_json.get("reason") == "token_missing"


class TestOutputRouting:
    """Container vs host artifact routing (agent-review/ vs tmp/).

    Both tests run from an unanchored root: they are this module's coverage of
    the CWD-relative branch of ``_review-common.sh``, which is why the reviewer
    templates have to be reachable from the root itself rather than through a
    git toplevel. The ``agent-review/`` directory the container branch routes
    into is created by the wrapper, not seeded by the root builder — the
    container test observes that too.
    """

    def _run_in_unanchored_ws(
        self,
        tmp_path: Path,
        *,
        review_session_id: str | None = None,
        workspace: str | None = None,
        container_context: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        """Run the wrapper from an unanchored root for routing assertions.

        The env is composed from ``_default_env`` and then narrowed, rather
        than rebuilt: hand-listing the entries would leave this — the module's
        only coverage of the CWD-relative branch — silently missing anything a
        future entry adds to the shared builder.
        """
        root = _unanchored_root(tmp_path)
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        env = _default_env(bin_dir, root)
        if container_context:
            # Container routing is selected by the ABSENCE of the host marker,
            # so this is a removal rather than an alternate value.
            env.pop("GEMINI_EXECUTION_CONTEXT")
        if review_session_id:
            env["REVIEW_SESSION_ID"] = review_session_id
        if workspace:
            env["WORKSPACE"] = workspace
        result = _run_review(tmp_path, env_overrides=env, root=root)
        return result, root.path

    def test_host_context_writes_to_tmp(self, tmp_path: Path) -> None:
        """``GEMINI_EXECUTION_CONTEXT=host`` -> output under ``tmp/``."""
        result, unanchored_ws = self._run_in_unanchored_ws(tmp_path)
        assert result.returncode == 0, result.stderr
        assert (unanchored_ws / "tmp" / f"gemini-review-output-{_ROUND}.md").exists()

    def test_container_context_writes_to_agent_review(self, tmp_path: Path) -> None:
        """Container context -> output under ``agent-review/`` with workspace/session id.

        The root ships no ``agent-review/``, so the directory existing at all is
        the wrapper's own ``mkdir -p`` at ``gemini-review.sh``:142.
        """
        result, unanchored_ws = self._run_in_unanchored_ws(
            tmp_path,
            review_session_id="test-session",
            workspace="brownfield-ai",
            container_context=True,
        )
        assert result.returncode == 0, result.stderr
        expected = unanchored_ws / "agent-review" / "brownfield-ai-gemini-review-output-test-session.md"
        assert expected.exists(), "agent-review output not produced"


# ---------------------------------------------------------------------------
# Req-019: Pro-tier 429/503 -> flash-high MEDIUM-tier fallback
# ---------------------------------------------------------------------------


def _install_shim_with_sequence(
    tmp_path: Path,
    *,
    exit_codes: list[int],
    stderr_texts: list[str],
    log_path: Path | None = None,
) -> Path:
    """Install a fake ``gemini`` shim whose exit code + stderr varies per call.

    The shim writes the per-call exit_code to a state file on each invocation
    and consumes the sequence in order. If more calls come than the sequence
    length, the last entry is reused (mirrors steady-state failure).

    Interpolated paths are ``shlex.quote``-bound for the reason
    ``_install_shim`` records.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    helper_path = bin_dir / "_shim_helper.py"
    helper_path.write_text(_SHIM_HELPER)
    state_file = bin_dir / "call_counter.txt"
    state_file.write_text("0")
    # Encode the sequences into separate files for the shell to look up.
    codes_file = bin_dir / "exit_codes.txt"
    codes_file.write_text("\n".join(str(c) for c in exit_codes) + "\n")
    stderr_file = bin_dir / "stderr_lines.txt"
    # Encode stderr lines one per line (literal '\\n' placeholders not expected).
    stderr_file.write_text("\n".join(stderr_texts) + "\n")
    log_file = log_path if log_path is not None else (tmp_path / "gemini-calls.log")
    q_helper = shlex.quote(str(helper_path))
    q_log = shlex.quote(str(log_file))
    q_state = shlex.quote(str(state_file))
    q_codes = shlex.quote(str(codes_file))
    q_stderr = shlex.quote(str(stderr_file))
    shim_body = (
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'python3 {q_helper} {q_log} "$@"\n'
        f"_n=$(cat {q_state})\n"
        f"_exit=$(awk -v n=\"$_n\" 'NR==n+1' {q_codes})\n"
        f"_stderr=$(awk -v n=\"$_n\" 'NR==n+1' {q_stderr})\n"
        'if [ -z "$_exit" ]; then\n'
        f"  _exit=$(tail -n1 {q_codes})\n"
        f"  _stderr=$(tail -n1 {q_stderr})\n"
        "fi\n"
        f"echo $(( _n + 1 )) > {q_state}\n"
        'if [ -n "$_stderr" ]; then printf \'%s\\n\' "$_stderr" >&2; fi\n'
        'exit "$_exit"\n'
    )
    shim = bin_dir / "gemini"
    shim.write_text(shim_body)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


class TestProTier429_503Fallback:
    """Pro-tier 429/503 retries once with gemini-3-flash-high."""

    def _run_sequence(
        self,
        tmp_path: Path,
        *,
        root: ScratchRoot,
        exit_codes: list[int],
        stderr_texts: list[str],
        extra_env: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> tuple[subprocess.CompletedProcess[str], list[ShimRecord]]:
        """Install a sequence-shim and invoke the wrapper under the new contract.

        Args:
            root: the throwaway workspace to run from; required, since the run
                resolves every artifact it writes against it.
        """
        log = tmp_path / "calls.log"
        bin_dir = _install_shim_with_sequence(
            tmp_path,
            exit_codes=exit_codes,
            stderr_texts=stderr_texts,
            log_path=log,
        )
        env = _default_env(bin_dir, root)
        env["EFFORT"] = "high"
        env["GEMINI_MODEL"] = "gemini-3.1-pro-preview"
        if extra_env:
            env.update(extra_env)
        result = _run_review(tmp_path, env_overrides=env, root=root, timeout=timeout)
        return result, _read_shim_log(log)

    def test_pro_429_retries_with_flash_high(self, tmp_path: Path) -> None:
        """429 on Pro tier -> second call with -m gemini-3-flash-high, success."""
        result, records = self._run_sequence(
            tmp_path,
            root=_anchored_root(tmp_path),
            exit_codes=[1, 0],
            stderr_texts=["Error: 429 Too Many Requests", ""],
        )
        assert result.returncode == 0, result.stderr
        assert "falling back to gemini-3-flash-high" in result.stderr
        assert len(records) == 2, f"expected 2 calls, got {len(records)}"
        assert "gemini-3.1-pro-high" in records[0]["argv"]
        assert "gemini-3-flash-high" in records[1]["argv"]

    def test_pro_503_retries_with_flash_high(self, tmp_path: Path) -> None:
        """503 on Pro tier -> second call with -m gemini-3-flash-high, success."""
        result, records = self._run_sequence(
            tmp_path,
            root=_anchored_root(tmp_path),
            exit_codes=[1, 0],
            stderr_texts=["Error: 503 Service Unavailable", ""],
        )
        assert result.returncode == 0, result.stderr
        assert "falling back to gemini-3-flash-high" in result.stderr
        assert len(records) == 2
        assert "gemini-3-flash-high" in records[1]["argv"]

    def test_pro_429_flash_retry_also_fails_emits_fallback(self, tmp_path: Path) -> None:
        """429 on Pro tier + flash-high retry also 429 -> GEMINI_FALLBACK exit 3."""
        root = _anchored_root(tmp_path)
        result, records = self._run_sequence(
            tmp_path,
            root=root,
            exit_codes=[1, 1],
            stderr_texts=[
                "Error: 429 Too Many Requests",
                "Error: 429 quota exceeded",
            ],
        )
        assert result.returncode == 3, result.stderr
        assert len(records) == 2
        # Read the parsed field, not a substring of the document: the JSON also
        # carries up to 500 bytes of CLI stderr, so a raw-text search could be
        # satisfied by the excerpt while ``signal`` said something else.
        exit_json = _read_exit_json(root)
        assert exit_json.get("signal") == "GEMINI_FALLBACK"
        # The retry rewrote GEMINI_MODEL to the Flash tier before this JSON was
        # built, so the Pro name can only appear here because the wrapper
        # captured the requested tier ahead of the rewrite. This is the only
        # run in the module where reporting the rewritten value would differ.
        assert exit_json.get("model") == "gemini-3.1-pro-preview"

    def test_pro_auth_error_no_fallback(self, tmp_path: Path) -> None:
        """Non-429/503 error (auth) -> terminal; no flash-high retry; exit 3."""
        root = _anchored_root(tmp_path)
        result, records = self._run_sequence(
            tmp_path,
            root=root,
            exit_codes=[1],
            stderr_texts=["Error: 401 Unauthorized: bad token"],
        )
        assert result.returncode == 3
        assert len(records) == 1, f"expected 1 call (no retry), got {len(records)}"
        assert "falling back" not in result.stderr
        exit_json = _read_exit_json(root)
        # GEMINI_FALLBACK on a terminal error is not a report that a retry
        # happened — it is the wrapper telling its caller "try the next
        # bridge". The no-retry property is carried entirely by the record
        # count above; the excerpt cannot discriminate it, because the sequence
        # shim reuses its last entry once exhausted and a second attempt would
        # write the same auth text. What the excerpt does witness is the
        # classification: the auth stderr reached the JSON rather than being
        # dropped on the terminal path.
        assert exit_json.get("signal") == "GEMINI_FALLBACK"
        assert "401 Unauthorized: bad token" in str(exit_json.get("stderr_excerpt"))

    def test_auth_error_invalidates_preflight_cache(self, tmp_path: Path) -> None:
        """Auth failure at execution time MUST delete the preflight cache."""
        cache_file = tmp_path / "gemini-preflight-cache.json"
        cache_file.write_text('{"mode":"local","gemini":{"cli":true}}\n')
        self._run_sequence(
            tmp_path,
            root=_anchored_root(tmp_path),
            exit_codes=[1],
            stderr_texts=["Error: 401 Unauthorized: bad token"],
            extra_env={"PREFLIGHT_CACHE_FILE": str(cache_file)},
        )
        assert not cache_file.exists(), "preflight cache should be invalidated after auth failure"

    def test_missing_binary_invalidates_preflight_cache(self, tmp_path: Path) -> None:
        """``command not found`` also invalidates the preflight cache."""
        cache_file = tmp_path / "gemini-preflight-cache.json"
        cache_file.write_text('{"mode":"local","gemini":{"cli":true}}\n')
        self._run_sequence(
            tmp_path,
            root=_anchored_root(tmp_path),
            exit_codes=[127],
            stderr_texts=["bash: gemini: command not found"],
            extra_env={"PREFLIGHT_CACHE_FILE": str(cache_file)},
        )
        assert not cache_file.exists(), "preflight cache should be invalidated after missing-binary failure"


# ---------------------------------------------------------------------------
# The partition guard itself.
#
# _verify_partition is the only thing keeping each test above on the branch it
# claims to cover, and none of those runs observes it: replace its body with a
# bare return and every test above still passes. Its failure mode is silent
# laxness, so these tests are its lock. Most drive the guard directly under
# tmp_path and lock its decision procedure only; its placement on the spawn
# path and the mapping it is handed there are separate properties, locked by
# the two tests here that go through _run_review.
# ---------------------------------------------------------------------------


class TestPartitionGuard:
    """``_verify_partition`` rejects any root whose filesystem or env contradicts it."""

    @staticmethod
    def _guard_env(tmp_path: Path, **extra: str) -> dict[str, str]:
        """Closed env shaped like the one ``_run_review`` builds.

        ``extra`` overrides any entry, ``PATH`` included — a caller that hands
        over a ``PATH`` with no git on it is testing the unreachable-git path.
        """
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home")}
        env.update(extra)
        return env

    @staticmethod
    def _bare_root(tmp_path: Path, name: str) -> Path:
        """Create an empty directory under ``tmp_path`` with no repository of its own."""
        root = tmp_path / name
        root.mkdir()
        return root

    @staticmethod
    def _install_home_sensitive_git(bin_dir: Path, *, home: Path, toplevel: Path) -> None:
        """Install a fake ``git`` that reports a worktree only under ``HOME=home``.

        Args:
            bin_dir: directory at the head of the probe's ``PATH``.
            home: the ``HOME`` value that makes the fake report a worktree.
            toplevel: the path it reports.

        ``HOME`` is a *synthetic* discriminator here, not a claim about real
        git: it is chosen because it is the single entry ``_run_review`` adds
        on top of the caller's overrides, so a probe answer that turns on it
        can only be explained by the guard having been handed the assembled
        mapping. Real git would reach ``HOME`` via ``~/.gitconfig``, which
        ``_run_review`` redirects to a scratch directory and therefore
        neutralises — which is exactly why the discriminator has to be faked.

        Interpolated values are ``shlex.quote``-bound for the reason
        ``_install_shim`` records.
        """
        shim = bin_dir / "git"
        shim.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            f'if [ "${{HOME:-}}" = {shlex.quote(str(home))} ]; then\n'
            f"  printf '%s\\n' {shlex.quote(str(toplevel))}\n"
            "  exit 0\n"
            "fi\n"
            "exit 128\n"
        )
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    @staticmethod
    def _stub_probe(monkeypatch: pytest.MonkeyPatch, *, returncode: int, stdout: str) -> None:
        """Pin ``_probe_git_toplevel``'s answer to a fixed exit status and stdout.

        Args:
            monkeypatch: fixture used to swap the module-level helper.
            returncode: exit status the fake probe reports.
            stdout: raw stdout the fake probe reports, before the guards trim
                it — payloads that differ only in whitespace are the point.

        Both guards mirror the two-part test at ``_review-common.sh``:136 —
        ``top=$(git rev-parse --show-toplevel 2>/dev/null) && [ -n "$top" ]``.
        Real ``git rev-parse --show-toplevel`` answers either exit 0 with a
        path or non-zero with nothing on stdout — a bare repository takes the
        second form, and no arrangement of worktree, ``GIT_DIR`` or
        ``GIT_WORK_TREE`` this module can build produces a mixed one. The
        exit-status and emptiness halves of that test are therefore reachable
        only through a stub.
        """

        def _fake(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(["git", "rev-parse", "--show-toplevel"], returncode, stdout, "")

        monkeypatch.setattr(sys.modules[__name__], "_probe_git_toplevel", _fake)

    def test_anchored_root_that_is_its_own_toplevel_passes(self, tmp_path: Path) -> None:
        root = self._bare_root(tmp_path, "anchored_ws")
        _write_git_skeleton(root)
        _verify_partition(ScratchRoot(root, anchored=True), self._guard_env(tmp_path))

    def test_anchored_root_whose_path_ends_in_a_space_passes(self, tmp_path: Path) -> None:
        # git prints the toplevel verbatim and command substitution keeps the
        # trailing space, so `cd "$top"` and `${top}/tmp/...` both use a path
        # that still has it. A guard trimming with `.strip()` compares a
        # DIFFERENT path and rejects a root the wrapper handles correctly.
        root = self._bare_root(tmp_path, "anchored ws ")
        _write_git_skeleton(root)
        _verify_partition(ScratchRoot(root, anchored=True), self._guard_env(tmp_path))

    def test_anchored_root_whose_path_ends_in_cr_passes(self, tmp_path: Path) -> None:
        # git prints the toplevel verbatim and command substitution strips the
        # trailing newline only, so `cd "$top"` uses a path that still carries
        # the CR. Reading the probe through a text wrapper applies
        # universal-newline translation, which rewrites the trailing \r\n to \n
        # and leaves the identity compare rejecting a root the wrapper handles
        # correctly — this is the case that makes the hand decode load-bearing.
        root = self._bare_root(tmp_path, "anchored_ws\r")
        _write_git_skeleton(root)
        _verify_partition(ScratchRoot(root, anchored=True), self._guard_env(tmp_path))

    def test_anchored_root_whose_path_carries_an_undecodable_byte_passes(self, tmp_path: Path) -> None:
        # A filename is a byte string here, and git prints the toplevel back
        # verbatim. A strict `bytes.decode()` raises UnicodeDecodeError on the
        # 0xff, turning a root the wrapper handles into an error attributed to
        # the guard; `os.fsdecode` applies surrogateescape and `Path.resolve()`
        # encodes it straight back, so the identity compare still sees one
        # directory. This is what makes the docstring's "byte-identical" claim
        # cover the whole payload rather than just its line endings.
        root = self._bare_root(tmp_path, os.fsdecode(b"anchored_ws_\xff"))
        _write_git_skeleton(root)
        _verify_partition(ScratchRoot(root, anchored=True), self._guard_env(tmp_path))

    def test_the_probe_bounds_its_wait(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # A git that never answers has to become a failure, not a stalled
        # session. The bound is invisible everywhere else: the timeout test
        # below raises TimeoutExpired from a patched subprocess.run and so
        # supplies its own value, and every real probe in this module answers
        # immediately.
        captured: dict[str, object] = {}

        def _capture(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            captured.update(kwargs)
            return subprocess.CompletedProcess(["git", "rev-parse", "--show-toplevel"], 128, b"", b"")

        monkeypatch.setattr(subprocess, "run", _capture)
        _probe_git_toplevel(tmp_path, self._guard_env(tmp_path))
        assert captured["timeout"] == 15

    def test_anchored_declaration_without_a_repository_rejected(self, tmp_path: Path) -> None:
        root = self._bare_root(tmp_path, "anchored_ws")
        with pytest.raises(RuntimeError, match="is not a git toplevel"):
            _verify_partition(ScratchRoot(root, anchored=True), self._guard_env(tmp_path))

    def test_anchored_declaration_inheriting_a_parent_toplevel_rejected(self, tmp_path: Path) -> None:
        # rev-parse succeeds here and names the parent, so a guard that only
        # checked the exit code would pass this root — and _review_sanitize_subject
        # would cd to the parent and write the sanitized subject there.
        parent = self._bare_root(tmp_path, "outer_ws")
        _write_git_skeleton(parent)
        root = parent / "nested_ws"
        root.mkdir()
        with pytest.raises(RuntimeError, match="anchors to .*outer_ws, not to itself"):
            _verify_partition(ScratchRoot(root, anchored=True), self._guard_env(tmp_path))

    def test_unanchored_root_with_no_git_ancestor_passes(self, tmp_path: Path) -> None:
        root = self._bare_root(tmp_path, "unanchored_ws")
        _verify_partition(ScratchRoot(root, anchored=False), self._guard_env(tmp_path))

    def test_unanchored_declaration_with_its_own_git_rejected(self, tmp_path: Path) -> None:
        root = self._bare_root(tmp_path, "unanchored_ws")
        _write_git_skeleton(root)
        with pytest.raises(RuntimeError, match=r"lies inside the git worktree at .*unanchored_ws$"):
            _verify_partition(ScratchRoot(root, anchored=False), self._guard_env(tmp_path))

    def test_unanchored_declaration_below_a_git_ancestor_rejected(self, tmp_path: Path) -> None:
        # The pattern is end-anchored because the root is a CHILD of outer_ws:
        # `match=` searches, so an unanchored `.*outer_ws` would be satisfied by
        # a message naming the root just as well as one naming the ancestor, and
        # naming the offending ancestor is the whole point of this message.
        parent = self._bare_root(tmp_path, "outer_ws")
        _write_git_skeleton(parent)
        root = parent / "unanchored_ws"
        root.mkdir()
        with pytest.raises(RuntimeError, match=r"lies inside the git worktree at .*outer_ws$"):
            _verify_partition(ScratchRoot(root, anchored=False), self._guard_env(tmp_path))

    def test_unanchored_declaration_below_a_git_ancestor_reached_by_symlink_rejected(self, tmp_path: Path) -> None:
        # The lexical chain is clean: nothing at or above tmp_path/linked_ws
        # carries a `.git`, and the worktree is a SIBLING of the root by name.
        # Only resolving the symlink puts the root inside it — which is the
        # chain git itself discovers along, since it walks the physical path.
        outer = self._bare_root(tmp_path, "symlinked_outer_ws")
        _write_git_skeleton(outer)
        inner = outer / "inner_ws"
        inner.mkdir()
        root = tmp_path / "linked_ws"
        root.symlink_to(inner)
        with pytest.raises(RuntimeError, match=r"lies inside the git worktree at .*symlinked_outer_ws$"):
            _verify_partition(ScratchRoot(root, anchored=False), self._guard_env(tmp_path))

    def test_unanchored_declaration_anchored_by_the_env_rejected(self, tmp_path: Path) -> None:
        # No .git at or above the root, so the ancestor walk is satisfied — the
        # filesystem proxy cannot see this. Git can: under GIT_DIR it answers
        # rev-parse successfully, which is the anchored branch.
        elsewhere = self._bare_root(tmp_path, "elsewhere")
        _write_git_skeleton(elsewhere)
        root = self._bare_root(tmp_path, "unanchored_ws")
        env = self._guard_env(tmp_path, GIT_DIR=str(elsewhere / ".git"))
        with pytest.raises(RuntimeError, match="declared unanchored but git selects the worktree"):
            _verify_partition(ScratchRoot(root, anchored=False), env)

    def test_git_unreachable_on_the_probe_path_rejected(self, tmp_path: Path) -> None:
        # The ancestor walk is satisfied, so the probe is what has to answer —
        # and it cannot, because PATH holds no git. Fail closed rather than
        # treat an unanswerable question as a passing declaration.
        root = self._bare_root(tmp_path, "unanchored_ws")
        empty_bin = self._bare_root(tmp_path, "empty_bin")
        env = self._guard_env(tmp_path, PATH=str(empty_bin))
        with pytest.raises(RuntimeError, match="git rev-parse could not be started"):
            _verify_partition(ScratchRoot(root, anchored=False), env)

    def test_probe_that_never_answers_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # A probe that hangs leaves the branch undetermined, which has to fail
        # closed like a contradiction rather than surface as a raw
        # TimeoutExpired from a test-support helper. Raising the exception from
        # a patched ``subprocess.run`` reaches the branch immediately — no real
        # 15-second wait and no timeout parameter threaded through the guard.
        root = self._bare_root(tmp_path, "unanchored_ws")

        def _never_answers(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            raise subprocess.TimeoutExpired(cmd=["git", "rev-parse", "--show-toplevel"], timeout=15)

        monkeypatch.setattr(subprocess, "run", _never_answers)
        with pytest.raises(RuntimeError, match="did not answer within 15s"):
            _verify_partition(ScratchRoot(root, anchored=False), self._guard_env(tmp_path))

    def test_anchored_declaration_with_an_exit_zero_blank_toplevel_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Exit 0 alone does not name a worktree. _review-common.sh:136 takes its
        # anchored branch only on `rev-parse` succeeding AND -n "$top", so a
        # guard that read the status alone would admit a root the wrapper then
        # handles on its CWD-relative branch. No skeleton is written: the probe
        # that would have observed one is stubbed out.
        root = self._bare_root(tmp_path, "anchored_ws")
        self._stub_probe(monkeypatch, returncode=0, stdout="\n")
        with pytest.raises(RuntimeError, match="is not a git toplevel"):
            _verify_partition(ScratchRoot(root, anchored=True), self._guard_env(tmp_path))

    def test_unanchored_declaration_with_an_exit_zero_blank_toplevel_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # The mirror of the case above: a blank toplevel is the CWD-relative
        # branch, which is what this root declares, so exit 0 on its own must
        # not be read as a contradiction.
        root = self._bare_root(tmp_path, "unanchored_ws")
        self._stub_probe(monkeypatch, returncode=0, stdout="\n")
        _verify_partition(ScratchRoot(root, anchored=False), self._guard_env(tmp_path))

    def test_unanchored_declaration_with_a_whitespace_only_toplevel_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # The one payload that inverts the model instead of mirroring it.
        # Command substitution strips trailing newlines ONLY, so `top=" "` is
        # -n-true at _review-common.sh:136 and the wrapper takes its anchored
        # branch. A guard trimming with `.strip()` sees "" and clears the root:
        # the run then anchors while the guard reported it unanchored, which is
        # the single direction of this partition that fails open and silent.
        # Like the two payloads above this is a stub construct, not an answer
        # real git gives — what it locks is the trim rule, against the later
        # edit that swaps `rstrip` for `strip`.
        root = self._bare_root(tmp_path, "unanchored_ws")
        self._stub_probe(monkeypatch, returncode=0, stdout=" \n")
        with pytest.raises(RuntimeError, match="declared unanchored but git selects the worktree"):
            _verify_partition(ScratchRoot(root, anchored=False), self._guard_env(tmp_path))

    def test_anchored_declaration_with_a_failing_probe_that_printed_a_path_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The other half of the two-part test: a named toplevel does not make
        # the branch anchored if the command failed. _review-common.sh:136
        # short-circuits the `&&` on a non-zero status regardless of what was
        # printed, so the guard has to read the status too — and it must fail
        # with its own message, not fall through to the identity compare.
        root = self._bare_root(tmp_path, "anchored_ws")
        self._stub_probe(monkeypatch, returncode=128, stdout=f"{tmp_path / 'somewhere_else'}\n")
        with pytest.raises(RuntimeError, match="is not a git toplevel"):
            _verify_partition(ScratchRoot(root, anchored=True), self._guard_env(tmp_path))

    def test_unanchored_declaration_with_a_failing_probe_that_printed_a_path_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The mirror: stdout naming a path is not a contradiction when the
        # probe exited non-zero, because the shell never reaches `[ -n "$top" ]`
        # and takes the CWD-relative branch this root declares.
        root = self._bare_root(tmp_path, "unanchored_ws")
        self._stub_probe(monkeypatch, returncode=128, stdout=f"{tmp_path / 'somewhere_else'}\n")
        _verify_partition(ScratchRoot(root, anchored=False), self._guard_env(tmp_path))

    def test_run_review_applies_the_guard_to_the_env_it_spawns_with(self, tmp_path: Path) -> None:
        """The guard runs on the spawn path, before the wrapper is spawned.

        The root has no ``.git`` at or above it, so nothing on disk contradicts
        its declaration and every direct-drive test above would pass it. Only
        the ``GIT_DIR`` merged into the spawn env re-anchors it, so raising
        witnesses that ``_run_review`` still calls the guard and still routes
        the caller's own overrides into it. That the mapping is the *assembled*
        one rather than the overrides alone is a separate property — ``GIT_DIR``
        is in both — locked by the test below.
        """
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        elsewhere = self._bare_root(tmp_path, "elsewhere")
        _write_git_skeleton(elsewhere)
        root = _unanchored_root(tmp_path)
        env = _default_env(bin_dir, root)
        env["GIT_DIR"] = str(elsewhere / ".git")
        with pytest.raises(RuntimeError, match="declared unanchored but git selects the worktree"):
            _run_review(tmp_path, env_overrides=env, root=root)
        assert _read_shim_log(log) == [], "guard must reject before the wrapper is spawned"

    def test_run_review_probes_under_the_assembled_env_not_the_overrides(self, tmp_path: Path) -> None:
        """The guard sees the merged mapping, ``HOME`` included.

        ``HOME`` is the whole delta between ``env_overrides`` and the mapping
        ``_run_review`` assembles, which is what makes it the usable
        discriminator — not any claim that real git re-anchors through it. A
        fake git that answers only under the scratch ``HOME`` reports a
        worktree if and only if the guard was handed the assembled env;
        passing the overrides alone leaves the probe unable to name one and
        the contradiction undetected.
        """
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        root = _unanchored_root(tmp_path)
        self._install_home_sensitive_git(bin_dir, home=tmp_path / "home", toplevel=root.path)
        env = _default_env(bin_dir, root)
        assert "HOME" not in env, "the delta this test turns on has to be absent from the overrides"
        with pytest.raises(RuntimeError, match="declared unanchored but git selects the worktree"):
            _run_review(tmp_path, env_overrides=env, root=root)
        assert _read_shim_log(log) == [], "guard must reject before the wrapper is spawned"


# ---------------------------------------------------------------------------
# Preconditions the scratch machinery states in prose.
#
# Scratch containment — the root under the test's own tmp_path — is a separate
# check from the partition for the reason _require_scratch_containment records,
# and nothing above observes it. It is also a different question from the
# wrapper's DIFF_FILE containment check, which bounds the subject rather than
# the root; TestDiffFileValidation owns that one.
#
# The three decision-procedure cases below are driven directly rather than
# through _run_review: two of them name the live checkout, where a regression
# in the guard turns a _run_review-level case into a wrapper run inside it.
# The spawn path is instead locked from a root that is outside tmp_path and
# still disposable.
# ---------------------------------------------------------------------------


class TestScratchRootPreconditions:
    """``_run_review`` and the root builders enforce what their docstrings claim."""

    @staticmethod
    def _uncontained_root(tmp_path: Path, name: str) -> ScratchRoot:
        """Provision a fully-seeded anchored root that is NOT inside ``tmp_path``.

        Returns:
            A root in pytest's basetemp — as disposable as ``tmp_path`` itself,
            so a guard regression lands here rather than in the live checkout,
            while still clearing every wrapper gate through to the shim call.
            That second half is what makes an absent artifact an observation
            instead of an accident.

        Args:
            name: distinct per caller. The basetemp is shared by every test in
                the session, so two callers reusing a name would address one
                root — see ``_provision_root``.
        """
        root = _provision_root(tmp_path.parent, name)
        _write_git_skeleton(root)
        return ScratchRoot(root, anchored=True)

    def test_a_root_outside_tmp_path_is_rejected(self, tmp_path: Path) -> None:
        """A root naming the live checkout is refused.

        Nothing else in the module stops this: the checkout is a git toplevel in
        its own right, so the anchored declaration is truthful and
        ``_verify_partition`` clears it.
        """
        with pytest.raises(RuntimeError, match="is not strictly inside the test's tmp_path"):
            _require_scratch_containment(ScratchRoot(WORKSPACE, anchored=True), tmp_path)

    def test_a_tmp_path_symlink_to_the_checkout_is_rejected(self, tmp_path: Path) -> None:
        """A symlink under ``tmp_path`` pointing at the checkout is refused.

        Lexically this root is a child of ``tmp_path``; only resolution reveals
        the live tree, for the reason ``_require_scratch_containment`` records.
        """
        link = tmp_path / "linked_ws"
        link.symlink_to(WORKSPACE)
        with pytest.raises(RuntimeError, match="is not strictly inside the test's tmp_path"):
            _require_scratch_containment(ScratchRoot(link, anchored=True), tmp_path)

    def test_tmp_path_itself_is_rejected_as_a_root(self, tmp_path: Path) -> None:
        """``tmp_path`` itself is not a usable root, for the reason ``_provision_root`` records."""
        with pytest.raises(RuntimeError, match="is not strictly inside the test's tmp_path"):
            _require_scratch_containment(ScratchRoot(tmp_path, anchored=False), tmp_path)

    def test_run_review_rejects_an_uncontained_root_before_spawning(self, tmp_path: Path) -> None:
        """The scratch-containment check is on the spawn path, not merely in a helper.

        This root clears every wrapper gate, so a run reaching the spawn calls
        the shim AND writes its review output — the wrapper truncates
        ``tmp/gemini-review-output-<ROUND>.md`` on the way into ``run_gemini``.
        Both absences are therefore observations of the same reordering: a check
        moved below the spawn still raises, and only the artifacts separate that
        from a check that ran first.

        ``tmp/gemini-exit.json`` cannot serve here. A cleared run exits 0, so the
        wrapper's failure block never runs and the exit signal is never written —
        the assertion would hold whether or not the wrapper ran.

        The live-checkout root above cannot witness this at all: its ``DIFF_FILE``
        names a subject that is not there, so the wrapper would die at that gate
        with the log empty either way.
        """
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        root = self._uncontained_root(tmp_path, "uncontained_ws")
        env = _default_env(bin_dir, root)
        with pytest.raises(RuntimeError, match="is not strictly inside the test's tmp_path"):
            _run_review(tmp_path, env_overrides=env, root=root)
        assert _read_shim_log(log) == [], "scratch containment must reject before the wrapper is spawned"
        assert not (root.path / "tmp" / f"gemini-review-output-{_ROUND}.md").exists(), "the wrapper ran and wrote into the uncontained root"

    def test_scratch_containment_is_checked_before_the_partition_probe(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An uncontained root starts no subprocess at all, not even the probe.

        ``_probe_git_toplevel`` runs with ``cwd=root``, so a scratch-containment
        check ordered after ``_verify_partition`` still blocks the wrapper while
        having already run git inside the tree the root names. Both orderings
        raise the same error, so the recorder — not the exception — is what
        separates them.
        """
        probed: list[Path] = []

        def _record(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
            probed.append(root)
            return subprocess.CompletedProcess(["git", "rev-parse", "--show-toplevel"], 0, f"{root}\n", "")

        monkeypatch.setattr(sys.modules[__name__], "_probe_git_toplevel", _record)
        bin_dir = _install_shim(tmp_path)
        root = self._uncontained_root(tmp_path, "probe_order_ws")
        env = _default_env(bin_dir, root)
        with pytest.raises(RuntimeError, match="is not strictly inside the test's tmp_path"):
            _run_review(tmp_path, env_overrides=env, root=root)
        assert probed == [], "the partition probe ran from a root scratch containment had not cleared"

    def test_a_home_override_is_rejected(self, tmp_path: Path) -> None:
        """``env_overrides`` cannot displace the scratch ``HOME``.

        The merge loop applies overrides last, so a caller-supplied ``HOME``
        would win — putting ``$HOME/.gemini`` and git's global config back
        wherever it pointed, and neutering the discriminator the assembled-env
        test turns on.
        """
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        root = _unanchored_root(tmp_path)
        env = _default_env(bin_dir, root)
        env["HOME"] = str(tmp_path / "not_the_scratch_home")
        with pytest.raises(RuntimeError, match="env_overrides may not carry HOME"):
            _run_review(tmp_path, env_overrides=env, root=root)
        assert _read_shim_log(log) == [], "the HOME guard must reject before the wrapper is spawned"

    def test_provisioning_rejects_a_missing_template_source(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A template source that is not there is named at the provisioning site.

        ``copytree`` fails on it either way; the check is what turns an errno
        from inside ``shutil`` into a message naming the repository invariant
        that broke.
        """
        monkeypatch.setattr(sys.modules[__name__], "REAL_TEMPLATES_DIR", tmp_path / "no_such_templates")
        with pytest.raises(RuntimeError, match="reviewer templates are missing"):
            _provision_root(tmp_path, "anchored_ws")

    def test_the_template_copy_is_a_copy_not_a_link_into_the_checkout(self, tmp_path: Path) -> None:
        """A scratch root reaches the reviewer templates through its own inodes.

        ``symlink_to`` resolves every read the wrapper makes, so it is invisible
        to every run in this module while restoring a writable path from a
        scratch root into the live checkout — the class of path the scratch roots
        exist to sever.
        Identity is the proof: a destination that is not a link, whose resolved
        path is not the canonical directory, and whose template does not share
        an inode with the canonical one, cannot carry a write there. That is
        established without performing a write, because the write that would
        demonstrate it lands in the live checkout when the property is broken.
        """
        root = _provision_root(tmp_path, "anchored_ws")
        reviewer_dir = root / ".claude" / "prompts" / "reviewer"
        assert not reviewer_dir.is_symlink(), "the reviewer directory is a link into the canonical tree"
        assert reviewer_dir.resolve() != REAL_TEMPLATES_DIR.resolve(), "the reviewer directory resolves onto the canonical tree"
        template = reviewer_dir / "diff.md"
        canonical = REAL_TEMPLATES_DIR / "diff.md"
        assert not template.is_symlink(), "the template itself is a link into the canonical tree"
        assert not template.samefile(canonical), "the template shares an inode with the canonical one, so a write reaches it"
        assert template.read_bytes() == canonical.read_bytes(), "the copy is not the canonical content the wrapper would load"

    def test_provisioning_the_same_root_twice_is_idempotent(self, tmp_path: Path) -> None:
        """A root may be provisioned again without the template copy raising.

        ``copytree`` refuses a destination that already exists, so without
        ``_copy_reviewer_templates``'s early return the second call raises
        ``FileExistsError`` — the call completing at all is the observation. A
        repeat call is reachable because ``_uncontained_root`` provisions into
        the basetemp every test in the session shares, where a name outlives the
        test that created it.

        Nothing is written into the copied template tree to witness this. Under
        the symlink form the test above forbids, such a write would land in the
        live checkout, which is not a thing to do in service of an assertion.

        The non-link identity properties are re-read on the SECOND call rather
        than left to the test above. A repeat provisioning is the only place the
        early return runs, so a variant that cleared the destination and relinked
        it instead would satisfy every remaining assertion here.
        """
        first = _provision_root(tmp_path, "anchored_ws")
        (first / "tmp" / SUBJECT_ARTIFACT).write_text("stale subject\n")
        second = _provision_root(tmp_path, "anchored_ws")
        assert second == first
        reviewer_dir = second / ".claude" / "prompts" / "reviewer"
        template = reviewer_dir / "diff.md"
        assert template.is_file(), "the second call left the root without templates"
        assert not reviewer_dir.is_symlink(), "the second call left the reviewer directory a link into the canonical tree"
        assert not template.is_symlink(), "the second call left the template a link into the canonical tree"
        assert not template.samefile(REAL_TEMPLATES_DIR / "diff.md"), (
            "the second call left the template sharing an inode with the canonical one"
        )
        assert (first / "tmp" / SUBJECT_ARTIFACT).read_text() == _SUBJECT_TEXT, "the subject was not refreshed"


# ---------------------------------------------------------------------------
# The spawn contract.
#
# _run_review's parameter list carries safeguards this slice rests on: ``root``
# is required and keyword-only, and no parameter offers a second way to choose
# the spawn's CWD. Every call site already passes ``root=`` by keyword, so each
# of those can be undone without a single test above noticing.
#
# The mapping and the spawn's own flags are in the same position. The wrapper
# reads plenty _default_env leaves unbound — EFFORT, WORKSPACE,
# REVIEW_SESSION_ID, GEMINI_MODEL, GEMINI_TIMEOUT, PREFLIGHT_CACHE_FILE, of
# which only GEMINI_TIMEOUT is left unbound by the module as a whole — and git,
# invoked from _review-common.sh, reads the whole GIT_* family. That last one is
# why the closure matters: an ambient GIT_DIR would move the run onto the
# anchoring branch it did not declare. _verify_partition probes under the same
# assembled mapping and would reject such a run rather than let it through, so
# what the closure buys is that the outcome stops depending on the environment
# the suite happens to be started in.
# ---------------------------------------------------------------------------


class TestRunReviewSpawnContract:
    """``_run_review``'s parameter list and the shape of the run it starts."""

    def test_root_is_required_and_keyword_only(self) -> None:
        """``root`` may acquire neither a default nor a positional slot.

        A default is a way to spawn without naming a root — whatever it named
        would become the CWD of every call that omitted one. A positional slot
        puts it beside ``tmp_path``, where the two are interchangeable at the
        call site and a swap reports as nothing.
        """
        root = inspect.signature(_run_review).parameters["root"]
        assert root.kind is inspect.Parameter.KEYWORD_ONLY, f"root is {root.kind.name}, so a call site can pass it positionally"
        assert root.default is inspect.Parameter.empty, f"root defaults to {root.default!r}, so a call site can omit it"

    def test_the_parameter_set_offers_no_second_cwd(self) -> None:
        """The spawn's working directory is ``root.path`` and nothing else.

        A second way to set it is a way to set it to a directory that never went
        through ``_require_scratch_containment``. Pinning the whole parameter
        list rather than the absence of the name ``cwd`` is what catches the
        forms that would otherwise slip past: a ``working_dir`` or ``run_from``
        alias, and a ``**kwargs`` — which appears in ``parameters`` under its own
        name and would forward a ``cwd`` straight through to ``subprocess.run``.
        """
        assert list(inspect.signature(_run_review).parameters) == ["tmp_path", "env_overrides", "root", "args", "timeout"]

    @staticmethod
    def _capture_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
        """Run ``_run_review`` with both subprocess calls faked and return the spawn kwargs.

        The probe is stubbed first so the only surviving ``subprocess.run`` is
        the wrapper spawn itself.
        """
        captured: dict[str, object] = {}

        def _capture(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            captured.update(kwargs)
            return subprocess.CompletedProcess(["bash", REVIEW_SCRIPT], 0, "", "")

        bin_dir = _install_shim(tmp_path)
        root = _anchored_root(tmp_path)
        env = _default_env(bin_dir, root)
        TestPartitionGuard._stub_probe(monkeypatch, returncode=0, stdout=f"{root.path}\n")
        monkeypatch.setattr(subprocess, "run", _capture)
        _run_review(tmp_path, env_overrides=env, root=root)
        captured["expected_env"] = {**env, "HOME": str(tmp_path / "home")}
        captured["expected_cwd"] = str(root.path)
        return captured

    def test_the_spawn_gets_a_closed_env_and_the_root_as_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The wrapper receives exactly ``PATH`` + ``HOME`` + the overrides.

        Inheriting the ambient environment would leave every other assertion in
        this module intact while handing the spawn the ``GIT_*`` entries the
        closed mapping exists to exclude.
        """
        captured = self._capture_spawn(tmp_path, monkeypatch)
        assert captured["cwd"] == captured["expected_cwd"]
        assert captured["env"] == captured["expected_env"]

    def test_the_spawn_is_bounded_and_reads_no_stdin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The wrapper cannot outlive its deadline or reach the session's stdin.

        Neither flag has a consequence any other assertion here can see, and both
        fail as a hang rather than as a result. Nothing the wrapper runs today
        reads the caller's stdin — ``cat`` at ``gemini-review.sh``:223 has two
        file operands, ``gemini``'s stdin is that pipe, ``jq -n`` takes null
        input and ``head -c 500`` takes a file operand — so ``DEVNULL`` is a
        forward guard: an edit that introduced a stdin-reading command would
        otherwise block the suite on whatever the session's terminal does. The
        timeout is the same shape of guard against a spawn that never returns to
        report anything at all.
        """
        captured = self._capture_spawn(tmp_path, monkeypatch)
        assert captured["stdin"] is subprocess.DEVNULL
        assert captured["timeout"] == 15


# ---------------------------------------------------------------------------
# The generated shell bodies.
#
# Three helpers in this module write bash and interpolate Python values into
# it. Every production call site passes tmp_path derivatives and plain
# literals, so the quoting that makes those interpolations safe is exercised by
# nothing: strip it and every test above still passes. These tests are its lock,
# and they are the only callers that hand the helpers shell-significant input.
# ---------------------------------------------------------------------------


class TestGeneratedShellBodyQuoting:
    """Values interpolated into generated shell arrive as data, never as syntax."""

    # An apostrophe closes the single-quoted form ``shlex.quote`` emits, so an
    # unquoted interpolation of a path under this directory reaches bash as
    # syntax rather than as a path: an odd count leaves the body unterminated,
    # and an even one pairs into a quoted region that swallows the separators
    # between the two and hands the command a mangled word list. Either way the
    # generated file stops doing what its caller asked.
    _ADVERSARIAL_DIR: str = "it's a dir"
    # A command substitution leaves an observable artifact when it is evaluated
    # instead of carried, which is what separates "quoted" from "looks quoted".
    _SENTINEL: str = "injected-sentinel.txt"

    @staticmethod
    def _run_shim(shim: Path, cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Invoke a generated shim directly.

        Args:
            shim: the generated bash file.
            cwd: working directory, and therefore where an evaluated command
                substitution drops its artifact — callers put the sentinel here.
            args: argv forwarded to the shim.

        Returns:
            The completed run.

        Driving the shim directly rather than through ``_run_review`` keeps the
        observation on the quoting: a wrapper run would have to clear every
        argument gate first, and a parse failure in the shim would reach the
        assertions only as a generic non-zero wrapper exit.
        """
        return subprocess.run(
            ["bash", str(shim), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(cwd)},
            cwd=str(cwd),
        )

    def test_install_shim_refuses_a_non_integer_exit_code(self, tmp_path: Path) -> None:
        """``exit_code`` is bound by ``:d``, which formats an integer and nothing else.

        This is a typing contract, not a runtime-injection one, and that is why
        no other test can observe it: the parameter is annotated ``int``, every
        call site passes a literal, and ``7`` renders identically with or
        without the format spec. Typing the VALUE ``Any`` reproduces what an
        untyped call site would hand it — a ``**kwargs`` splat, a value read out
        of JSON — without an inline suppression and without erasing the callable:
        the call keeps full arity and keyword checking, so a rename or a
        signature change here still fails type-checking.

        The refusal has to land before the body is assembled, since a value
        reaching the ``exit`` line unquoted is a second statement.
        """
        injected: Any = "0; touch pwned"
        with pytest.raises(ValueError, match="Unknown format code 'd'"):
            _install_shim(tmp_path, exit_code=injected)
        assert not (tmp_path / "bin" / "gemini").exists(), "the shim was written before exit_code was validated"

    def test_install_shim_carries_adversarial_paths_and_payload(self, tmp_path: Path) -> None:
        """``_install_shim`` quotes both interpolated paths and the stderr payload.

        Unquoting a path mangles the command line that runs the helper;
        unquoting the payload hands ``printf`` a command to run and a word list
        instead of one string. The run also exercises ``exit_code`` and
        ``stderr_text``, whose only production callers are these tests.
        """
        parent = tmp_path / self._ADVERSARIAL_DIR
        parent.mkdir()
        log = tmp_path / f"{self._ADVERSARIAL_DIR} logs" / "calls.log"
        log.parent.mkdir()
        payload = f"Error: 429 $(touch {self._SENTINEL}) Too Many Requests"
        bin_dir = _install_shim(parent, exit_code=7, stderr_text=payload, log_path=log)
        result = self._run_shim(bin_dir / "gemini", tmp_path, ["-m", "gemini-3.1-pro-high"])
        assert result.returncode == 7, result.stderr
        assert not (tmp_path / self._SENTINEL).exists(), "the payload's command substitution was evaluated"
        assert result.stderr.rstrip("\n") == payload
        records = _read_shim_log(log)
        assert records, "the helper never logged, so one of the two interpolated paths did not survive"
        assert records[0]["argv"] == ["-m", "gemini-3.1-pro-high"]

    def test_install_shim_with_sequence_carries_adversarial_paths_and_payload(self, tmp_path: Path) -> None:
        """The sequence shim quotes all five of the paths it interpolates.

        Four sit under the adversarial parent and the log under an adversarial
        sibling, so every one of them carries an apostrophe and unquoting any
        breaks the line it sits on. The payload reaches the shim through a data file rather
        than the body; the assertion on it locks the quoted expansion that
        prints it back, which is a different property from the quoting above.
        """
        parent = tmp_path / self._ADVERSARIAL_DIR
        parent.mkdir()
        log = tmp_path / f"{self._ADVERSARIAL_DIR} logs" / "calls.log"
        log.parent.mkdir()
        payload = f"Error: 503 $(touch {self._SENTINEL}) Service Unavailable"
        bin_dir = _install_shim_with_sequence(parent, exit_codes=[5], stderr_texts=[payload], log_path=log)
        result = self._run_shim(bin_dir / "gemini", tmp_path, ["-m", "gemini-3.1-pro-high"])
        assert result.returncode == 5, result.stderr
        assert not (tmp_path / self._SENTINEL).exists(), "the payload's command substitution was evaluated"
        assert result.stderr.rstrip("\n") == payload
        records = _read_shim_log(log)
        assert records, "the helper never logged, so one of the interpolated paths did not survive"
        assert records[0]["argv"] == ["-m", "gemini-3.1-pro-high"]

    def test_home_sensitive_git_carries_adversarial_home_and_toplevel(self, tmp_path: Path) -> None:
        """The fake git quotes the ``HOME`` it compares and the toplevel it prints.

        The generator belongs to ``TestPartitionGuard``, which owns the only
        other caller; the property it shares with the two shim builders is what
        puts its lock here.
        """
        bin_dir = tmp_path / f"{self._ADVERSARIAL_DIR} bin"
        bin_dir.mkdir()
        home = tmp_path / f"{self._ADVERSARIAL_DIR} home"
        toplevel = Path(f"{tmp_path}/top $(touch {self._SENTINEL}) level")
        TestPartitionGuard._install_home_sensitive_git(bin_dir, home=home, toplevel=toplevel)
        probe = _probe_git_toplevel(tmp_path, {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(home)})
        assert probe.returncode == 0, probe.stderr
        assert not (tmp_path / self._SENTINEL).exists(), "the toplevel's command substitution was evaluated"
        assert probe.stdout.rstrip("\n") == str(toplevel)


# ---------------------------------------------------------------------------
# The live-checkout artifact guard.
#
# _no_live_checkout_artifacts is the module's backstop: every root above is
# supposed to keep the wrapper inside tmp_path, and this fixture is what reports
# the case where one did not. Nothing above observes it — drop autouse=True, or
# delete the fixture outright, and every test above still passes — so its watch
# set, its comparison and its tolerance of an entry it cannot stat are locked
# here.
#
# Every test below that needs a checkout to act on monkeypatches WORKSPACE to
# its own tmp_path. pytest sets an autouse fixture up before the fixtures a test
# requests and tears it down after them, so the guard's own before/after pair
# brackets the monkeypatch and still reads the real checkout on both sides.
# ---------------------------------------------------------------------------


class TestLiveCheckoutArtifactGuard:
    """The watch set covers what the wrappers touch, and the comparison fires."""

    # Wrapper-named tmp/ paths deliberately left outside the watch set, spelled
    # ``tmp/<name>`` to match the WORKSPACE-relative keys the snapshot returns.
    # Empty: every path gemini-review.sh and _review-common.sh name is watched,
    # and an exemption has to be argued here rather than assumed by omission.
    _UNWATCHED_WRAPPER_TMP_PATHS: frozenset[str] = frozenset()

    # The tmp/ names ``wrapper_tmp_paths`` derives from the two wrapper sources
    # under this module's substitutions, pinned rather than left to whatever the
    # scan returns. The coverage comparison below proves only that everything the
    # scanner FOUND is watched, so a wrapper edit the scanner cannot see would
    # narrow the derived set with the comparison still empty — the regex has no
    # ``/`` in its character class and does not expand a shell variable, and
    # gemini-review.sh already spells the output directory as one
    # (``OUTPUT_DIR="tmp"`` at :137, used at :142), so rewriting :138 as
    # ``"${OUTPUT_DIR}/gemini-review-output-${ROUND}.md"`` is a pure rename that
    # would drop this module's most important artifact from the derivation.
    # ``gemini-subject-sanitized-<round>.txt`` is reachable only through
    # _review-common.sh, so pinning it also witnesses that both scanned sources
    # contributed.
    _DERIVED_WRAPPER_TMP_NAMES: frozenset[str] = frozenset({
        ".gemini-preflight-cache.json",
        "gemini-exit.json",
        "gemini-review-err.txt",
        f"gemini-review-output-{_ROUND}.md",
        f"gemini-subject-sanitized-{_ROUND}.txt",
    })

    @staticmethod
    def _relocate_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Point ``WORKSPACE`` at ``tmp_path`` and return its ``tmp/`` directory."""
        monkeypatch.setattr(sys.modules[__name__], "WORKSPACE", tmp_path)
        live_tmp = tmp_path / "tmp"
        live_tmp.mkdir()
        return live_tmp

    def test_the_watch_set_covers_every_tmp_path_the_wrappers_name(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every ``tmp/`` path read out of the wrapper sources is watched.

        This is the mechanical half of the guard: the watch set is a handful of
        globs, and a wrapper that starts writing a new ``tmp/`` name would
        otherwise leave the blast radius quietly narrower than the prose claims.
        The paths are created and put through ``_live_artifact_snapshot`` rather
        than matched against the patterns by hand, so the assertion runs the
        same matcher the fixture does.

        The derivation is pinned first, for the reason
        ``_DERIVED_WRAPPER_TMP_NAMES`` records: a coverage comparison over a set
        the scanner silently under-read would pass on the artifacts it missed.
        """
        named = wrapper_tmp_paths([Path(REVIEW_SCRIPT), REVIEW_COMMON], {"ROUND": _ROUND, "suffix": _ROUND, "reviewer": "gemini"})
        assert named == self._DERIVED_WRAPPER_TMP_NAMES, (
            "the scan no longer derives the pinned names; a wrapper source moved, gained a tmp/ path, or now spells one through a variable"
        )
        live_tmp = self._relocate_workspace(tmp_path, monkeypatch)
        for name in sorted(named):
            (live_tmp / name).write_text("live artifact\n")
        uncovered = {f"tmp/{name}" for name in named} - set(_live_artifact_snapshot())
        assert uncovered == self._UNWATCHED_WRAPPER_TMP_PATHS

    def test_the_watch_set_covers_the_test_owned_subjects(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both subject names this module writes are watched.

        Neither is wrapper-named, so the mechanical guard above does not reach
        them. ``SUBJECT_ARTIFACT`` happens to share the ``gemini-`` prefix; the
        empty one shares a prefix with no wrapper path at all and is the reason
        the watch set carries a literal name alongside its globs.
        """
        live_tmp = self._relocate_workspace(tmp_path, monkeypatch)
        (live_tmp / SUBJECT_ARTIFACT).write_text(_SUBJECT_TEXT)
        (live_tmp / EMPTY_SUBJECT_ARTIFACT).touch()
        assert set(_live_artifact_snapshot()) == {f"tmp/{SUBJECT_ARTIFACT}", f"tmp/{EMPTY_SUBJECT_ARTIFACT}"}

    def test_the_watch_set_ignores_a_tmp_file_neither_wrapper_names(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A ``tmp/`` file outside the watched prefixes is not reported.

        Every other test here relocates ``WORKSPACE`` onto a directory holding
        only its own files, so widening a glob to ``tmp/*`` satisfies all of
        them. This is the case that separates the watched set from the whole of
        ``tmp/``: the real checkout's ``tmp/`` also carries junit XML, pytest
        caches and the other bridges' review outputs, and reporting a concurrent
        write to one of those would fail whichever test happened to be running.
        """
        live_tmp = self._relocate_workspace(tmp_path, monkeypatch)
        (live_tmp / "junit.xml").write_text("<testsuite/>\n")
        (live_tmp / "codex-review-output-1.md").write_text("another bridge's output\n")
        assert _live_artifact_snapshot() == {}

    def test_the_watch_set_spans_both_directories_and_keys_on_the_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``agent-review/`` is watched too, and a shared basename stays two entries.

        ``wrapper_tmp_paths`` reads ``tmp/`` names only, so the container branch's
        output directory is outside the mechanical guard above and is named here
        instead. The routed name carries no ``gemini-`` prefix — the wrapper
        builds it from ``${WORKSPACE}`` first — which is what a watch pattern
        borrowed from the ``tmp/`` side would miss.
        """
        live_tmp = self._relocate_workspace(tmp_path, monkeypatch)
        agent_review = tmp_path / "agent-review"
        agent_review.mkdir()
        (live_tmp / "gemini-exit.json").write_text("host signal\n")
        (agent_review / "gemini-exit.json").write_text("same basename, other directory\n")
        (agent_review / "brownfield-ai-gemini-review-output-test-session.md").write_text("routed output\n")
        assert set(_live_artifact_snapshot()) == {
            "tmp/gemini-exit.json",
            "agent-review/gemini-exit.json",
            "agent-review/brownfield-ai-gemini-review-output-test-session.md",
        }

    def test_the_snapshot_reports_a_created_and_a_deleted_artifact(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A new artifact and a removed one both change the snapshot.

        The deleted path is the dot-prefixed preflight cache, which is the one
        live-checkout artifact the wrapper REMOVES — ``gemini-review.sh``:348, on
        any auth or missing-binary classification — and the one
        ``test_pro_auth_error_no_fallback`` reaches without an override.
        """
        live_tmp = self._relocate_workspace(tmp_path, monkeypatch)
        cache = live_tmp / ".gemini-preflight-cache.json"
        cache.write_text('{"mode":"local"}\n')
        before = _live_artifact_snapshot()
        assert "tmp/.gemini-preflight-cache.json" in before, "a dot-prefixed artifact is outside the watch set"
        cache.unlink()
        (live_tmp / f"gemini-review-output-{_ROUND}.md").write_text("written by the run\n")
        after = _live_artifact_snapshot()
        assert set(before) - set(after) == {"tmp/.gemini-preflight-cache.json"}
        assert set(after) - set(before) == {f"tmp/gemini-review-output-{_ROUND}.md"}

    def test_the_snapshot_reports_a_rewrite_inside_one_mtime_tick(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A rewrite is reported even when the mtime is identical.

        The mtime is pinned back to its pre-write value, which is what a rewrite
        landing inside a single clock tick does on its own. Recording the mtime
        alone reads that as no change at all; the size is the second component
        that separates them.
        """
        live_tmp = self._relocate_workspace(tmp_path, monkeypatch)
        cache = live_tmp / ".gemini-preflight-cache.json"
        cache.write_text('{"mode":"local"}\n')
        stamp = cache.stat()
        before = _live_artifact_snapshot()
        cache.write_text('{"mode":"container","gemini":{"cli":false}}\n')
        os.utime(cache, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert cache.stat().st_mtime_ns == stamp.st_mtime_ns, "the mtime moved, so this no longer tests the size component"
        assert _live_artifact_snapshot() != before

    def test_the_snapshot_tolerates_an_entry_it_cannot_stat(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unstattable entry is recorded absent instead of raising out of teardown.

        A dangling symlink reproduces what a delete landing between the glob and
        the ``stat`` produces. Letting that escape would replace the fixture's
        named assertion with an error attributed to teardown, on a test that may
        have done nothing wrong.
        """
        live_tmp = self._relocate_workspace(tmp_path, monkeypatch)
        (live_tmp / "gemini-review-err.txt").write_text("kept\n")
        (live_tmp / "gemini-dangling.md").symlink_to(tmp_path / "no_such_target")
        assert set(_live_artifact_snapshot()) == {"tmp/gemini-review-err.txt"}

    def test_the_fixture_is_autouse(self) -> None:
        """``_no_live_checkout_artifacts`` applies without being requested.

        Dropping ``autouse=True`` leaves a fixture nothing requests, so the
        guard stops running everywhere while every other test in the module
        still passes — the exact failure mode it exists to prevent, applied to
        itself.
        """
        marker = getattr(globals()["_no_live_checkout_artifacts"], "_fixture_function_marker", None)
        assert marker is not None, "pytest no longer exposes the fixture marker here — update this assertion"
        assert marker.autouse

    def test_the_fixture_fails_a_test_that_changed_a_watched_artifact(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Driving the fixture's own generator shows the comparison firing.

        pytest wraps a fixture in an object that refuses direct calls and leaves
        the undecorated generator at ``__wrapped__``. Advancing it by hand is how
        a guard whose whole job is to fail the test it is attached to gets
        observed without standing up a nested pytest session to fail.
        """
        live_tmp = self._relocate_workspace(tmp_path, monkeypatch)
        guard = globals()["_no_live_checkout_artifacts"].__wrapped__()
        next(guard)
        (live_tmp / "gemini-exit.json").write_text("written by the run\n")
        with pytest.raises(AssertionError, match="watched artifacts under .* differ across this test"):
            next(guard)

    def test_the_fixture_passes_a_test_that_changed_nothing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The mirror: an untouched checkout is not reported.

        Without this, a guard hard-wired to fail would satisfy the test above
        while making every other test in the module unrunnable.
        """
        live_tmp = self._relocate_workspace(tmp_path, monkeypatch)
        (live_tmp / "gemini-exit.json").write_text("left alone\n")
        guard = globals()["_no_live_checkout_artifacts"].__wrapped__()
        next(guard)
        with pytest.raises(StopIteration):
            next(guard)
