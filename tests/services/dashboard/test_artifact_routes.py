"""Tests for the artifact timeline and detail API routes.

Validates the ``/api/artifacts/timeline/{epic_id}`` and
``/api/artifacts/{doc_id}`` endpoints using mocked ChromaDB
dependencies.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from services.dashboard.app import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ARTIFACT: dict[str, Any] = {
    "id": "art-001",
    "document": "Step result content",
    "metadata": {
        "epic_id": "TEST-001",
        "artifact_type": "step_result",
        "wave": "2",
        "domain": "backend",
        "verdict": "GREEN",
        "timestamp": "2026-04-01T10:00:00",
        "step": "1",
        "agent_model": "opus-4",
        "artifact_status": "active",
        "version": 1,
        "attempt": "1",
        "sub_plan": "",
        "parent_id": "",
        "branches": "feat/test",
        "epic_status": "in_progress",
        "agent_role": "implementer",
    },
}

SAMPLE_ARTIFACT_2: dict[str, Any] = {
    "id": "art-002",
    "document": "Gate verdict content",
    "metadata": {
        "epic_id": "TEST-001",
        "artifact_type": "gate_verdict",
        "wave": "1",
        "domain": "frontend",
        "verdict": "FAIL",
        "timestamp": "2026-04-02T12:00:00",
        "step": "2",
        "agent_model": "opus-4",
        "artifact_status": "active",
        "version": 1,
        "attempt": "1",
        "sub_plan": "",
        "parent_id": "",
        "branches": "feat/test",
        "epic_status": "in_progress",
        "agent_role": "reviewer",
    },
}


@pytest.fixture(autouse=True)
def _override_dependencies(dashboard_overrides):
    """Use the shared conftest fixture for all tests in this module."""
    yield dashboard_overrides


# ---------------------------------------------------------------------------
# GET /api/artifacts/timeline/{epic_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeline_returns_200() -> None:
    mock_artifacts = [SAMPLE_ARTIFACT, SAMPLE_ARTIFACT_2]
    with patch(
        "services.dashboard.routers.artifacts.get_timeline",
        return_value=mock_artifacts,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/artifacts/timeline/TEST-001")

    assert response.status_code == 200
    body = response.json()
    assert "artifacts" in body
    assert "has_more" in body
    assert len(body["artifacts"]) == 2
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_timeline_with_filters() -> None:
    mock_artifacts = [SAMPLE_ARTIFACT, SAMPLE_ARTIFACT_2]
    with patch(
        "services.dashboard.routers.artifacts.get_timeline",
        return_value=mock_artifacts,
    ) as mock_get:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/artifacts/timeline/TEST-001?artifact_type=step_result&wave=2&domain=backend&verdict=GREEN")

    assert response.status_code == 200
    body = response.json()
    # artifact_type filter is passed to get_timeline
    call_args = mock_get.call_args
    filters_arg = call_args[0][1]
    assert filters_arg["artifact_type"] == "step_result"
    # wave, domain, verdict are post-filtered: only SAMPLE_ARTIFACT matches all
    assert len(body["artifacts"]) == 1
    assert body["artifacts"][0]["id"] == "art-001"


@pytest.mark.asyncio
async def test_timeline_empty_returns_200() -> None:
    with patch(
        "services.dashboard.routers.artifacts.get_timeline",
        return_value=[],
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/artifacts/timeline/TEST-001")

    assert response.status_code == 200
    body = response.json()
    assert body["artifacts"] == []
    assert body["has_more"] is False


# ---------------------------------------------------------------------------
# GET /api/artifacts/{doc_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifact_detail_returns_200() -> None:
    with patch(
        "services.dashboard.routers.artifacts.get_artifact",
        return_value=SAMPLE_ARTIFACT,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/artifacts/art-001")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "art-001"
    assert body["document"] == "Step result content"
    assert body["metadata"]["artifact_type"] == "step_result"


@pytest.mark.asyncio
async def test_artifact_detail_not_found_returns_404() -> None:
    with patch(
        "services.dashboard.routers.artifacts.get_artifact",
        return_value=None,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/artifacts/nonexistent-id")

    assert response.status_code == 404
    assert "nonexistent-id" in response.json()["detail"]
