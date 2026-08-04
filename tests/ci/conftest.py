"""Fixtures for the ``ci/`` changed-file router tests.

The harness itself — constants, assertions, and the shared ``RouterContract``
— lives in ``helpers.router_harness``; only the fixture needs to be here.
"""

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from helpers.router_harness import GIT_STUB, NOOP_STUB, REPO_ROOT, RouteFn


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
        # Pin the push branch of test_changed.sh so CHANGED_FILES comes from a
        # single intercepted `git diff --name-only`. Its local branch unions
        # four git queries, two of which would leak real worktree state into
        # the fixture. test_staged.sh ignores this variable.
        env["GITHUB_EVENT_NAME"] = "push"

        return subprocess.run(
            ["bash", str(REPO_ROOT / "ci" / script), target],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

    return _route
