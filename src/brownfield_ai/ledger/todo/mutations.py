"""Write operations (mutations) for the TODO subsystem.

Provides functions for creating, updating, completing, and assigning
TODOs with dual-store persistence (SQLite + ChromaDB).  Category
management is also included here.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from brownfield_ai.ledger.artifacts.mutations import save_artifact
from brownfield_ai.ledger.epics.lifecycle import create_epic
from brownfield_ai.ledger.todo.constants import _CATEGORY_NAME_PATTERN, format_todo_id
from brownfield_ai.ledger.todo.context import build_chromadb_document
from brownfield_ai.ledger.todo.queries import get_todo


def add_todo(
    db: sqlite3.Connection,
    collection: Any,
    title: str,
    context: dict[str, Any],
    *,
    description: str = "",
    notes: str = "",
    category: str = "",
    secondary_categories: str = "",
    priority: int = 5,
    source_workspace: str = "",
) -> int:
    """Insert a new TODO into SQLite and ChromaDB.

    Writes to SQLite first (transactional), then upserts the ChromaDB
    document for semantic search. Returns the auto-incremented TODO ID.

    Args:
        db: SQLite database connection.
        collection: ChromaDB ``todos`` collection.
        title: TODO title (required).
        context: Context snapshot dictionary from ``capture_context()``.
        description: Optional description text.
        notes: Optional free-text notes (included in context snapshot).
        category: Primary category name (may be empty).
        secondary_categories: Space-delimited secondary category names.
        priority: Numeric priority 0-9 where 0 is highest.
        source_workspace: Host workspace path where the TODO was created.

    Returns:
        The auto-incremented TODO ID.
    """
    now = datetime.now().isoformat()
    context_json = json.dumps(context)

    cursor = db.execute(
        """
        INSERT INTO todos (
            title, description, context_snapshot, category,
            secondary_categories, priority, source_workspace,
            status, created_at, last_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
        """,
        (title, description, context_json, category or None, secondary_categories or None, priority, source_workspace, now, now),
    )
    db.commit()
    if cursor.lastrowid is None:
        raise RuntimeError("INSERT failed to produce a row ID")
    todo_id: int = cursor.lastrowid

    # ChromaDB document
    doc_text = build_chromadb_document(title, description, context)
    collection.upsert(
        ids=[str(todo_id)],
        documents=[doc_text],
        metadatas=[
            {
                "todo_id": todo_id,
                "status": "open",
                "category": category or "",
                "priority": priority,
                "epic_id": "",
                "source_workspace": source_workspace,
                "created_at": now,
            }
        ],
    )

    return todo_id


def detect_duplicates(
    collection: Any,
    document_text: str,
    *,
    threshold: int = 3,
) -> list[dict[str, Any]]:
    """Query ChromaDB for semantically similar existing TODOs.

    Args:
        collection: ChromaDB ``todos`` collection.
        document_text: The document text to search against.
        threshold: Maximum number of similar results to return.

    Returns:
        Top N similar TODOs as dicts with ``id``, ``document``,
        ``metadata``, and ``distance`` keys. Empty list if collection
        is empty or query fails.
    """
    try:
        results = collection.query(query_texts=[document_text], n_results=threshold)
    except (ValueError, RuntimeError, IndexError):
        # ChromaDB raises ValueError for empty collections, RuntimeError for
        # initialization errors, and IndexError for out-of-range access.
        return []

    matches: list[dict[str, Any]] = []
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for i, doc_id in enumerate(ids):
        matches.append({
            "id": doc_id,
            "document": documents[i] if i < len(documents) else "",
            "metadata": metadatas[i] if i < len(metadatas) else {},
            "distance": distances[i] if i < len(distances) else 0.0,
        })

    return matches


def update_todo(db: sqlite3.Connection, collection: Any, todo_id: int, **fields: Any) -> None:
    """Update a TODO's mutable fields in SQLite and ChromaDB.

    Only applies fields that are explicitly provided. Rejects ``epic_id``
    and ``status`` as fields — use ``assign_todo()`` or ``done_todo()``
    for lifecycle transitions.

    Args:
        db: SQLite database connection.
        collection: ChromaDB ``todos`` collection.
        todo_id: The integer TODO ID.
        **fields: Keyword arguments for fields to update. Supported keys:
            ``title``, ``description``, ``priority``, ``category``,
            ``secondary_categories``.

    Raises:
        ValueError: If ``epic_id`` or ``status`` is passed, or if no
            valid fields are provided, or if the TODO does not exist.
    """
    rejected = {"epic_id", "status"} & set(fields)
    if rejected:
        raise ValueError(f"Cannot update {rejected} via update_todo(). Use assign_todo()/done_todo() instead.")

    allowed = {"title", "description", "priority", "category", "secondary_categories"}
    valid_fields = {k: v for k, v in fields.items() if k in allowed}

    if not valid_fields:
        raise ValueError("No valid fields provided for update.")

    existing = get_todo(db, todo_id)
    if not existing:
        raise ValueError(f"TODO {format_todo_id(todo_id)} not found.")

    now = datetime.now().isoformat()
    valid_fields["last_updated_at"] = now

    set_clauses = ", ".join(f"{k} = ?" for k in valid_fields)
    values = list(valid_fields.values()) + [todo_id]
    # Assign to variable so ruff S608 does not flag the parameterized execute call.
    update_sql = f"UPDATE todos SET {set_clauses} WHERE id = ?"
    db.execute(update_sql, values)
    db.commit()

    # Rebuild ChromaDB document with updated fields
    merged = {**existing, **valid_fields}
    context_dict = json.loads(merged.get("context_snapshot") or "{}")
    doc_text = build_chromadb_document(merged["title"], merged.get("description", ""), context_dict)
    collection.upsert(
        ids=[str(todo_id)],
        documents=[doc_text],
        metadatas=[
            {
                "todo_id": todo_id,
                "status": merged.get("status", "open"),
                "category": merged.get("category", ""),
                "priority": merged.get("priority", 5),
                "epic_id": merged.get("epic_id", ""),
                "source_workspace": merged.get("source_workspace", ""),
                "created_at": merged.get("created_at", ""),
            }
        ],
    )


def done_todo(db: sqlite3.Connection, collection: Any, todo_id: int, resolution: str) -> None:
    """Mark a TODO as done with a required resolution note.

    Args:
        db: SQLite database connection.
        collection: ChromaDB ``todos`` collection.
        todo_id: The integer TODO ID.
        resolution: Required resolution note explaining how the TODO
            was addressed.

    Raises:
        ValueError: If the TODO does not exist or is already done.
    """
    existing = get_todo(db, todo_id)
    if not existing:
        raise ValueError(f"TODO {format_todo_id(todo_id)} not found.")
    if existing["status"] == "done":
        raise ValueError(f"TODO {format_todo_id(todo_id)} is already done.")

    now = datetime.now().isoformat()
    db.execute(
        "UPDATE todos SET status = 'done', resolution = ?, last_updated_at = ? WHERE id = ?",
        (resolution, now, todo_id),
    )
    db.commit()

    # Update ChromaDB metadata (include documents for consistency with add_todo/update_todo)
    context_dict = json.loads(existing.get("context_snapshot") or "{}")
    doc_text = build_chromadb_document(existing["title"], existing.get("description", ""), context_dict)
    collection.upsert(
        ids=[str(todo_id)],
        documents=[doc_text],
        metadatas=[
            {
                "todo_id": todo_id,
                "status": "done",
                "category": existing.get("category", ""),
                "priority": existing.get("priority", 5),
                "epic_id": existing.get("epic_id", ""),
                "source_workspace": existing.get("source_workspace", ""),
                "created_at": existing.get("created_at", ""),
            }
        ],
    )


def assign_todo(
    db: sqlite3.Connection,
    todos_collection: Any,
    ledger_collection: Any,
    todo_id: int,
    epic_id: str,
) -> None:
    """Assign a TODO to an epic, auto-creating a backlog epic if needed.

    Sets the TODO's ``epic_id`` and transitions status to ``assigned``.
    Creates the target epic via ``create_epic()`` if it does not already
    exist. Checkpoints a ``todo_linked`` artifact to the execution ledger
    collection for audit trail.

    Args:
        db: SQLite database connection.
        todos_collection: ChromaDB ``todos`` collection.
        ledger_collection: ChromaDB execution ledger collection.
        todo_id: The integer TODO ID.
        epic_id: The epic identifier to assign to.

    Raises:
        ValueError: If the TODO does not exist.
    """
    existing = get_todo(db, todo_id)
    if not existing:
        raise ValueError(f"TODO {format_todo_id(todo_id)} not found.")

    # Auto-create backlog epic if it does not exist
    create_epic(db, epic_id=epic_id, title=f"Backlog epic for {epic_id}", status="backlog")

    now = datetime.now().isoformat()
    db.execute(
        "UPDATE todos SET epic_id = ?, status = 'assigned', last_updated_at = ? WHERE id = ?",
        (epic_id, now, todo_id),
    )
    db.commit()

    # Update ChromaDB todos metadata (include documents for consistency with add_todo/update_todo)
    context_dict = json.loads(existing.get("context_snapshot") or "{}")
    doc_text = build_chromadb_document(existing["title"], existing.get("description", ""), context_dict)
    todos_collection.upsert(
        ids=[str(todo_id)],
        documents=[doc_text],
        metadatas=[
            {
                "todo_id": todo_id,
                "status": "assigned",
                "category": existing.get("category", ""),
                "priority": existing.get("priority", 5),
                "epic_id": epic_id,
                "source_workspace": existing.get("source_workspace", ""),
                "created_at": existing.get("created_at", ""),
            }
        ],
    )

    # Checkpoint todo_linked artifact to the execution ledger
    formatted_id = format_todo_id(todo_id)
    content = f"Linked {formatted_id}: {existing['title']}"
    stores = (ledger_collection, db)

    # Resolve the actual epic status rather than hardcoding "backlog"
    epic_row = db.execute("SELECT status FROM epics WHERE epic_id = ?", (epic_id,)).fetchone()
    actual_epic_status = epic_row["status"] if epic_row else ""

    save_artifact(
        stores=stores,
        content=content,
        params={
            "epic_id": epic_id,
            "artifact_type": "todo_linked",
            "agent_model": "",
            "wave": "",
            "domain": "",
            "step": "",
            "agent_role": "",
            "verdict": "",
            "version": 1,
            "parent_id": "",
            "epic_status": actual_epic_status,
            "title": "",
            "priority": 5,
            "depends_on": "[]",
        },
    )


def insert_category(db: sqlite3.Connection, name: str, description: str) -> None:
    """Insert a new category into the todo_categories table.

    Validates that the category name matches the required pattern
    (lowercase alphanumeric and hyphens only).

    Args:
        db: SQLite database connection.
        name: Category name (must match ``^[a-z0-9-]+$``).
        description: Human-readable category description.

    Raises:
        ValueError: If the name does not match the required pattern.
    """
    if not _CATEGORY_NAME_PATTERN.match(name):
        raise ValueError(f"Category name '{name}' must match ^[a-z0-9-]+$ (lowercase alphanumeric and hyphens only).")

    now = datetime.now().isoformat()
    db.execute(
        "INSERT OR IGNORE INTO todo_categories (name, description, created_at) VALUES (?, ?, ?)",
        (name, description, now),
    )
    db.commit()
