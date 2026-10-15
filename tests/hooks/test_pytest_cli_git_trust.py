"""Regression test for the safe.directory entry in docker/pytest-cli/Dockerfile.

pytest-cli runs as the system user ``agent``, whose uid does not own the
bind-mounted checkout on a Linux runner. Without the image's system-scope
``safe.directory /app``, git's ownership check refuses every call against the
repo. Docker Desktop remaps bind-mount ownership, so this only fails on Linux.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Strip every source of trust except the image's system gitconfig, so the test
# passes only if the Dockerfile entry is present.
_SYSTEM_SCOPE_ONLY_ENV = {
    **{key: value for key, value in os.environ.items() if not key.startswith("GIT_CONFIG")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_COUNT": "0",
}


@pytest.mark.skipif(not Path("/.dockerenv").exists(), reason="checks the pytest-cli image's system gitconfig")
def test_git_reads_mounted_checkout_with_system_config_only() -> None:
    """Git must read the /app checkout using only the image's system config."""
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", "docker/pytest-cli/Dockerfile"],
        cwd=REPO_ROOT,
        env=_SYSTEM_SCOPE_ONLY_ENV,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"git refused the mounted checkout; is `safe.directory /app` still in docker/pytest-cli/Dockerfile?\nstderr: {result.stderr}"
    )
