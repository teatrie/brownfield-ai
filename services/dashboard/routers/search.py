"""Unified semantic search across artifacts, TODOs, and epics.

Exposes a single search endpoint that queries one or more ChromaDB
collections and returns results in a normalised shape, sorted by
vector distance.  All ChromaDB calls are delegated via
``asyncio.to_thread`` to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from services.dashboard.deps import (
    get_chromadb_collection,
    get_epics_collection,
    get_todos_collection,
)

if TYPE_CHECKING:
    import chromadb
    from chromadb.api.types import QueryResult

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/api", tags=["search"])

VALID_SCOPES: frozenset[str] = frozenset({"all", "artifacts", "todos", "epics"})


def _normalise_results(
    raw: QueryResult,
    source: str,
) -> list[dict[str, Any]]:
    """Convert raw ChromaDB query output into a flat result list.

    Args:
        raw: The QueryResult returned by ``collection.query()``.
        source: Label to attach (``"artifact"``, ``"todo"``, or ``"epic"``).

    Returns:
        A list of dicts with ``source``, ``id``, ``document``, ``metadata``,
        and ``distance`` keys.
    """
    ids = raw.get("ids") or [[]]
    documents = raw.get("documents") or [[]]
    metadatas = raw.get("metadatas") or [[]]
    distances = raw.get("distances") or [[]]

    results: list[dict[str, Any]] = []
    for i, doc_id in enumerate(ids[0]):
        results.append({
            "source": source,
            "id": doc_id,
            "document": documents[0][i] if i < len(documents[0]) else "",
            "metadata": metadatas[0][i] if i < len(metadatas[0]) else {},
            "distance": distances[0][i] if i < len(distances[0]) else 0.0,
        })
    return results


@router.get("/search")
async def search(
    q: str = Query(..., description="Search query text"),
    scope: str = Query("all", description="Search scope: all, artifacts, todos, or epics"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results per collection"),
    collection: chromadb.Collection = Depends(get_chromadb_collection),
    todos_collection: chromadb.Collection = Depends(get_todos_collection),
    epics_collection: chromadb.Collection = Depends(get_epics_collection),
) -> dict[str, Any]:
    """Search across artifacts, TODOs, and epics via ChromaDB similarity.

    Queries one or more ChromaDB collections based on ``scope``, merges
    the results into a unified shape, and returns them sorted by vector
    distance (ascending).

    Args:
        q: The search query text (1-500 characters).
        scope: Which collections to query (``all``, ``artifacts``,
            ``todos``, or ``epics``).
        limit: Maximum number of results to return per collection.
        collection: Injected ``execution_ledger`` ChromaDB collection.
        todos_collection: Injected ``todos`` ChromaDB collection.
        epics_collection: Injected ``epics`` ChromaDB collection.

    Returns:
        A dictionary with ``results`` (list), ``query`` (str), and
        ``scope`` (str).

    Raises:
        HTTPException: 400 if ``q`` is empty, exceeds 500 characters,
            or ``scope`` is invalid.
    """
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' must be non-empty")
    if len(q) > 500:
        raise HTTPException(status_code=400, detail="Query parameter 'q' must not exceed 500 characters")
    if scope not in VALID_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scope '{scope}'. Must be one of: {', '.join(sorted(VALID_SCOPES))}",
        )

    merged: list[dict[str, Any]] = []

    if scope == "all":
        results = await asyncio.gather(
            asyncio.to_thread(collection.query, query_texts=[q], n_results=limit),
            asyncio.to_thread(todos_collection.query, query_texts=[q], n_results=limit),
            asyncio.to_thread(epics_collection.query, query_texts=[q], n_results=limit),
            return_exceptions=True,
        )
        labels = ("artifact", "todo", "epic")
        for raw, label in zip(results, labels):
            if isinstance(raw, (ConnectionError, ValueError)):
                logger.warning("Search query failed for %s: %s", label, raw)
                continue
            if isinstance(raw, BaseException):
                raise raw
            merged.extend(_normalise_results(raw, label))
    elif scope == "artifacts":
        single = await asyncio.to_thread(
            collection.query,
            query_texts=[q],
            n_results=limit,
        )
        merged.extend(_normalise_results(single, "artifact"))
    elif scope == "todos":
        single = await asyncio.to_thread(
            todos_collection.query,
            query_texts=[q],
            n_results=limit,
        )
        merged.extend(_normalise_results(single, "todo"))
    elif scope == "epics":
        single = await asyncio.to_thread(
            epics_collection.query,
            query_texts=[q],
            n_results=limit,
        )
        merged.extend(_normalise_results(single, "epic"))

    merged.sort(key=lambda r: r["distance"])

    return {"results": merged, "query": q, "scope": scope}
