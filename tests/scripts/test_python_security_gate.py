"""Tests for the python-security-gate.sh host-side validation script.

Verifies that the gate script correctly validates Python execution requests
before Docker container invocation, including mode validation, path safety,
git-tracking checks, and artifact generation.

Every run executes a copy of the gate placed at ``GATE_SCRIPT`` under a scratch
root in the test's ``tmp_path``. The gate derives ``WORKSPACE_ROOT`` from its
own location, not from the CWD, so the copy writes its nonce under the scratch
root and resolves and git-checks paths against it. The scratch root is its own
git repo indexing the paths the tests pass as tracked. ``run_gate`` takes the
root as a required argument, so no run falls back to the real checkout.
"""

import hashlib
import re
import shutil
import subprocess
import time
from pathlib import Path

import git
import pytest

GATE_SCRIPT = "docker/shared/python-security-gate.sh"
WORKSPACE = Path(__file__).resolve().parents[2]
GATE_SOURCE = WORKSPACE / GATE_SCRIPT

# Paths the tests rely on being git-tracked, so each keeps reaching the gate
# branch past its ``git ls-files`` check. The gate reads no file content.
_TRACKED_PATHS: tuple[str, ...] = (
    "scripts/__init__.py",
    "scripts/aws_vault_auth.sh",
    "ci/detect_bypasses.py",
    "tests/scripts/placeholder.py",
)


def run_gate(
    root: Path,
    mode: str,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    """Invoke the gate copy under ``root`` with the given mode and arguments."""
    cmd = [GATE_SCRIPT, mode, *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(root),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def gate_root(tmp_path: Path) -> Path:
    """Build a scratch git repo holding a copy of the gate and the tracked paths."""
    root = tmp_path.resolve()
    gate = root / GATE_SCRIPT
    gate.parent.mkdir(parents=True)
    shutil.copy2(GATE_SOURCE, gate)
    for rel in _TRACKED_PATHS:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).touch()
    git.Repo.init(root).index.add([str(root / rel) for rel in _TRACKED_PATHS])
    return root


@pytest.fixture()
def untracked_py_file(gate_root: Path) -> str:
    """Create an untracked .py file in the scratch root's tmp/ for rejection tests."""
    path = gate_root / "tmp" / "scratch_gate_test.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# untracked scratch file\n")
    return str(path.relative_to(gate_root))


@pytest.fixture()
def symlink_outside_workspace(gate_root: Path) -> str:
    """Create a symlink inside the scratch root's tmp/ that points outside it."""
    link_path = gate_root / "tmp" / "escape_link.py"
    link_path.parent.mkdir(parents=True, exist_ok=True)
    # Point at /etc/hosts which exists on all POSIX systems
    link_path.symlink_to("/etc/hosts")
    return str(link_path.relative_to(gate_root))


@pytest.fixture()
def gate_artifact_dir(gate_root: Path) -> Path:
    """Ensure the scratch root's tmp/ directory exists."""
    artifact_dir = gate_root / "tmp"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


# ---------------------------------------------------------------------------
# Negative tests -- must reject with non-zero exit
# ---------------------------------------------------------------------------


class TestRejections:
    """Tests that verify the gate rejects invalid inputs."""

    def test_run_mode_rejects_non_py_file(self, gate_root: Path) -> None:
        """[Req-001] run mode with non-.py file must be rejected."""
        result = run_gate(gate_root, "run", "scripts/aws_vault_auth.sh")
        assert result.returncode != 0, f"Expected non-zero exit for non-.py file, got {result.returncode}"
        assert "run mode only accepts .py files" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_run_mode_rejects_inline_code(self, gate_root: Path) -> None:
        """[Req-002] run mode with -c flag (inline code) must be rejected."""
        result = run_gate(gate_root, "run", "-c", 'print("hi")')
        assert result.returncode != 0, f"Expected non-zero exit for -c flag, got {result.returncode}"
        assert "dangerous flag '-c'" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_run_mode_rejects_module_flag(self, gate_root: Path) -> None:
        """[Req-003] run mode with -m flag must be rejected."""
        result = run_gate(gate_root, "run", "-m", "http.server")
        assert result.returncode != 0, f"Expected non-zero exit for -m flag, got {result.returncode}"
        assert "dangerous flag '-m'" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_run_mode_rejects_untracked_file(self, gate_root: Path, untracked_py_file: str) -> None:
        """[Req-004] run mode with untracked file must be rejected."""
        result = run_gate(gate_root, "run", untracked_py_file)
        assert result.returncode != 0, f"Expected non-zero exit for untracked file, got {result.returncode}"
        assert "file is not git-tracked" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_run_mode_rejects_absolute_path_outside_workspace(self, gate_root: Path) -> None:
        """[Req-005] run mode with path outside workspace must be rejected."""
        result = run_gate(gate_root, "run", "/etc/passwd")
        assert result.returncode != 0, f"Expected non-zero exit for outside-workspace path, got {result.returncode}"
        assert "path resolves outside workspace" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_run_mode_rejects_relative_traversal(self, gate_root: Path) -> None:
        """[Req-006] run mode with relative path traversal must be rejected."""
        # One ``..`` undoes scripts/ and one more per component below /, so the
        # path names the real /etc/passwd and the gate resolves an existing file.
        result = run_gate(gate_root, "run", "scripts/" + "../" * len(gate_root.parts) + "etc/passwd")
        assert result.returncode != 0, f"Expected non-zero exit for traversal path, got {result.returncode}"
        assert "path resolves outside workspace" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_empty_arguments_rejected(self, gate_root: Path) -> None:
        """[Req-007] No path arguments after mode must be rejected."""
        result = run_gate(gate_root, "run")
        assert result.returncode != 0, f"Expected non-zero exit for empty arguments, got {result.returncode}"
        assert "at least one path argument is required" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_symlink_outside_workspace_rejected(self, gate_root: Path, symlink_outside_workspace: str) -> None:
        """[Req-008] Symlink resolving outside workspace must be rejected."""
        result = run_gate(gate_root, "run", symlink_outside_workspace)
        assert result.returncode != 0, f"Expected non-zero exit for symlink escape, got {result.returncode}"
        assert "path resolves outside workspace" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    @pytest.mark.parametrize(
        "flag",
        ["-c", "-m"],
        ids=["inline-code", "module"],
    )
    def test_dangerous_flags_rejected(self, gate_root: Path, flag: str) -> None:
        """[Req-002][Req-003] Dangerous flags -c and -m must be rejected."""
        result = run_gate(gate_root, "run", flag, "payload")
        assert result.returncode != 0, f"Expected non-zero exit for flag '{flag}', got {result.returncode}"
        assert f"dangerous flag '{flag}'" in result.stderr, f"Rejected by another branch: {result.stderr!r}"


# ---------------------------------------------------------------------------
# Positive tests -- must pass with zero exit
# ---------------------------------------------------------------------------


class TestAcceptances:
    """Tests that verify the gate accepts valid inputs."""

    def test_run_mode_accepts_tracked_py_file(self, gate_root: Path, gate_artifact_dir: Path) -> None:
        """[Req-009] run mode with tracked .py file must pass and write artifact."""
        result = run_gate(gate_root, "run", "scripts/__init__.py")
        assert result.returncode == 0, f"Expected exit 0 for tracked .py file, got {result.returncode}\nstderr: {result.stderr}"
        artifact = gate_artifact_dir / ".python-gate-pass"
        assert artifact.exists(), f"Gate artifact not found at {artifact}"

    def test_test_mode_accepts_directory_with_pytest_flags(self, gate_root: Path) -> None:
        """[Req-010] test mode with directory + pytest flags via -- must pass."""
        result = run_gate(
            gate_root,
            "test",
            "tests/scripts/",
            "--",
            "-v",
            "--tb=short",
        )
        assert result.returncode == 0, f"Expected exit 0 for test mode with directory, got {result.returncode}\nstderr: {result.stderr}"

    def test_lint_mode_accepts_allowed_command(self, gate_root: Path) -> None:
        """[Req-011] lint mode with allowed ruff command must pass."""
        result = run_gate(
            gate_root,
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

    def test_multiple_positional_paths_all_validated(self, gate_root: Path) -> None:
        """[Req-012] Multiple positional paths must each be validated."""
        result = run_gate(
            gate_root,
            "run",
            "scripts/__init__.py",
            "ci/detect_bypasses.py",
        )
        assert result.returncode == 0, f"Expected exit 0 for multiple tracked files, got {result.returncode}\nstderr: {result.stderr}"

    def test_multiple_positional_paths_rejects_an_untracked_second_path(self, gate_root: Path, untracked_py_file: str) -> None:
        """[Req-012] A path after a valid one is still validated."""
        result = run_gate(gate_root, "run", "scripts/__init__.py", untracked_py_file)
        assert result.returncode != 0, f"Expected non-zero exit for an untracked second path, got {result.returncode}"
        assert f"file is not git-tracked: {untracked_py_file}" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_disallowed_lint_command_rejected(self, gate_root: Path) -> None:
        """[Req-013] lint mode with non-allowlisted command must be rejected."""
        result = run_gate(gate_root, "lint", "rm", "-rf", "/")
        assert result.returncode != 0, f"Expected non-zero exit for disallowed lint command, got {result.returncode}"
        assert "lint command not in allowlist" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_gate_writes_static_artifact(self, gate_root: Path, gate_artifact_dir: Path) -> None:
        """[Req-014] Gate must write artifact with static filename."""
        result = run_gate(gate_root, "run", "scripts/__init__.py")
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        artifact = gate_artifact_dir / ".python-gate-pass"
        assert artifact.exists(), f"Artifact not found at {artifact}"

    def test_gate_artifact_contains_valid_format(self, gate_root: Path, gate_artifact_dir: Path) -> None:
        """[Req-015] Gate artifact must contain valid timestamp and hash."""
        result = run_gate(gate_root, "run", "scripts/__init__.py")
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

    def test_run_mode_allows_unbuffered_flag(self, gate_root: Path) -> None:
        """[Req-001] run mode must allow the -u flag (not dangerous)."""
        result = run_gate(gate_root, "run", "-u", "scripts/__init__.py")
        assert result.returncode == 0, f"Expected exit 0 for -u flag, got {result.returncode}\nstderr: {result.stderr}"
