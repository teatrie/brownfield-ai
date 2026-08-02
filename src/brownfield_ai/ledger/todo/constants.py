"""Shared constants and ID utilities for the TODO subsystem.

Houses the canonical column list, regex patterns, collection name, and
format/parse helpers consumed across queries, mutations, display, and CLI
modules.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TODOS_COLLECTION_NAME: str = "todos"

_TODOS_BASE_SQL: str = (
    "SELECT id, title, description, context_snapshot, category,"
    " secondary_categories, priority, epic_id, source_workspace,"
    " status, resolution, created_at, last_updated_at FROM todos"
)

_EPIC_ID_PATTERN: re.Pattern[str] = re.compile(r"[A-Z]+-\d+")
_CATEGORY_NAME_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9-]+$")


# ---------------------------------------------------------------------------
# ID formatting
# ---------------------------------------------------------------------------


def format_todo_id(id_int: int) -> str:
    """Format an integer TODO ID as a zero-padded display string.

    Args:
        id_int: The integer TODO ID.

    Returns:
        Formatted ID like ``TODO-0001``.
    """
    return f"TODO-{id_int:04d}"


def parse_todo_id(id_str: str) -> int:
    """Parse a TODO ID string into its integer value.

    Accepts both prefixed format (``TODO-0003``) and bare integers (``3``).

    Args:
        id_str: The TODO ID string to parse.

    Returns:
        The integer TODO ID.

    Raises:
        ValueError: If the string cannot be parsed as a TODO ID.
    """
    cleaned = id_str.strip().upper()
    if cleaned.startswith("TODO-"):
        cleaned = cleaned[5:]
    return int(cleaned)
