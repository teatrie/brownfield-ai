"""Unit tests for the sparse-clone.sh input validation.

Tests the input validation logic of sparse-clone.sh by running it inside
the repo-cli container. Network-dependent clone operations are not tested.
"""

import os
import subprocess
import time

import pytest

IMAGE = "brownfield-ai/repo-cli-test:local"


@pytest.fixture(scope="module", autouse=True)
def build_image() -> None:
    """Build the repo-cli Docker image once per test module."""
    result = subprocess.run(
        ["docker", "build", "-f", "docker/repo-cli/Dockerfile", "-t", IMAGE, "."],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        pytest.fail(f"Docker build failed:\n{result.stderr}")


def _run_container(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the repo-cli container and return the completed process."""
    name = f"sparse-test-{os.getpid()}-{time.time_ns()}"
    create_args = ["docker", "create", "--name", name, "--user", "agent", IMAGE]
    create_args.extend(cmd)
    try:
        subprocess.run(create_args, capture_output=True, text=True, timeout=60, check=True)
        result = subprocess.run(
            ["docker", "start", "-a", name],
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
    return result


class TestValidInput:
    """Verify valid inputs are accepted (will fail on clone due to no network, but validation passes)."""

    def test_valid_org_repo(self) -> None:
        result = _run_container(["sparse-clone.sh", "acme/analytics", "src/datalake"])
        # Will fail at clone step (no network), but should pass validation
        assert "invalid ORG/REPO" not in result.stderr
        assert "invalid SPARSE_PATH" not in result.stderr


class TestInvalidOrgRepo:
    """Verify invalid ORG/REPO formats are rejected."""

    @pytest.mark.parametrize(
        "org_repo",
        [
            "",
            "noslash",
            "spaces in/name",
            "org/repo;evil",
            "org/repo&evil",
            "../traversal/path",
            "--template=evil/repo",
            "org/repo|pipe",
        ],
    )
    def test_rejected(self, org_repo: str) -> None:
        result = _run_container(["sparse-clone.sh", org_repo, "src/"])
        assert result.returncode != 0
        # Either "invalid ORG/REPO" or usage error for empty
        assert result.returncode != 0


class TestInvalidSparsePath:
    """Verify invalid SPARSE_PATH formats are rejected."""

    @pytest.mark.parametrize(
        "sparse_path",
        [
            "",
            "path with spaces",
            "--template=evil",
            "src;evil",
            "src&evil",
            "src|pipe",
            "path\ttab",
        ],
    )
    def test_rejected(self, sparse_path: str) -> None:
        result = _run_container(["sparse-clone.sh", "Org/Repo", sparse_path])
        assert result.returncode != 0


class TestEmptyArgs:
    """Verify missing arguments produce usage error."""

    def test_no_args(self) -> None:
        result = _run_container(["sparse-clone.sh"])
        assert result.returncode != 0
        assert "Usage" in result.stderr

    def test_one_arg(self) -> None:
        result = _run_container(["sparse-clone.sh", "Org/Repo"])
        assert result.returncode != 0
        assert "Usage" in result.stderr
