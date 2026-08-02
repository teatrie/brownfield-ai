"""Read-only query functions for the artifact subsystem.

Provides filtered, paginated, and single-document retrieval from
ChromaDB collections. All functions accept a ChromaDB collection
as the first argument and return plain dictionaries.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_and_filter(
    collection: Any,
    epic_id: str,
    artifact_type: str,
) -> dict[str, Any]:
    """Query ChromaDB with ``$and`` filter, falling back to single filter.

    Attempts a combined ``$and`` filter on *epic_id* and *artifact_type*.
    If the operator is unavailable (older ChromaDB), falls back to filtering
    by *epic_id* only and post-filtering results client-side.

    Args:
        collection: The ChromaDB collection.
        epic_id: Epic identifier to filter on.
        artifact_type: Artifact type to filter on.

    Returns:
        dict: ChromaDB ``get()`` result dictionary.
    """
    try:
        result: dict[str, Any] = collection.get(
            where={
                "$and": [
                    {"epic_id": epic_id},
                    {"artifact_type": artifact_type},
                ]
            }
        )
        return result
    except (ValueError, TypeError):
        results = collection.get(where={"epic_id": epic_id})
        # Client-side post-filter
        filtered_ids: list[str] = []
        filtered_docs: list[str] = []
        filtered_metas: list[dict[str, Any]] = []
        for i, meta in enumerate(results.get("metadatas", [])):
            if meta.get("artifact_type") == artifact_type:
                filtered_ids.append(results["ids"][i])
                filtered_docs.append(results["documents"][i])
                filtered_metas.append(results["metadatas"][i])
        return {
            "ids": filtered_ids,
            "documents": filtered_docs,
            "metadatas": filtered_metas,
        }


def query_artifacts(
    collection: Any,
    query_text: str,
    filters: dict[str, str],
) -> list[dict[str, Any]]:
    """Perform semantic search across ledger artifacts.

    Supports optional ``where`` filters on *epic_id* and/or
    *artifact_type*. Uses ``$and`` with graceful fallback per Req-023.

    Args:
        collection: The ChromaDB collection.
        query_text: The search query text.
        filters: Dictionary with optional keys ``epic_id``,
            ``artifact_type``, and ``n`` (max results, default 5).

    Returns:
        list: List of result dictionaries with ``id``, ``document``,
        ``metadata``, and ``distance`` keys.
    """
    epic_id = filters.get("epic_id", "")
    artifact_type = filters.get("artifact_type", "")
    n = int(filters.get("n", 5))

    where_filter: dict[str, Any] | None = None
    if epic_id and artifact_type:
        try:
            where_filter = {
                "$and": [
                    {"epic_id": epic_id},
                    {"artifact_type": artifact_type},
                ]
            }
            results = collection.query(
                query_texts=[query_text],
                n_results=n,
                where=where_filter,
            )
        except (ValueError, TypeError):
            results = collection.query(
                query_texts=[query_text],
                n_results=n,
                where={"epic_id": epic_id},
            )
            # Client-side post-filter
            filtered: list[dict[str, Any]] = []
            if results["ids"] and results["ids"][0]:
                for i in range(len(results["ids"][0])):
                    meta = results["metadatas"][0][i]
                    if meta.get("artifact_type") == artifact_type:
                        filtered.append({
                            "id": results["ids"][0][i],
                            "document": results["documents"][0][i],
                            "metadata": meta,
                            "distance": (results["distances"][0][i] if results.get("distances") else "N/A"),
                        })
            return filtered
    elif epic_id:
        where_filter = {"epic_id": epic_id}
    elif artifact_type:
        where_filter = {"artifact_type": artifact_type}

    kwargs: dict[str, Any] = {
        "query_texts": [query_text],
        "n_results": n,
    }
    if where_filter is not None:
        kwargs["where"] = where_filter

    results = collection.query(**kwargs)

    output: list[dict[str, Any]] = []
    if results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            output.append({
                "id": results["ids"][0][i],
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": (results["distances"][0][i] if results.get("distances") else "N/A"),
            })
    return output


def search_epics_core(
    collection: Any,
    query_text: str,
    *,
    n: int = 5,
) -> list[dict[str, Any]]:
    """Search the epics collection by semantic similarity.

    Args:
        collection: The ChromaDB epics collection.
        query_text: The search query text.
        n: Maximum number of results to return.

    Returns:
        list: List of result dicts with ``id``, ``document``,
        ``metadata``, and ``distance`` keys.
    """
    results = collection.query(query_texts=[query_text], n_results=n)
    output: list[dict[str, Any]] = []
    if results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            output.append({
                "id": results["ids"][0][i],
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": (results["distances"][0][i] if results.get("distances") else "N/A"),
            })
    return output


def filter_artifacts(
    collection: Any,
    epic_id: str,
    *,
    artifact_type: str = "",
    sub_plan: str = "",
    attempt: str = "",
    verdict: str = "",
    artifact_status: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Filter ledger artifacts by deterministic metadata match.

    Unlike ``query_artifacts`` (semantic search), this uses exact metadata
    filters via ``collection.get()``. All non-empty parameters are combined
    with a ChromaDB ``$and`` operator when more than one filter is present.
    A client-side post-filter is always applied as a belt-and-suspenders
    guard in case the backing ChromaDB version does not honour ``$and``.

    Args:
        collection: The ChromaDB collection.
        epic_id: The epic identifier (always required).
        artifact_type: Optional artifact type filter.
        sub_plan: Optional sub-plan label filter.
        attempt: Optional attempt number filter.
        verdict: Optional verdict filter.
        artifact_status: Optional artifact status filter.
        limit: Maximum number of results to return (default 50).

    Returns:
        list: Artifacts matching all supplied filters, sorted newest-first.
    """
    # Build filter dict from all non-empty parameters
    expected: dict[str, str] = {"epic_id": epic_id}
    if artifact_type:
        expected["artifact_type"] = artifact_type
    if sub_plan:
        expected["sub_plan"] = sub_plan
    if attempt:
        expected["attempt"] = attempt
    if verdict:
        expected["verdict"] = verdict
    if artifact_status:
        expected["artifact_status"] = artifact_status

    if len(expected) == 1:
        result = collection.get(where={"epic_id": epic_id})
    else:
        filters: list[dict[str, str]] = [{k: v} for k, v in expected.items()]
        try:
            result = collection.get(where={"$and": filters})
        except (ValueError, TypeError):
            logger.warning("ChromaDB $and filter unsupported; falling back to epic_id filter + client post-filter")
            result = collection.get(where={"epic_id": epic_id})

    items: list[dict[str, Any]] = []
    for i, meta in enumerate(result.get("metadatas", [])):
        if all(meta.get(k) == v for k, v in expected.items()):
            items.append({
                "id": result["ids"][i],
                "document": result["documents"][i],
                "metadata": meta,
            })

    items.sort(key=lambda x: x["metadata"].get("timestamp", ""), reverse=True)
    return items[:limit]


def get_timeline(
    collection: Any,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    """List all artifacts for an epic, sorted chronologically by ID.

    Args:
        collection: The ChromaDB collection.
        filters: Dictionary with keys ``epic_id``, optional
            ``artifact_type``, and ``limit`` (default 50).

    Returns:
        list: Sorted list of artifact dictionaries.
    """
    epic_id = filters.get("epic_id", "")
    artifact_type = filters.get("artifact_type", "")
    limit = int(filters.get("limit", 50))

    if epic_id and artifact_type:
        results = build_and_filter(collection, epic_id, artifact_type)
    elif epic_id:
        results = collection.get(where={"epic_id": epic_id})
    else:
        results = collection.get()

    items: list[dict[str, Any]] = []
    for i, doc_id in enumerate(results.get("ids", [])):
        items.append({
            "id": doc_id,
            "document": results["documents"][i],
            "metadata": results["metadatas"][i],
        })

    items.sort(key=lambda x: x["id"])
    if limit > 0:
        items = items[:limit]
    return items


def get_artifact(
    collection: Any,
    doc_id: str,
) -> dict[str, Any] | None:
    """Retrieve a single document by exact ID.

    Args:
        collection: The ChromaDB collection.
        doc_id: The exact document ID.

    Returns:
        dict or None: The artifact dictionary, or ``None`` if not found.
    """
    results = collection.get(ids=[doc_id])
    if not results["ids"]:
        return None
    return {
        "id": results["ids"][0],
        "document": results["documents"][0],
        "metadata": results["metadatas"][0],
    }
