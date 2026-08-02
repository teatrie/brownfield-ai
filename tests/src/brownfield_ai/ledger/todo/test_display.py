"""Tests for brownfield_ai.ledger.todo.display — render_compact_table and render_verbose."""

from __future__ import annotations

import json

from brownfield_ai.ledger.todo.display import render_compact_table, render_verbose

# ---------------------------------------------------------------------------
# render_compact_table
# ---------------------------------------------------------------------------


def test_render_compact_table_shows_no_todos_when_empty() -> None:
    """Empty list produces 'No TODOs found.' message."""
    result = render_compact_table([])
    assert result == "No TODOs found."


def test_render_compact_table_includes_formatted_id_and_title() -> None:
    """Formatted ID, title, status, and category appear in the output."""
    todos = [{"id": 1, "title": "Fix memory leak", "status": "open", "priority": 3, "category": "infra"}]

    result = render_compact_table(todos)

    assert "TODO-0001" in result
    assert "Fix memory leak" in result
    assert "open" in result
    assert "infra" in result


def test_render_compact_table_handles_missing_optional_fields() -> None:
    """Minimal dict without optional fields renders without error."""
    todos = [{"id": 5, "title": "Minimal TODO"}]

    result = render_compact_table(todos)

    assert "TODO-0005" in result
    assert "Minimal TODO" in result


# ---------------------------------------------------------------------------
# render_verbose
# ---------------------------------------------------------------------------


def test_render_verbose_shows_no_todos_when_empty() -> None:
    """Empty list produces 'No TODOs found.' message."""
    result = render_verbose([])
    assert result == "No TODOs found."


def test_render_verbose_renders_context_snapshot_as_text() -> None:
    """Context snapshot fields are rendered as indented key-value pairs."""
    ctx = {
        "schema_version": 1,
        "git_branch": "ACME-9999/branch",
        "active_epic_id": "ACME-9999",
        "modified_files": ["src/main.py"],
        "recent_commits": [{"sha": "abc123ef", "message": "commit msg"}],
        "notes": "",
    }
    todos = [
        {
            "id": 2,
            "title": "Verbose TODO",
            "description": "Some description",
            "status": "open",
            "priority": 1,
            "category": "agents",
            "secondary_categories": None,
            "epic_id": None,
            "source_workspace": "/ws",
            "resolution": None,
            "created_at": "2026-01-01T00:00:00",
            "last_updated_at": "2026-01-01T00:00:00",
            "context_snapshot": json.dumps(ctx),
        }
    ]

    result = render_verbose(todos)

    assert "TODO-0002" in result
    assert "Verbose TODO" in result
    assert "ACME-9999/branch" in result
    assert "src/main.py" in result
    assert "abc123ef" in result


def test_render_verbose_skips_missing_optional_fields_gracefully() -> None:
    """Minimal dict without optional fields renders without error."""
    todos = [{"id": 7, "title": "Sparse TODO"}]

    result = render_verbose(todos)

    assert "TODO-0007" in result
    assert "Sparse TODO" in result


def test_render_verbose_handles_malformed_context_snapshot() -> None:
    """Malformed JSON in context_snapshot is rendered as raw text."""
    todos = [
        {
            "id": 3,
            "title": "Bad Context",
            "context_snapshot": "not-valid-json{{{",
        }
    ]

    result = render_verbose(todos)

    assert "TODO-0003" in result
    assert "Bad Context" in result
