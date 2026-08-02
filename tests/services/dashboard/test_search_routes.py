"""Tests for the unified semantic search API route.

Validates the ``/api/search`` endpoint across all scopes
(``all``, ``artifacts``, ``todos``, ``epics``) using mocked
ChromaDB collection dependencies.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from services.dashboard.app import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_query_result(
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, Any]],
    distances: list[float],
) -> dict[str, Any]:
    """Build a ChromaDB-shaped query result dict.

    Args:
        ids: Document identifiers.
        documents: Document text contents.
        metadatas: Metadata dictionaries.
        distances: Vector distances from the query.

    Returns:
        A dict matching the shape of ``collection.query()`` output.
    """
    return {
        "ids": [ids],
        "documents": [documents],
        "metadatas": [metadatas],
        "distances": [distances],
    }


@pytest.fixture(autouse=True)
def _override_dependencies(dashboard_overrides):
    """Use the shared conftest fixture for all tests in this module."""
    yield {
        "db": dashboard_overrides["db"],
        "artifacts": dashboard_overrides["collection"],
        "todos": dashboard_overrides["todos_collection"],
        "epics": dashboard_overrides["epics_collection"],
    }


# ---------------------------------------------------------------------------
# GET /api/search — scope=all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_all_returns_200(_override_dependencies: dict[str, Any]) -> None:
    mocks = _override_dependencies

    mocks["artifacts"].query.return_value = _mock_query_result(
        ids=["art-1"],
        documents=["artifact doc"],
        metadatas=[{"epic_id": "TEST-001", "artifact_type": "step_result"}],
        distances=[0.3],
    )
    mocks["todos"].query.return_value = _mock_query_result(
        ids=["todo-1"],
        documents=["todo doc"],
        metadatas=[{"status": "open"}],
        distances=[0.5],
    )
    mocks["epics"].query.return_value = _mock_query_result(
        ids=["EPIC-1"],
        documents=["epic doc"],
        metadatas=[{"status": "in_progress"}],
        distances=[0.1],
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/search?q=test&scope=all")

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "test"
    assert body["scope"] == "all"
    assert len(body["results"]) == 3
    # Results should be sorted by distance ascending
    assert body["results"][0]["source"] == "epic"
    assert body["results"][0]["distance"] == 0.1
    assert body["results"][1]["source"] == "artifact"
    assert body["results"][1]["distance"] == 0.3
    assert body["results"][2]["source"] == "todo"
    assert body["results"][2]["distance"] == 0.5


@pytest.mark.asyncio
async def test_search_all_partial_failure_returns_surviving_results(
    _override_dependencies: dict[str, Any],
) -> None:
    """When one collection fails during scope=all, surviving results are returned."""
    mocks = _override_dependencies

    mocks["artifacts"].query.return_value = _mock_query_result(
        ids=["art-1"],
        documents=["artifact doc"],
        metadatas=[{"epic_id": "TEST-001", "artifact_type": "step_result"}],
        distances=[0.3],
    )
    mocks["todos"].query.side_effect = ConnectionError("ChromaDB unavailable")
    mocks["epics"].query.return_value = _mock_query_result(
        ids=["EPIC-1"],
        documents=["epic doc"],
        metadatas=[{"status": "in_progress"}],
        distances=[0.1],
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/search?q=test&scope=all")

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 2
    sources = {r["source"] for r in body["results"]}
    assert sources == {"artifact", "epic"}


# ---------------------------------------------------------------------------
# GET /api/search — scope=artifacts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_artifacts_scope(_override_dependencies: dict[str, Any]) -> None:
    mocks = _override_dependencies

    mocks["artifacts"].query.return_value = _mock_query_result(
        ids=["art-1"],
        documents=["artifact doc"],
        metadatas=[{"artifact_type": "step_result"}],
        distances=[0.2],
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/search?q=test&scope=artifacts")

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["source"] == "artifact"
    mocks["todos"].query.assert_not_called()
    mocks["epics"].query.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/search — scope=todos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_todos_scope(_override_dependencies: dict[str, Any]) -> None:
    mocks = _override_dependencies

    mocks["todos"].query.return_value = _mock_query_result(
        ids=["todo-1"],
        documents=["todo doc"],
        metadatas=[{"status": "open"}],
        distances=[0.4],
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/search?q=test&scope=todos")

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["source"] == "todo"
    mocks["artifacts"].query.assert_not_called()
    mocks["epics"].query.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/search — scope=epics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_epics_scope(_override_dependencies: dict[str, Any]) -> None:
    mocks = _override_dependencies

    mocks["epics"].query.return_value = _mock_query_result(
        ids=["EPIC-1"],
        documents=["epic doc"],
        metadatas=[{"status": "in_progress"}],
        distances=[0.15],
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/search?q=test&scope=epics")

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["source"] == "epic"
    mocks["artifacts"].query.assert_not_called()
    mocks["todos"].query.assert_not_called()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_empty_query_returns_400() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/search?q=")

    assert response.status_code == 400
    assert "non-empty" in response.json()["detail"]


@pytest.mark.asyncio
async def test_search_query_too_long_returns_400() -> None:
    long_q = "x" * 501
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/search?q={long_q}")

    assert response.status_code == 400
    assert "500" in response.json()["detail"]


@pytest.mark.asyncio
async def test_search_invalid_scope_returns_400() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/search?q=test&scope=invalid")

    assert response.status_code == 400
    assert "Invalid scope" in response.json()["detail"]
