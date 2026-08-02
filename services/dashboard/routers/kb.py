"""Knowledge Base browser API for ChromaDB document collections.

Exposes endpoints to list collections, browse documents with pagination,
retrieve single documents, and perform semantic search within a selected
KB collection.  All ChromaDB calls are delegated via ``asyncio.to_thread``
to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from services.dashboard.deps import KB_COLLECTIONS, get_chromadb_client, get_kb_collection

if TYPE_CHECKING:
    import chromadb
    from chromadb.api.types import QueryResult

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/api/kb", tags=["knowledge-base"])


@router.get("/collections")
async def list_collections(
    client: chromadb.ClientAPI = Depends(get_chromadb_client),
) -> dict[str, Any]:
    """List allowed KB collection names with document counts.

    Args:
        client: Injected ChromaDB client from dependency.

    Returns:
        A dict with ``collections`` key containing name/count pairs.

    Raises:
        HTTPException: 503 if ChromaDB is unavailable.
    """

    async def _get_count(name: str) -> dict[str, Any]:
        try:
            coll = await asyncio.to_thread(client.get_collection, name)
            count = await asyncio.to_thread(coll.count)
        except ValueError:
            return {"name": name, "count": 0}
        return {"name": name, "count": count}

    results = await asyncio.gather(
        *[_get_count(name) for name in sorted(KB_COLLECTIONS)],
    )

    return {"collections": list(results)}


@router.get("/documents")
async def list_documents(
    limit: int = Query(20, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    collection: chromadb.Collection = Depends(get_kb_collection),
) -> dict[str, Any]:
    """List documents in a KB collection with pagination.

    Delegates pagination to ChromaDB via ``limit`` and ``offset`` arguments.

    Args:
        limit: Maximum documents per page (1-200).
        offset: Number of documents to skip.
        collection: Injected ChromaDB collection from dependency.

    Returns:
        A dict with ``documents``, ``total``, and ``has_more`` keys.
    """
    raw, total = await asyncio.gather(
        asyncio.to_thread(
            collection.get,
            limit=limit,
            offset=offset,
            include=["documents", "metadatas"],
        ),
        asyncio.to_thread(collection.count),
    )

    ids = raw.get("ids") or []
    documents_list = raw.get("documents") or []
    metadatas = raw.get("metadatas") or []

    items: list[dict[str, Any]] = []
    for i, doc_id in enumerate(ids):
        items.append({
            "id": doc_id,
            "document": documents_list[i] if i < len(documents_list) else "",
            "metadata": (metadatas[i] or {}) if i < len(metadatas) else {},
        })

    return {"documents": items, "total": total, "has_more": (offset + limit) < total}


@router.get("/documents/{doc_id}")
async def document_detail(
    doc_id: str,
    collection: chromadb.Collection = Depends(get_kb_collection),
) -> dict[str, Any]:
    """Return full detail for a single KB document.

    Args:
        doc_id: The document identifier.
        collection: Injected ChromaDB collection from dependency.

    Returns:
        A dict with ``id``, ``document``, and ``metadata`` keys.

    Raises:
        HTTPException: 404 if the document does not exist.
    """
    raw = await asyncio.to_thread(collection.get, ids=[doc_id])
    ids = raw.get("ids") or []
    if not ids:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")

    documents_list = raw.get("documents") or []
    metadatas = raw.get("metadatas") or []

    return {
        "id": ids[0],
        "document": documents_list[0] if documents_list else "",
        "metadata": (metadatas[0] or {}) if metadatas else {},
    }


def _normalise_results(raw: QueryResult) -> list[dict[str, Any]]:
    """Convert raw ChromaDB query output into a flat result list.

    Args:
        raw: The QueryResult returned by ``collection.query()``.

    Returns:
        A list of dicts with ``id``, ``document``, ``metadata``,
        and ``distance`` keys.
    """
    ids = raw.get("ids") or [[]]
    documents = raw.get("documents") or [[]]
    metadatas = raw.get("metadatas") or [[]]
    distances = raw.get("distances") or [[]]

    results: list[dict[str, Any]] = []
    for i, doc_id in enumerate(ids[0]):
        results.append({
            "id": doc_id,
            "document": documents[0][i] if i < len(documents[0]) else "",
            "metadata": (metadatas[0][i] or {}) if i < len(metadatas[0]) else {},
            "distance": distances[0][i] if i < len(distances[0]) else 0.0,
        })
    return results


@router.get("/search")
async def search_documents(
    q: str = Query(..., description="Search query text"),
    limit: int = Query(10, ge=1, le=100, description="Maximum results"),
    collection: chromadb.Collection = Depends(get_kb_collection),
) -> dict[str, Any]:
    """Semantic search within a KB collection.

    Args:
        q: The search query text (1-500 characters).
        limit: Maximum number of results to return.
        collection: Injected ChromaDB collection from dependency.

    Returns:
        A dict with ``results``, ``query``, and ``collection`` keys.

    Raises:
        HTTPException: 400 if ``q`` is empty/whitespace or exceeds 500 chars.
    """
    if not q.strip():
        raise HTTPException(
            status_code=400,
            detail="Query parameter 'q' must be non-empty",
        )
    if len(q) > 500:
        raise HTTPException(
            status_code=400,
            detail="Query parameter 'q' must not exceed 500 characters",
        )

    raw = await asyncio.to_thread(
        collection.query,
        query_texts=[q],
        n_results=limit,
    )

    return {
        "results": _normalise_results(raw),
        "query": q,
        "collection": collection.name,
    }
