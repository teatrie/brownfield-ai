"""Unit tests for brownfield_ai.ledger.artifacts.mutations."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from brownfield_ai.ledger.artifacts.mutations import save_artifact, supersede_previous


def test_save_artifact_persists_sub_plans_to_metadata() -> None:
    """Verify sub_plans field is preserved through save_artifact to ChromaDB."""
    mock_collection = MagicMock()
    mock_db = MagicMock()
    params = {
        "epic_id": "ACME-0001",
        "artifact_type": "gate_verdict",
        "wave": "",
        "domain": "",
        "step": "",
        "agent_role": "",
        "agent_model": "claude-opus-4",
        "verdict": "pass",
        "version": 1,
        "parent_id": "",
        "epic_status": "in_progress",
        "title": "",
        "priority": 5,
        "depends_on": "[]",
        "sub_plan": "",
        "sub_plans": "A:0,1|B:2",
        "attempt": "",
        "branches": "",
    }
    save_artifact((mock_collection, mock_db), "test content body", params)
    assert mock_collection.upsert.call_count == 1
    metadatas = mock_collection.upsert.call_args.kwargs["metadatas"]
    assert metadatas[0]["sub_plans"] == "A:0,1|B:2"


# supersede_previous() tests


def test_supersede_previous_marks_active_as_superseded() -> None:
    mock_collection = MagicMock()
    update_calls: list[dict[str, str]] = []

    def capture_update(**kwargs: Any) -> None:
        update_calls.append(kwargs["metadatas"][0])

    mock_collection.update.side_effect = capture_update
    with patch(
        "brownfield_ai.ledger.artifacts.mutations.build_and_filter",
        return_value={
            "ids": ["id1", "id2"],
            "metadatas": [
                {"artifact_status": "active", "epic_id": "ACME-100"},
                {"artifact_status": "active", "epic_id": "ACME-100"},
            ],
        },
    ):
        supersede_previous(mock_collection, "ACME-100", "plan_snapshot")
    assert len(update_calls) == 2
    assert update_calls[0]["artifact_status"] == "superseded"
    assert update_calls[1]["artifact_status"] == "superseded"


def test_supersede_previous_skips_already_superseded() -> None:
    mock_collection = MagicMock()
    with patch(
        "brownfield_ai.ledger.artifacts.mutations.build_and_filter",
        return_value={
            "ids": ["id1"],
            "metadatas": [
                {"artifact_status": "superseded", "epic_id": "ACME-100"},
            ],
        },
    ):
        supersede_previous(mock_collection, "ACME-100", "plan_snapshot")
    mock_collection.update.assert_not_called()


def test_supersede_previous_does_not_mutate_source_metadata() -> None:
    mock_collection = MagicMock()
    source_meta = {"artifact_status": "active", "epic_id": "ACME-100"}
    with patch(
        "brownfield_ai.ledger.artifacts.mutations.build_and_filter",
        return_value={"ids": ["id1"], "metadatas": [source_meta]},
    ):
        supersede_previous(mock_collection, "ACME-100", "plan_snapshot")
    assert source_meta["artifact_status"] == "active"


def test_supersede_previous_empty_collection() -> None:
    mock_collection = MagicMock()
    with patch(
        "brownfield_ai.ledger.artifacts.mutations.build_and_filter",
        return_value={"ids": [], "metadatas": []},
    ):
        supersede_previous(mock_collection, "ACME-100", "plan_snapshot")
    mock_collection.update.assert_not_called()


# save_artifact() edge case tests

_BASE_PARAMS: dict[str, object] = {
    "epic_id": "ACME-100",
    "artifact_type": "",
    "wave": "",
    "domain": "",
    "step": "",
    "agent_role": "",
    "agent_model": "claude-sonnet-4",
    "verdict": "",
    "version": 1,
    "parent_id": "",
    "epic_status": "in_progress",
    "title": "",
    "priority": 5,
    "depends_on": "[]",
    "sub_plan": "",
    "sub_plans": "",
    "attempt": "",
    "branches": "",
}


@patch("brownfield_ai.ledger.artifacts.mutations.upsert_epic_index")
@patch("brownfield_ai.ledger.artifacts.mutations.supersede_previous")
def test_save_artifact_supersedes_plan_snapshot(
    mock_supersede: MagicMock,
    mock_upsert: MagicMock,
) -> None:
    mock_collection = MagicMock()
    mock_db = MagicMock()
    params = {**_BASE_PARAMS, "artifact_type": "plan_snapshot"}
    save_artifact((mock_collection, mock_db), "content", params)
    mock_supersede.assert_called_once()
    supersede_args = mock_supersede.call_args[0]
    assert supersede_args[1] == "ACME-100"  # epic_id
    assert supersede_args[2] == "plan_snapshot"  # artifact_type
    mock_upsert.assert_called_once()


@patch("brownfield_ai.ledger.artifacts.mutations.upsert_epic_index")
@patch("brownfield_ai.ledger.artifacts.mutations.supersede_previous")
def test_save_artifact_supersedes_requirement_map(
    mock_supersede: MagicMock,
    mock_upsert: MagicMock,
) -> None:
    mock_collection = MagicMock()
    mock_db = MagicMock()
    params = {**_BASE_PARAMS, "artifact_type": "requirement_map"}
    save_artifact((mock_collection, mock_db), "content", params)
    mock_supersede.assert_called_once()
    supersede_args = mock_supersede.call_args[0]
    assert supersede_args[1] == "ACME-100"  # epic_id
    assert supersede_args[2] == "requirement_map"  # artifact_type
    mock_upsert.assert_not_called()


@patch("brownfield_ai.ledger.artifacts.mutations.upsert_epic_index")
@patch("brownfield_ai.ledger.artifacts.mutations.supersede_previous")
def test_save_artifact_does_not_supersede_step_result(
    mock_supersede: MagicMock,
    mock_upsert: MagicMock,
) -> None:
    mock_collection = MagicMock()
    mock_db = MagicMock()
    params = {**_BASE_PARAMS, "artifact_type": "step_result"}
    save_artifact((mock_collection, mock_db), "content", params)
    mock_supersede.assert_not_called()
    mock_upsert.assert_not_called()
