"""Home page stats API route for the ledger dashboard.

Exposes a single ``GET /api/stats/home`` endpoint that aggregates epic,
TODO, and activity metrics.  SQLite queries run in a single thread
(DD-4: thread-safe access), parallelized against the ChromaDB call
via ``asyncio.gather``.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3

import chromadb
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from brownfield_ai.ledger.stats import get_activity_stats, get_sqlite_stats
from services.dashboard.deps import get_chromadb_client, get_sqlite_db

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class CategoryCount(BaseModel):
    """Single entry in the by-category breakdown."""

    category: str
    count: int


class EpicStatsResponse(BaseModel):
    """Epic aggregate statistics."""

    by_status: dict[str, int]
    active: int
    blocked: int
    completed_24h: int
    created_24h: int
    total: int


class TodoStatsResponse(BaseModel):
    """TODO aggregate statistics."""

    open: int
    assigned: int
    done: int
    total: int
    high_priority_open: int
    by_category: list[CategoryCount]


class ActivityStatsResponse(BaseModel):
    """Activity statistics from ChromaDB artifacts."""

    artifacts_1h: int
    artifacts_24h: int
    gates_24h: dict[str, int]
    prs_created_7d: int
    prs_merged_7d: int


class HomeStatsResponse(BaseModel):
    """Full home page stats response."""

    epics: EpicStatsResponse
    todos: TodoStatsResponse
    activity: ActivityStatsResponse | None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router: APIRouter = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats/home", response_model=HomeStatsResponse)
async def get_home_stats(
    db: sqlite3.Connection = Depends(get_sqlite_db),
    chromadb_client: chromadb.ClientAPI = Depends(get_chromadb_client),
) -> HomeStatsResponse:
    """Return aggregated statistics for the dashboard home page.

    Parallelizes SQLite queries (epic + TODO stats in a single thread)
    against the ChromaDB activity query via ``asyncio.gather``.  If
    ChromaDB fails, returns ``activity: null`` with SQLite sections intact.

    Args:
        db: Injected SQLite connection from the dependency factory.
        chromadb_client: Injected ChromaDB client from the dependency factory.

    Returns:
        A :class:`HomeStatsResponse` with epics, todos, and activity sections.
    """

    async def _fetch_activity() -> dict | None:
        try:
            collection = chromadb_client.get_or_create_collection("execution_ledger")
            return await asyncio.to_thread(get_activity_stats, collection)
        except (ConnectionError, ValueError, RuntimeError) as exc:
            logger.warning("ChromaDB activity stats failed: %s", exc)
            return None

    sqlite_result, activity_result = await asyncio.gather(
        asyncio.to_thread(get_sqlite_stats, db),
        _fetch_activity(),
    )

    activity_response: ActivityStatsResponse | None = None
    if activity_result is not None:
        activity_response = ActivityStatsResponse(**activity_result)

    return HomeStatsResponse(
        epics=EpicStatsResponse(**sqlite_result["epics"]),
        todos=TodoStatsResponse(**sqlite_result["todos"]),
        activity=activity_response,
    )
