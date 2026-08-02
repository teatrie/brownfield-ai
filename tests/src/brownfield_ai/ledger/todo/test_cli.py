"""Tests for brownfield_ai.ledger.todo.cli — CLI wrappers (add_batch, file I/O, validation)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from brownfield_ai.ledger.todo.cli import add_batch

# ---------------------------------------------------------------------------
# add_batch
# ---------------------------------------------------------------------------


def test_add_batch_creates_todos_from_valid_file(tmp_path, make_db, make_collection, make_client_mock) -> None:
    """Two valid entries without epic_id each trigger exactly one add_todo call."""
    batch = [
        {"title": "First TODO", "category": "infra", "priority": 3},
        {"title": "Second TODO", "category": "agents", "priority": 7},
    ]
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(json.dumps(batch))

    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    client_mock = make_client_mock(todos_col, ledger_col)

    with (
        patch("brownfield_ai.ledger.todo.cli.get_db", return_value=db),
        patch("brownfield_ai.ledger.todo.cli.get_client", return_value=client_mock),
        patch("brownfield_ai.ledger.todo.cli.add_todo") as mock_add_todo,
        patch("brownfield_ai.ledger.todo.cli.capture_context", return_value={"schema_version": 1}),
    ):
        mock_add_todo.return_value = 1
        add_batch(batch_file=str(batch_file))

    assert mock_add_todo.call_count == 2
    first_call_kwargs = mock_add_todo.call_args_list[0]
    assert first_call_kwargs.args[2] == "First TODO"
    assert first_call_kwargs.kwargs["category"] == "infra"
    assert first_call_kwargs.kwargs["priority"] == 3
    second_call_kwargs = mock_add_todo.call_args_list[1]
    assert second_call_kwargs.args[2] == "Second TODO"


def test_add_batch_validates_category_pattern(tmp_path, make_db, make_collection, make_client_mock) -> None:
    """An entry whose category violates ^[a-z0-9-]+$ causes SystemExit."""
    batch = [{"title": "Bad Category", "category": "INVALID_CAPS", "priority": 5}]
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(json.dumps(batch))

    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    client_mock = make_client_mock(todos_col, ledger_col)

    with (
        patch("brownfield_ai.ledger.todo.cli.get_db", return_value=db),
        patch("brownfield_ai.ledger.todo.cli.get_client", return_value=client_mock),
    ):
        with pytest.raises(SystemExit):
            add_batch(batch_file=str(batch_file))


def test_add_batch_validates_priority_range_too_high(tmp_path, make_db, make_collection, make_client_mock) -> None:
    """Priority > 9 causes SystemExit."""
    batch = [{"title": "High Prio", "category": "infra", "priority": 10}]
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(json.dumps(batch))

    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    client_mock = make_client_mock(todos_col, ledger_col)

    with (
        patch("brownfield_ai.ledger.todo.cli.get_db", return_value=db),
        patch("brownfield_ai.ledger.todo.cli.get_client", return_value=client_mock),
    ):
        with pytest.raises(SystemExit):
            add_batch(batch_file=str(batch_file))


def test_add_batch_validates_priority_range_negative(tmp_path, make_db, make_collection, make_client_mock) -> None:
    """Priority < 0 causes SystemExit."""
    batch = [{"title": "Negative Prio", "category": "infra", "priority": -1}]
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(json.dumps(batch))

    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    client_mock = make_client_mock(todos_col, ledger_col)

    with (
        patch("brownfield_ai.ledger.todo.cli.get_db", return_value=db),
        patch("brownfield_ai.ledger.todo.cli.get_client", return_value=client_mock),
    ):
        with pytest.raises(SystemExit):
            add_batch(batch_file=str(batch_file))


def test_add_batch_rejects_missing_required_field_title(tmp_path, make_db, make_collection, make_client_mock) -> None:
    """Entry missing ``title`` causes SystemExit."""
    batch: list[dict[str, Any]] = [{"category": "infra", "priority": 5}]
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(json.dumps(batch))

    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    client_mock = make_client_mock(todos_col, ledger_col)

    with (
        patch("brownfield_ai.ledger.todo.cli.get_db", return_value=db),
        patch("brownfield_ai.ledger.todo.cli.get_client", return_value=client_mock),
    ):
        with pytest.raises(SystemExit):
            add_batch(batch_file=str(batch_file))


def test_add_batch_rejects_missing_required_field_category(tmp_path, make_db, make_collection, make_client_mock) -> None:
    """Entry missing ``category`` causes SystemExit."""
    batch: list[dict[str, Any]] = [{"title": "No Category", "priority": 5}]
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(json.dumps(batch))

    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    client_mock = make_client_mock(todos_col, ledger_col)

    with (
        patch("brownfield_ai.ledger.todo.cli.get_db", return_value=db),
        patch("brownfield_ai.ledger.todo.cli.get_client", return_value=client_mock),
    ):
        with pytest.raises(SystemExit):
            add_batch(batch_file=str(batch_file))


def test_add_batch_rejects_missing_required_field_priority(tmp_path, make_db, make_collection, make_client_mock) -> None:
    """Entry missing ``priority`` causes SystemExit."""
    batch: list[dict[str, Any]] = [{"title": "No Priority", "category": "infra"}]
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(json.dumps(batch))

    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    client_mock = make_client_mock(todos_col, ledger_col)

    with (
        patch("brownfield_ai.ledger.todo.cli.get_db", return_value=db),
        patch("brownfield_ai.ledger.todo.cli.get_client", return_value=client_mock),
    ):
        with pytest.raises(SystemExit):
            add_batch(batch_file=str(batch_file))


def test_add_batch_rejects_malformed_json(tmp_path, make_db, make_collection, make_client_mock) -> None:
    """A file containing invalid JSON causes SystemExit."""
    batch_file = tmp_path / "batch.json"
    batch_file.write_text("{not valid json[[[")

    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    client_mock = make_client_mock(todos_col, ledger_col)

    with (
        patch("brownfield_ai.ledger.todo.cli.get_db", return_value=db),
        patch("brownfield_ai.ledger.todo.cli.get_client", return_value=client_mock),
    ):
        with pytest.raises(SystemExit):
            add_batch(batch_file=str(batch_file))


def test_add_batch_assigns_to_epic_when_epic_id_present(tmp_path, make_db, make_collection, make_client_mock) -> None:
    """An entry with ``epic_id`` causes ``assign_todo`` to be called."""
    batch = [{"title": "Epic TODO", "category": "agents", "priority": 2, "epic_id": "ACME-1234"}]
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(json.dumps(batch))

    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    client_mock = make_client_mock(todos_col, ledger_col)

    with (
        patch("brownfield_ai.ledger.todo.cli.get_db", return_value=db),
        patch("brownfield_ai.ledger.todo.cli.get_client", return_value=client_mock),
        patch("brownfield_ai.ledger.todo.cli.add_todo", return_value=42) as mock_add_todo,
        patch("brownfield_ai.ledger.todo.cli.assign_todo") as mock_assign_todo,
        patch("brownfield_ai.ledger.todo.cli.capture_context", return_value={"schema_version": 1}),
    ):
        add_batch(batch_file=str(batch_file))

    mock_add_todo.assert_called_once()
    mock_assign_todo.assert_called_once()
    assign_call = mock_assign_todo.call_args
    # Fourth positional arg is todo_id, fifth is epic_id
    assert assign_call.args[3] == 42
    assert assign_call.args[4] == "ACME-1234"


def test_add_batch_handles_empty_array(tmp_path, make_db, make_collection, make_client_mock) -> None:
    """An empty JSON array produces no errors and zero add_todo calls."""
    batch_file = tmp_path / "batch.json"
    batch_file.write_text("[]")

    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    client_mock = make_client_mock(todos_col, ledger_col)

    with (
        patch("brownfield_ai.ledger.todo.cli.get_db", return_value=db),
        patch("brownfield_ai.ledger.todo.cli.get_client", return_value=client_mock),
        patch("brownfield_ai.ledger.todo.cli.add_todo") as mock_add_todo,
    ):
        add_batch(batch_file=str(batch_file))

    mock_add_todo.assert_not_called()


def test_add_batch_rejects_nonexistent_file(tmp_path, make_db, make_collection, make_client_mock) -> None:
    """A batch_file path that does not exist causes SystemExit."""
    nonexistent = str(tmp_path / "does_not_exist.json")

    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    client_mock = make_client_mock(todos_col, ledger_col)

    with (
        patch("brownfield_ai.ledger.todo.cli.get_db", return_value=db),
        patch("brownfield_ai.ledger.todo.cli.get_client", return_value=client_mock),
    ):
        with pytest.raises(SystemExit):
            add_batch(batch_file=nonexistent)


def test_add_batch_fails_fast_on_first_invalid_entry(tmp_path, make_db, make_collection, make_client_mock) -> None:
    """Validation runs over all entries before any add_todo call.

    Two entries: first valid, second has bad category. SystemExit is raised
    and add_todo must not have been called at all (validate-all-first semantics).
    """
    batch = [
        {"title": "Valid Entry", "category": "infra", "priority": 4},
        {"title": "Invalid Entry", "category": "BAD_CAPS", "priority": 4},
    ]
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(json.dumps(batch))

    db = make_db
    todos_col = make_collection
    ledger_col = MagicMock()
    client_mock = make_client_mock(todos_col, ledger_col)

    with (
        patch("brownfield_ai.ledger.todo.cli.get_db", return_value=db),
        patch("brownfield_ai.ledger.todo.cli.get_client", return_value=client_mock),
        patch("brownfield_ai.ledger.todo.cli.add_todo") as mock_add_todo,
    ):
        with pytest.raises(SystemExit):
            add_batch(batch_file=str(batch_file))

    mock_add_todo.assert_not_called()
