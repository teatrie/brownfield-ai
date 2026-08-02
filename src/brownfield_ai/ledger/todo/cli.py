"""CLI wrappers (thin defopt handlers) for the TODO subsystem.

Each function is a CLI subcommand that wires up infrastructure (DB, ChromaDB)
and delegates to the service-layer functions in ``queries``, ``mutations``,
``context``, and ``display``.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import defopt

from brownfield_ai.ledger.artifacts.constants import COLLECTION_NAME
from brownfield_ai.ledger.infra import get_client, get_db
from brownfield_ai.ledger.todo.constants import (
    _CATEGORY_NAME_PATTERN,
    TODOS_COLLECTION_NAME,
    format_todo_id,
    parse_todo_id,
)
from brownfield_ai.ledger.todo.context import build_chromadb_document, capture_context
from brownfield_ai.ledger.todo.display import render_compact_table, render_verbose
from brownfield_ai.ledger.todo.mutations import (
    add_todo,
    assign_todo,
    detect_duplicates,
    done_todo,
    insert_category,
    update_todo,
)
from brownfield_ai.ledger.todo.queries import fetch_categories, list_todos


def add_batch(*, batch_file: str) -> None:
    """Add TODOs in batch from a JSON file.

    Reads a JSON array from ``batch_file``, validates each entry, and creates
    TODOs via ``add_todo()``. Entries with ``epic_id`` are auto-assigned.

    Args:
        batch_file: Path to a JSON file containing a list of TODO entries.

    Raises:
        SystemExit: If the batch file is missing, malformed, or any entry
            fails validation.
    """
    # --- Read file ---
    try:
        with open(batch_file) as fh:
            entries = json.load(fh)
    except FileNotFoundError:
        print(f"ERROR: batch file not found: {batch_file}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON in batch file: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(entries, list):
        print("ERROR: batch file must contain a JSON array", file=sys.stderr)
        sys.exit(1)

    # --- Validate ALL entries before any DB writes ---
    for idx, entry in enumerate(entries):
        if not isinstance(entry.get("title"), str) or not entry.get("title"):
            print(f"ERROR: entry {idx} missing required field 'title'", file=sys.stderr)
            sys.exit(1)
        if not isinstance(entry.get("category"), str) or not entry.get("category"):
            print(f"ERROR: entry {idx} missing required field 'category'", file=sys.stderr)
            sys.exit(1)
        if "priority" not in entry or not isinstance(entry["priority"], int):
            print(f"ERROR: entry {idx} missing required field 'priority'", file=sys.stderr)
            sys.exit(1)
        if not _CATEGORY_NAME_PATTERN.match(entry["category"]):
            print(
                f"ERROR: entry {idx} category '{entry['category']}' must match {_CATEGORY_NAME_PATTERN.pattern}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not (0 <= entry["priority"] <= 9):
            print(f"ERROR: entry {idx} priority {entry['priority']} must be in range 0-9", file=sys.stderr)
            sys.exit(1)

    # --- Process entries ---
    db = get_db()
    try:
        client = get_client()
        collection = client.get_or_create_collection(name=TODOS_COLLECTION_NAME)
        ledger_collection = client.get_or_create_collection(name=COLLECTION_NAME)

        source_workspace = os.environ.get("HOST_PWD", os.getcwd())
        context = capture_context(db)

        for entry in entries:
            todo_id = add_todo(
                db,
                collection,
                entry["title"],
                context,
                category=entry["category"],
                priority=entry["priority"],
                source_workspace=source_workspace,
            )
            print(f"Created {format_todo_id(todo_id)}: {entry['title']}")

            if entry.get("epic_id"):
                assign_todo(db, collection, ledger_collection, todo_id, entry["epic_id"])
    finally:
        db.close()


def add(
    title: str,
    *,
    description: str = "",
    notes: str = "",
    category: str = "",
    secondary_categories: str = "",
    priority: int = 5,
) -> None:
    """Add a new TODO with auto-captured git context.

    Captures the current git branch, modified files, and recent commits
    as a context snapshot. Runs duplicate detection and prints a warning
    if similar TODOs exist (non-blocking).

    Args:
        title: The TODO title (required).
        description: Optional longer description.
        notes: Optional free-text notes included in context snapshot.
        category: Primary category name.
        secondary_categories: Space-delimited secondary category names.
        priority: Numeric priority 0-9 where 0 is highest (default 5).
    """
    db = get_db()
    try:
        client = get_client()
        collection = client.get_or_create_collection(name=TODOS_COLLECTION_NAME)

        source_workspace = os.environ.get("HOST_PWD", os.getcwd())
        context = capture_context(db, notes=notes)

        # Duplicate detection (non-blocking)
        doc_text = build_chromadb_document(title, description, context)
        duplicates = detect_duplicates(collection, doc_text)
        if duplicates:
            print("WARNING: Similar TODOs detected:")
            for dup in duplicates:
                meta = dup.get("metadata", {})
                dup_id = format_todo_id(meta.get("todo_id", 0)) if meta.get("todo_id") else dup.get("id", "?")
                distance = dup.get("distance", 0.0)
                print(f"  {dup_id} (distance: {distance:.3f})")

        todo_id = add_todo(
            db,
            collection,
            title,
            context,
            description=description,
            notes=notes,
            category=category,
            secondary_categories=secondary_categories,
            priority=priority,
            source_workspace=source_workspace,
        )
        print(f"Created {format_todo_id(todo_id)}: {title}")
    finally:
        db.close()


def list_(
    *,
    status: str = "open",
    category: str = "",
    epic_id: str = "",
    limit: int = 20,
    offset: int = 0,
    verbose: bool = False,
) -> None:
    """List TODOs with optional filters and pagination.

    Args:
        status: Status filter. Space-delimited for multiple values
            (e.g. ``"open assigned"``). Use ``"all"`` for no filter.
        category: Filter by primary category (exact match).
        epic_id: Filter by associated epic ID (exact match).
        limit: Maximum number of results (default 20).
        offset: Pagination offset (default 0).
        verbose: Show all fields including context snapshot (default False).
    """
    db = get_db()
    try:
        if status == "all":
            statuses: list[str] = []
        else:
            statuses = status.split()

        todos = list_todos(db, statuses, category=category, epic_id=epic_id, limit=limit, offset=offset)

        if verbose:
            print(render_verbose(todos))
        else:
            print(render_compact_table(todos))
    finally:
        db.close()


def done(todo_id: str, *, resolution: str) -> None:
    """Mark a TODO as done with a resolution note.

    Args:
        todo_id: The TODO ID (accepts ``TODO-0003`` or ``3``).
        resolution: Required resolution note explaining how the TODO
            was addressed.
    """
    db = get_db()
    try:
        client = get_client()
        collection = client.get_or_create_collection(name=TODOS_COLLECTION_NAME)

        parsed_id = parse_todo_id(todo_id)
        done_todo(db, collection, parsed_id, resolution)
        print(f"Marked {format_todo_id(parsed_id)} as done.")
    finally:
        db.close()


def assign(todo_id: str, *, epic_id: str) -> None:
    """Assign a TODO to an epic, creating a backlog epic if needed.

    Args:
        todo_id: The TODO ID (accepts ``TODO-0003`` or ``3``).
        epic_id: The epic identifier to assign to.
    """
    db = get_db()
    try:
        client = get_client()
        todos_collection = client.get_or_create_collection(name=TODOS_COLLECTION_NAME)
        ledger_collection = client.get_or_create_collection(name=COLLECTION_NAME)

        parsed_id = parse_todo_id(todo_id)
        assign_todo(db, todos_collection, ledger_collection, parsed_id, epic_id)
        print(f"Assigned {format_todo_id(parsed_id)} to epic {epic_id}.")
    finally:
        db.close()


def update(
    todo_id: str,
    *,
    title: str = "",
    description: str = "",
    priority: int = -1,
    category: str = "",
    secondary_categories: str = "",
) -> None:
    """Update a TODO's mutable fields.

    Only non-sentinel values are applied. Empty strings and priority=-1
    are treated as "not provided" and excluded from the update.

    Args:
        todo_id: The TODO ID (accepts ``TODO-0003`` or ``3``).
        title: New title (empty = no change).
        description: New description (empty = no change).
        priority: New priority 0-9 (``-1`` = no change).
        category: New primary category (empty = no change).
        secondary_categories: New secondary categories (empty = no change).
    """
    db = get_db()
    try:
        client = get_client()
        collection = client.get_or_create_collection(name=TODOS_COLLECTION_NAME)

        parsed_id = parse_todo_id(todo_id)

        # Filter sentinel values
        fields: dict[str, Any] = {}
        if title:
            fields["title"] = title
        if description:
            fields["description"] = description
        if priority >= 0:
            fields["priority"] = priority
        if category:
            fields["category"] = category
        if secondary_categories:
            fields["secondary_categories"] = secondary_categories

        if not fields:
            print("No fields to update (all values are defaults).")
            return

        update_todo(db, collection, parsed_id, **fields)
        print(f"Updated {format_todo_id(parsed_id)}.")
    finally:
        db.close()


def add_category(name: str, *, description: str) -> None:
    """Add a new TODO category.

    Category names must be lowercase alphanumeric with hyphens only.

    Args:
        name: Category name (must match ``^[a-z0-9-]+$``).
        description: Human-readable category description.
    """
    db = get_db()
    try:
        insert_category(db, name, description)
        print(f"Added category: {name}")
    finally:
        db.close()


def list_categories() -> None:
    """List all available TODO categories."""
    db = get_db()
    try:
        categories = fetch_categories(db)

        if not categories:
            print("No categories found.")
            return

        header = f"{'Name':<20} Description"
        separator = "-" * 60
        lines = [header, separator]
        for cat in categories:
            lines.append(f"{cat['name']:<20} {cat.get('description', '')}")
        print("\n".join(lines))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    defopt.run([add, add_batch, list_, done, assign, update, add_category, list_categories])
