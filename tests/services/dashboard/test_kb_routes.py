"""Tests for the Knowledge Base browser API routes.

Validates the ``/api/kb/*`` endpoints for collection listing,
document browsing, document detail, and semantic search using
mocked ChromaDB collection dependencies.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from services.dashboard.app import app
from services.dashboard.deps import get_chromadb_client, get_kb_collection

# ---------------------------------------------------------------------------
# Helpers
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


def _mock_get_result(
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a ChromaDB-shaped get result dict (no nesting).

    Args:
        ids: Document identifiers.
        documents: Document text contents.
        metadatas: Metadata dictionaries.

    Returns:
        A dict matching the shape of ``collection.get()`` output.
    """
    return {
        "ids": ids,
        "documents": documents,
        "metadatas": metadatas,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _override_dependencies(dashboard_overrides):
    """Use the shared conftest fixture for all tests in this module."""
    yield dashboard_overrides


# ---------------------------------------------------------------------------
# GET /api/kb/collections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_collections_returns_200(
    _override_dependencies: dict[str, Any],
) -> None:
    """List collections returns 200 with name and count for each allowed collection."""
    mock_client = _override_dependencies["chromadb_client"]
    mock_coll_ltd = MagicMock()
    mock_coll_ltd.count.return_value = 5
    mock_coll_ch = MagicMock()
    mock_coll_ch.count.return_value = 3

    def fake_get_collection(name: str) -> MagicMock:
        if name == "chat_history":
            return mock_coll_ch
        return mock_coll_ltd

    mock_client.get_collection.side_effect = fake_get_collection

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/kb/collections")

    assert response.status_code == 200
    body = response.json()
    names = {c["name"] for c in body["collections"]}
    assert names == {"long_term_document", "chat_history"}


@pytest.mark.asyncio
async def test_list_collections_chromadb_unavailable_503(
    _override_dependencies: dict[str, Any],
) -> None:
    """List collections returns 503 when ChromaDB client dependency raises."""
    from fastapi import HTTPException as _HTTPException

    def raise_unavailable() -> None:
        raise _HTTPException(status_code=503, detail="ChromaDB unavailable: down")

    app.dependency_overrides[get_chromadb_client] = raise_unavailable

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/kb/collections")

    assert response.status_code == 503


# ---------------------------------------------------------------------------
# GET /api/kb/documents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_documents_default_collection(
    _override_dependencies: dict[str, Any],
) -> None:
    """List documents with default collection returns 200 with all items."""
    mock_kb = _override_dependencies["kb_collection"]
    mock_kb.get.return_value = _mock_get_result(
        ids=["id1", "id2"],
        documents=["doc1", "doc2"],
        metadatas=[{"k": "v1"}, {"k": "v2"}],
    )
    mock_kb.count.return_value = 2

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/kb/documents")

    assert response.status_code == 200
    body = response.json()
    assert len(body["documents"]) == 2
    assert body["total"] == 2
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_list_documents_pagination(
    _override_dependencies: dict[str, Any],
) -> None:
    """Pagination delegates limit/offset to ChromaDB and sets has_more."""
    mock_kb = _override_dependencies["kb_collection"]
    # Simulate server-side pagination: first call returns 2 items, second 1
    mock_kb.get.side_effect = [
        _mock_get_result(ids=["id1", "id2"], documents=["doc1", "doc2"], metadatas=[{}, {}]),
        _mock_get_result(ids=["id3"], documents=["doc3"], metadatas=[{}]),
    ]
    mock_kb.count.return_value = 3

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp1 = await client.get("/api/kb/documents?limit=2&offset=0")
        resp2 = await client.get("/api/kb/documents?limit=2&offset=2")

    assert resp1.status_code == 200
    body1 = resp1.json()
    assert len(body1["documents"]) == 2
    assert body1["has_more"] is True
    assert body1["total"] == 3

    assert resp2.status_code == 200
    body2 = resp2.json()
    assert len(body2["documents"]) == 1
    assert body2["has_more"] is False


@pytest.mark.asyncio
async def test_list_documents_offset_beyond_total(
    _override_dependencies: dict[str, Any],
) -> None:
    """Offset beyond total returns empty page with has_more=False."""
    mock_kb = _override_dependencies["kb_collection"]
    mock_kb.get.return_value = _mock_get_result(
        ids=[],
        documents=[],
        metadatas=[],
    )
    mock_kb.count.return_value = 2

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/kb/documents?limit=20&offset=100")

    assert response.status_code == 200
    body = response.json()
    assert len(body["documents"]) == 0
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_list_documents_invalid_collection_400(
    _override_dependencies: dict[str, Any],
) -> None:
    """List documents with an invalid collection name returns 400."""
    app.dependency_overrides.pop(get_kb_collection, None)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/kb/documents?collection=invalid")

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/kb/documents/{doc_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_detail_found(
    _override_dependencies: dict[str, Any],
) -> None:
    """Document detail endpoint returns the document when it exists."""
    mock_kb = _override_dependencies["kb_collection"]
    mock_kb.get.return_value = _mock_get_result(
        ids=["abc123"],
        documents=["Full document content here"],
        metadatas=[{"source": "manual", "created": "2026-01-01"}],
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/kb/documents/abc123")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "abc123"
    assert body["document"] == "Full document content here"
    assert body["metadata"]["source"] == "manual"


@pytest.mark.asyncio
async def test_document_detail_not_found_404(
    _override_dependencies: dict[str, Any],
) -> None:
    """Document detail endpoint returns 404 when the document does not exist."""
    mock_kb = _override_dependencies["kb_collection"]
    mock_kb.get.return_value = {"ids": [], "documents": [], "metadatas": []}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/kb/documents/missing")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/kb/search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_results(
    _override_dependencies: dict[str, Any],
) -> None:
    """Search endpoint returns normalised results with id, document, metadata, distance."""
    mock_kb = _override_dependencies["kb_collection"]
    mock_kb.name = "long_term_document"
    mock_kb.query.return_value = _mock_query_result(
        ids=["res1", "res2"],
        documents=["result doc 1", "result doc 2"],
        metadatas=[{"topic": "python"}, {"topic": "testing"}],
        distances=[0.1, 0.4],
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/kb/search?q=python+testing")

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "python testing"
    assert body["collection"] == "long_term_document"
    assert len(body["results"]) == 2
    assert body["results"][0]["id"] == "res1"
    assert body["results"][0]["distance"] == 0.1


@pytest.mark.asyncio
async def test_search_empty_query_400() -> None:
    """Search with whitespace-only query returns 400."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/kb/search?q=%20")

    assert response.status_code == 400
    assert "non-empty" in response.json()["detail"]


@pytest.mark.asyncio
async def test_search_query_too_long_400() -> None:
    """Search with a query exceeding 500 characters returns 400."""
    long_q = "x" * 501
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/kb/search?q={long_q}")

    assert response.status_code == 400
    assert "500" in response.json()["detail"]


@pytest.mark.asyncio
async def test_search_invalid_collection_400(
    _override_dependencies: dict[str, Any],
) -> None:
    """Search with an invalid collection name returns 400."""
    app.dependency_overrides.pop(get_kb_collection, None)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/kb/search?q=test&collection=invalid")

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_search_missing_q_422() -> None:
    """Search with no q parameter returns 422 from FastAPI validation."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/kb/search")

    assert response.status_code == 422
