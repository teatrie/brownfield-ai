"""Tests for the home stats API route.

Validates the ``GET /api/stats/home`` endpoint including response schema,
partial failure when ChromaDB is unavailable, and correct SQLite
aggregation values from seeded test data.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import httpx
import pytest

from services.dashboard.app import app


@pytest.fixture(autouse=True)
def _override_dependencies(dashboard_overrides):
    """Use the shared conftest fixture for all tests in this module."""
    yield dashboard_overrides


@pytest.mark.asyncio
async def test_stats_home_returns_200(dashboard_overrides) -> None:
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": [], "metadatas": []}
    chromadb_client = dashboard_overrides["chromadb_client"]
    chromadb_client.get_or_create_collection.return_value = mock_collection

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/stats/home")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_stats_home_response_schema(dashboard_overrides) -> None:
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": [], "metadatas": []}
    chromadb_client = dashboard_overrides["chromadb_client"]
    chromadb_client.get_or_create_collection.return_value = mock_collection

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/stats/home")

    assert response.status_code == 200
    body = response.json()
    assert "epics" in body
    assert "todos" in body
    assert "activity" in body

    epic_keys = {"by_status", "active", "blocked", "completed_24h", "created_24h", "total"}
    assert set(body["epics"].keys()) == epic_keys

    todo_keys = {"open", "assigned", "done", "total", "high_priority_open", "by_category"}
    assert set(body["todos"].keys()) == todo_keys


@pytest.mark.asyncio
async def test_stats_home_epic_counts(dashboard_overrides) -> None:
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": [], "metadatas": []}
    chromadb_client = dashboard_overrides["chromadb_client"]
    chromadb_client.get_or_create_collection.return_value = mock_collection

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/stats/home")

    body = response.json()
    # Conftest seeds 2 epics: TEST-001 (in_progress) and TEST-002 (backlog)
    assert body["epics"]["total"] == 2
    assert body["epics"]["by_status"]["in_progress"] == 1
    assert body["epics"]["by_status"]["backlog"] == 1
    assert body["epics"]["active"] == 1
    assert body["epics"]["blocked"] == 0


@pytest.mark.asyncio
async def test_stats_home_todo_counts(dashboard_overrides) -> None:
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": [], "metadatas": []}
    chromadb_client = dashboard_overrides["chromadb_client"]
    chromadb_client.get_or_create_collection.return_value = mock_collection

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/stats/home")

    body = response.json()
    # Conftest seeds: id=1 (open, p5, infra) and id=2 (done, p3, code)
    assert body["todos"]["open"] == 1
    assert body["todos"]["done"] == 1
    assert body["todos"]["total"] == 2
    assert body["todos"]["high_priority_open"] == 0


@pytest.mark.asyncio
async def test_stats_home_todo_by_category(dashboard_overrides) -> None:
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": [], "metadatas": []}
    chromadb_client = dashboard_overrides["chromadb_client"]
    chromadb_client.get_or_create_collection.return_value = mock_collection

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/stats/home")

    body = response.json()
    categories = {c["category"]: c["count"] for c in body["todos"]["by_category"]}
    assert "infra" in categories
    assert categories["infra"] == 1


@pytest.mark.asyncio
async def test_stats_home_chromadb_failure_returns_null_activity(dashboard_overrides) -> None:
    chromadb_client = dashboard_overrides["chromadb_client"]
    chromadb_client.get_or_create_collection.side_effect = ConnectionError("ChromaDB down")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/stats/home")

    assert response.status_code == 200
    body = response.json()
    assert body["activity"] is None
    # SQLite sections still present
    assert body["epics"]["total"] == 2
    assert body["todos"]["total"] == 2


@pytest.mark.asyncio
async def test_stats_home_activity_stats(dashboard_overrides) -> None:
    now = datetime.now()
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["a1", "a2"],
        "metadatas": [
            {
                "timestamp": (now - timedelta(minutes=30)).isoformat(),
                "artifact_type": "gate_verdict",
                "verdict": "GREEN",
            },
            {
                "timestamp": (now - timedelta(hours=2)).isoformat(),
                "artifact_type": "pr_created",
            },
        ],
    }
    chromadb_client = dashboard_overrides["chromadb_client"]
    chromadb_client.get_or_create_collection.return_value = mock_collection

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/stats/home")

    body = response.json()
    assert body["activity"] is not None
    assert body["activity"]["artifacts_1h"] == 1
    assert body["activity"]["artifacts_24h"] == 2
    assert body["activity"]["gates_24h"]["pass"] == 1
    assert body["activity"]["prs_created_7d"] == 1
