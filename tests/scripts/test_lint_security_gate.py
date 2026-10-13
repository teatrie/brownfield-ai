"""Tests for the lint-security-gate.sh host-side validation script.

Verifies that the gate script correctly validates lint execution requests
before Docker container invocation, including mode validation, command
allowlist enforcement, helm subcommand validation, and artifact generation.

Every run executes a copy of the gate placed at ``GATE_SCRIPT`` under a scratch
root in the test's ``tmp_path``. The gate derives ``WORKSPACE_ROOT`` from its
own location, not from the CWD, so the copy writes its nonces under the scratch
root. The gate runs no path or git checks, so the root holds only the copy. The
autouse ``_no_real_checkout_gate_artifacts`` fixture watches the real
checkout's nonces a run escaping the scratch root would touch.
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

import pytest
from helpers.wrapper_sources import wrapper_tmp_paths

GATE_SCRIPT = "docker/shared/lint-security-gate.sh"
WORKSPACE = Path(__file__).resolve().parents[2]
# Bound at import so a test that relocates WORKSPACE still reads the real gate.
GATE_SOURCE = WORKSPACE / GATE_SCRIPT

# Real-checkout nonces, relative to WORKSPACE, that the gate writes when a run
# escapes its scratch root.
_WATCHED_PATHS: tuple[str, ...] = (
    "tmp/.lint-gate-pass",
    "tmp/.lint-fix-gate-pass",
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
    """Fail the test across which a watched real-checkout nonce changed.

    A test that rewrites or deletes a real nonce races whichever gated lint
    command is in flight. A concurrent gated lint run against this checkout
    reports identically.
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

    A path that vanishes mid-snapshot is recorded absent: a concurrent delete is
    a difference to report, not a teardown error.
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
    """Place a copy of the gate under ``tmp_path`` and return it as the scratch root."""
    gate = tmp_path / GATE_SCRIPT
    gate.parent.mkdir(parents=True)
    shutil.copy2(GATE_SOURCE, gate)
    return tmp_path


@pytest.fixture()
def lint_artifact_dir(gate_root: Path) -> Path:
    """Ensure the scratch root's tmp/ directory exists."""
    artifact_dir = gate_root / "tmp"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


# ---------------------------------------------------------------------------
# Negative tests -- must reject with non-zero exit
# ---------------------------------------------------------------------------


class TestRejections:
    """Tests that verify the gate rejects invalid inputs."""

    def test_no_mode_argument(self, gate_root: Path) -> None:
        """Gate must reject invocation without a mode argument."""
        cmd = [GATE_SCRIPT]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(gate_root),
        )
        assert result.returncode != 0, f"Expected non-zero exit for missing mode, got {result.returncode}"

    def test_unknown_mode_rejected(self, gate_root: Path) -> None:
        """Gate must reject unknown modes."""
        result = run_gate(gate_root, "run", "shellcheck", "scripts/")
        assert result.returncode != 0, f"Expected non-zero exit for unknown mode, got {result.returncode}"

    def test_lint_mode_rejects_disallowed_command(self, gate_root: Path) -> None:
        """Lint mode must reject commands not in the allowlist."""
        result = run_gate(gate_root, "lint", "rm", "-rf", "/")
        assert result.returncode != 0, f"Expected non-zero exit for disallowed lint command, got {result.returncode}"
        assert "not in allowlist" in result.stderr.lower() or "allowlist" in result.stderr.lower()

    def test_lint_mode_rejects_bash(self, gate_root: Path) -> None:
        """Lint mode must reject bash (not a lint tool)."""
        result = run_gate(gate_root, "lint", "bash", "-c", "echo pwned")
        assert result.returncode != 0, f"Expected non-zero exit for bash in lint gate, got {result.returncode}"

    def test_fix_mode_rejects_disallowed_command(self, gate_root: Path) -> None:
        """Fix mode must reject commands not in the allowlist."""
        result = run_gate(gate_root, "fix", "pip", "install", "malicious")
        assert result.returncode != 0, f"Expected non-zero exit for disallowed fix command, got {result.returncode}"

    def test_lint_mode_rejects_empty_command(self, gate_root: Path) -> None:
        """Lint mode must reject invocation with no command arguments."""
        result = run_gate(gate_root, "lint")
        assert result.returncode != 0, f"Expected non-zero exit for empty lint command, got {result.returncode}"

    def test_fix_mode_rejects_empty_command(self, gate_root: Path) -> None:
        """Fix mode must reject invocation with no command arguments."""
        result = run_gate(gate_root, "fix")
        assert result.returncode != 0, f"Expected non-zero exit for empty fix command, got {result.returncode}"


# ---------------------------------------------------------------------------
# Positive tests -- must pass with zero exit
# ---------------------------------------------------------------------------


class TestAcceptances:
    """Tests that verify the gate accepts valid inputs."""

    def test_lint_mode_accepts_shellcheck(self, gate_root: Path, lint_artifact_dir: Path) -> None:
        """Lint mode with shellcheck must pass and write artifact."""
        result = run_gate(gate_root, "lint", "shellcheck", "scripts/foo.sh")
        assert result.returncode == 0, f"Expected exit 0 for shellcheck, got {result.returncode}\nstderr: {result.stderr}"
        artifact = lint_artifact_dir / ".lint-gate-pass"
        assert artifact.exists(), f"Gate artifact not found at {artifact}"

    def test_lint_mode_accepts_hadolint(self, gate_root: Path, lint_artifact_dir: Path) -> None:
        """Lint mode with hadolint must pass and write artifact."""
        result = run_gate(gate_root, "lint", "hadolint", "Dockerfile")
        assert result.returncode == 0, f"Expected exit 0 for hadolint, got {result.returncode}\nstderr: {result.stderr}"
        artifact = lint_artifact_dir / ".lint-gate-pass"
        assert artifact.exists(), f"Gate artifact not found at {artifact}"

    def test_lint_mode_accepts_yamllint(self, gate_root: Path) -> None:
        """Lint mode with yamllint must pass and write artifact."""
        result = run_gate(gate_root, "lint", "yamllint", "-c", ".yamllint.yml", ".")
        assert result.returncode == 0, f"Expected exit 0 for yamllint, got {result.returncode}\nstderr: {result.stderr}"

    def test_lint_mode_accepts_markdownlint(self, gate_root: Path) -> None:
        """Lint mode with markdownlint-cli2 must pass and write artifact."""
        result = run_gate(gate_root, "lint", "markdownlint-cli2", "docs/")
        assert result.returncode == 0, f"Expected exit 0 for markdownlint-cli2, got {result.returncode}\nstderr: {result.stderr}"

    def test_lint_mode_accepts_jsonlint_batch(self, gate_root: Path) -> None:
        """Lint mode with jsonlint-batch.sh must pass and write artifact."""
        result = run_gate(gate_root, "lint", "jsonlint-batch.sh", "foo.json")
        assert result.returncode == 0, f"Expected exit 0 for jsonlint-batch.sh, got {result.returncode}\nstderr: {result.stderr}"

    def test_fix_mode_accepts_markdownlint(self, gate_root: Path, lint_artifact_dir: Path) -> None:
        """Fix mode with markdownlint-cli2 must pass and write fix artifact."""
        result = run_gate(gate_root, "fix", "markdownlint-cli2", "--fix")
        assert result.returncode == 0, f"Expected exit 0 for fix markdownlint-cli2, got {result.returncode}\nstderr: {result.stderr}"
        artifact = lint_artifact_dir / ".lint-fix-gate-pass"
        assert artifact.exists(), f"Fix gate artifact not found at {artifact}"

    def test_lint_mode_accepts_kubeconform(self, gate_root: Path) -> None:
        """Lint mode with kubeconform must pass and write artifact."""
        result = run_gate(gate_root, "lint", "kubeconform", "manifests/")
        assert result.returncode == 0, f"Expected exit 0 for kubeconform, got {result.returncode}\nstderr: {result.stderr}"


# ---------------------------------------------------------------------------
# Helm subcommand validation
# ---------------------------------------------------------------------------


class TestHelmSubcommand:
    """Tests for helm subcommand validation in the gate."""

    def test_lint_allows_helm_template(self, gate_root: Path) -> None:
        """Lint mode must accept helm template."""
        result = run_gate(gate_root, "lint", "helm", "template", "my-chart")
        assert result.returncode == 0, f"Expected exit 0 for helm template, got {result.returncode}\nstderr: {result.stderr}"

    def test_lint_allows_helm_lint(self, gate_root: Path) -> None:
        """Lint mode must accept helm lint."""
        result = run_gate(gate_root, "lint", "helm", "lint", "my-chart")
        assert result.returncode == 0, f"Expected exit 0 for helm lint, got {result.returncode}\nstderr: {result.stderr}"

    def test_lint_rejects_helm_install(self, gate_root: Path) -> None:
        """Lint mode must reject helm install."""
        result = run_gate(gate_root, "lint", "helm", "install", "release", "chart")
        assert result.returncode != 0, f"Expected non-zero exit for helm install, got {result.returncode}"

    def test_lint_rejects_helm_delete(self, gate_root: Path) -> None:
        """Lint mode must reject helm delete."""
        result = run_gate(gate_root, "lint", "helm", "delete", "release")
        assert result.returncode != 0, f"Expected non-zero exit for helm delete, got {result.returncode}"

    def test_lint_rejects_helm_upgrade(self, gate_root: Path) -> None:
        """Lint mode must reject helm upgrade."""
        result = run_gate(gate_root, "lint", "helm", "upgrade", "release", "chart")
        assert result.returncode != 0, f"Expected non-zero exit for helm upgrade, got {result.returncode}"

    def test_lint_rejects_helm_bare(self, gate_root: Path) -> None:
        """Lint mode must reject bare helm with no subcommand."""
        result = run_gate(gate_root, "lint", "helm")
        assert result.returncode != 0, f"Expected non-zero exit for bare helm, got {result.returncode}"


# ---------------------------------------------------------------------------
# Artifact format tests
# ---------------------------------------------------------------------------


class TestArtifactFormat:
    """Tests that verify gate artifact correctness."""

    def test_lint_artifact_contains_valid_format(self, gate_root: Path, lint_artifact_dir: Path) -> None:
        """Lint gate artifact must contain valid timestamp and hash."""
        result = run_gate(gate_root, "lint", "shellcheck", "scripts/foo.sh")
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        artifact = lint_artifact_dir / ".lint-gate-pass"
        content = artifact.read_text().strip()

        pattern = re.compile(r"^GATE_PASS=(\d+):([a-f0-9]{64})$")
        match = pattern.match(content)
        assert match is not None, f"Artifact content does not match expected format 'GATE_PASS=<ts>:<sha256>': {content!r}"
        ts = int(match.group(1))
        assert abs(time.time() - ts) < 60, f"Artifact timestamp {ts} is not recent"

    def test_fix_artifact_contains_valid_format(self, gate_root: Path, lint_artifact_dir: Path) -> None:
        """Fix gate artifact must contain valid timestamp and hash."""
        result = run_gate(gate_root, "fix", "markdownlint-cli2", "--fix")
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        artifact = lint_artifact_dir / ".lint-fix-gate-pass"
        content = artifact.read_text().strip()

        pattern = re.compile(r"^GATE_PASS=(\d+):([a-f0-9]{64})$")
        match = pattern.match(content)
        assert match is not None, f"Artifact content does not match expected format 'GATE_PASS=<ts>:<sha256>': {content!r}"

    def test_artifact_hash_matches_command(self, gate_root: Path, lint_artifact_dir: Path) -> None:
        """Gate artifact hash must match SHA-256 of the command string."""
        cmd_str = "shellcheck scripts/foo.sh"
        result = run_gate(gate_root, "lint", "shellcheck", "scripts/foo.sh")
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        artifact = lint_artifact_dir / ".lint-gate-pass"
        content = artifact.read_text().strip()

        pattern = re.compile(r"^GATE_PASS=(\d+):([a-f0-9]{64})$")
        match = pattern.match(content)
        assert match is not None
        expected_hash = hashlib.sha256(cmd_str.encode()).hexdigest()
        assert match.group(2) == expected_hash, f"Artifact hash mismatch: expected {expected_hash}, got {match.group(2)}"


# ---------------------------------------------------------------------------
# Command allowlist boundary tests
# ---------------------------------------------------------------------------


class TestCommandAllowlistBoundary:
    """Tests verifying exact command allowlist boundaries."""

    @pytest.mark.parametrize(
        "cmd_args",
        [
            ("shellcheck", "scripts/foo.sh"),
            ("shellcheck", "-x", "scripts/foo.sh"),
            ("hadolint", "Dockerfile"),
            ("yamllint", "-c", ".yamllint.yml", "."),
            ("markdownlint-cli2", "docs/"),
            ("jsonlint", "foo.json"),
            ("jsonlint-batch.sh", "foo.json", "bar.json"),
            ("sqlfluff", "lint", "queries/"),
            ("kubeconform", "manifests/"),
            ("helm", "template", "my-chart"),
            ("helm", "lint", "my-chart"),
        ],
        ids=[
            "shellcheck-basic",
            "shellcheck-with-flags",
            "hadolint-basic",
            "yamllint-with-config",
            "markdownlint-basic",
            "jsonlint-basic",
            "jsonlint-batch",
            "sqlfluff-lint",
            "kubeconform-basic",
            "helm-template",
            "helm-lint",
        ],
    )
    def test_lint_allows_valid_commands(
        self,
        gate_root: Path,
        cmd_args: tuple[str, ...],
    ) -> None:
        """Lint mode must accept all allowlisted command prefixes."""
        result = run_gate(gate_root, "lint", *cmd_args)
        assert result.returncode == 0, f"Expected exit 0 for {cmd_args}, got {result.returncode}\nstderr: {result.stderr}"

    @pytest.mark.parametrize(
        "cmd_args",
        [
            ("bash", "-c", "echo pwned"),
            ("sh", "-c", "echo pwned"),
            ("pip", "install", "malicious"),
            ("helm", "install", "release", "chart"),
            ("helm", "upgrade", "release", "chart"),
        ],
        ids=[
            "bash-injection",
            "sh-injection",
            "pip-injection",
            "helm-install",
            "helm-upgrade",
        ],
    )
    def test_lint_rejects_dangerous_commands(self, gate_root: Path, cmd_args: tuple[str, ...]) -> None:
        """Lint mode must reject commands not in the allowlist."""
        result = run_gate(gate_root, "lint", *cmd_args)
        assert result.returncode != 0, f"Expected non-zero exit for {cmd_args}, got {result.returncode}"


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
    """The watch set covers the nonces the gate writes, and the comparison fires."""

    @staticmethod
    def _relocate_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Point ``WORKSPACE`` at ``tmp_path`` and return its ``tmp/`` directory."""
        monkeypatch.setattr(sys.modules[__name__], "WORKSPACE", tmp_path)
        live_tmp = tmp_path / "tmp"
        live_tmp.mkdir()
        return live_tmp

    def test_the_watch_set_covers_every_tmp_path_the_gate_names(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        named = wrapper_tmp_paths([GATE_SOURCE], {})
        assert named == {".lint-gate-pass", ".lint-fix-gate-pass"}, (
            "the gate now names another tmp/ path; watch it or argue its exemption here"
        )
        live_tmp = self._relocate_workspace(tmp_path, monkeypatch)
        for name in named:
            (live_tmp / name).write_text("GATE_PASS=0:x\n")
        assert set(_watched_snapshot()) == {f"tmp/{name}" for name in named}

    def test_the_fixture_fails_a_test_that_deleted_a_watched_nonce(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Driving the fixture's generator by hand shows the comparison firing.

        pytest leaves the undecorated generator at ``__wrapped__``; advancing it
        observes a guard whose job is to fail its own test without a nested
        pytest session.
        """
        nonce = self._relocate_workspace(tmp_path, monkeypatch) / ".lint-fix-gate-pass"
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
        nonce = self._relocate_workspace(tmp_path, monkeypatch) / ".lint-gate-pass"
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
        (self._relocate_workspace(tmp_path, monkeypatch) / ".lint-gate-pass").write_text("GATE_PASS=0:x\n")
        guard = globals()["_no_real_checkout_gate_artifacts"].__wrapped__()
        next(guard)
        with pytest.raises(StopIteration):
            next(guard)

    def test_the_fixture_is_autouse(self) -> None:
        marker = getattr(globals()["_no_real_checkout_gate_artifacts"], "_fixture_function_marker", None)
        assert marker is not None, "pytest no longer exposes the fixture marker here — update this assertion"
        assert marker.autouse
