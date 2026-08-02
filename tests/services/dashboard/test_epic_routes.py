"""Tests for the epic management API routes.

Validates the ``/api/epics``, ``/api/epics/{epic_id}``, and
``/api/epics/{epic_id}/transitions`` endpoints using mocked
SQLite and ChromaDB dependencies.
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

SAMPLE_EPIC_ROW: dict[str, Any] = {
    "epic_id": "TEST-001",
    "status": "in_progress",
    "priority": 3,
    "depends_on": "[]",
    "claimed_by": "agent-1",
    "claimed_at": "2026-01-01",
    "title": "Test Epic",
    "created_at": "2026-01-01",
    "last_updated_at": "2026-01-02",
    "current_prs": None,
}


@pytest.fixture(autouse=True)
def _override_dependencies(dashboard_overrides):
    """Use the shared conftest fixture for all tests in this module."""
    yield dashboard_overrides


# ---------------------------------------------------------------------------
# GET /api/epics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_epics_returns_200() -> None:
    sample_epics = [SAMPLE_EPIC_ROW]
    with patch(
        "services.dashboard.routers.epics.list_epics",
        return_value=(sample_epics, False),
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/epics")

    assert response.status_code == 200
    body = response.json()
    assert "epics" in body
    assert "has_more" in body
    assert body["epics"] == sample_epics
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_list_epics_with_status_filter() -> None:
    with patch(
        "services.dashboard.routers.epics.list_epics",
        return_value=([], True),
    ) as mock_list:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/epics?status=in_progress&limit=10&offset=5")

    assert response.status_code == 200
    mock_list.assert_called_once()
    call_args = mock_list.call_args
    # Positional: db, status_filter; keyword: limit, offset
    assert call_args[0][1] == "in_progress"
    assert call_args[1]["limit"] == 10
    assert call_args[1]["offset"] == 5


@pytest.mark.asyncio
async def test_list_epics_invalid_status_returns_400() -> None:
    with patch(
        "services.dashboard.routers.epics.list_epics",
        side_effect=ValueError("bad status"),
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/epics?status=nonexistent")

    assert response.status_code == 400
    assert "bad status" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/epics/{epic_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_epic_detail_returns_200() -> None:
    mock_context: dict[str, Any] = {
        "plan_snapshot": None,
        "design_decisions": [],
        "step_results": [],
        "wave_summaries": [],
        "gate_verdicts": [],
        "requirement_map": None,
        "pr_created": [],
        "pr_merged": [],
        "open_todos": [],
    }
    mock_artifacts: list[dict[str, Any]] = [
        {"id": "art-1", "document": "content", "metadata": {"epic_id": "TEST-001"}},
    ]

    with (
        patch(
            "services.dashboard.routers.epics.get_resume_context",
            return_value=mock_context,
        ),
        patch(
            "services.dashboard.routers.epics.get_timeline",
            return_value=mock_artifacts,
        ),
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/epics/TEST-001")

    assert response.status_code == 200
    body = response.json()
    assert "epic" in body
    assert "artifacts" in body
    assert "context" in body
    assert "valid_transitions" in body
    assert body["epic"]["epic_id"] == "TEST-001"
    assert body["artifacts"] == mock_artifacts
    assert body["context"] == mock_context
    assert isinstance(body["valid_transitions"], list)


@pytest.mark.asyncio
async def test_epic_detail_not_found_returns_404() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/epics/NONEXISTENT-999")

    assert response.status_code == 404
    assert "NONEXISTENT-999" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/epics/{epic_id}/transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_epic_transitions_returns_valid_states() -> None:
    with patch(
        "services.dashboard.routers.epics.VALID_TRANSITIONS",
        {"in_progress": ["completed", "abandoned"]},
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/epics/TEST-001/transitions")

    assert response.status_code == 200
    body = response.json()
    assert body["current_status"] == "in_progress"
    assert "completed" in body["valid_transitions"]
    assert "abandoned" in body["valid_transitions"]


@pytest.mark.asyncio
async def test_epic_transitions_not_found_returns_404() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/epics/MISSING-999/transitions")

    assert response.status_code == 404
