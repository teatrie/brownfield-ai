"""TODO listing API routes for the ledger dashboard.

Exposes a read-only paginated endpoint for querying TODOs with optional
filtering by status, category, and epic assignment, plus configurable
sorting and pagination.  All synchronous SQLite calls are delegated via
``asyncio.to_thread`` to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from brownfield_ai.ledger.todo.queries import get_todo
from services.dashboard.deps import get_sqlite_db

# ---------------------------------------------------------------------------
# Whitelists for SQL interpolation safety
# ---------------------------------------------------------------------------

_SORT_WHITELIST: frozenset[str] = frozenset({"priority", "created_at", "last_updated_at"})
_ORDER_WHITELIST: frozenset[str] = frozenset({"asc", "desc"})

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TodoListItem(BaseModel):
    """Single TODO item in a list response."""

    id: int
    title: str
    status: str
    priority: int
    category: str | None
    epic_id: str | None
    description: str | None
    created_at: str
    last_updated_at: str


class TodoListResponse(BaseModel):
    """Paginated TODO list response."""

    todos: list[TodoListItem]
    total: int
    has_more: bool


# ---------------------------------------------------------------------------
# Internal query helper
# ---------------------------------------------------------------------------


def _query_todos(
    db: sqlite3.Connection,
    *,
    status: str,
    category: str | None,
    epic_id: str | None,
    sort: str,
    order: str,
    limit: int,
    offset: int,
) -> TodoListResponse:
    """Execute the filtered, sorted, paginated TODO query against SQLite.

    ``sort`` and ``order`` are string-interpolated into the SQL statement
    rather than parameterized because SQLite does not support parameterized
    column/direction expressions.  Both values MUST have been validated
    against their respective whitelists by the caller before this function
    is invoked.

    Args:
        db: Open SQLite connection with ``row_factory = sqlite3.Row``.
        status: Status filter value.  When ``"all"``, no WHERE clause is
            added for status.
        category: Optional category filter value.
        epic_id: Optional epic-ID filter value.
        sort: Column name to sort by (pre-validated against whitelist).
        order: Sort direction, either ``"asc"`` or ``"desc"``
            (pre-validated against whitelist).
        limit: Maximum number of rows to return.
        offset: Number of rows to skip before returning results.

    Returns:
        A :class:`TodoListResponse` containing the matched rows, the total
        count of matching rows (without pagination), and a ``has_more``
        flag.
    """
    where_clauses: list[str] = []
    params: list[object] = []

    if status != "all":
        where_clauses.append("status = ?")
        params.append(status)

    if category is not None:
        where_clauses.append("category = ?")
        params.append(category)

    if epic_id is not None:
        where_clauses.append("epic_id = ?")
        params.append(epic_id)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    count_sql = f"SELECT COUNT(*) FROM todos {where_sql}"
    total: int = db.execute(count_sql, params).fetchone()[0]

    # sort and order are interpolated after whitelist validation in the route handler
    rows_sql = (
        f"SELECT id, title, status, priority, category, epic_id, description, "
        f"created_at, last_updated_at "
        f"FROM todos {where_sql} "
        f"ORDER BY {sort} {order} "
        f"LIMIT ? OFFSET ?"
    )
    rows = db.execute(rows_sql, [*params, limit, offset]).fetchall()

    todos = [
        TodoListItem(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            priority=row["priority"],
            category=row["category"],
            epic_id=row["epic_id"],
            description=row["description"],
            created_at=row["created_at"],
            last_updated_at=row["last_updated_at"],
        )
        for row in rows
    ]

    has_more = (offset + limit) < total
    return TodoListResponse(todos=todos, total=total, has_more=has_more)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router: APIRouter = APIRouter(prefix="/api", tags=["todos"])


@router.get("/todos", response_model=TodoListResponse)
async def list_todos(
    db: sqlite3.Connection = Depends(get_sqlite_db),
    *,
    status: str = "open",
    category: str | None = None,
    epic_id: str | None = None,
    sort: str = "priority",
    order: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> TodoListResponse:
    """Return a paginated, filtered list of TODO items.

    Supports filtering by status, category, and linked epic.  Results are
    sorted by a validated column and direction, and are bounded to a
    configurable page size (maximum 200 rows).

    Args:
        db: Injected SQLite connection from the dependency factory.
        status: Status filter.  Pass ``"all"`` to omit the status WHERE
            clause entirely (default ``"open"``).
        category: Optional category string to filter on.
        epic_id: Optional epic ID string to filter on.
        sort: Column to sort by.  Must be one of ``priority``,
            ``created_at``, or ``last_updated_at`` (default ``"priority"``).
        order: Sort direction, either ``"asc"`` or ``"desc"``
            (default ``"asc"``).
        limit: Maximum rows per page; capped at 200 (default 50).
        offset: Number of rows to skip for pagination (default 0).

    Returns:
        A :class:`TodoListResponse` with ``todos``, ``total``, and
        ``has_more``.

    Raises:
        HTTPException: 400 if ``sort`` or ``order`` contain an invalid value.
    """
    if sort not in _SORT_WHITELIST:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort column '{sort}'. Must be one of: {sorted(_SORT_WHITELIST)}",
        )

    if order not in _ORDER_WHITELIST:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid order direction '{order}'. Must be one of: {sorted(_ORDER_WHITELIST)}",
        )

    effective_limit = min(limit, 200)

    return await asyncio.to_thread(
        _query_todos,
        db,
        status=status,
        category=category,
        epic_id=epic_id,
        sort=sort,
        order=order,
        limit=effective_limit,
        offset=offset,
    )


@router.get("/todos/{todo_id}", response_model=TodoListItem)
async def get_todo_by_id(
    todo_id: int,
    db: sqlite3.Connection = Depends(get_sqlite_db),
) -> TodoListItem:
    """Fetch a single TODO item by its integer ID.

    Args:
        todo_id: Path parameter identifying the TODO.
        db: Injected SQLite connection from the dependency factory.

    Returns:
        The matching :class:`TodoListItem`.

    Raises:
        HTTPException: 404 if no TODO exists with the given ID.
    """
    row = await asyncio.to_thread(get_todo, db, todo_id)
    if row is None:
        raise HTTPException(status_code=404, detail="TODO not found")
    return TodoListItem(**row)
