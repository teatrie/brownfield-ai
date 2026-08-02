"""Tests for the lint-security-gate.sh host-side validation script.

Verifies that the gate script correctly validates lint execution requests
before Docker container invocation, including mode validation, command
allowlist enforcement, helm subcommand validation, and artifact generation.
"""

import hashlib
import re
import subprocess
import time
from collections.abc import Generator
from pathlib import Path

import pytest

GATE_SCRIPT = "docker/shared/lint-security-gate.sh"
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
def lint_artifact_dir() -> Generator[Path, None, None]:
    """Ensure the tmp/ directory exists and clean up lint gate artifacts after."""
    artifact_dir = WORKSPACE / "tmp"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    yield artifact_dir
    (artifact_dir / ".lint-gate-pass").unlink(missing_ok=True)
    (artifact_dir / ".lint-fix-gate-pass").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Negative tests -- must reject with non-zero exit
# ---------------------------------------------------------------------------


class TestRejections:
    """Tests that verify the gate rejects invalid inputs."""

    def test_no_mode_argument(self) -> None:
        """Gate must reject invocation without a mode argument."""
        cmd = [GATE_SCRIPT]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(WORKSPACE),
        )
        assert result.returncode != 0, f"Expected non-zero exit for missing mode, got {result.returncode}"

    def test_unknown_mode_rejected(self) -> None:
        """Gate must reject unknown modes."""
        result = run_gate("run", "shellcheck", "scripts/")
        assert result.returncode != 0, f"Expected non-zero exit for unknown mode, got {result.returncode}"

    def test_lint_mode_rejects_disallowed_command(self) -> None:
        """Lint mode must reject commands not in the allowlist."""
        result = run_gate("lint", "rm", "-rf", "/")
        assert result.returncode != 0, f"Expected non-zero exit for disallowed lint command, got {result.returncode}"
        assert "not in allowlist" in result.stderr.lower() or "allowlist" in result.stderr.lower()

    def test_lint_mode_rejects_bash(self) -> None:
        """Lint mode must reject bash (not a lint tool)."""
        result = run_gate("lint", "bash", "-c", "echo pwned")
        assert result.returncode != 0, f"Expected non-zero exit for bash in lint gate, got {result.returncode}"

    def test_fix_mode_rejects_disallowed_command(self) -> None:
        """Fix mode must reject commands not in the allowlist."""
        result = run_gate("fix", "pip", "install", "malicious")
        assert result.returncode != 0, f"Expected non-zero exit for disallowed fix command, got {result.returncode}"

    def test_lint_mode_rejects_empty_command(self) -> None:
        """Lint mode must reject invocation with no command arguments."""
        result = run_gate("lint")
        assert result.returncode != 0, f"Expected non-zero exit for empty lint command, got {result.returncode}"

    def test_fix_mode_rejects_empty_command(self) -> None:
        """Fix mode must reject invocation with no command arguments."""
        result = run_gate("fix")
        assert result.returncode != 0, f"Expected non-zero exit for empty fix command, got {result.returncode}"


# ---------------------------------------------------------------------------
# Positive tests -- must pass with zero exit
# ---------------------------------------------------------------------------


class TestAcceptances:
    """Tests that verify the gate accepts valid inputs."""

    def test_lint_mode_accepts_shellcheck(self, lint_artifact_dir: Path) -> None:
        """Lint mode with shellcheck must pass and write artifact."""
        result = run_gate("lint", "shellcheck", "scripts/foo.sh")
        assert result.returncode == 0, f"Expected exit 0 for shellcheck, got {result.returncode}\nstderr: {result.stderr}"
        artifact = lint_artifact_dir / ".lint-gate-pass"
        assert artifact.exists(), f"Gate artifact not found at {artifact}"

    def test_lint_mode_accepts_hadolint(self, lint_artifact_dir: Path) -> None:
        """Lint mode with hadolint must pass and write artifact."""
        result = run_gate("lint", "hadolint", "Dockerfile")
        assert result.returncode == 0, f"Expected exit 0 for hadolint, got {result.returncode}\nstderr: {result.stderr}"
        artifact = lint_artifact_dir / ".lint-gate-pass"
        assert artifact.exists(), f"Gate artifact not found at {artifact}"

    def test_lint_mode_accepts_yamllint(self, lint_artifact_dir: Path) -> None:
        """Lint mode with yamllint must pass and write artifact."""
        result = run_gate("lint", "yamllint", "-c", ".yamllint.yml", ".")
        assert result.returncode == 0, f"Expected exit 0 for yamllint, got {result.returncode}\nstderr: {result.stderr}"

    def test_lint_mode_accepts_markdownlint(self, lint_artifact_dir: Path) -> None:
        """Lint mode with markdownlint-cli2 must pass and write artifact."""
        result = run_gate("lint", "markdownlint-cli2", "docs/")
        assert result.returncode == 0, f"Expected exit 0 for markdownlint-cli2, got {result.returncode}\nstderr: {result.stderr}"

    def test_lint_mode_accepts_jsonlint_batch(self, lint_artifact_dir: Path) -> None:
        """Lint mode with jsonlint-batch.sh must pass and write artifact."""
        result = run_gate("lint", "jsonlint-batch.sh", "foo.json")
        assert result.returncode == 0, f"Expected exit 0 for jsonlint-batch.sh, got {result.returncode}\nstderr: {result.stderr}"

    def test_fix_mode_accepts_markdownlint(self, lint_artifact_dir: Path) -> None:
        """Fix mode with markdownlint-cli2 must pass and write fix artifact."""
        result = run_gate("fix", "markdownlint-cli2", "--fix")
        assert result.returncode == 0, f"Expected exit 0 for fix markdownlint-cli2, got {result.returncode}\nstderr: {result.stderr}"
        artifact = lint_artifact_dir / ".lint-fix-gate-pass"
        assert artifact.exists(), f"Fix gate artifact not found at {artifact}"

    def test_lint_mode_accepts_kubeconform(self, lint_artifact_dir: Path) -> None:
        """Lint mode with kubeconform must pass and write artifact."""
        result = run_gate("lint", "kubeconform", "manifests/")
        assert result.returncode == 0, f"Expected exit 0 for kubeconform, got {result.returncode}\nstderr: {result.stderr}"


# ---------------------------------------------------------------------------
# Helm subcommand validation
# ---------------------------------------------------------------------------


class TestHelmSubcommand:
    """Tests for helm subcommand validation in the gate."""

    def test_lint_allows_helm_template(self, lint_artifact_dir: Path) -> None:
        """Lint mode must accept helm template."""
        result = run_gate("lint", "helm", "template", "my-chart")
        assert result.returncode == 0, f"Expected exit 0 for helm template, got {result.returncode}\nstderr: {result.stderr}"

    def test_lint_allows_helm_lint(self, lint_artifact_dir: Path) -> None:
        """Lint mode must accept helm lint."""
        result = run_gate("lint", "helm", "lint", "my-chart")
        assert result.returncode == 0, f"Expected exit 0 for helm lint, got {result.returncode}\nstderr: {result.stderr}"

    def test_lint_rejects_helm_install(self) -> None:
        """Lint mode must reject helm install."""
        result = run_gate("lint", "helm", "install", "release", "chart")
        assert result.returncode != 0, f"Expected non-zero exit for helm install, got {result.returncode}"

    def test_lint_rejects_helm_delete(self) -> None:
        """Lint mode must reject helm delete."""
        result = run_gate("lint", "helm", "delete", "release")
        assert result.returncode != 0, f"Expected non-zero exit for helm delete, got {result.returncode}"

    def test_lint_rejects_helm_upgrade(self) -> None:
        """Lint mode must reject helm upgrade."""
        result = run_gate("lint", "helm", "upgrade", "release", "chart")
        assert result.returncode != 0, f"Expected non-zero exit for helm upgrade, got {result.returncode}"

    def test_lint_rejects_helm_bare(self) -> None:
        """Lint mode must reject bare helm with no subcommand."""
        result = run_gate("lint", "helm")
        assert result.returncode != 0, f"Expected non-zero exit for bare helm, got {result.returncode}"


# ---------------------------------------------------------------------------
# Artifact format tests
# ---------------------------------------------------------------------------


class TestArtifactFormat:
    """Tests that verify gate artifact correctness."""

    def test_lint_artifact_contains_valid_format(self, lint_artifact_dir: Path) -> None:
        """Lint gate artifact must contain valid timestamp and hash."""
        result = run_gate("lint", "shellcheck", "scripts/foo.sh")
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        artifact = lint_artifact_dir / ".lint-gate-pass"
        content = artifact.read_text().strip()

        pattern = re.compile(r"^GATE_PASS=(\d+):([a-f0-9]{64})$")
        match = pattern.match(content)
        assert match is not None, f"Artifact content does not match expected format 'GATE_PASS=<ts>:<sha256>': {content!r}"
        ts = int(match.group(1))
        assert abs(time.time() - ts) < 60, f"Artifact timestamp {ts} is not recent"

    def test_fix_artifact_contains_valid_format(self, lint_artifact_dir: Path) -> None:
        """Fix gate artifact must contain valid timestamp and hash."""
        result = run_gate("fix", "markdownlint-cli2", "--fix")
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
        artifact = lint_artifact_dir / ".lint-fix-gate-pass"
        content = artifact.read_text().strip()

        pattern = re.compile(r"^GATE_PASS=(\d+):([a-f0-9]{64})$")
        match = pattern.match(content)
        assert match is not None, f"Artifact content does not match expected format 'GATE_PASS=<ts>:<sha256>': {content!r}"

    def test_artifact_hash_matches_command(self, lint_artifact_dir: Path) -> None:
        """Gate artifact hash must match SHA-256 of the command string."""
        cmd_str = "shellcheck scripts/foo.sh"
        result = run_gate("lint", "shellcheck", "scripts/foo.sh")
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
        cmd_args: tuple[str, ...],
        lint_artifact_dir: Path,
    ) -> None:
        """Lint mode must accept all allowlisted command prefixes."""
        result = run_gate("lint", *cmd_args)
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
    def test_lint_rejects_dangerous_commands(self, cmd_args: tuple[str, ...]) -> None:
        """Lint mode must reject commands not in the allowlist."""
        result = run_gate("lint", *cmd_args)
        assert result.returncode != 0, f"Expected non-zero exit for {cmd_args}, got {result.returncode}"
