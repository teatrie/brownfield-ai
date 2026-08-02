"""Integration tests for the python-gate-entrypoint.sh in python-cli.

Builds the python-cli Docker image via subprocess (not the Docker SDK, per TID251)
and verifies:
- Entrypoint rejects execution without gate artifact
- Entrypoint allows execution with valid gate artifact
- Entrypoint rejects expired gate artifacts
- PYTHON_GATE_DISABLED=1 bypasses the gate
- Entrypoint script is readable but not writable by agent user
- Processes run as the agent user, not root
- Entrypoint ruff S-rules lint blocks scripts with dangerous patterns
- Entrypoint conftest.py ruff S-rules scanning blocks dangerous fixtures
"""

import os
import shutil
import subprocess
import tempfile
import time

import pytest

IMAGE = "brownfield-ai/python-cli-gate-test:local"


@pytest.fixture(scope="module", autouse=True)
def build_image() -> None:
    """Build the python-cli Docker image once per test module."""
    result = subprocess.run(
        [
            "docker",
            "build",
            "-f",
            "docker/python-cli/Dockerfile",
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
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".gate", delete=False, dir=tmp_dir)
    tmp.write(content)
    tmp.close()
    os.chmod(tmp.name, 0o644)
    return os.path.abspath(tmp.name)


def _run_container(
    cmd: list[str],
    gate_content: str | None = None,
    env_vars: dict[str, str] | None = None,
    entrypoint: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the python-cli container and return the completed process.

    Uses ``docker create`` + ``docker cp`` + ``docker start`` instead of
    ``docker run -v`` so that gate file injection works in Docker-in-Docker
    environments where volume mount paths resolve against the HOST filesystem
    rather than the calling container's filesystem.

    Args:
        cmd: Command and arguments to execute in the container.
        gate_content: If provided, written to a temp file and copied into
            the container as the gate artifact at ``/tmp/.python-gate-pass``
            via ``docker cp`` (Docker API, not filesystem mount).
        env_vars: Optional environment variables to inject via ``-e KEY=VALUE``.
        entrypoint: Override the container entrypoint (e.g., ``bash``).

    Returns:
        The completed subprocess result with stdout and stderr captured.
    """
    name = f"gate-test-{os.getpid()}-{time.time_ns()}"
    gate_path: str | None = None

    create_args: list[str] = ["docker", "create", "--name", name, "--user", "agent"]

    if entrypoint is not None:
        create_args += ["--entrypoint", entrypoint]

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
                ["docker", "cp", gate_path, f"{name}:/tmp/.python-gate-pass"],
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


def _run_container_with_script(
    script_content: str,
    gate_content: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a Python script inside the container with optional gate artifact.

    Creates the container, copies the script and gate artifact via docker cp,
    then starts the container to execute python3 on the script.

    Args:
        script_content: Python source code to write and execute.
        gate_content: Gate artifact content. If None, no artifact is injected.

    Returns:
        The completed subprocess result.
    """
    name = f"gate-test-{os.getpid()}-{time.time_ns()}"
    gate_path: str | None = None
    script_path: str | None = None

    tmp_dir = os.path.join(os.getcwd(), "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    create_args = [
        "docker",
        "create",
        "--name",
        name,
        "--user",
        "agent",
        IMAGE,
        "python3",
        "/tmp/test_script.py",
    ]

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
                ["docker", "cp", gate_path, f"{name}:/tmp/.python-gate-pass"],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )

        # Write script to temp file and copy into container
        script_tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            dir=tmp_dir,
        )
        script_tmp.write(script_content)
        script_tmp.close()
        os.chmod(script_tmp.name, 0o644)
        script_path = script_tmp.name
        subprocess.run(
            ["docker", "cp", script_path, f"{name}:/tmp/test_script.py"],
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
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
        if gate_path is not None and os.path.exists(gate_path):
            os.unlink(gate_path)
        if script_path is not None and os.path.exists(script_path):
            os.unlink(script_path)

    return result


class TestEntrypointWithoutArtifact:
    """Tests verifying entrypoint rejects execution without gate artifact."""

    def test_rejects_without_gate_artifact(self) -> None:
        """[Req-016] Container rejects execution when gate artifact is missing."""
        result = _run_container(["python3", "--version"])
        assert result.returncode != 0
        assert "Security gate artifact not found" in result.stderr

    def test_error_message_mentions_task_wrappers(self) -> None:
        """[Req-016] Error message guides user to task wrappers."""
        result = _run_container(["python3", "--version"])
        assert "task wrappers" in result.stderr


class TestEntrypointWithValidArtifact:
    """Tests verifying entrypoint allows execution with valid artifact."""

    def test_allows_with_valid_artifact(self) -> None:
        """[Req-017] Container allows execution with valid gate artifact."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(["python3", "--version"], gate_content=gate_content)
        assert result.returncode == 0
        assert "Python" in result.stdout


class TestEntrypointExpiredArtifact:
    """Tests verifying entrypoint rejects expired artifacts."""

    def test_rejects_expired_artifact(self) -> None:
        """[Req-018] Container rejects gate artifact older than 120 seconds."""
        ts = int(time.time()) - 200
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(["python3", "--version"], gate_content=gate_content)
        assert result.returncode != 0
        assert "expired" in result.stderr.lower()


class TestEntrypointBypass:
    """Tests verifying PYTHON_GATE_DISABLED bypass works."""

    def test_bypass_with_env_var(self) -> None:
        """[Req-019] PYTHON_GATE_DISABLED=1 bypasses gate with warning."""
        result = _run_container(
            ["python3", "--version"],
            env_vars={"PYTHON_GATE_DISABLED": "1"},
        )
        assert result.returncode == 0
        assert "WARNING" in result.stderr
        assert "bypassed" in result.stderr.lower()


class TestContainerHardening:
    """Tests verifying container security properties."""

    def test_entrypoint_readable_by_agent(self) -> None:
        """[Req-020] Entrypoint script is readable by agent user."""
        result = _run_container(
            ["cat", "/usr/local/bin/entrypoint.sh"],
            env_vars={"PYTHON_GATE_DISABLED": "1"},
        )
        assert result.returncode == 0
        assert "GATE_FILE" in result.stdout

    def test_entrypoint_not_writable_by_agent(self) -> None:
        """[Req-021] Entrypoint script is not writable by agent user."""
        result = _run_container(
            ["-c", "echo test > /usr/local/bin/entrypoint.sh"],
            entrypoint="bash",
        )
        assert result.returncode != 0
        assert "Permission denied" in result.stderr

    def test_process_runs_as_agent_user(self) -> None:
        """[Req-022] Processes inside container run as agent, not root."""
        result = _run_container(
            ["id"],
            env_vars={"PYTHON_GATE_DISABLED": "1"},
        )
        assert result.returncode == 0
        assert "agent" in result.stdout


class TestRuffSecurityLint:
    """Tests verifying Layer 3 ruff S-rules security lint on python3 scripts."""

    def test_blocks_script_with_eval(self) -> None:
        """Entrypoint blocks python3 script containing eval() (S307)."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container_with_script(
            "user_input = input()\nresult = eval(user_input)\n",
            gate_content=gate_content,
        )
        assert result.returncode != 0
        assert "BLOCKED" in result.stderr or "S307" in result.stderr

    def test_blocks_script_with_subprocess_shell(self) -> None:
        """Entrypoint blocks python3 script with subprocess shell=True (S602)."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container_with_script(
            "import subprocess\nsubprocess.call('ls', shell=True)\n",
            gate_content=gate_content,
        )
        assert result.returncode != 0
        assert "BLOCKED" in result.stderr or "S602" in result.stderr

    def test_allows_clean_script(self) -> None:
        """Entrypoint allows python3 script with no S-rule violations."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container_with_script(
            "print('hello world')\n",
            gate_content=gate_content,
        )
        assert result.returncode == 0
        assert "hello world" in result.stdout


def _run_container_with_conftest(
    conftest_content: str,
    cmd: list[str],
    gate_content: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a pytest command with a conftest.py placed in a test directory.

    Creates the container, copies the gate artifact and a test directory
    containing the given ``conftest.py`` via ``docker cp``, then starts
    the container to execute the provided command.

    Args:
        conftest_content: Source code to write into ``conftest.py``.
        cmd: Full command list (e.g., ``["pytest", "/tmp/tests"]``).
        gate_content: Gate artifact content. If None, no artifact is injected.

    Returns:
        The completed subprocess result.
    """
    name = f"gate-test-{os.getpid()}-{time.time_ns()}"
    gate_path: str | None = None
    tmp_dir = os.path.join(os.getcwd(), "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    local_test_dir: str | None = None

    create_args: list[str] = [
        "docker",
        "create",
        "--name",
        name,
        "--user",
        "agent",
        IMAGE,
    ]
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
                ["docker", "cp", gate_path, f"{name}:/tmp/.python-gate-pass"],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )

        # Build a local directory containing conftest.py, then copy it
        # into the container as /tmp/tests/ via docker cp.
        local_test_dir = tempfile.mkdtemp(dir=tmp_dir, prefix="conftest_")
        conftest_path = os.path.join(local_test_dir, "conftest.py")
        with open(conftest_path, "w") as fh:
            fh.write(conftest_content)
        os.chmod(conftest_path, 0o644)

        subprocess.run(
            ["docker", "cp", local_test_dir, f"{name}:/tmp/tests"],
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
        if local_test_dir is not None and os.path.exists(local_test_dir):
            shutil.rmtree(local_test_dir, ignore_errors=True)

    return result


class TestConftestScanning:
    """Tests verifying conftest.py ruff S-rules scanning for pytest invocations."""

    def test_blocks_conftest_with_eval(self) -> None:
        """Entrypoint blocks pytest when conftest.py contains eval() (S307)."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container_with_conftest(
            conftest_content="user_input = input()\nresult = eval(user_input)\n",
            cmd=["pytest", "/tmp/tests"],
            gate_content=gate_content,
        )
        assert result.returncode != 0
        assert "BLOCKED" in result.stderr or "S307" in result.stderr

    def test_allows_clean_conftest(self) -> None:
        """Entrypoint allows pytest when conftest.py has no S-rule violations."""
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container_with_conftest(
            conftest_content=("import pytest\n\n\n@pytest.fixture\ndef sample_fixture():\n    return 42\n"),
            cmd=["pytest", "/tmp/tests"],
            gate_content=gate_content,
        )
        # The conftest scan itself must pass (exit != 1 from our gate).
        # pytest may still return non-zero if no tests are collected, so
        # we verify the gate did NOT block rather than asserting rc == 0.
        assert "BLOCKED" not in result.stderr
        assert "Fix conftest.py S-rule violations" not in result.stderr

    def test_no_scanning_without_directory_args(self) -> None:
        """Entrypoint skips conftest scanning when no directory args given.

        Note: pytest is not installed in python-cli (only in pytest-cli),
        so the command exits 127 (not found). The test verifies that the
        entrypoint gate itself does not block — the conftest scanning code
        path is not triggered without directory args.
        """
        ts = int(time.time())
        gate_content = f"GATE_PASS={ts}:abc123"
        result = _run_container(
            ["pytest", "--version"],
            gate_content=gate_content,
        )
        # Gate must not block; pytest not found (127) is expected in python-cli
        assert "BLOCKED" not in result.stderr
        assert "Fix conftest.py S-rule violations" not in result.stderr
