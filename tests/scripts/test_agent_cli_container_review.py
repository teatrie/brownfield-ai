"""Container-level integration test for the agent-cli review wrappers.

Gemini r1 F1 (BLOCKING) shipped in Phase A because
``_review-common.sh`` was not ``COPY``-ed into the ``agent-cli`` Docker
image. The wrappers in ``/usr/local/bin/*-review.sh`` source
``$(dirname "$0")/_review-common.sh`` — which at runtime resolves to
``/usr/local/bin/_review-common.sh``. When that file is absent, every
container-mode review aborts with::

    /usr/local/bin/gemini-review.sh: line 63: /usr/local/bin/_review-common.sh: No such file or directory

The prior test suite never exercised the built image — all wrapper
tests invoked the host-side shell script against a PATH-prepended fake
``codex`` shim. This test module closes that gap with a minimal
shape check: build the image (if not already built) and confirm that
``/usr/local/bin/_review-common.sh`` is (a) present and (b) sources
cleanly, exposing the ``_review_validate_type`` function symbol.

The test is marked ``@pytest.mark.integration`` and is auto-skipped
when the Docker daemon is unreachable — a developer running
``task test:scripts:staged`` on a machine without Docker will see the
test skipped rather than failing spuriously. ``task test:changed``
runs the broader suite including this file, so the test participates
in the pre-push gate when the branch touches the Docker image or the
helper file.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

WORKSPACE: Path = Path(__file__).resolve().parents[2]


def _inside_docker_container() -> bool:
    """Return ``True`` when the test process is itself running inside Docker.

    The canonical markers are:

    * ``/.dockerenv`` — created by the Docker daemon at container start.
    * ``DOCKER_HOST`` env var set to a non-default socket.

    The pytest-cli container used by ``task test:scripts:staged`` has
    ``/.dockerenv`` and mounts ``/var/run/docker.sock`` — the daemon is
    reachable from inside, but re-running ``docker compose`` from there
    hits mount-path mismatches (compose resolves ``./`` against the
    pytest-cli cwd, not the host workspace). So the test must skip when
    it detects it is already nested.
    """
    return Path("/.dockerenv").exists()


def _docker_available() -> bool:
    """Return ``True`` when ``docker info`` succeeds within a short timeout.

    ``docker info`` is preferred over ``docker version`` because it only
    succeeds when the daemon socket is reachable — ``docker version``
    returns partial output even with no daemon. A 5-second wall-clock
    ceiling keeps the skip-detection cheap on CI runners that lack
    Docker entirely.
    """
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


INSIDE_CONTAINER: bool = _inside_docker_container()
DOCKER_AVAILABLE: bool = _docker_available()


# Skip when (a) docker is unreachable or (b) the test process is already
# running inside a pytest-cli container (the nested-compose path fails
# with a read-only ``/app/agent-review`` mount). Host runs via
# ``task test:changed`` (which invokes pytest-cli) would therefore
# skip too — host integration coverage relies on a direct pytest
# invocation outside the container wrapper.
pytestmark = pytest.mark.skipif(
    INSIDE_CONTAINER or not DOCKER_AVAILABLE,
    reason=(
        "container integration test requires a host-side Docker daemon and "
        "cannot run from inside the pytest-cli container (nested-compose "
        "mount paths diverge)"
    ),
)


def _build_agent_cli() -> None:
    """Ensure the agent-cli image exists; build if missing.

    Uses ``docker compose build`` rather than ``docker build`` directly so
    the image name, tag, and build context all track the committed
    compose file. A missing image surfaces as a build failure rather than
    a silent ``docker run`` 125. Build is a no-op when the image is
    already up to date.
    """
    subprocess.run(
        ["docker", "compose", "build", "agent-cli"],
        cwd=str(WORKSPACE),
        check=True,
        timeout=600,
    )


@pytest.mark.integration
class TestReviewCommonShippedInContainer:
    """Regression gate for gemini r1 F1.

    The helper MUST be present inside the container image and source
    cleanly — a missing helper would make every container-mode review
    abort at startup.
    """

    def test_review_common_sh_present_and_sources_cleanly(self) -> None:
        """``/usr/local/bin/_review-common.sh`` exists and sources cleanly.

        The oneliner:

        1. Lists the file (verifying it was ``COPY``-ed into the image).
        2. Sources the file in a fresh bash, then echoes a sentinel
           string. If sourcing fails with ``No such file or directory``,
           the ``SOURCED`` sentinel never appears, the outer shell exits
           non-zero, and pytest fails with stderr visible.
        3. Probes one known function symbol (``_review_validate_type``)
           via ``declare -F`` to ensure the helper body actually loaded —
           an empty / truncated COPY would still exist on disk but not
           export the function.
        """
        _build_agent_cli()
        cmd = [
            "docker",
            "compose",
            "run",
            "--rm",
            "--entrypoint",
            "bash",
            "agent-cli",
            "-c",
            (
                "set -e && "
                "ls -l /usr/local/bin/_review-common.sh && "
                ". /usr/local/bin/_review-common.sh && "
                "declare -F _review_validate_type >/dev/null && "
                "echo SOURCED"
            ),
        ]
        result = subprocess.run(
            cmd,
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"container integration failed: stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "SOURCED" in result.stdout, f"helper did not source inside container; stdout={result.stdout!r} stderr={result.stderr!r}"
