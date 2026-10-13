"""Tests for the python-security-gate.sh host-side validation script.

Verifies that the gate script correctly validates Python execution requests
before Docker container invocation, including mode validation, path safety,
git-tracking checks, and artifact generation.

Every run executes a copy of the gate placed at ``GATE_SCRIPT`` under a scratch
root in the test's ``tmp_path``. The gate derives ``WORKSPACE_ROOT`` from its
own location, not from the CWD, so the copy writes its nonce under the scratch
root and resolves and git-checks paths against it. The scratch root is its own
git repo indexing the paths the tests pass as tracked. The autouse
``_no_real_checkout_gate_artifacts`` fixture watches the real checkout's paths
a run escaping the scratch root would touch.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import git
import pytest
from helpers.wrapper_sources import wrapper_tmp_paths

GATE_SCRIPT = "docker/shared/python-security-gate.sh"
WORKSPACE = Path(__file__).resolve().parents[2]
# Bound at import so a test that relocates WORKSPACE still reads the real gate.
GATE_SOURCE = WORKSPACE / GATE_SCRIPT

# Paths the tests rely on being git-tracked, so each keeps reaching the gate
# branch past its ``git ls-files`` check. The gate reads no file content.
_TRACKED_PATHS: tuple[str, ...] = (
    "scripts/__init__.py",
    "scripts/aws_vault_auth.sh",
    "ci/detect_bypasses.py",
    "tests/scripts/placeholder.py",
)

# Real-checkout paths, relative to WORKSPACE, that the gate and this module's
# fixtures write when a run escapes its scratch root.
_WATCHED_PATHS: tuple[str, ...] = (
    "tmp/.python-gate-pass",
    "tmp/scratch_gate_test.py",
    "tmp/escape_link.py",
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


@pytest.fixture(autouse=True)
def _no_real_checkout_gate_artifacts() -> Iterator[None]:
    """Fail the test across which a watched real-checkout path changed.

    The real ``tmp/.python-gate-pass`` is bind-mounted by every gated ``task``
    run, so a test that rewrites or deletes it races whichever gated command
    is in flight. The task runner writes and removes it outside the pytest
    session, so that never straddles a test; a concurrent gated command against
    this checkout does, and reports identically.
    """
    before = _watched_snapshot()
    yield
    after = _watched_snapshot()
    assert after == before, (
        f"watched gate artifacts under {WORKSPACE} differ across this test: {sorted(set(after.items()) ^ set(before.items()))}. "
        "A gate run that escaped its scratch root is what this guard exists for; a gated task run against this checkout "
        "concurrently reports identically."
    )


def _watched_snapshot() -> dict[str, tuple[int, int]]:
    """Map each present watched path to the size and mtime that identify it.

    ``lstat`` records a symlink itself rather than its target, so the escape
    link is watched even when it dangles. A path that vanishes mid-snapshot is
    recorded absent: a concurrent delete is a difference to report, not a
    teardown error.
    """
    snapshot: dict[str, tuple[int, int]] = {}
    for rel in _WATCHED_PATHS:
        try:
            info = (WORKSPACE / rel).lstat()
        except FileNotFoundError:
            continue
        snapshot[rel] = (info.st_size, info.st_mtime_ns)
    return snapshot


@pytest.fixture()
def gate_root(tmp_path: Path) -> Path:
    """Build a scratch git repo holding a copy of the gate and the tracked paths.

    Resolved so the gate's ``realpath`` output and its own root share one
    spelling; otherwise a symlinked ``tmp_path`` puts every existing path
    outside the workspace.
    """
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

    def test_run_mode_rejects_inline_code(self, gate_root: Path) -> None:
        """[Req-002] run mode with -c flag (inline code) must be rejected."""
        result = run_gate(gate_root, "run", "-c", 'print("hi")')
        assert result.returncode != 0, f"Expected non-zero exit for -c flag, got {result.returncode}"

    def test_run_mode_rejects_module_flag(self, gate_root: Path) -> None:
        """[Req-003] run mode with -m flag must be rejected."""
        result = run_gate(gate_root, "run", "-m", "http.server")
        assert result.returncode != 0, f"Expected non-zero exit for -m flag, got {result.returncode}"

    def test_run_mode_rejects_untracked_file(self, gate_root: Path, untracked_py_file: str) -> None:
        """[Req-004] run mode with untracked file must be rejected."""
        result = run_gate(gate_root, "run", untracked_py_file)
        assert result.returncode != 0, f"Expected non-zero exit for untracked file, got {result.returncode}"

    def test_run_mode_rejects_absolute_path_outside_workspace(self, gate_root: Path) -> None:
        """[Req-005] run mode with path outside workspace must be rejected."""
        result = run_gate(gate_root, "run", "/etc/passwd")
        assert result.returncode != 0, f"Expected non-zero exit for outside-workspace path, got {result.returncode}"

    def test_run_mode_rejects_relative_traversal(self, gate_root: Path) -> None:
        """[Req-006] run mode with relative path traversal must be rejected."""
        result = run_gate(gate_root, "run", "scripts/../../../etc/passwd")
        assert result.returncode != 0, f"Expected non-zero exit for traversal path, got {result.returncode}"

    def test_empty_arguments_rejected(self, gate_root: Path) -> None:
        """[Req-007] No path arguments after mode must be rejected."""
        result = run_gate(gate_root, "run")
        assert result.returncode != 0, f"Expected non-zero exit for empty arguments, got {result.returncode}"

    def test_symlink_outside_workspace_rejected(self, gate_root: Path, symlink_outside_workspace: str) -> None:
        """[Req-008] Symlink resolving outside workspace must be rejected."""
        result = run_gate(gate_root, "run", symlink_outside_workspace)
        assert result.returncode != 0, f"Expected non-zero exit for symlink escape, got {result.returncode}"

    @pytest.mark.parametrize(
        "flag",
        ["-c", "-m"],
        ids=["inline-code", "module"],
    )
    def test_dangerous_flags_rejected(self, gate_root: Path, flag: str) -> None:
        """[Req-002][Req-003] Dangerous flags -c and -m must be rejected."""
        result = run_gate(gate_root, "run", flag, "payload")
        assert result.returncode != 0, f"Expected non-zero exit for flag '{flag}', got {result.returncode}"


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

    def test_disallowed_lint_command_rejected(self, gate_root: Path) -> None:
        """[Req-013] lint mode with non-allowlisted command must be rejected."""
        result = run_gate(gate_root, "lint", "rm", "-rf", "/")
        assert result.returncode != 0, f"Expected non-zero exit for disallowed lint command, got {result.returncode}"

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


# ---------------------------------------------------------------------------
# The real-checkout gate artifact guard.
#
# Nothing above observes _no_real_checkout_gate_artifacts: drop autouse=True
# and every test above still passes. These tests lock its watch set and its
# comparison. Each monkeypatches WORKSPACE to its own tmp_path; pytest sets an
# autouse fixture up before requested fixtures and tears it down after them, so
# the guard's own snapshots bracket the monkeypatch and read the real checkout.
# ---------------------------------------------------------------------------


class TestRealCheckoutGateArtifactGuard:
    """The watch set covers what the gate and fixtures write, and the comparison fires."""

    @staticmethod
    def _relocate_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Point ``WORKSPACE`` at ``tmp_path`` and return its ``tmp/`` directory."""
        monkeypatch.setattr(sys.modules[__name__], "WORKSPACE", tmp_path)
        live_tmp = tmp_path / "tmp"
        live_tmp.mkdir()
        return live_tmp

    def test_the_watch_set_covers_the_gate_nonce_and_the_fixture_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The gate's own ``tmp/`` names are derived from its source and pinned.

        The escape link is created dangling, so it is only recorded if the
        snapshot reads the link itself rather than following it.
        """
        named = wrapper_tmp_paths([GATE_SOURCE], {})
        assert named == {".python-gate-pass"}, "the gate now names another tmp/ path; watch it or argue its exemption here"
        live_tmp = self._relocate_workspace(tmp_path, monkeypatch)
        for name in named:
            (live_tmp / name).write_text("GATE_PASS=0:x\n")
        (live_tmp / "scratch_gate_test.py").write_text("# untracked scratch file\n")
        (live_tmp / "escape_link.py").symlink_to(tmp_path / "no_such_target")
        snapshot = _watched_snapshot()
        assert {f"tmp/{name}" for name in named} <= set(snapshot)
        assert set(snapshot) == set(_WATCHED_PATHS)

    def test_the_fixture_fails_a_test_that_deleted_a_watched_nonce(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Driving the fixture's generator by hand shows the comparison firing.

        pytest leaves the undecorated generator at ``__wrapped__``; advancing it
        observes a guard whose job is to fail its own test without a nested
        pytest session.
        """
        nonce = self._relocate_workspace(tmp_path, monkeypatch) / ".python-gate-pass"
        nonce.write_text("GATE_PASS=0:x\n")
        guard = globals()["_no_real_checkout_gate_artifacts"].__wrapped__()
        next(guard)
        nonce.unlink()
        with pytest.raises(AssertionError, match="watched gate artifacts under .* differ across this test"):
            next(guard)

    def test_the_fixture_fails_a_test_that_rewrote_a_watched_nonce_at_the_same_length(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The gate's nonce is fixed-length, so the mtime alone must carry a rewrite.

        The mtime is backdated first so the rewrite cannot land in the same tick.
        """
        nonce = self._relocate_workspace(tmp_path, monkeypatch) / ".python-gate-pass"
        nonce.write_text(f"GATE_PASS=1000000000:{'a' * 64}\n")
        backdated = nonce.stat().st_mtime_ns - 1_000_000_000
        os.utime(nonce, ns=(backdated, backdated))
        size = nonce.stat().st_size
        guard = globals()["_no_real_checkout_gate_artifacts"].__wrapped__()
        next(guard)
        nonce.write_text(f"GATE_PASS=1000000001:{'b' * 64}\n")
        assert nonce.stat().st_size == size, "the rewrite changed length, so this no longer isolates the mtime component"
        with pytest.raises(AssertionError, match="watched gate artifacts under .* differ across this test"):
            next(guard)

    def test_the_fixture_passes_a_test_that_changed_nothing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (self._relocate_workspace(tmp_path, monkeypatch) / ".python-gate-pass").write_text("GATE_PASS=0:x\n")
        guard = globals()["_no_real_checkout_gate_artifacts"].__wrapped__()
        next(guard)
        with pytest.raises(StopIteration):
            next(guard)

    def test_the_fixture_is_autouse(self) -> None:
        marker = getattr(globals()["_no_real_checkout_gate_artifacts"], "_fixture_function_marker", None)
        assert marker is not None, "pytest no longer exposes the fixture marker here — update this assertion"
        assert marker.autouse
