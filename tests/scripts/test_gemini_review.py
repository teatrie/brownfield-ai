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
``tmp_path``. The wrapper resolves its exit signal, review output and preflight
cache against the CWD, and ``_review-common.sh`` resolves the sanitized subject
against the git toplevel it discovers from that CWD — so a spawn inheriting the
pytest process CWD writes the artifacts a live review uses.

Two kinds of root exist because ``_review-common.sh`` branches on ``git
rev-parse --show-toplevel``: ``_anchored_root`` IS its own git toplevel and
drives the absolute-path branch, ``_unanchored_root`` has no ``.git`` ancestor
and drives the CWD-relative branch. ``_run_review`` puts every root through
``_verify_partition`` before spawning anything.

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

import json
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, TypedDict

import pytest

WORKSPACE: Path = Path(__file__).resolve().parents[2]
REVIEW_SCRIPT: str = str(WORKSPACE / "scripts" / "agent-cli" / "gemini-review.sh")
# Canonical reviewer templates. Read-only: each scratch root symlinks this
# directory into place so ``_review_template_path`` resolves, and the wrapper
# only concatenates the template it finds there.
REAL_TEMPLATES_DIR: Path = WORKSPACE / ".claude" / "prompts" / "reviewer"

# Standard diff-subject filenames used across tests. The wrapper's
# _review_validate_diff_file helper only accepts files realpath-contained
# under the run's own ``tmp/`` or ``agent-review/`` directories, so each
# subject lives in the scratch root the run works from. It imposes no
# basename constraint, so these names are test-owned.
SUBJECT_ARTIFACT: str = "gemini-test-subject.txt"
EMPTY_SUBJECT_ARTIFACT: str = "empty-subject-for-gemini-test.txt"
_SUBJECT_TEXT: str = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@\n-a\n+b\n"

# The round every run here executes at. Every env this module builds passes it
# through, so assertions can name tmp/gemini-review-output-<ROUND>.md and
# observe the resolved round end to end. The value itself carries no meaning —
# it is pinned only to be distinct from the wrapper's own default.
_ROUND: str = "999"


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

    Every Python value reaching the generated script goes through
    ``shlex.quote``: these bodies are shell *syntax*, so a quote, backtick or
    ``$(...)`` in a path or a stderr line would otherwise be parsed rather
    than carried.
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
    selects and ``_verify_partition`` holds it to that declaration — silently
    landing on the other branch would leave every assertion passing while the
    branch went uncovered.
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


def _unanchored_root(tmp_path: Path, *, agent_review: bool = False) -> ScratchRoot:
    """Return a scratch root with no ``.git`` at or above it.

    Args:
        agent_review: also create the ``agent-review/`` sibling of ``tmp/``.
            Off by default — only the container-routing branch writes there,
            and ``_review_validate_diff_file`` tolerates its absence.

    Returns:
        The root to spawn the wrapper from, seeded with ``tmp/<subject>`` and
        the reviewer templates.
    """
    root = _provision_root(tmp_path, "unanchored_ws")
    if agent_review:
        (root / "agent-review").mkdir(exist_ok=True)
    return ScratchRoot(root, anchored=False)


def _provision_root(tmp_path: Path, name: str) -> Path:
    """Create a scratch root carrying the file structure gemini-review.sh needs.

    Returns:
        The created root.

    The root is a child of ``tmp_path`` rather than ``tmp_path`` itself so the
    mock bin dir, the scratch ``HOME`` and the explicitly-passed cache files
    stay outside the tree a wrapper can reach through a CWD-relative write.
    """
    root = tmp_path / name
    (root / "tmp").mkdir(parents=True, exist_ok=True)
    (root / "tmp" / SUBJECT_ARTIFACT).write_text(_SUBJECT_TEXT)
    _link_reviewer_templates(root)
    return root


def _link_reviewer_templates(root: Path) -> None:
    """Symlink the canonical reviewer templates into a scratch root.

    ``_review_template_path`` yields ``.claude/prompts/reviewer/<type>.md``
    under the run's toplevel or CWD, so the root has to resolve that path.
    Mirroring the directory by symlink keeps the templates a single read-only
    source rather than a copy that can drift.
    """
    claude_dir = root / ".claude" / "prompts" / "reviewer"
    if claude_dir.exists() or claude_dir.is_symlink():
        return
    claude_dir.parent.mkdir(parents=True, exist_ok=True)
    claude_dir.symlink_to(REAL_TEMPLATES_DIR)


def _write_git_skeleton(root: Path) -> None:
    """Make ``root`` a repository git accepts as a worktree toplevel.

    An empty ``.git`` directory does NOT qualify: ``git rev-parse
    --show-toplevel`` rejects it and discovery continues UP. Where ``tmp_path``
    sits inside a real checkout — a ``TMPDIR`` pointed into the working tree —
    that walk returns the enclosing checkout at exit 0, silently re-anchoring
    the wrapper onto the live repository; where it does not, the walk
    terminates at ``/`` and git exits 128. ``HEAD`` naming a ref plus the
    ``objects/`` and ``refs/`` directories is the minimum git accepts.
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
    run fails the guard whichever branch was declared. The unanchored side
    keeps the ancestor walk ahead of that probe because the walk is a pure
    filesystem check that no environment entry can silence, whereas the probe
    can be (``GIT_CEILING_DIRECTORIES``, an ownership refusal); running the
    un-suppressible check first means a suppressed probe cannot buy a pass for
    a root that plainly sits in a worktree.
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
    """
    probe = _probe_git_toplevel(root, env)
    reported = probe.stdout.strip()
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
    """
    probe = _probe_git_toplevel(root, env)
    reported = probe.stdout.strip()
    if probe.returncode == 0 and reported:
        raise RuntimeError(f"scratch root {root} is declared unanchored but git selects the worktree at {reported} under this environment")


def _reject_git_ancestor(root: Path) -> None:
    """Fail when ``root`` or any ancestor of it is a git worktree.

    Raises:
        RuntimeError: a ``.git`` entry exists at or above ``root``, which would
            route wrapper writes to that worktree instead of the scratch root.

    Both the lexical chain and the symlink-resolved chain are walked because
    git discovers a worktree along the physical path, so a ``.git`` that only
    appears once symlinks are resolved would escape a lexical walk.
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
        The completed ``git rev-parse --show-toplevel`` run. Return code 0
        means git selected a worktree and stdout names it.

    Raises:
        RuntimeError: no git was found on ``env``'s ``PATH`` (or ``root`` no
            longer exists), or the probe did not answer within its timeout.
            Other start failures — a non-executable git, a ``root`` that is not
            a directory — propagate as the ``OSError`` subclass they are.

    ``lang.python.md`` routes git operations through GitPython; this helper is a
    narrow exception. The question is not "what does git say" but "what will git
    say to the wrapper spawn this root is being vetted for", which depends on
    the ``PATH`` and ``GIT_*`` entries of the exact mapping the spawn receives —
    a library call would answer against this interpreter's ambient environment
    instead. One read-only ``rev-parse``, no repository mutation.
    """
    try:
        return subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
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
        RuntimeError: ``_verify_partition`` rejected ``root`` under the
            assembled env, propagated unchanged — nothing is spawned.

    ``HOME`` is a scratch directory because ``run_gemini`` calls ``mkdir -p
    "$HOME/.gemini"`` unconditionally; it sits beside the scratch root rather
    than inside it. The env mapping is closed — nothing is inherited from
    ``os.environ`` — and the ``GIT_*`` family stays out in particular, since an
    entry like ``GIT_WORK_TREE`` or ``GIT_DIR`` moves a run onto the branch it
    did not declare. Exclusion cannot cover everything that does that: git
    config reaches the same outcome through ``core.worktree``. The scratch
    ``HOME`` does close off the global config route (git resolves
    ``~/.gitconfig`` through ``$HOME``), but the system config
    (``/etc/gitconfig`` — no ``GIT_CONFIG_NOSYSTEM`` is set here) and any
    repository-local config are read regardless of the env. What holds the
    partition is therefore the guard itself — ``_verify_partition`` probes git
    under this exact assembled mapping, from this exact root, before anything
    is spawned.
    """
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
        _assert_effort_enum_rejection(root)

    def test_low_rejected_at_enum(self, tmp_path: Path) -> None:
        """``low`` is rejected upfront — reviewer floor is MEDIUM tier (HIGH internal)."""
        root = _anchored_root(tmp_path)
        result, records = self._run_with_effort(tmp_path, effort="low", model="gemini-3.1-pro-preview", root=root)
        assert result.returncode != 0
        assert "EFFORT must be one of {medium,high,xhigh,max}" in result.stderr
        assert records == []
        _assert_effort_enum_rejection(root)


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


def _assert_diff_file_rejection(root: ScratchRoot) -> None:
    """Assert the exit JSON under ``root`` names the DIFF_FILE gate specifically.

    ``error_class`` is ``arg_validation`` for every argument gate, so the
    excerpt is what distinguishes this rejection from a REVIEW_TYPE, EFFORT or
    ``--round`` one.
    """
    exit_json = _read_exit_json(root)
    assert exit_json.get("signal") == "GEMINI_ERROR"
    assert exit_json.get("error_class") == "arg_validation"
    assert exit_json.get("stderr_excerpt") == "DIFF_FILE invalid or missing"


def _assert_effort_enum_rejection(root: ScratchRoot) -> None:
    """Assert the exit JSON under ``root`` names the EFFORT gate specifically.

    The stderr message alone does not witness that the run left a machine-
    readable signal behind, nor that it landed under the scratch root rather
    than the CWD the pytest process was started from; only reading the file
    back from ``root`` does both.
    """
    exit_json = _read_exit_json(root)
    assert exit_json.get("signal") == "GEMINI_ERROR"
    assert exit_json.get("error_class") == "arg_validation"
    assert exit_json.get("stderr_excerpt") == "EFFORT enum rejected"


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
        exit_json = _read_exit_json(root)
        assert exit_json.get("signal") == "GEMINI_ERROR"
        assert exit_json.get("error_class") == "arg_validation"
        # error_class is shared by every argument gate; the excerpt is what
        # names REVIEW_TYPE rather than DIFF_FILE, EFFORT or --round.
        assert exit_json.get("stderr_excerpt") == "REVIEW_TYPE invalid or missing"

    def test_invalid_review_type_enum_rejected(self, tmp_path: Path) -> None:
        """REVIEW_TYPE=foo (not in enum) -> arg_validation rejection."""
        log = tmp_path / "calls.log"
        bin_dir = _install_shim(tmp_path, log_path=log)
        root = _anchored_root(tmp_path)
        env = _default_env(bin_dir, root, review_type="foo")
        result = _run_review(tmp_path, env_overrides=env, root=root)
        assert result.returncode != 0
        assert _read_shim_log(log) == []
        exit_json = _read_exit_json(root)
        assert exit_json.get("signal") == "GEMINI_ERROR"
        assert exit_json.get("error_class") == "arg_validation"
        assert exit_json.get("stderr_excerpt") == "REVIEW_TYPE invalid or missing"


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
        _assert_diff_file_rejection(root)

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
        _assert_diff_file_rejection(root)

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
        _assert_diff_file_rejection(root)

    def test_diff_file_outside_tmp_rejected(self, tmp_path: Path) -> None:
        """DIFF_FILE outside tmp/ or agent-review/ -> arg_validation rejection.

        The subject sits at the root itself — a sibling of ``tmp/``, not a
        child of it — which is the placement the containment guard rejects.
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
        _assert_diff_file_rejection(root)


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
        wrapper names both artifacts it writes after the round it resolved, so
        the filenames report the round end to end rather than restating the env
        entry that set it. The two path assertions are branch-insensitive —
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
        exit_json = _read_exit_json(root)
        assert exit_json.get("signal") == "GEMINI_ERROR"
        assert exit_json.get("error_class") == "arg_validation"
        assert exit_json.get("stderr_excerpt") == "--round must be a positive integer >= 1"

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
        exit_json = _read_exit_json(root)
        assert exit_json.get("signal") == "GEMINI_ERROR"
        assert exit_json.get("error_class") == "arg_validation"
        assert exit_json.get("stderr_excerpt") == "--round must be a positive integer >= 1"


class TestTokenAndSecretGuards:
    """Token-missing / secrets-guard behaviors.

    The ``/app/.env`` FATAL guard only trips inside a container and is
    covered by a separate integration test; we verify the token-missing
    signal here (host OAuth path is exercised by every other test via
    ``GEMINI_EXECUTION_CONTEXT=host`` + ``GEMINI_API_KEY=test``).
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
    git toplevel. ``agent-review/`` is provisioned here and nowhere else — the
    container branch routes its output there.
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
        root = _unanchored_root(tmp_path, agent_review=True)
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
        """Container context -> output under ``agent-review/`` with workspace/session id."""
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

        ``root`` is keyword-only for the reason ``_run_review`` makes it so: a
        positional slot next to ``tmp_path`` would put two ``Path``-flavoured
        arguments side by side, which is a silent misrouting waiting to happen,
        and this is the one that decides where every artifact of the run lands.
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
        # bridge". The signal alone is near-tautological here (exit 3 has one
        # producer), so the discriminating assertion is the excerpt: it can
        # only carry the auth stderr of the sole attempt if no second attempt
        # overwrote the capture file.
        assert exit_json.get("signal") == "GEMINI_FALLBACK"
        assert "401 Unauthorized: bad token" in str(exit_json.get("stderr_excerpt"))
        assert exit_json.get("model") == "gemini-3.1-pro-preview"

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
            stdout: raw stdout the fake probe reports, before ``.strip()``.

        Both guards mirror the two-part test at ``_review-common.sh``:136 —
        ``top=$(git rev-parse --show-toplevel 2>/dev/null) && [ -n "$top" ]``.
        A payload is only admissible here if it selects the SAME branch in that
        line as in the guard, and command substitution strips trailing newlines
        ONLY: a stdout of ``" \\n"`` leaves ``top=" "``, which is ``-n``-true in
        the shell while ``.strip()`` makes it falsy in Python — the single
        payload that inverts the model rather than mirroring it. ``"\\n"``
        yields ``top=""`` and a falsy ``reported``: blank to both. A non-zero
        status short-circuits the ``&&`` in the shell whatever was printed,
        matching the guards' exit-status clauses.

        Neither combination arises from real ``git rev-parse --show-toplevel``,
        which is why they are reachable only through a stubbed probe.
        """

        def _fake(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(["git", "rev-parse", "--show-toplevel"], returncode, stdout, "")

        monkeypatch.setattr(sys.modules[__name__], "_probe_git_toplevel", _fake)

    def test_anchored_root_that_is_its_own_toplevel_passes(self, tmp_path: Path) -> None:
        root = self._bare_root(tmp_path, "anchored_ws")
        _write_git_skeleton(root)
        _verify_partition(ScratchRoot(root, anchored=True), self._guard_env(tmp_path))

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

        def _never_answers(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
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
        """The guard runs on the spawn path, before anything is spawned.

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
