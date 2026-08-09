"""Fixtures for the ``ci/`` changed-file router tests.

The harnesses themselves — constants, assertions, and the shared
``RouterContract`` / ``LintRouterContract`` — live in
``helpers.router_harness`` and ``helpers.lint_router_harness``; only the
fixtures need to be here.
"""

import itertools
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from helpers.lint_router_harness import FAILING_TASK_ENV, TASK_STUB, LintRouteFn
from helpers.router_harness import GIT_STUB, NOOP_STUB, REPO_ROOT, RouteFn

#: Event name pinning the push branch of ``lint_changed.sh`` /
#: ``test_changed.sh``, so CHANGED_FILES comes from a single intercepted
#: ``git diff --name-only``. The local branch is stubbed just as completely,
#: but it unions four queries through ``sort -u``, which would deliver the
#: synthetic list deduplicated and reordered; pinning keeps each router's input
#: identical to what the test wrote. The ``*_staged.sh`` routers ignore it.
PINNED_EVENT_NAME = "push"


@pytest.fixture
def route(tmp_path: Path) -> RouteFn:
    """
    Run a router script against a synthetic changed-file list.

    Args:
        tmp_path: pytest-provided scratch directory holding the stubs.

    Returns:
        Callable taking the script filename under ``ci/`` and the changed-file
        list, plus an optional keyword-only ``target`` (default ``scripts``),
        and returning the completed process.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # `task` is stubbed alongside `docker` so a changed-file list reaching the
    # agent-cli branch of test_changed.sh cannot launch the real
    # container-integration suite from a unit test.
    for name, body in (("git", GIT_STUB), ("docker", NOOP_STUB), ("task", NOOP_STUB)):
        stub = bin_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)

    # The routers run against a fake workspace, not the repository. The
    # security gate is invoked by a path relative to the working directory, so
    # this is the only way to shadow it — and it must be shadowed: the gate
    # writes tmp/.python-gate-pass, which in CI is already owned by the outer
    # gate run's uid, so the nested write fails with EACCES and `set -e` kills
    # the router before it announces anything. `tests/` is symlinked in so the
    # `[ -f "$test_file" ]` probes still see real test files.
    workspace = tmp_path / "workspace"
    (workspace / "docker" / "shared").mkdir(parents=True)
    gate = workspace / "docker" / "shared" / "python-security-gate.sh"
    gate.write_text(NOOP_STUB, encoding="utf-8")
    gate.chmod(0o755)
    (workspace / "tmp").mkdir()
    (workspace / "tests").symlink_to(REPO_ROOT / "tests")

    listing = tmp_path / "changed-files.txt"

    def _route(
        script: str,
        changed_files: Sequence[str],
        *,
        target: str = "scripts",
    ) -> subprocess.CompletedProcess[str]:
        listing.write_text("".join(f"{path}\n" for path in changed_files), encoding="utf-8")

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["ROUTER_TEST_CHANGED_FILES"] = str(listing)
        env["GITHUB_EVENT_NAME"] = PINNED_EVENT_NAME

        return subprocess.run(
            ["bash", str(REPO_ROOT / "ci" / script), target],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

    return _route


@pytest.fixture
def lint_route(tmp_path: Path) -> LintRouteFn:
    """
    Run a lint router script against a synthetic changed-file list.

    Args:
        tmp_path: pytest-provided scratch directory holding the stubs.

    Returns:
        Callable taking the script filename under ``ci/`` and the changed-file
        list, plus optional keyword-only ``absent`` (listed paths to leave
        uncreated) and ``failing_task`` (a target the stubbed ``task`` must
        exit non-zero on), and returning the completed process.
    """
    bin_dir = tmp_path / "lint-bin"
    bin_dir.mkdir()
    # `task` echoes its argv instead of no-opping, so an assertion can name the
    # target the router delegated to rather than trusting the banner alone.
    for name, body in (("git", GIT_STUB), ("task", TASK_STUB)):
        stub = bin_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)

    # Parent of the bare per-call workspaces. Both routers read pyproject.toml
    # and .markdownlint-cli2.yaml from the working directory for ignore
    # patterns, and absent means "no ignores", which is what these assertions
    # want. ci/repo_routing.sh is sourced relative to BASH_SOURCE, so it still
    # resolves against the repository — harmless, since `task` is stubbed.
    workspaces = tmp_path / "lint-workspaces"
    workspaces.mkdir()
    workspace_serial = itertools.count()

    listing = tmp_path / "lint-changed-files.txt"

    def _lint_route(
        script: str,
        changed_files: Sequence[str],
        *,
        absent: Sequence[str] = (),
        failing_task: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        # One workspace per call, not one per fixture: the placeholders below
        # would otherwise survive into the next call within the same test,
        # where an assertion on a path's *absence* would be satisfied by the
        # leftover rather than by the router.
        workspace = workspaces / str(next(workspace_serial))
        workspace.mkdir()

        # A misspelt `absent` entry would materialise the path it meant to
        # withhold, and a deletion assertion would then pass against a router
        # that never reads the pre-filter list. Fail on the typo instead.
        unlisted = [path for path in absent if path not in changed_files]
        assert not unlisted, f"`absent` paths must also appear in `changed_files`: {unlisted}"

        # Both routers drop changed paths that are absent from the working
        # tree, so an un-materialised list would route nothing and every
        # assertion would read as a routing hole. Placeholders are created in
        # place rather than symlinked from the repository, so no assertion can
        # depend on real file contents. `absent` withholds the placeholder for
        # a named path, which is the shape of a diff that deletes a file: the
        # changed-file listing still reports it, the working tree does not
        # carry it.
        for path in changed_files:
            if path in absent:
                continue
            placeholder = workspace / path
            placeholder.parent.mkdir(parents=True, exist_ok=True)
            placeholder.touch()

        listing.write_text("".join(f"{path}\n" for path in changed_files), encoding="utf-8")

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["ROUTER_TEST_CHANGED_FILES"] = str(listing)
        env["GITHUB_EVENT_NAME"] = PINNED_EVENT_NAME
        # Written unconditionally: an empty value is the stub's off switch, and
        # assigning it here means an inherited value cannot turn the failure
        # mode on for a route that did not ask for it.
        env[FAILING_TASK_ENV] = failing_task or ""

        return subprocess.run(
            ["bash", str(REPO_ROOT / "ci" / script)],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

    return _lint_route
