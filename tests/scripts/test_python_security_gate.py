"""Tests for the python-security-gate.sh host-side validation script.

Verifies that the gate script correctly validates Python execution requests
before Docker container invocation, including mode validation, path safety,
git-tracking checks, and artifact generation.
"""

import hashlib
import re
import subprocess
import time
from collections.abc import Generator
from pathlib import Path

import pytest

GATE_SCRIPT = "docker/shared/python-security-gate.sh"
WORKSPACE = Path(__file__).resolve().parents[2]


def run_gate(
    mode: str,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    """Invoke the gate script with the given mode and arguments."""
    cmd = [GATE_SCRIPT, mode, *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(WORKSPACE),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def untracked_py_file() -> Generator[str, None, None]:
    """Create a temporary untracked .py file in tmp/ for rejection tests."""
    path = WORKSPACE / "tmp" / "scratch_gate_test.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# untracked scratch file\n")
    yield str(path.relative_to(WORKSPACE))
    path.unlink(missing_ok=True)


@pytest.fixture()
def symlink_outside_workspace() -> Generator[str, None, None]:
    """Create a symlink inside tmp/ that points outside the workspace."""
    link_path = WORKSPACE / "tmp" / "escape_link.py"
    link_path.parent.mkdir(parents=True, exist_ok=True)
    # Point at /etc/hosts which exists on all POSIX systems
    if link_path.is_symlink() or link_path.exists():
        link_path.unlink()
    link_path.symlink_to("/etc/hosts")
    yield str(link_path.relative_to(WORKSPACE))
    link_path.unlink(missing_ok=True)


@pytest.fixture()
def gate_artifact_dir() -> Generator[Path, None, None]:
    """Ensure the tmp/ directory exists and clean up gate artifacts after."""
    artifact_dir = WORKSPACE / "tmp"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    yield artifact_dir
    # Clean up gate-pass artifact created during the test
    artifact = artifact_dir / ".python-gate-pass"
    artifact.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Negative tests -- must reject with non-zero exit
# ---------------------------------------------------------------------------


class TestRejections:
    """Tests that verify the gate rejects invalid inputs."""

    def test_run_mode_rejects_non_py_file(self) -> None:
        """[Req-001] run mode with non-.py file must be rejected."""
        result = run_gate("run", "scripts/aws_vault_auth.sh")
        assert result.returncode != 0, f"Expected non-zero exit for non-.py file, got {result.returncode}"

    def test_run_mode_rejects_inline_code(self) -> None:
        """[Req-002] run mode with -c flag (inline code) must be rejected."""
        result = run_gate("run", "-c", 'print("hi")')
        assert result.returncode != 0, f"Expected non-zero exit for -c flag, got {result.returncode}"

    def test_run_mode_rejects_module_flag(self) -> None:
        """[Req-003] run mode with -m flag must be rejected."""
        result = run_gate("run", "-m", "http.server")
        assert result.returncode != 0, f"Expected non-zero exit for -m flag, got {result.returncode}"

    def test_run_mode_rejects_untracked_file(self, untracked_py_file: str) -> None:
        """[Req-004] run mode with untracked file must be rejected."""
        result = run_gate("run", untracked_py_file)
        assert result.returncode != 0, f"Expected non-zero exit for untracked file, got {result.returncode}"

    def test_run_mode_rejects_absolute_path_outside_workspace(self) -> None:
        """[Req-005] run mode with path outside workspace must be rejected."""
        result = run_gate("run", "/etc/passwd")
        assert result.returncode != 0, f"Expected non-zero exit for outside-workspace path, got {result.returncode}"

    def test_run_mode_rejects_relative_traversal(self) -> None:
        """[Req-006] run mode with relative path traversal must be rejected."""
        result = run_gate("run", "scripts/../../../etc/passwd")
        assert result.returncode != 0, f"Expected non-zero exit for traversal path, got {result.returncode}"

    def test_empty_arguments_rejected(self) -> None:
        """[Req-007] No path arguments after mode must be rejected."""
        result = run_gate("run")
        assert result.returncode != 0, f"Expected non-zero exit for empty arguments, got {result.returncode}"

    def test_symlink_outside_workspace_rejected(self, symlink_outside_workspace: str) -> None:
        """[Req-008] Symlink resolving outside workspace must be rejected."""
        result = run_gate("run", symlink_outside_workspace)
        assert result.returncode != 0, f"Expected non-zero exit for symlink escape, got {result.returncode}"

    @pytest.mark.parametrize(
        "flag",
        ["-c", "-m"],
        ids=["inline-code", "module"],
    )
    def test_dangerous_flags_rejected(self, flag: str) -> None:
        """[Req-002][Req-003] Dangerous flags -c and -m must be rejected."""
        result = run_gate("run", flag, "payload")
        assert result.returncode != 0, f"Expected non-zero exit for flag '{flag}', got {result.returncode}"


# ---------------------------------------------------------------------------
# Positive tests -- must pass with zero exit
# ---------------------------------------------------------------------------


class TestAcceptances:
    """Tests that verify the gate accepts valid inputs."""

    def test_run_mode_accepts_tracked_py_file(self, gate_artifact_dir: Path) -> None:
        """[Req-009] run mode with tracked .py file must pass and write artifact."""
        result = run_gate("run", "scripts/__init__.py")
        assert result.returncode == 0, f"Expected exit 0 for tracked .py file, got {result.returncode}\nstderr: {result.stderr}"
        artifact = gate_artifact_dir / ".python-gate-pass"
        assert artifact.exists(), f"Gate artifact not found at {artifact}"

    def test_test_mode_accepts_directory_with_pytest_flags(self, gate_artifact_dir: Path) -> None:
        """[Req-010] test mode with directory + pytest flags via -- must pass."""
        result = run_gate(
            "test",
            "tests/scripts/",
            "--",
            "-v",
            "--tb=short",
        )
        assert result.returncode == 0, f"Expected exit 0 for test mode with directory, got {result.returncode}\nstderr: {result.stderr}"

    def test_lint_mode_accepts_allowed_command(self, gate_artifact_dir: Path) -> None:
        """[Req-011] lint mode with allowed ruff command must pass."""
        result = run_gate(
            "lint",
            "ruff",
            "check",
            "--select",
            "S",
            "scripts/",
        )
        assert result.returncode == 0, f"Expected exit 0 for allowed lint command, got {result.returncode}\nstderr: {result.stderr}"


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests that verify edge cases and artifact correctness."""

    def test_multiple_positional_paths_all_validated(self, gate_artifact_dir: Path) -> None:
        """[Req-012] Multiple positional paths must each be validated."""
        result = run_gate(
            "run",
            "scripts/__init__.py",
            "ci/detect_bypasses.py",
        )
        assert result.returncode == 0, f"Expected exit 0 for multiple tracked files, got {result.returncode}\nstderr: {result.stderr}"

    def test_disallowed_lint_command_rejected(self) -> None:
        """[Req-013] lint mode with non-allowlisted command must be rejected."""
        result = run_gate("lint", "rm", "-rf", "/")
        assert result.returncode != 0, f"Expected non-zero exit for disallowed lint command, got {result.returncode}"

    def test_gate_writes_static_artifact(self, gate_artifact_dir: Path) -> None:
        """[Req-014] Gate must write artifact with static filename."""
        result = run_gate("run", "scripts/__init__.py")
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        artifact = gate_artifact_dir / ".python-gate-pass"
        assert artifact.exists(), f"Artifact not found at {artifact}"

    def test_gate_artifact_contains_valid_format(self, gate_artifact_dir: Path) -> None:
        """[Req-015] Gate artifact must contain valid timestamp and hash."""
        result = run_gate("run", "scripts/__init__.py")
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        artifact = gate_artifact_dir / ".python-gate-pass"
        content = artifact.read_text().strip()

        # Expected format: GATE_PASS=<unix_ts>:<sha256_hex>
        pattern = re.compile(r"^GATE_PASS=(\d+):([a-f0-9]{64})$")
        match = pattern.match(content)
        assert match is not None, f"Artifact content does not match expected format 'GATE_PASS=<ts>:<sha256>': {content!r}"
        ts = int(match.group(1))
        # Timestamp must be within the last 60 seconds
        assert abs(time.time() - ts) < 60, f"Artifact timestamp {ts} is not recent"
        # Hash must be a valid SHA-256 of the paths used
        path_hash = hashlib.sha256(b"scripts/__init__.py").hexdigest()
        assert match.group(2) == path_hash, f"Artifact hash mismatch: expected {path_hash}, got {match.group(2)}"

    def test_run_mode_allows_unbuffered_flag(self) -> None:
        """[Req-001] run mode must allow the -u flag (not dangerous)."""
        result = run_gate("run", "-u", "scripts/__init__.py")
        assert result.returncode == 0, f"Expected exit 0 for -u flag, got {result.returncode}\nstderr: {result.stderr}"
