"""Integration tests for the lint-gate-entrypoint.sh in infra-lint.

Builds the infra-lint Docker image via subprocess and verifies:
- Entrypoint rejects execution without gate artifact
- Entrypoint allows execution with valid gate artifact (lint and fix modes)
- Entrypoint rejects expired gate artifacts
- LINT_GATE_DISABLED=1 bypasses the gate
- Entrypoint script is readable but not writable by agent user
- Processes run as the agent user, not root
- Command allowlist enforcement
- Helm subcommand validation
"""

import os
import subprocess
import tempfile
import time

import pytest

IMAGE = "brownfield-ai/infra-lint-gate-test:local"


@pytest.fixture(scope="module", autouse=True)
def build_image() -> None:
    """Build the infra-lint Docker image once per test module."""
    result = subprocess.run(
        [
            "docker",
            "build",
            "-f",
            "docker/builders/Dockerfile.infra-lint",
            "-t",
            IMAGE,
            ".",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        pytest.fail(f"Docker build failed:\n{result.stderr}")


def _write_gate_file(content: str) -> str:
    """Write a gate artifact to a temp file and return its absolute path.

    Args:
        content: The gate artifact content to write.

    Returns:
        Absolute path to the temporary gate file.
    """
    tmp_dir = os.path.join(os.getcwd(), "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".gate",
        delete=False,
        dir=tmp_dir,
    )
    tmp.write(content)
    tmp.close()
    os.chmod(tmp.name, 0o644)
    return os.path.abspath(tmp.name)


def _run_container(
    cmd: list[str],
    *,
    gate_content: str | None = None,
    gate_artifact_name: str = ".lint-gate-pass",
    env_vars: dict[str, str] | None = None,
    entrypoint_override: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the infra-lint container and return the completed process.

    Uses ``docker create`` + ``docker cp`` + ``docker start`` instead of
    ``docker run -v`` so that gate file injection works in Docker-in-Docker
    environments where volume mount paths resolve against the HOST filesystem
    rather than the calling container's filesystem.

    Args:
        cmd: Command and arguments to execute in the container.
        gate_content: If provided, written to a temp file and copied into
            the container as the gate artifact via ``docker cp``.
        gate_artifact_name: Name of the gate artifact file (default: .lint-gate-pass).
        env_vars: Optional environment variables to inject via ``-e KEY=VALUE``.
        entrypoint_override: Override the container entrypoint (e.g., ``bash``).

    Returns:
        The completed subprocess result with stdout and stderr captured.
    """
    name = f"lint-gate-test-{os.getpid()}-{time.time_ns()}"
    gate_path: str | None = None

    create_args: list[str] = ["docker", "create", "--name", name, "--user", "agent"]

    if entrypoint_override is not None:
        create_args += ["--entrypoint", entrypoint_override]

    if env_vars:
        for key, value in env_vars.items():
            create_args += ["-e", f"{key}={value}"]

    create_args.append(IMAGE)
    create_args.extend(cmd)

    try:
        subprocess.run(
            create_args,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )

        if gate_content is not None:
            gate_path = _write_gate_file(gate_content)
            subprocess.run(
                ["docker", "cp", gate_path, f"{name}:/tmp/{gate_artifact_name}"],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )

        result = subprocess.run(
            ["docker", "start", "-a", name],
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
            timeout=30,
        )
        if gate_path is not None and os.path.exists(gate_path):
            os.unlink(gate_path)

    return result


class TestEntrypointWithoutArtifact:
    """Tests verifying entrypoint rejects execution without gate artifact."""

    def test_rejects_without_gate_artifact(self) -> None:
        """Container rejects execution when gate artifact is missing."""
        result = _run_container(["shellcheck", "--version"])
        assert result.returncode != 0
        assert "Security gate artifact not found" in result.stderr

    def test_error_message_mentions_task_wrappers(self) -> None:
        """Error message guides user to task wrappers."""
        result = _run_container(["shellcheck", "--version"])
        assert "task wrappers" in result.stderr


class TestEntrypointWithLintArtifact:
    """Tests verifying entrypoint allows execution with valid lint artifact."""

    def test_allows_shellcheck_with_valid_artifact(self) -> None:
        """Container allows shellcheck execution with valid lint gate artifact."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(
            ["shellcheck", "--version"],
            gate_content=gate_content,
            gate_artifact_name=".lint-gate-pass",
        )
        assert result.returncode == 0

    def test_allows_hadolint_with_valid_artifact(self) -> None:
        """Container allows hadolint execution with valid lint gate artifact."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(
            ["hadolint", "--version"],
            gate_content=gate_content,
            gate_artifact_name=".lint-gate-pass",
        )
        assert result.returncode == 0

    def test_allows_yamllint_with_valid_artifact(self) -> None:
        """Container allows yamllint execution with valid lint gate artifact."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(
            ["yamllint", "--version"],
            gate_content=gate_content,
            gate_artifact_name=".lint-gate-pass",
        )
        assert result.returncode == 0


class TestEntrypointWithFixArtifact:
    """Tests verifying entrypoint allows execution with valid fix artifact."""

    def test_allows_markdownlint_with_fix_artifact(self) -> None:
        """Container allows markdownlint-cli2 execution with fix gate artifact."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(
            ["markdownlint-cli2", "--help"],
            gate_content=gate_content,
            gate_artifact_name=".lint-fix-gate-pass",
        )
        # markdownlint-cli2 --help exits with code 2 (tool behavior).
        # Verify the entrypoint allowed execution (no gate error in stderr).
        assert "Security gate artifact not found" not in result.stderr
        assert "not in allowlist" not in result.stderr


class TestEntrypointExpiredArtifact:
    """Tests verifying entrypoint rejects expired artifacts."""

    def test_rejects_expired_lint_artifact(self) -> None:
        """Container rejects lint gate artifact older than 120 seconds."""
        ts = int(time.time()) - 200
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(
            ["shellcheck", "--version"],
            gate_content=gate_content,
            gate_artifact_name=".lint-gate-pass",
        )
        assert result.returncode != 0
        assert "expired" in result.stderr.lower()

    def test_rejects_expired_fix_artifact(self) -> None:
        """Container rejects fix gate artifact older than 120 seconds."""
        ts = int(time.time()) - 200
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(
            ["markdownlint-cli2", "--help"],
            gate_content=gate_content,
            gate_artifact_name=".lint-fix-gate-pass",
        )
        assert result.returncode != 0
        assert "expired" in result.stderr.lower()


class TestEntrypointBypass:
    """Tests verifying LINT_GATE_DISABLED bypass works."""

    def test_bypass_with_env_var(self) -> None:
        """LINT_GATE_DISABLED=1 bypasses gate with warning."""
        result = _run_container(
            ["shellcheck", "--version"],
            env_vars={"LINT_GATE_DISABLED": "1"},
        )
        assert result.returncode == 0
        assert "WARNING" in result.stderr
        assert "bypassed" in result.stderr.lower()


class TestCommandAllowlist:
    """Tests verifying command allowlist in entrypoint."""

    def test_rejects_bash(self) -> None:
        """Entrypoint rejects bash (not in allowlist)."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(
            ["bash", "-c", "echo pwned"],
            gate_content=gate_content,
        )
        assert result.returncode != 0
        assert "allowlist" in result.stderr.lower()

    def test_rejects_sh(self) -> None:
        """Entrypoint rejects sh (not in allowlist)."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(
            ["sh", "-c", "echo pwned"],
            gate_content=gate_content,
        )
        assert result.returncode != 0


class TestHelmSubcommandEntrypoint:
    """Tests verifying helm subcommand validation in entrypoint."""

    def test_allows_helm_template(self) -> None:
        """Entrypoint allows helm template subcommand."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(
            ["helm", "template", "--help"],
            gate_content=gate_content,
        )
        assert result.returncode == 0

    def test_allows_helm_lint(self) -> None:
        """Entrypoint allows helm lint subcommand."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(
            ["helm", "lint", "--help"],
            gate_content=gate_content,
        )
        assert result.returncode == 0

    def test_rejects_helm_install(self) -> None:
        """Entrypoint rejects helm install subcommand."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(
            ["helm", "install", "release", "chart"],
            gate_content=gate_content,
        )
        assert result.returncode != 0
        assert "not allowed" in result.stderr.lower()

    def test_rejects_helm_no_subcommand(self) -> None:
        """Entrypoint rejects helm with no subcommand."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(
            ["helm"],
            gate_content=gate_content,
        )
        assert result.returncode != 0


class TestContainerHardening:
    """Tests verifying container security properties."""

    def test_entrypoint_readable_by_agent(self) -> None:
        """Entrypoint script is readable by agent user."""
        result = _run_container(
            ["cat", "/usr/local/bin/entrypoint.sh"],
            env_vars={"LINT_GATE_DISABLED": "1"},
        )
        assert result.returncode == 0
        assert "GATE_FILE" in result.stdout

    def test_entrypoint_not_writable_by_agent(self) -> None:
        """Entrypoint script is not writable by agent user."""
        result = _run_container(
            ["-c", "echo test > /usr/local/bin/entrypoint.sh"],
            entrypoint_override="bash",
        )
        assert result.returncode != 0
        assert "Permission denied" in result.stderr

    def test_process_runs_as_agent_user(self) -> None:
        """Processes inside container run as agent, not root."""
        result = _run_container(
            ["id"],
            env_vars={"LINT_GATE_DISABLED": "1"},
        )
        assert result.returncode == 0
        assert "agent" in result.stdout

    def test_jsonlint_batch_not_writable_by_agent(self) -> None:
        """jsonlint-batch.sh is not writable by agent user."""
        result = _run_container(
            ["-c", "echo test > /usr/local/bin/jsonlint-batch.sh"],
            entrypoint_override="bash",
        )
        assert result.returncode != 0
        assert "Permission denied" in result.stderr
