"""Tests for brownfield_ai.ledger.todo.constants — ID formatting and parsing."""

from __future__ import annotations

import pytest

from brownfield_ai.ledger.todo.constants import format_todo_id, parse_todo_id

# ---------------------------------------------------------------------------
# format_todo_id
# ---------------------------------------------------------------------------


def test_format_todo_id_zero_pads_to_four_digits() -> None:
    """Verify zero-padding across the ID range."""
    assert format_todo_id(1) == "TODO-0001"
    assert format_todo_id(42) == "TODO-0042"
    assert format_todo_id(1000) == "TODO-1000"
    assert format_todo_id(9999) == "TODO-9999"


# ---------------------------------------------------------------------------
# parse_todo_id
# ---------------------------------------------------------------------------


def test_parse_todo_id_accepts_prefixed_format() -> None:
    """Standard TODO-NNNN format parses correctly."""
    assert parse_todo_id("TODO-0003") == 3
    assert parse_todo_id("TODO-0042") == 42


def test_parse_todo_id_accepts_bare_integer() -> None:
    """Bare integers and whitespace-padded inputs parse correctly."""
    assert parse_todo_id("3") == 3
    assert parse_todo_id("  7  ") == 7


def test_parse_todo_id_accepts_lowercase_prefix() -> None:
    """Case-insensitive prefix handling."""
    assert parse_todo_id("todo-0005") == 5


def test_parse_todo_id_raises_on_invalid_input() -> None:
    """Non-numeric input raises ValueError."""
    with pytest.raises(ValueError):
        parse_todo_id("NOT-A-NUMBER")
