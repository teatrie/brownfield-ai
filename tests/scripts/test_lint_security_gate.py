"""Tests for the lint-security-gate.sh host-side validation script.

Verifies that the gate script correctly validates lint execution requests
before Docker container invocation, including mode validation, command
allowlist enforcement, helm subcommand validation, and artifact generation.

Every run executes a copy of the gate placed at ``GATE_SCRIPT`` under a scratch
root in the test's ``tmp_path``. The gate derives ``WORKSPACE_ROOT`` from its
own location, not from the CWD, so the copy writes its nonces under the scratch
root. The gate runs no path or git checks, so the root holds only the copy.
``run_gate`` takes the root as a required argument, so no run falls back to the
real checkout.
"""

import hashlib
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

GATE_SCRIPT = "docker/shared/lint-security-gate.sh"
WORKSPACE = Path(__file__).resolve().parents[2]
GATE_SOURCE = WORKSPACE / GATE_SCRIPT


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
        assert "mode argument required" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_unknown_mode_rejected(self, gate_root: Path) -> None:
        """Gate must reject unknown modes."""
        result = run_gate(gate_root, "run", "shellcheck", "scripts/")
        assert result.returncode != 0, f"Expected non-zero exit for unknown mode, got {result.returncode}"
        assert "unknown mode 'run'" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_lint_mode_rejects_disallowed_command(self, gate_root: Path) -> None:
        """Lint mode must reject commands not in the allowlist."""
        result = run_gate(gate_root, "lint", "rm", "-rf", "/")
        assert result.returncode != 0, f"Expected non-zero exit for disallowed lint command, got {result.returncode}"
        assert "not in allowlist" in result.stderr.lower() or "allowlist" in result.stderr.lower()
        assert "command not in allowlist" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_lint_mode_rejects_bash(self, gate_root: Path) -> None:
        """Lint mode must reject bash (not a lint tool)."""
        result = run_gate(gate_root, "lint", "bash", "-c", "echo pwned")
        assert result.returncode != 0, f"Expected non-zero exit for bash in lint gate, got {result.returncode}"
        assert "command not in allowlist" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_fix_mode_rejects_disallowed_command(self, gate_root: Path) -> None:
        """Fix mode must reject commands not in the allowlist."""
        result = run_gate(gate_root, "fix", "pip", "install", "malicious")
        assert result.returncode != 0, f"Expected non-zero exit for disallowed fix command, got {result.returncode}"
        assert "command not in allowlist" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_lint_mode_rejects_empty_command(self, gate_root: Path) -> None:
        """Lint mode must reject invocation with no command arguments."""
        result = run_gate(gate_root, "lint")
        assert result.returncode != 0, f"Expected non-zero exit for empty lint command, got {result.returncode}"
        assert "command argument required after mode" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_fix_mode_rejects_empty_command(self, gate_root: Path) -> None:
        """Fix mode must reject invocation with no command arguments."""
        result = run_gate(gate_root, "fix")
        assert result.returncode != 0, f"Expected non-zero exit for empty fix command, got {result.returncode}"
        assert "command argument required after mode" in result.stderr, f"Rejected by another branch: {result.stderr!r}"


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
        assert "helm subcommand not allowed" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_lint_rejects_helm_delete(self, gate_root: Path) -> None:
        """Lint mode must reject helm delete."""
        result = run_gate(gate_root, "lint", "helm", "delete", "release")
        assert result.returncode != 0, f"Expected non-zero exit for helm delete, got {result.returncode}"
        assert "helm subcommand not allowed" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_lint_rejects_helm_upgrade(self, gate_root: Path) -> None:
        """Lint mode must reject helm upgrade."""
        result = run_gate(gate_root, "lint", "helm", "upgrade", "release", "chart")
        assert result.returncode != 0, f"Expected non-zero exit for helm upgrade, got {result.returncode}"
        assert "helm subcommand not allowed" in result.stderr, f"Rejected by another branch: {result.stderr!r}"

    def test_lint_rejects_helm_bare(self, gate_root: Path) -> None:
        """Lint mode must reject bare helm with no subcommand."""
        result = run_gate(gate_root, "lint", "helm")
        assert result.returncode != 0, f"Expected non-zero exit for bare helm, got {result.returncode}"
        assert "helm subcommand not allowed" in result.stderr, f"Rejected by another branch: {result.stderr!r}"


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
        ("cmd_args", "branch_phrase"),
        [
            (("bash", "-c", "echo pwned"), "command not in allowlist"),
            (("sh", "-c", "echo pwned"), "command not in allowlist"),
            (("pip", "install", "malicious"), "command not in allowlist"),
            (("helm", "install", "release", "chart"), "helm subcommand not allowed"),
            (("helm", "upgrade", "release", "chart"), "helm subcommand not allowed"),
        ],
        ids=[
            "bash-injection",
            "sh-injection",
            "pip-injection",
            "helm-install",
            "helm-upgrade",
        ],
    )
    def test_lint_rejects_dangerous_commands(self, gate_root: Path, cmd_args: tuple[str, ...], branch_phrase: str) -> None:
        """Lint mode must reject commands not in the allowlist."""
        result = run_gate(gate_root, "lint", *cmd_args)
        assert result.returncode != 0, f"Expected non-zero exit for {cmd_args}, got {result.returncode}"
        assert branch_phrase in result.stderr, f"Rejected by another branch: {result.stderr!r}"
