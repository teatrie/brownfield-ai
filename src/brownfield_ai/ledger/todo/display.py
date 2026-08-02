"""Display rendering functions for TODO records.

Provides compact tabular and verbose multi-line renderers consumed by
the CLI ``list_`` subcommand.
"""

from __future__ import annotations

import json
from typing import Any

from brownfield_ai.ledger.todo.constants import format_todo_id


def render_compact_table(todos: list[dict[str, Any]]) -> str:
    """Render TODOs as a compact tabular display.

    Columns: ID (TODO-0001), priority, status, category, title.

    Args:
        todos: List of TODO row dictionaries.

    Returns:
        Formatted table string with header and aligned columns.
    """
    if not todos:
        return "No TODOs found."

    header = f"{'ID':<11} {'Pri':>3} {'Status':<10} {'Category':<16} Title"
    separator = "-" * 80
    lines = [header, separator]

    for todo in todos:
        todo_id = format_todo_id(todo["id"])
        priority = str(todo.get("priority", 5))
        status = todo.get("status", "open")
        category = todo.get("category", "") or ""
        title = todo.get("title", "")
        lines.append(f"{todo_id:<11} {priority:>3} {status:<10} {category:<16} {title}")

    return "\n".join(lines)


def render_verbose(todos: list[dict[str, Any]]) -> str:
    """Render TODOs with all fields in a human-readable verbose format.

    The ``context_snapshot`` is rendered as indented key-value text rather
    than raw JSON. Missing fields are skipped gracefully.

    Args:
        todos: List of TODO row dictionaries.

    Returns:
        Verbose multi-line display string.
    """
    if not todos:
        return "No TODOs found."

    sections: list[str] = []
    for todo in todos:
        lines: list[str] = []
        todo_id = format_todo_id(todo["id"])
        lines.append(f"--- {todo_id} ---")
        lines.append(f"  Title:        {todo.get('title', '')}")

        if todo.get("description"):
            lines.append(f"  Description:  {todo['description']}")

        lines.append(f"  Priority:     {todo.get('priority', 5)}")
        lines.append(f"  Status:       {todo.get('status', 'open')}")

        if todo.get("category"):
            lines.append(f"  Category:     {todo['category']}")
        if todo.get("secondary_categories"):
            lines.append(f"  Secondary:    {todo['secondary_categories']}")
        if todo.get("epic_id"):
            lines.append(f"  Epic:         {todo['epic_id']}")
        if todo.get("source_workspace"):
            lines.append(f"  Workspace:    {todo['source_workspace']}")
        if todo.get("resolution"):
            lines.append(f"  Resolution:   {todo['resolution']}")
        if todo.get("created_at"):
            lines.append(f"  Created:      {todo['created_at']}")
        if todo.get("last_updated_at"):
            lines.append(f"  Updated:      {todo['last_updated_at']}")

        # Render context_snapshot as human-readable indented text
        context_raw = todo.get("context_snapshot")
        if context_raw:
            try:
                ctx = json.loads(context_raw)
                lines.append("  Context:")
                if ctx.get("git_branch"):
                    lines.append(f"    Branch:          {ctx['git_branch']}")
                if ctx.get("active_epic_id"):
                    lines.append(f"    Active Epic:     {ctx['active_epic_id']}")
                if ctx.get("modified_files"):
                    lines.append("    Modified Files:")
                    for f in ctx["modified_files"]:
                        lines.append(f"      - {f}")
                if ctx.get("recent_commits"):
                    lines.append("    Recent Commits:")
                    for commit in ctx["recent_commits"]:
                        lines.append(f"      - {commit.get('sha', '')[:8]} {commit.get('message', '')}")
                if ctx.get("notes"):
                    lines.append(f"    Notes:           {ctx['notes']}")
            except (json.JSONDecodeError, TypeError):
                lines.append(f"  Context:      {context_raw}")

        sections.append("\n".join(lines))

    return "\n\n".join(sections)
