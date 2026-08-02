"""Epic management API routes for the ledger dashboard.

Exposes read-only endpoints for listing, inspecting, and querying
valid state transitions of execution-ledger epics.  All database
and ChromaDB calls are delegated to the ``brownfield_ai.ledger`` package
via ``asyncio.to_thread`` to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

from brownfield_ai.ledger.artifacts.queries import get_timeline
from brownfield_ai.ledger.epics.constants import EPIC_BY_ID_SQL, VALID_TRANSITIONS
from brownfield_ai.ledger.epics.queries import get_resume_context, list_epics
from services.dashboard.deps import get_chromadb_collection, get_sqlite_db

if TYPE_CHECKING:
    import chromadb

router: APIRouter = APIRouter(prefix="/api", tags=["epics"])


async def _fetch_epic_row(
    db: sqlite3.Connection,
    epic_id: str,
) -> dict[str, Any]:
    """Look up a single epic row from SQLite by its ID.

    Args:
        db: SQLite database connection.
        epic_id: The unique epic identifier.

    Returns:
        A dictionary of the epic's column values.

    Raises:
        HTTPException: 404 if the epic does not exist.
    """
    row: sqlite3.Row | None = await asyncio.to_thread(lambda: db.execute(EPIC_BY_ID_SQL, (epic_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail=f"Epic '{epic_id}' not found")
    return dict(row)


@router.get("/epics")
async def list_epics_endpoint(
    db: sqlite3.Connection = Depends(get_sqlite_db),
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a paginated list of epics, optionally filtered by status.

    Args:
        db: Injected SQLite connection from the dependency factory.
        status: Optional status string to filter epics.
        limit: Maximum number of epics per page (default 50).
        offset: Number of epics to skip (default 0).

    Returns:
        A dictionary with ``epics`` (list) and ``has_more`` (bool).

    Raises:
        HTTPException: 400 if the provided status filter is invalid.
    """
    try:
        epics, has_more = await asyncio.to_thread(list_epics, db, status, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"epics": epics, "has_more": has_more}


@router.get("/epics/{epic_id}")
async def epic_detail(
    epic_id: str,
    db: sqlite3.Connection = Depends(get_sqlite_db),
    collection: chromadb.Collection = Depends(get_chromadb_collection),
) -> dict[str, Any]:
    """Return full detail for a single epic.

    Combines the SQLite metadata row, the ChromaDB resume context,
    the artifact timeline, and the set of valid status transitions.

    Args:
        epic_id: Path parameter identifying the epic.
        db: Injected SQLite connection.
        collection: Injected ChromaDB collection.

    Returns:
        A dictionary with ``epic``, ``artifacts``, ``context``, and
        ``valid_transitions`` keys.

    Raises:
        HTTPException: 404 if the epic does not exist.
    """
    epic = await _fetch_epic_row(db, epic_id)

    context, artifacts = await asyncio.gather(
        asyncio.to_thread(get_resume_context, collection, db, epic_id),
        asyncio.to_thread(get_timeline, collection, {"epic_id": epic_id}),
    )

    return {
        "epic": epic,
        "artifacts": artifacts,
        "context": context,
        "valid_transitions": VALID_TRANSITIONS.get(epic["status"], []),
    }


@router.get("/epics/{epic_id}/transitions")
async def epic_transitions(
    epic_id: str,
    db: sqlite3.Connection = Depends(get_sqlite_db),
) -> dict[str, Any]:
    """Return the valid next-status transitions for the given epic.

    Args:
        epic_id: Path parameter identifying the epic.
        db: Injected SQLite connection.

    Returns:
        A dictionary with ``current_status`` and ``valid_transitions``.

    Raises:
        HTTPException: 404 if the epic does not exist.
    """
    epic = await _fetch_epic_row(db, epic_id)
    return {
        "current_status": epic["status"],
        "valid_transitions": VALID_TRANSITIONS.get(epic["status"], []),
    }
