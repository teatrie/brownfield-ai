"""Shared pytest configuration for the brownfield-ai test suite.

Provides skill script path injection, ``aws_mock`` marker integration
with LocalStack, and session-scoped Docker service management via
``pytest-docker``.  Dashboard-specific fixtures live in
``tests/services/dashboard/conftest.py``.
"""

import glob
import os
import sys

import pytest
import requests

# ---------------------------------------------------------------------------
# Early sys.path setup — must complete before pytest loads subdirectory
# conftest modules (e.g. tests/services/dashboard/conftest.py) which
# import dashboard packages at module scope.
# ---------------------------------------------------------------------------
_CONFTEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_CONFTEST_DIR)

for _d in glob.glob(os.path.join(_REPO_ROOT, ".claude/skills/*/scripts")) + glob.glob(
    os.path.join(_REPO_ROOT, "workflows/*/skills/*/scripts")
):
    if _d not in sys.path:
        sys.path.insert(0, _d)

_DASHBOARD_SERVICE = os.path.join(_REPO_ROOT, "services", "dashboard")
for _p in [_REPO_ROOT, _DASHBOARD_SERVICE]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def pytest_configure(config):
    # Re-apply path injection via config.rootdir for robustness (idempotent —
    # paths added at module scope above are skipped via the ``not in`` guard).
    root = str(config.rootdir)
    skill_scripts = glob.glob(os.path.join(root, ".claude/skills/*/scripts"))
    skill_scripts += glob.glob(os.path.join(root, "workflows/*/skills/*/scripts"))
    for d in skill_scripts:
        if d not in sys.path:
            sys.path.insert(0, d)

    for p in [root, os.path.join(root, "services", "dashboard")]:
        if p not in sys.path:
            sys.path.insert(0, p)

    config.addinivalue_line("markers", "aws_mock: configure AWS environments to point to the local Moto server (LocalStack)")

    # Ensure a placeholder API key is present so runner tests can exercise
    # subprocess paths without a real credential. Tests that require the key
    # to be absent use patch.dict(os.environ, {}, clear=True) to override this.
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-placeholder")


@pytest.fixture(autouse=True)
def _aws_mock_marker(request):
    """Automatically use localstack_env if the aws_mock marker is applied."""
    if request.node.get_closest_marker("aws_mock"):
        request.getfixturevalue("localstack_env")


@pytest.fixture(scope="session")
def docker_compose_project_name():
    """Ensure pytest-docker always uses 'aws' as the project name so the container is predictably named
    'aws-localstack-1'."""
    return "aws"


@pytest.fixture(scope="session")
def docker_compose_file(pytestconfig):
    return os.path.join(str(pytestconfig.rootdir), "tests", "envs", "aws", "docker-compose.yml")


@pytest.fixture(scope="session")
def docker_ip(pytestconfig):
    return "host.docker.internal" if os.path.exists("/.dockerenv") else "127.0.0.1"


@pytest.fixture(scope="function")
def localstack_env(docker_ip, docker_services, monkeypatch):
    """Ensure LocalStack is running and set environment variables for AWS SDKs to point to it."""
    # pytest-docker handles spin up and down
    # Get port
    port = docker_services.port_for("localstack", 5000)
    url = f"http://{docker_ip}:{port}"
    docker_services.wait_until_responsive(timeout=30.0, pause=0.5, check=lambda: _is_responsive(url))

    # Drop any real-account context inherited from the developer's shell. A named
    # AWS_PROFILE makes botocore resolve ~/.aws/config and raise ProfileNotFound
    # before it ever reaches the mock endpoint, so these tests are only hermetic
    # once the host's profile and session are cleared.
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ENDPOINT_URL", url)

    try:
        yield url
    finally:
        # Reset Moto state after each test so state doesn't bleed across tests
        try:
            requests.post(f"{url}/moto-api/reset", timeout=5)
        except requests.exceptions.RequestException:
            pass


def _is_responsive(url):
    try:
        response = requests.get(url, timeout=1)
        if response.status_code == 200:
            return True
    except requests.exceptions.ConnectionError:
        return False
    return False
