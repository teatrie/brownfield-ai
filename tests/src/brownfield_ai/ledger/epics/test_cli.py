"""Unit tests for brownfield_ai.ledger.epics.cli.

Tests every CLI subcommand in the epics module (10 functions, 28 tests).
All service-layer calls are patched at the import-binding site
(``brownfield_ai.ledger.epics.cli.*``), never at the definition site.
"""

from __future__ import annotations

import json
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from brownfield_ai.ledger.artifacts.constants import COLLECTION_NAME
from brownfield_ai.ledger.epics.cli import (
    check_reviews_cli,
    create,
    index_epics,
    next_plan,
    process_reviews_cli,
    release,
    resume,
    set_prs_cli,
    status,
    touch,
)

# ---------------------------------------------------------------------------
# Patch target prefix
# ---------------------------------------------------------------------------

_CLI = "brownfield_ai.ledger.epics.cli"


# ---------------------------------------------------------------------------
# touch (2 tests)
# ---------------------------------------------------------------------------


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.touch_epic", return_value=True)
def test_touch_prints_touched_on_success(
    mock_touch: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """touch() prints 'Touched <id>' when the epic exists."""
    touch("ACME-100")
    out = capsys.readouterr().out
    assert "Touched ACME-100" in out


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.touch_epic", return_value=False)
def test_touch_exits_1_when_epic_not_found(
    mock_touch: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """touch() prints not-found message and exits 1 when epic is missing."""
    with pytest.raises(SystemExit) as exc_info:
        touch("ACME-GONE")
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "not found" in out


# ---------------------------------------------------------------------------
# create (2 tests)
# ---------------------------------------------------------------------------


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.create_epic", return_value=True)
def test_create_prints_created_on_insert(
    mock_create: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """create() prints 'Created epic ...' on successful insert."""
    create("ACME-200", title="New Epic")
    out = capsys.readouterr().out
    assert "Created epic ACME-200" in out
    mock_create.assert_called_once()
    _, kwargs = mock_create.call_args
    assert kwargs["status"] == "backlog"
    assert kwargs["priority"] == 5


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.create_epic", return_value=False)
def test_create_prints_already_exists_on_duplicate(
    mock_create: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """create() prints 'already exists' when the epic is a duplicate."""
    create("ACME-200", title="Dup Epic")
    out = capsys.readouterr().out
    assert "already exists" in out


# ---------------------------------------------------------------------------
# status (8 tests)
# ---------------------------------------------------------------------------


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.update_status", return_value={"success": True})
def test_status_prints_updated_on_success(
    mock_update: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """status() prints 'Updated <id> to <status>' on success."""
    status("ACME-300", new_status="in_progress")
    out = capsys.readouterr().out
    assert "Updated ACME-300 to in_progress" in out


@patch(f"{_CLI}.get_db")
@patch(
    f"{_CLI}.update_status",
    return_value={"success": False, "error": "Transition denied"},
)
def test_status_exits_1_on_error(
    mock_update: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """status() prints error and exits 1 on failed transition."""
    with pytest.raises(SystemExit) as exc_info:
        status("ACME-300", new_status="completed")
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Transition denied" in out


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.update_status", return_value={"success": True})
def test_status_fast_path_warns_when_not_approved(
    mock_update: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """fast_path=True with non-approved status prints warning and calls with fast_path=False."""
    status("ACME-300", new_status="in_progress", fast_path=True)
    out = capsys.readouterr().out
    assert "Warning" in out
    assert "no effect" in out
    # Verify update_status was called with fast_path=False (overridden)
    mock_update.assert_called_once()
    _, kwargs = mock_update.call_args
    assert kwargs["fast_path"] is False


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.get_client")
@patch(
    f"{_CLI}.build_and_filter",
    return_value={"ids": []},
)
def test_status_fast_path_blocks_without_artifact(
    mock_filter: MagicMock,
    mock_client: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """fast_path approval is blocked when no pr_changes_required artifact exists."""
    with pytest.raises(SystemExit) as exc_info:
        status("ACME-300", new_status="approved", fast_path=True)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Fast-path approval blocked" in out


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.get_client")
@patch(
    f"{_CLI}.build_and_filter",
    return_value={"ids": ["artifact-1"]},
)
@patch(f"{_CLI}.update_status", return_value={"success": True})
def test_status_fast_path_allows_with_artifact(
    mock_update: MagicMock,
    mock_filter: MagicMock,
    mock_client: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """fast_path approval succeeds when a pr_changes_required artifact exists."""
    status("ACME-300", new_status="approved", fast_path=True)
    out = capsys.readouterr().out
    assert "Updated ACME-300 to approved" in out


@patch(f"{_CLI}.get_db")
@patch(
    f"{_CLI}.update_status",
    side_effect=[
        {"success": False, "action": "confirm_orphan", "todo_ids": [1, 2]},
        {"success": True},
    ],
)
@patch.dict("os.environ", {"CI": "true"})
def test_status_orphan_confirm_auto_forces_in_ci(
    mock_update: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """In CI mode, orphan confirmation is auto-forced and update_status called twice."""
    status("ACME-300", new_status="abandoned")
    out = capsys.readouterr().out
    assert "auto-forcing" in out
    assert "Updated ACME-300 to abandoned" in out
    assert mock_update.call_count == 2
    # Second call must include force=True
    _, second_kwargs = mock_update.call_args_list[1]
    assert second_kwargs["force"] is True


@patch(f"{_CLI}.get_db")
@patch(
    f"{_CLI}.update_status",
    side_effect=[
        {"success": False, "action": "confirm_orphan", "todo_ids": [1]},
        {"success": True},
    ],
)
@patch("builtins.input", return_value="y")
def test_status_orphan_confirm_interactive_yes(
    mock_input: MagicMock,
    mock_update: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Interactive 'y' confirms orphan and calls update_status with force=True."""
    status("ACME-300", new_status="abandoned")
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "Updated ACME-300 to abandoned" in out
    assert mock_update.call_count == 2
    _, second_kwargs = mock_update.call_args_list[1]
    assert second_kwargs["force"] is True


@patch(f"{_CLI}.get_db")
@patch(
    f"{_CLI}.update_status",
    side_effect=[
        {"success": False, "action": "confirm_orphan", "todo_ids": [1]},
    ],
)
@patch("builtins.input", return_value="n")
def test_status_orphan_confirm_interactive_no(
    mock_input: MagicMock,
    mock_update: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Interactive 'n' aborts the orphan and exits 1."""
    with pytest.raises(SystemExit) as exc_info:
        status("ACME-300", new_status="abandoned")
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Aborted." in out
    # Only the first call fires (no force retry)
    assert mock_update.call_count == 1


@patch(f"{_CLI}.get_db")
@patch(
    f"{_CLI}.update_status",
    return_value={"success": False},
)
def test_status_silent_fallthrough_no_action_no_error(
    mock_update: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """status() silently returns when result has no action or error key."""
    status("ACME-300", new_status="completed")
    out = capsys.readouterr().out
    assert "Updated" not in out
    assert "error" not in out.lower()


# ---------------------------------------------------------------------------
# next_plan (2 tests)
# ---------------------------------------------------------------------------


@patch(f"{_CLI}.get_db")
@patch(
    f"{_CLI}.claim_next",
    return_value={"epic_id": "ACME-400", "status": "approved"},
)
def test_next_plan_prints_json_on_claim(
    mock_claim: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """next_plan() prints JSON when a plan is claimed."""
    next_plan(claimed_by="agent-1")
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["epic_id"] == "ACME-400"
    mock_claim.assert_called_once_with(mock_db.return_value, "agent-1", 24)


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.claim_next", return_value=None)
def test_next_plan_prints_no_plans_on_none(
    mock_claim: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """next_plan() prints 'No plans available.' when nothing is claimable."""
    next_plan(claimed_by="agent-1")
    out = capsys.readouterr().out
    assert "No plans available." in out


# ---------------------------------------------------------------------------
# release (2 tests)
# ---------------------------------------------------------------------------


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.release_epic", return_value=True)
def test_release_prints_released_on_success(
    mock_release: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """release() prints 'Released <id>' on success."""
    release("ACME-500")
    out = capsys.readouterr().out
    assert "Released ACME-500" in out


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.release_epic", return_value=False)
def test_release_exits_1_when_not_found(
    mock_release: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """release() exits 1 when epic not found or not in_progress."""
    with pytest.raises(SystemExit) as exc_info:
        release("ACME-GONE")
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "not found" in out


# ---------------------------------------------------------------------------
# set_prs_cli (1 test)
# ---------------------------------------------------------------------------


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.set_current_prs")
def test_set_prs_cli_prints_confirmation(
    mock_set: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """set_prs_cli() prints confirmation with epic_id and pr_refs."""
    set_prs_cli("ACME-600", pr_refs="org/repo#1,org/repo#2")
    out = capsys.readouterr().out
    assert "ACME-600" in out
    assert "org/repo#1,org/repo#2" in out
    mock_set.assert_called_once_with(mock_db.return_value, "ACME-600", "org/repo#1,org/repo#2")


# ---------------------------------------------------------------------------
# check_reviews_cli (1 test)
# ---------------------------------------------------------------------------


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.check_reviews", return_value="ACME-700 in_review org/repo#3")
def test_check_reviews_cli_prints_result(
    mock_check: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """check_reviews_cli() prints the result from check_reviews."""
    check_reviews_cli()
    out = capsys.readouterr().out
    assert "ACME-700" in out
    assert "org/repo#3" in out
    mock_check.assert_called_once_with(mock_db.return_value)


# ---------------------------------------------------------------------------
# process_reviews_cli (3 tests)
# ---------------------------------------------------------------------------


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.process_reviews", return_value="Processed 2 reviews")
def test_process_reviews_cli_prints_result(
    mock_process: MagicMock,
    mock_db: MagicMock,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """process_reviews_cli() reads the file and prints the result."""
    reviews_file = tmp_path / "reviews.json"
    reviews_file.write_text('[{"pr": "org/repo#1", "state": "APPROVED"}]')
    process_reviews_cli(reviews_file=str(reviews_file))
    out = capsys.readouterr().out
    assert "Processed 2 reviews" in out


@patch(f"{_CLI}.get_db")
def test_process_reviews_cli_exits_1_on_missing_file(
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """process_reviews_cli() exits 1 when the reviews file does not exist."""
    with pytest.raises(SystemExit) as exc_info:
        process_reviews_cli(reviews_file="/nonexistent/path/reviews.json")
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "not found" in out


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.process_reviews", side_effect=ValueError("bad json"))
def test_process_reviews_cli_exits_1_on_invalid_json(
    mock_process: MagicMock,
    mock_db: MagicMock,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """process_reviews_cli() exits 1 and prints message on invalid JSON."""
    reviews_file = tmp_path / "bad.json"
    reviews_file.write_text("not valid json")
    with pytest.raises(SystemExit) as exc_info:
        process_reviews_cli(reviews_file=str(reviews_file))
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Invalid reviews JSON" in out


# ---------------------------------------------------------------------------
# index_epics (5 tests)
# ---------------------------------------------------------------------------


@patch(f"{_CLI}.get_db")
@patch(
    f"{_CLI}.list_epics",
    return_value=(
        [
            {"epic_id": "ACME-800", "status": "in_progress", "priority": 3, "title": "Indexing"},
            {"epic_id": "ACME-801", "status": "backlog", "priority": 5, "title": "Other"},
        ],
        False,
    ),
)
def test_index_epics_prints_compact_rows(
    mock_list: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """index_epics() prints one compact line per epic in default mode."""
    index_epics()
    out = capsys.readouterr().out
    assert "ACME-800" in out
    assert "[in_progress]" in out
    assert "p3" in out
    assert "ACME-801" in out


@patch(f"{_CLI}.get_db")
@patch(
    f"{_CLI}.list_epics",
    return_value=(
        [{"epic_id": "ACME-810", "status": "approved", "priority": 1, "title": "Verbose"}],
        False,
    ),
)
def test_index_epics_verbose_prints_json(
    mock_list: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """index_epics(verbose=True) prints full JSON for each epic.

    Note: with multiple rows, the source prints one ``json.dumps()`` block per
    row (concatenated JSON objects, not a JSON array). This is intentional
    JSONL-style CLI output. This test uses a single row so ``json.loads``
    succeeds on the full stdout.
    """
    index_epics(verbose=True)
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["epic_id"] == "ACME-810"


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.list_epics", return_value=([], False))
def test_index_epics_prints_no_epics_when_empty(
    mock_list: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """index_epics() prints 'No epics found.' when the list is empty."""
    index_epics()
    out = capsys.readouterr().out
    assert "No epics found." in out


@patch(f"{_CLI}.get_db")
@patch(
    f"{_CLI}.list_epics",
    return_value=(
        [{"epic_id": "ACME-820", "status": "backlog", "priority": 5, "title": "Page"}],
        True,
    ),
)
def test_index_epics_shows_pagination_hint(
    mock_list: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """index_epics() shows pagination hint when has_more is True."""
    index_epics()
    out = capsys.readouterr().out
    assert "--offset" in out
    assert "next page" in out


@patch(f"{_CLI}.get_db")
@patch(
    f"{_CLI}.list_epics",
    return_value=(
        [{"epic_id": "ACME-830", "status": "in_progress", "priority": 2, "title": "Filtered"}],
        False,
    ),
)
def test_index_epics_passes_status_filter(
    mock_list: MagicMock,
    mock_db: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """index_epics() forwards status_filter to list_epics."""
    index_epics(status_filter="in_progress")
    mock_list.assert_called_once_with(
        mock_db.return_value,
        "in_progress",
        limit=100,
        offset=0,
    )


# ---------------------------------------------------------------------------
# resume (1 test)
# ---------------------------------------------------------------------------


@patch(f"{_CLI}.get_db")
@patch(f"{_CLI}.get_resume_context", return_value={})
@patch(f"{_CLI}.get_client")
def test_resume_prints_json_context(
    mock_client: MagicMock,
    mock_resume: MagicMock,
    mock_db: MagicMock,
    make_collection: MagicMock,
    make_client_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """resume() prints valid JSON and calls get_or_create_collection with COLLECTION_NAME."""
    client = make_client_mock(make_collection)
    mock_client.return_value = client

    resume("ACME-900")
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert isinstance(parsed, dict)
    client.get_or_create_collection.assert_called_once_with(name=COLLECTION_NAME)
    mock_resume.assert_called_once_with(make_collection, mock_db.return_value, "ACME-900")
