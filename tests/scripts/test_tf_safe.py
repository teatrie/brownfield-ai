"""Integration tests for the tf-safe.sh entrypoint in infra-terraform.

Builds the Docker image and verifies that allowed terraform subcommands
(init, fmt, plan, show) are permitted while destructive commands
(apply, destroy, import, workspace) are blocked.
"""

import os
import platform
import subprocess
import warnings

import pytest

IMAGE = "brownfield-ai/infra-terraform:local"


@pytest.fixture(scope="module", autouse=True)
def build_image() -> None:
    """Build the infra-terraform Docker image once per test module."""
    result = subprocess.run(
        [
            "docker",
            "build",
            "-f",
            "docker/builders/Dockerfile.infra-terraform",
            "-t",
            IMAGE,
            "docker/builders",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"Docker build failed:\n{result.stderr}")


def _run_container(cmd: str) -> subprocess.CompletedProcess[str]:
    """Run the infra-terraform container with a single subcommand."""
    return subprocess.run(
        ["docker", "run", "--rm", "--user", "agent", IMAGE, cmd],
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("cmd", ["init", "fmt", "plan", "show"])
def test_allowed_command_not_blocked(cmd: str) -> None:
    """Allowed subcommands must not be rejected by the tf-safe wrapper."""
    result = _run_container(cmd)
    assert "not allowed" not in result.stderr.lower(), f"Command '{cmd}' was blocked by tf-safe but should be allowed:\n{result.stderr}"


@pytest.mark.parametrize("cmd", ["apply", "destroy", "import", "workspace"])
def test_blocked_command_exits_nonzero(cmd: str) -> None:
    """Blocked subcommands should be rejected with exit 1."""
    result = _run_container(cmd)
    assert result.returncode == 1, f"Expected exit 1 for '{cmd}', got {result.returncode}"
    assert "not allowed" in result.stderr.lower(), f"Expected 'not allowed' in stderr for '{cmd}', got:\n{result.stderr}"


def test_no_args_exits_nonzero() -> None:
    """Running with no arguments should print usage and exit 1."""
    result = subprocess.run(
        ["docker", "run", "--rm", "--user", "agent", IMAGE],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "usage" in result.stderr.lower(), f"Expected 'Usage' in stderr, got:\n{result.stderr}"


def test_chained_commands_all_allowed() -> None:
    """Chaining allowed commands with -- separators must not be blocked."""
    result = subprocess.run(
        ["docker", "run", "--rm", "--user", "agent", IMAGE, "init", "--", "fmt"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "not allowed" not in result.stderr.lower(), f"Chained allowed commands were blocked:\n{result.stderr}"


def test_chained_commands_blocked_in_second_position() -> None:
    """A blocked command in any position of a chain must be rejected."""
    result = subprocess.run(
        ["docker", "run", "--rm", "--user", "agent", IMAGE, "init", "--", "apply"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}"
    assert "not allowed" in result.stderr.lower(), f"Expected 'not allowed' in stderr:\n{result.stderr}"


def test_direct_entrypoint_bypass_blocked() -> None:
    """Direct --entrypoint to the hidden binary must be denied for non-root."""
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "agent",
            "--entrypoint",
            "/bin/_tf_exec_internal",
            IMAGE,
            "plan",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0, f"Expected non-zero exit, got {result.returncode}"
    if "permission denied" not in result.stderr.lower():
        # macOS container runtimes (Docker Desktop/LinuxKit, OrbStack, Colima)
        # bypass chmod 0700 on direct --entrypoint exec. On Mac, we verify
        # non-zero exit only (terraform fails due to missing config, not
        # permission denial). On Linux CI, the strict "permission denied"
        # assertion fires. Detected via kernel substring or Darwin platform.
        # See docker/README.md.
        _mac_runtime = any(k in os.uname().release for k in ("linuxkit", "orbstack", "colima")) or platform.system() == "Darwin"
        if _mac_runtime:
            warnings.warn(
                "macOS container runtime bypasses chmod 0700 on --entrypoint exec. "
                "Sudoers and Claude Code deny rules provide fallback coverage.",
                stacklevel=1,
            )
        else:
            raise AssertionError(f"Expected 'permission denied' in stderr:\n{result.stderr}")


def test_bash_entrypoint_bypass_blocked() -> None:
    """Bash shell bypass to the hidden binary must be denied for non-root."""
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "agent",
            "--entrypoint",
            "/bin/bash",
            IMAGE,
            "-c",
            "/bin/_tf_exec_internal plan",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0, f"Expected non-zero exit, got {result.returncode}"
    assert "permission denied" in result.stderr.lower(), f"Expected 'permission denied' in stderr:\n{result.stderr}"
