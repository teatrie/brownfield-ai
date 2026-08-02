"""Write action API routes for the ledger dashboard.

Exposes mutation endpoints for epic status, priority, and PR references,
as well as TODO completion, assignment, priority, and category updates.
All service-layer calls are delegated via ``asyncio.to_thread`` to avoid
blocking the event loop.  Successful mutations broadcast WebSocket events
for real-time UI updates.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from brownfield_ai.ledger.epics.lifecycle import update_epic_priority, update_status
from brownfield_ai.ledger.epics.prs import clear_current_prs, set_current_prs
from brownfield_ai.ledger.todo.mutations import assign_todo, done_todo, update_todo
from services.dashboard.deps import (
    get_chromadb_collection,
    get_sqlite_db,
    get_todos_collection,
)

if TYPE_CHECKING:
    import chromadb

    from services.dashboard.ws import ConnectionManager

logger: logging.Logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[None]] = set()

# ---------------------------------------------------------------------------
# Pydantic request models (Req-025)
# ---------------------------------------------------------------------------


class StatusUpdateRequest(BaseModel):
    """Request body for updating an epic's workflow status."""

    new_status: str


class PriorityUpdateRequest(BaseModel):
    """Request body for updating an epic's priority."""

    priority: int = Field(ge=0, le=9)


class PrRefsRequest(BaseModel):
    """Request body for setting PR references on an epic."""

    pr_refs: str

    @field_validator("pr_refs")
    @classmethod
    def validate_pr_refs(cls, v: str) -> str:
        """Validate that every comma-separated entry matches ``owner/repo#number``.

        Args:
            v: Raw PR-refs string from the request body.

        Returns:
            The validated string, unchanged.

        Raises:
            ValueError: If any entry does not match the expected format.
        """
        for entry in v.split(","):
            entry = entry.strip()
            if entry and not re.match(r"^[\w.\-]+/[\w.\-]+#\d+$", entry):
                raise ValueError(f"Invalid PR ref format: '{entry}'. Expected: owner/repo#number")
        return v


class TodoDoneRequest(BaseModel):
    """Request body for marking a TODO as done."""

    resolution: str = Field(min_length=1)


class TodoAssignRequest(BaseModel):
    """Request body for assigning a TODO to an epic."""

    epic_id: str = Field(min_length=1)


class TodoPriorityRequest(BaseModel):
    """Request body for updating a TODO's priority."""

    priority: int = Field(ge=0, le=9)


class TodoCategoryRequest(BaseModel):
    """Request body for updating a TODO's category."""

    category: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router: APIRouter = APIRouter(prefix="/api", tags=["actions"])


async def _safe_broadcast(ws_manager: ConnectionManager, message: dict[str, Any]) -> None:
    """Broadcast a WebSocket message, logging errors without propagating.

    Uses broad ``except Exception`` intentionally: this is a fire-and-forget
    wrapper where *any* broadcast failure (network, serialization, closed
    connection) must be swallowed to avoid breaking the HTTP response path.
    All failures are logged with full traceback via ``logger.exception``.

    Args:
        ws_manager: The WebSocket connection manager.
        message: The message payload to broadcast.
    """
    try:
        await ws_manager.broadcast(message)
    except Exception:
        logger.exception("WebSocket broadcast failed for message type=%s", message.get("type"))


def _schedule_broadcast(ws_manager: ConnectionManager, message: dict[str, Any]) -> None:
    """Schedule a fire-and-forget broadcast, preventing GC of the task.

    Stores the task in a module-level set and removes it via a done
    callback, following the ``asyncio`` documentation guidance for
    tasks that must not be garbage-collected before completion.

    Args:
        ws_manager: The WebSocket connection manager.
        message: The message payload to broadcast.
    """
    task = asyncio.create_task(_safe_broadcast(ws_manager, message))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ---------------------------------------------------------------------------
# Epic action routes
# ---------------------------------------------------------------------------


@router.patch("/epics/{epic_id}/status")
async def update_epic_status(
    epic_id: str,
    body: StatusUpdateRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_sqlite_db),
) -> dict[str, Any]:
    """Transition an epic to a new workflow status.

    Args:
        epic_id: Path parameter identifying the epic.
        body: Request body containing the target status.
        request: The incoming request (used to access the WebSocket manager).
        db: Injected SQLite connection.

    Returns:
        A dictionary confirming success and the new status.

    Raises:
        HTTPException: 400 if the transition is invalid or the service
            layer rejects the update.
    """
    try:
        result: dict[str, Any] = await asyncio.to_thread(update_status, db, epic_id, body.new_status)
    except SystemExit as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Status update failed: {exc}",
        ) from exc

    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Status update failed"),
        )

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        _schedule_broadcast(
            ws_manager,
            {
                "type": "epic_updated",
                "epic_id": epic_id,
                "data": {"field": "status", "value": body.new_status},
            },
        )

    return {"success": True, "new_status": body.new_status}


@router.patch("/epics/{epic_id}/priority")
async def update_epic_priority_endpoint(
    epic_id: str,
    body: PriorityUpdateRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_sqlite_db),
) -> dict[str, Any]:
    """Update an epic's priority value.

    Args:
        epic_id: Path parameter identifying the epic.
        body: Request body containing the new priority.
        request: The incoming request (used to access the WebSocket manager).
        db: Injected SQLite connection.

    Returns:
        A dictionary confirming success and the new priority.

    Raises:
        HTTPException: 400 if the service layer rejects the update.
    """
    try:
        await asyncio.to_thread(update_epic_priority, db, epic_id, priority=body.priority)
    except SystemExit as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Priority update failed: {exc}",
        ) from exc

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        _schedule_broadcast(
            ws_manager,
            {
                "type": "epic_updated",
                "epic_id": epic_id,
                "data": {"field": "priority", "value": body.priority},
            },
        )

    return {"success": True, "priority": body.priority}


@router.put("/epics/{epic_id}/prs")
async def set_epic_prs(
    epic_id: str,
    body: PrRefsRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_sqlite_db),
) -> dict[str, Any]:
    """Set the PR references for an epic.

    Args:
        epic_id: Path parameter identifying the epic.
        body: Request body containing the comma-separated PR refs.
        request: The incoming request (used to access the WebSocket manager).
        db: Injected SQLite connection.

    Returns:
        A dictionary confirming success and the PR refs.

    Raises:
        HTTPException: 400 if the service layer rejects the update.
    """
    try:
        await asyncio.to_thread(set_current_prs, db, epic_id, body.pr_refs)
    except SystemExit as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Set PR refs failed: {exc}",
        ) from exc

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        _schedule_broadcast(
            ws_manager,
            {
                "type": "epic_updated",
                "epic_id": epic_id,
                "data": {"field": "pr_refs", "value": body.pr_refs},
            },
        )

    return {"success": True, "pr_refs": body.pr_refs}


@router.delete("/epics/{epic_id}/prs")
async def clear_epic_prs(
    epic_id: str,
    request: Request,
    db: sqlite3.Connection = Depends(get_sqlite_db),
) -> dict[str, Any]:
    """Clear all PR references from an epic.

    Args:
        epic_id: Path parameter identifying the epic.
        request: The incoming request (used to access the WebSocket manager).
        db: Injected SQLite connection.

    Returns:
        A dictionary confirming success.

    Raises:
        HTTPException: 400 if the service layer rejects the update.
    """
    try:
        await asyncio.to_thread(clear_current_prs, db, epic_id)
    except SystemExit as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Clear PR refs failed: {exc}",
        ) from exc

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        _schedule_broadcast(
            ws_manager,
            {
                "type": "epic_updated",
                "epic_id": epic_id,
                "data": {"field": "pr_refs", "value": ""},
            },
        )

    return {"success": True}


# ---------------------------------------------------------------------------
# TODO action routes
# ---------------------------------------------------------------------------


@router.patch("/todos/{todo_id}/done")
async def mark_todo_done(
    todo_id: int,
    body: TodoDoneRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_sqlite_db),
    collection: chromadb.Collection = Depends(get_todos_collection),
) -> dict[str, Any]:
    """Mark a TODO item as done with a resolution note.

    Args:
        todo_id: Path parameter identifying the TODO.
        body: Request body containing the resolution text.
        request: The incoming request (used to access the WebSocket manager).
        db: Injected SQLite connection.
        collection: Injected ChromaDB todos collection.

    Returns:
        A dictionary confirming success.

    Raises:
        HTTPException: 400 if the TODO does not exist or the operation fails.
    """
    try:
        await asyncio.to_thread(done_todo, db, collection, todo_id, body.resolution)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        _schedule_broadcast(
            ws_manager,
            {
                "type": "todo_updated",
                "data": {"todo_id": todo_id, "field": "status", "value": "done"},
            },
        )

    return {"success": True}


@router.patch("/todos/{todo_id}/assign")
async def assign_todo_endpoint(
    todo_id: int,
    body: TodoAssignRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_sqlite_db),
    todos_collection: chromadb.Collection = Depends(get_todos_collection),
    ledger_collection: chromadb.Collection = Depends(get_chromadb_collection),
) -> dict[str, Any]:
    """Assign a TODO item to an epic.

    Args:
        todo_id: Path parameter identifying the TODO.
        body: Request body containing the epic ID to assign.
        request: The incoming request (used to access the WebSocket manager).
        db: Injected SQLite connection.
        todos_collection: Injected ChromaDB todos collection.
        ledger_collection: Injected ChromaDB execution_ledger collection.

    Returns:
        A dictionary confirming success and the assigned epic ID.

    Raises:
        HTTPException: 400 if the assignment fails.
    """
    try:
        await asyncio.to_thread(assign_todo, db, todos_collection, ledger_collection, todo_id, body.epic_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        _schedule_broadcast(
            ws_manager,
            {
                "type": "todo_updated",
                "data": {"todo_id": todo_id, "field": "epic_id", "value": body.epic_id},
            },
        )

    return {"success": True, "epic_id": body.epic_id}


@router.patch("/todos/{todo_id}/priority")
async def update_todo_priority(
    todo_id: int,
    body: TodoPriorityRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_sqlite_db),
    collection: chromadb.Collection = Depends(get_todos_collection),
) -> dict[str, Any]:
    """Update a TODO item's priority.

    Args:
        todo_id: Path parameter identifying the TODO.
        body: Request body containing the new priority.
        request: The incoming request (used to access the WebSocket manager).
        db: Injected SQLite connection.
        collection: Injected ChromaDB todos collection.

    Returns:
        A dictionary confirming success and the new priority.

    Raises:
        HTTPException: 400 if the update fails.
    """
    try:
        await asyncio.to_thread(update_todo, db, collection, todo_id, priority=body.priority)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        _schedule_broadcast(
            ws_manager,
            {
                "type": "todo_updated",
                "data": {"todo_id": todo_id, "field": "priority", "value": body.priority},
            },
        )

    return {"success": True, "priority": body.priority}


@router.patch("/todos/{todo_id}/category")
async def update_todo_category(
    todo_id: int,
    body: TodoCategoryRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_sqlite_db),
    collection: chromadb.Collection = Depends(get_todos_collection),
) -> dict[str, Any]:
    """Update a TODO item's category.

    Args:
        todo_id: Path parameter identifying the TODO.
        body: Request body containing the new category.
        request: The incoming request (used to access the WebSocket manager).
        db: Injected SQLite connection.
        collection: Injected ChromaDB todos collection.

    Returns:
        A dictionary confirming success and the new category.

    Raises:
        HTTPException: 400 if the update fails.
    """
    try:
        await asyncio.to_thread(update_todo, db, collection, todo_id, category=body.category)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        _schedule_broadcast(
            ws_manager,
            {
                "type": "todo_updated",
                "data": {"todo_id": todo_id, "field": "category", "value": body.category},
            },
        )

    return {"success": True, "category": body.category}
