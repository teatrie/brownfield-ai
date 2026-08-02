"""Unit tests for brownfield_ai.ledger.artifacts.queries."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from brownfield_ai.ledger.artifacts.queries import (
    build_and_filter,
    filter_artifacts,
    get_artifact,
    get_timeline,
    query_artifacts,
    search_epics_core,
)

# ---------------------------------------------------------------------------
# Shared test metadata base
# ---------------------------------------------------------------------------

_ARTIFACT_META_BASE: dict[str, str] = {
    "epic_id": "ACME-100",
    "artifact_type": "step_result",
    "timestamp": "2026-01-01T00:00:00",
    "verdict": "pass",
    "sub_plan": "A",
    "attempt": "1",
    "artifact_status": "active",
}


# ---------------------------------------------------------------------------
# filter_artifacts() tests
# ---------------------------------------------------------------------------


def test_filter_artifacts_by_epic_and_type() -> None:
    """Verify $and filter is used when both epic_id and artifact_type are set."""
    meta_match = {**_ARTIFACT_META_BASE, "artifact_type": "step_result"}
    meta_other = {**_ARTIFACT_META_BASE, "artifact_type": "plan_snapshot"}
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["id1", "id2"],
        "documents": ["doc1", "doc2"],
        "metadatas": [meta_match, meta_other],
    }
    results = filter_artifacts(mock_collection, "ACME-100", artifact_type="step_result")
    assert len(results) == 1
    assert results[0]["metadata"]["artifact_type"] == "step_result"
    where = mock_collection.get.call_args.kwargs["where"]
    assert "$and" in where


def test_filter_artifacts_with_sub_plan_and_attempt() -> None:
    """Verify filtering by sub_plan and attempt returns the correct subset."""
    meta_a1 = {**_ARTIFACT_META_BASE, "sub_plan": "A", "attempt": "1", "timestamp": "2026-01-01T00:00:00"}
    meta_a2 = {**_ARTIFACT_META_BASE, "sub_plan": "A", "attempt": "2", "timestamp": "2026-01-02T00:00:00"}
    meta_b1 = {**_ARTIFACT_META_BASE, "sub_plan": "B", "attempt": "1", "timestamp": "2026-01-03T00:00:00"}
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["id1", "id2", "id3"],
        "documents": ["doc1", "doc2", "doc3"],
        "metadatas": [meta_a1, meta_a2, meta_b1],
    }
    results = filter_artifacts(mock_collection, "ACME-100", sub_plan="A", attempt="2")
    assert len(results) == 1
    assert results[0]["metadata"]["sub_plan"] == "A"
    assert results[0]["metadata"]["attempt"] == "2"


def test_filter_artifacts_by_epic_id_only() -> None:
    """Verify simple epic_id filter uses no $and operator."""
    meta1 = {**_ARTIFACT_META_BASE}
    meta2 = {**_ARTIFACT_META_BASE, "timestamp": "2026-01-02T00:00:00"}
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["id1", "id2"],
        "documents": ["doc1", "doc2"],
        "metadatas": [meta1, meta2],
    }
    results = filter_artifacts(mock_collection, "ACME-100")
    assert len(results) == 2
    where = mock_collection.get.call_args.kwargs["where"]
    assert "$and" not in where
    assert where == {"epic_id": "ACME-100"}


def test_filter_artifacts_with_verdict_filter() -> None:
    """Verify verdict filter returns only matching artifacts."""
    meta_pass = {**_ARTIFACT_META_BASE, "verdict": "pass"}
    meta_fail = {**_ARTIFACT_META_BASE, "verdict": "fail", "timestamp": "2026-01-02T00:00:00"}
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["id1", "id2"],
        "documents": ["doc1", "doc2"],
        "metadatas": [meta_pass, meta_fail],
    }
    results = filter_artifacts(mock_collection, "ACME-100", verdict="pass")
    assert len(results) == 1
    assert results[0]["metadata"]["verdict"] == "pass"


def test_filter_artifacts_fallback_on_and_unsupported() -> None:
    """Verify fallback to epic_id filter when $and is unsupported."""
    meta_match = {**_ARTIFACT_META_BASE, "artifact_type": "step_result"}
    meta_other = {**_ARTIFACT_META_BASE, "artifact_type": "plan_snapshot"}

    def get_side_effect(**kwargs: Any) -> dict[str, list[Any]]:
        where = kwargs.get("where", {})
        if "$and" in where:
            raise ValueError("$and operator not supported")
        return {
            "ids": ["id1", "id2"],
            "documents": ["doc1", "doc2"],
            "metadatas": [meta_match, meta_other],
        }

    mock_collection = MagicMock()
    mock_collection.get.side_effect = get_side_effect
    results = filter_artifacts(mock_collection, "ACME-100", artifact_type="step_result")
    assert mock_collection.get.call_count == 2
    assert len(results) == 1
    assert results[0]["metadata"]["artifact_type"] == "step_result"


def test_filter_artifacts_returns_empty_for_no_matches() -> None:
    """Verify empty list is returned when no artifacts match."""
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
    results = filter_artifacts(mock_collection, "ACME-100")
    assert results == []


def test_filter_artifacts_sorts_by_timestamp_descending() -> None:
    """Verify results are sorted newest-first by timestamp."""
    meta_old = {**_ARTIFACT_META_BASE, "timestamp": "2026-01-01T00:00:00"}
    meta_new = {**_ARTIFACT_META_BASE, "timestamp": "2026-01-03T00:00:00"}
    meta_mid = {**_ARTIFACT_META_BASE, "timestamp": "2026-01-02T00:00:00"}
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["id1", "id2", "id3"],
        "documents": ["doc1", "doc2", "doc3"],
        "metadatas": [meta_old, meta_new, meta_mid],
    }
    results = filter_artifacts(mock_collection, "ACME-100")
    assert len(results) == 3
    assert results[0]["metadata"]["timestamp"] == "2026-01-03T00:00:00"
    assert results[1]["metadata"]["timestamp"] == "2026-01-02T00:00:00"
    assert results[2]["metadata"]["timestamp"] == "2026-01-01T00:00:00"


def test_filter_artifacts_respects_limit() -> None:
    """Verify results are capped at the specified limit."""
    metas = [{**_ARTIFACT_META_BASE, "timestamp": f"2026-01-0{i}T00:00:00"} for i in range(1, 6)]
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": [f"id{i}" for i in range(1, 6)],
        "documents": [f"doc{i}" for i in range(1, 6)],
        "metadatas": metas,
    }
    results = filter_artifacts(mock_collection, "ACME-100", limit=2)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# build_and_filter() tests
# ---------------------------------------------------------------------------


def test_build_and_filter_uses_and_operator() -> None:
    """Verify $and operator is used in the ChromaDB query."""
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
    build_and_filter(mock_collection, "ACME-100", "step_result")
    mock_collection.get.assert_called_once_with(
        where={
            "$and": [
                {"epic_id": "ACME-100"},
                {"artifact_type": "step_result"},
            ]
        }
    )


def test_build_and_filter_fallback_path() -> None:
    """Verify fallback to epic_id filter with client-side post-filtering."""
    meta_match = {**_ARTIFACT_META_BASE, "artifact_type": "step_result"}
    meta_other = {**_ARTIFACT_META_BASE, "artifact_type": "plan_snapshot"}

    call_count = 0

    def get_side_effect(**kwargs: Any) -> dict[str, list[Any]]:
        nonlocal call_count
        call_count += 1
        where = kwargs.get("where", {})
        if "$and" in where:
            raise ValueError("$and operator not supported")
        return {
            "ids": ["id1", "id2"],
            "documents": ["doc1", "doc2"],
            "metadatas": [meta_match, meta_other],
        }

    mock_collection = MagicMock()
    mock_collection.get.side_effect = get_side_effect
    result = build_and_filter(mock_collection, "ACME-100", "step_result")
    assert call_count == 2
    fallback_call = mock_collection.get.call_args_list[1]
    fallback_where = fallback_call.kwargs.get("where") or fallback_call.args[0]
    assert fallback_where == {"epic_id": "ACME-100"}
    assert result["ids"] == ["id1"]
    assert result["metadatas"][0]["artifact_type"] == "step_result"


# ---------------------------------------------------------------------------
# search_epics_core() tests
# ---------------------------------------------------------------------------


def test_search_epics_core_returns_normalized_results() -> None:
    """Verify results are normalized into flat dicts with distance."""
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["epic-1", "epic-2"]],
        "documents": [["DX-001 DX Tooling in_progress", "DX-002 Bug Fix backlog"]],
        "metadatas": [[{"status": "in_progress", "title": "DX Tooling"}, {"status": "backlog", "title": "Bug Fix"}]],
        "distances": [[0.1, 0.5]],
    }
    results = search_epics_core(mock_collection, "tooling", n=5)
    assert len(results) == 2
    assert results[0]["id"] == "epic-1"
    assert results[0]["document"] == "DX-001 DX Tooling in_progress"
    assert results[0]["metadata"]["status"] == "in_progress"
    assert results[0]["distance"] == 0.1
    assert results[1]["id"] == "epic-2"


def test_search_epics_core_empty_results() -> None:
    """Verify empty list is returned for no matches."""
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }
    results = search_epics_core(mock_collection, "nonexistent", n=5)
    assert results == []


def test_search_epics_core_missing_distances_returns_na() -> None:
    """Verify 'N/A' is returned when distances are missing from response."""
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["epic-1"]],
        "documents": [["DX-001 DX Tooling in_progress"]],
        "metadatas": [[{"status": "in_progress", "title": "DX Tooling"}]],
    }
    results = search_epics_core(mock_collection, "tooling", n=5)
    assert len(results) == 1
    assert results[0]["distance"] == "N/A"


# ---------------------------------------------------------------------------
# query_artifacts() tests
# ---------------------------------------------------------------------------


def test_query_artifacts_with_both_epic_and_type_filters() -> None:
    meta = {**_ARTIFACT_META_BASE}
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["id1"]],
        "documents": [["doc1"]],
        "metadatas": [[meta]],
        "distances": [[0.1]],
    }
    results = query_artifacts(
        mock_collection,
        "search text",
        {"epic_id": "ACME-100", "artifact_type": "step_result"},
    )
    call_kwargs = mock_collection.query.call_args.kwargs
    assert "where" in call_kwargs
    and_filters = call_kwargs["where"]["$and"]
    assert {"epic_id": "ACME-100"} in and_filters
    assert {"artifact_type": "step_result"} in and_filters
    assert len(results) == 1
    assert set(results[0].keys()) == {"id", "document", "metadata", "distance"}


def test_query_artifacts_fallback_on_and_unsupported() -> None:
    meta_step = {**_ARTIFACT_META_BASE, "artifact_type": "step_result"}
    meta_plan = {**_ARTIFACT_META_BASE, "artifact_type": "plan_snapshot"}

    def query_side_effect(**kwargs: Any) -> dict[str, list[Any]]:
        where = kwargs.get("where", {})
        if "$and" in where:
            raise ValueError("$and operator not supported")
        return {
            "ids": [["id1", "id2"]],
            "documents": [["doc1", "doc2"]],
            "metadatas": [[meta_step, meta_plan]],
            "distances": [[0.1, 0.2]],
        }

    mock_collection = MagicMock()
    mock_collection.query.side_effect = query_side_effect
    results = query_artifacts(
        mock_collection,
        "search",
        {"epic_id": "ACME-100", "artifact_type": "step_result"},
    )
    assert mock_collection.query.call_count == 2
    assert len(results) == 1
    assert results[0]["metadata"]["artifact_type"] == "step_result"


def test_query_artifacts_with_epic_only_filter() -> None:
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }
    query_artifacts(mock_collection, "search", {"epic_id": "ACME-100"})
    call_kwargs = mock_collection.query.call_args.kwargs
    assert call_kwargs["where"] == {"epic_id": "ACME-100"}


def test_query_artifacts_with_artifact_type_only_filter() -> None:
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }
    query_artifacts(mock_collection, "search", {"artifact_type": "step_result"})
    call_kwargs = mock_collection.query.call_args.kwargs
    assert call_kwargs["where"] == {"artifact_type": "step_result"}


def test_query_artifacts_no_filters() -> None:
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }
    query_artifacts(mock_collection, "search", {})
    call_kwargs = mock_collection.query.call_args.kwargs
    assert "where" not in call_kwargs
    assert "query_texts" in call_kwargs
    assert "n_results" in call_kwargs


def test_query_artifacts_empty_results() -> None:
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }
    results = query_artifacts(mock_collection, "search", {})
    assert results == []


# ---------------------------------------------------------------------------
# get_timeline() tests
# ---------------------------------------------------------------------------


def test_get_timeline_sorts_by_id() -> None:
    meta = {**_ARTIFACT_META_BASE}
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["c-id", "a-id", "b-id"],
        "documents": ["doc-c", "doc-a", "doc-b"],
        "metadatas": [meta, meta, meta],
    }
    results = get_timeline(
        mock_collection,
        {"epic_id": "ACME-100", "artifact_type": "", "limit": 50},
    )
    assert [r["id"] for r in results] == ["a-id", "b-id", "c-id"]


def test_get_timeline_with_artifact_type_filter() -> None:
    meta = {**_ARTIFACT_META_BASE}
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["id1"],
        "documents": ["doc1"],
        "metadatas": [meta],
    }
    results = get_timeline(
        mock_collection,
        {"epic_id": "ACME-100", "artifact_type": "step_result", "limit": 50},
    )
    assert len(results) == 1
    # Verify build_and_filter path was taken (uses $and filter)
    get_kwargs = mock_collection.get.call_args.kwargs
    assert "$and" in get_kwargs.get("where", {})


def test_get_timeline_with_epic_id_only() -> None:
    meta = {**_ARTIFACT_META_BASE}
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["id1"],
        "documents": ["doc1"],
        "metadatas": [meta],
    }
    get_timeline(
        mock_collection,
        {"epic_id": "ACME-100", "artifact_type": "", "limit": 50},
    )
    mock_collection.get.assert_called_once_with(where={"epic_id": "ACME-100"})


def test_get_timeline_no_filters() -> None:
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": [],
        "documents": [],
        "metadatas": [],
    }
    get_timeline(mock_collection, {"epic_id": "", "artifact_type": "", "limit": 50})
    mock_collection.get.assert_called_once_with()


def test_get_timeline_respects_limit() -> None:
    meta = {**_ARTIFACT_META_BASE}
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["id1", "id2", "id3", "id4", "id5"],
        "documents": ["doc1", "doc2", "doc3", "doc4", "doc5"],
        "metadatas": [meta, meta, meta, meta, meta],
    }
    results = get_timeline(
        mock_collection,
        {"epic_id": "ACME-100", "artifact_type": "", "limit": 2},
    )
    assert len(results) == 2


def test_get_timeline_empty_results() -> None:
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": [],
        "documents": [],
        "metadatas": [],
    }
    results = get_timeline(
        mock_collection,
        {"epic_id": "ACME-100", "artifact_type": "", "limit": 50},
    )
    assert results == []


def test_get_timeline_limit_zero_returns_all() -> None:
    meta = {**_ARTIFACT_META_BASE}
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["id1", "id2", "id3"],
        "documents": ["doc1", "doc2", "doc3"],
        "metadatas": [meta, meta, meta],
    }
    results = get_timeline(
        mock_collection,
        {"epic_id": "ACME-100", "artifact_type": "", "limit": 0},
    )
    assert len(results) == 3


# ---------------------------------------------------------------------------
# get_artifact() tests
# ---------------------------------------------------------------------------


def test_get_artifact_returns_document() -> None:
    meta = {**_ARTIFACT_META_BASE}
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["doc-1"],
        "documents": ["content"],
        "metadatas": [meta],
    }
    result = get_artifact(mock_collection, "doc-1")
    mock_collection.get.assert_called_once_with(ids=["doc-1"])
    assert result is not None
    assert set(result.keys()) == {"id", "document", "metadata"}
    assert result["id"] == "doc-1"
    assert result["document"] == "content"
    assert result["metadata"] == meta


def test_get_artifact_returns_none_when_missing() -> None:
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": [],
        "documents": [],
        "metadatas": [],
    }
    result = get_artifact(mock_collection, "missing-id")
    assert result is None
