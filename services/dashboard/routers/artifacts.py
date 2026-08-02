"""Artifact timeline and detail API routes for the ledger dashboard.

Exposes read-only endpoints for listing artifacts in chronological
order (with optional filters) and fetching individual artifact detail.
All ChromaDB calls are delegated to the ``brownfield_ai.ledger.artifacts``
service layer via ``asyncio.to_thread`` to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

from brownfield_ai.ledger.artifacts.queries import get_artifact, get_timeline
from services.dashboard.deps import get_chromadb_collection

if TYPE_CHECKING:
    import chromadb

router: APIRouter = APIRouter(prefix="/api", tags=["artifacts"])


def _matches_metadata(
    metadata: dict[str, Any],
    *,
    wave: str | None,
    domain: str | None,
    verdict: str | None,
) -> bool:
    """Check whether artifact metadata matches the given filter criteria.

    Args:
        metadata: The artifact's metadata dictionary.
        wave: If provided, require metadata ``wave`` to match.
        domain: If provided, require metadata ``domain`` to match.
        verdict: If provided, require metadata ``verdict`` to match (case-insensitive).

    Returns:
        True if all non-None filters match the metadata values.
    """
    if wave and metadata.get("wave", "") != wave:
        return False
    if domain and metadata.get("domain", "") != domain:
        return False
    if verdict and (metadata.get("verdict", "") or "").upper() != verdict.upper():
        return False
    return True


@router.get("/artifacts/timeline/{epic_id}")
async def artifact_timeline(
    epic_id: str,
    collection: chromadb.Collection = Depends(get_chromadb_collection),
    *,
    artifact_type: str | None = None,
    wave: str | None = None,
    domain: str | None = None,
    verdict: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a paginated, filtered timeline of artifacts for an epic.

    Fetches all matching artifacts from ChromaDB via ``get_timeline``,
    applies in-memory post-filters for ``wave``, ``domain``, and
    ``verdict`` (which ``get_timeline`` does not support natively),
    then slices for pagination.

    Args:
        epic_id: Path parameter identifying the epic.
        collection: Injected ChromaDB collection.
        artifact_type: Optional filter for artifact type.
        wave: Optional filter for wave metadata field.
        domain: Optional filter for domain metadata field.
        verdict: Optional filter for verdict metadata field.
        limit: Maximum number of artifacts per page (default 50).
        offset: Number of artifacts to skip (default 0).

    Returns:
        A dictionary with ``artifacts`` (list) and ``has_more`` (bool).
    """
    filters: dict[str, Any] = {"epic_id": epic_id}
    if artifact_type:
        filters["artifact_type"] = artifact_type

    artifacts: list[dict[str, Any]] = await asyncio.to_thread(get_timeline, collection, filters)

    if wave or domain or verdict:
        artifacts = [
            a
            for a in artifacts
            if _matches_metadata(
                a.get("metadata", {}),
                wave=wave,
                domain=domain,
                verdict=verdict,
            )
        ]

    total = len(artifacts)
    page = artifacts[offset : offset + limit]

    return {"artifacts": page, "has_more": (offset + limit) < total}


@router.get("/artifacts/{doc_id:path}")
async def artifact_detail(
    doc_id: str,
    collection: chromadb.Collection = Depends(get_chromadb_collection),
) -> dict[str, Any]:
    """Return full detail for a single artifact.

    Args:
        doc_id: Path parameter identifying the artifact document.
        collection: Injected ChromaDB collection.

    Returns:
        The artifact dictionary with ``id``, ``document``, and ``metadata``.

    Raises:
        HTTPException: 404 if the artifact does not exist.
    """
    result: dict[str, Any] | None = await asyncio.to_thread(get_artifact, collection, doc_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Artifact '{doc_id}' not found")
    return result
