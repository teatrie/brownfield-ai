from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from brownfield_ai.tools.ralph.client import (
    get_latest_session_exit,
    ledger_filter,
    ledger_query,
    ledger_resume,
    ledger_save,
    ledger_set_prs,
    ledger_status,
    ledger_touch,
    parse_branches,
    parse_json_output,
    parse_sub_plans,
    serialize_branches,
    serialize_sub_plans,
)

# ---------------------------------------------------------------------------
# parse_sub_plans
# ---------------------------------------------------------------------------


def test_parse_sub_plans_basic() -> None:
    snapshot: dict[str, Any] = {"metadata": {"sub_plans": "A:0,1|B:2,3|C:4,5,6,QA"}}
    result = parse_sub_plans(snapshot)
    assert len(result) == 3
    assert result[0] == {"label": "A", "waves": ["0", "1"]}
    assert result[1] == {"label": "B", "waves": ["2", "3"]}
    assert result[2] == {"label": "C", "waves": ["4", "5", "6", "QA"]}


def test_parse_sub_plans_opaque_wave_ids() -> None:
    snapshot: dict[str, Any] = {"metadata": {"sub_plans": "A:0,1,3a|B:3b,4"}}
    result = parse_sub_plans(snapshot)
    assert result[0]["waves"] == ["0", "1", "3a"]
    assert result[1]["waves"] == ["3b", "4"]


def test_parse_sub_plans_empty_metadata() -> None:
    assert parse_sub_plans({}) == []
    assert parse_sub_plans({"metadata": {}}) == []
    assert parse_sub_plans({"metadata": {"sub_plans": ""}}) == []


def test_parse_sub_plans_single_plan() -> None:
    snapshot: dict[str, Any] = {"metadata": {"sub_plans": "X:0"}}
    result = parse_sub_plans(snapshot)
    assert len(result) == 1
    assert result[0] == {"label": "X", "waves": ["0"]}


# ---------------------------------------------------------------------------
# serialize_sub_plans
# ---------------------------------------------------------------------------


def test_serialize_sub_plans_round_trip() -> None:
    original = "A:0,1|B:2,3|C:4,5,6,QA"
    snapshot: dict[str, Any] = {"metadata": {"sub_plans": original}}
    assert serialize_sub_plans(parse_sub_plans(snapshot)) == original


def test_serialize_sub_plans_with_wave_splitting() -> None:
    original = "A:P,0,1,2,3a|B:3b,4,QA"
    snapshot: dict[str, Any] = {"metadata": {"sub_plans": original}}
    assert serialize_sub_plans(parse_sub_plans(snapshot)) == original


def test_serialize_sub_plans_empty_list() -> None:
    assert serialize_sub_plans([]) == ""


# ---------------------------------------------------------------------------
# parse_branches
# ---------------------------------------------------------------------------


def test_parse_branches_multi_repo() -> None:
    s = "brownfield-ai:feat/ACME-1234|service-b:feat/ACME-1234-sub|analytics:feat/ACME-1234-lake"
    result = parse_branches(s)
    assert result == {
        "brownfield-ai": "feat/ACME-1234",
        "service-b": "feat/ACME-1234-sub",
        "analytics": "feat/ACME-1234-lake",
    }


def test_parse_branches_empty_input() -> None:
    assert parse_branches("") == {}


def test_parse_branches_whitespace_only() -> None:
    assert parse_branches("   ") == {}


def test_parse_branches_single_repo() -> None:
    result = parse_branches("brownfield-ai:main")
    assert result == {"brownfield-ai": "main"}


# ---------------------------------------------------------------------------
# serialize_branches
# ---------------------------------------------------------------------------


def test_serialize_branches_round_trip() -> None:
    original = "brownfield-ai:feat/ACME-1234|service-b:feat/ACME-1234-sub"
    assert serialize_branches(parse_branches(original)) == original


def test_serialize_branches_empty_dict() -> None:
    assert serialize_branches({}) == ""


# ---------------------------------------------------------------------------
# parse_json_output
# ---------------------------------------------------------------------------


def test_parse_json_output_with_preamble() -> None:
    output = 'Some preamble\nContainer starting...\n{"key": "value"}\n'
    assert parse_json_output(output) == {"key": "value"}


def test_parse_json_output_array() -> None:
    output = 'preamble\n[{"a": 1}, {"a": 2}]'
    result = parse_json_output(output)
    assert len(result) == 2
    assert result[0] == {"a": 1}


def test_parse_json_output_no_json_raises() -> None:
    with pytest.raises(ValueError, match="No JSON found"):
        parse_json_output("no json here\njust text")


def test_parse_json_output_json_only() -> None:
    output = '{"status": "ok"}'
    assert parse_json_output(output) == {"status": "ok"}


def test_parse_json_output_multiline_json() -> None:
    output = 'preamble\n{\n  "a": 1,\n  "b": 2\n}'
    result = parse_json_output(output)
    assert result == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# ledger_resume (subprocess mock)
# ---------------------------------------------------------------------------


def _make_completed_process(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["task", "ledger:test", "--"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_ledger_resume_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = '{"epic_id": "ACME-100", "plan_snapshot": {}}'
    mock_run = MagicMock(return_value=_make_completed_process(stdout=payload))
    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    result = ledger_resume("ACME-100")
    assert result == {"epic_id": "ACME-100", "plan_snapshot": {}}
    mock_run.assert_called_once_with("resume", ["ACME-100"])


def test_ledger_resume_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_run(task_name: str, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise RuntimeError("task ledger:resume failed (exit 1): some error")

    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    with pytest.raises(RuntimeError, match="task ledger:resume failed"):
        ledger_resume("ACME-100")


# ---------------------------------------------------------------------------
# ledger_touch
# ---------------------------------------------------------------------------


def test_ledger_touch_calls_correct_task(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_run = MagicMock(return_value=_make_completed_process())
    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    ledger_touch("ACME-200")
    mock_run.assert_called_once_with("touch", ["ACME-200"])


# ---------------------------------------------------------------------------
# ledger_status
# ---------------------------------------------------------------------------


def test_ledger_status_passes_new_status_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_run = MagicMock(return_value=_make_completed_process())
    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    ledger_status("ACME-300", "blocked")
    mock_run.assert_called_once_with(
        "status",
        ["ACME-300"],
        flag_args={"new-status": "blocked"},
    )


# ---------------------------------------------------------------------------
# ledger_save
# ---------------------------------------------------------------------------


def test_ledger_save_passes_correct_args(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_run = MagicMock(return_value=_make_completed_process())
    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    ledger_save("ACME-400", "session_exit", "some document body", metadata='{"key": "val"}')
    assert mock_run.call_count == 1
    call_args = mock_run.call_args
    assert call_args[0][0] == "save"
    # Post-migration: no positional content slot remains.
    assert call_args[0][1] == []
    flag_args = (
        call_args[1]["flag_args"]
        if "flag_args" in call_args[1]
        else call_args[0][2]
        if len(call_args[0]) > 2
        else call_args[1].get("flag_args")
    )
    # Document body now travels via the --content flag.
    assert flag_args["content"] == "some document body"
    assert "some document body" not in call_args[0][1]
    assert '"ACME-400"' in flag_args["fields"]
    assert '"session_exit"' in flag_args["fields"]
    assert flag_args["metadata"] == '{"key": "val"}'


def test_ledger_save_empty_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_run = MagicMock(return_value=_make_completed_process())
    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    ledger_save("ACME-400", "session_exit", "body")
    call_args = mock_run.call_args
    flag_args = call_args[1].get("flag_args") or call_args[0][2]
    assert flag_args["content"] == "body"
    assert flag_args["metadata"] == ""


def test_ledger_save_rejects_empty_document(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_run = MagicMock(return_value=_make_completed_process())
    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    with pytest.raises(ValueError, match="document must be a non-empty string"):
        ledger_save("ACME-400", "session_exit", "")
    mock_run.assert_not_called()


def test_ledger_save_rejects_whitespace_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """A whitespace-only document is rejected before dispatch.

    The current guard ``if not document:`` treats ``"   "`` as truthy and
    forwards it to ``_run_task``, which would persist a blank artifact (and
    the downstream CLI's inline strip-check would then reject it, wasting a
    container round-trip). The fixed guard must strip before the emptiness
    check so ``_run_task`` is never called.
    """
    mock_run = MagicMock(return_value=_make_completed_process())
    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    with pytest.raises(ValueError, match="document must be a non-empty string"):
        ledger_save("ACME-400", "session_exit", "   ")
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# ledger_query
# ---------------------------------------------------------------------------


def test_ledger_query_parses_results(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = '[{"id": "1", "metadata": {}}, {"id": "2", "metadata": {}}]'
    mock_run = MagicMock(return_value=_make_completed_process(stdout=payload))
    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    result = ledger_query("ACME-500", artifact_type="wave_summary")
    assert len(result) == 2


def test_ledger_query_returns_empty_on_parse_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_run = MagicMock(return_value=_make_completed_process(stdout="no json here"))
    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    result = ledger_query("ACME-500")
    assert result == []


# ---------------------------------------------------------------------------
# get_latest_session_exit
# ---------------------------------------------------------------------------


def test_get_latest_session_exit_returns_last(monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = [
        {"id": "latest", "metadata": {"verdict": "pass"}},
        {"id": "old", "metadata": {"verdict": "fail"}},
    ]

    def mock_filter(
        epic_id: str,
        *,
        artifact_type: str = "",
        sub_plan: str = "",
        attempt: str = "",
        verdict: str = "",
        artifact_status: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return artifacts

    monkeypatch.setattr("brownfield_ai.tools.ralph.client.ledger_filter", mock_filter)

    result = get_latest_session_exit("ACME-600", "A", 1)
    assert result is not None
    assert result["id"] == "latest"


def test_get_latest_session_exit_returns_none_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_filter(
        epic_id: str,
        *,
        artifact_type: str = "",
        sub_plan: str = "",
        attempt: str = "",
        verdict: str = "",
        artifact_status: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr("brownfield_ai.tools.ralph.client.ledger_filter", mock_filter)

    result = get_latest_session_exit("ACME-600", "A", 1)
    assert result is None


# ---------------------------------------------------------------------------
# ledger_set_prs
# ---------------------------------------------------------------------------


def test_ledger_set_prs_passes_csv_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    """ledger_set_prs passes comma-separated PR refs to the task."""
    mock_run = MagicMock(return_value=_make_completed_process())
    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    ledger_set_prs("ACME-100", "acme/brownfield-ai#10,acme/service-b#20")
    mock_run.assert_called_once()
    call_args = mock_run.call_args
    # Verify epic_id is in positional args
    assert "ACME-100" in call_args[0][1]
    # Verify pr-refs flag contains the CSV
    flag_args = call_args[1].get("flag_args") or call_args[0][2]
    assert "acme/brownfield-ai#10,acme/service-b#20" in flag_args.get("pr-refs", "")


def test_ledger_set_prs_single_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """ledger_set_prs works with a single PR ref."""
    mock_run = MagicMock(return_value=_make_completed_process())
    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    ledger_set_prs("ACME-200", "acme/brownfield-ai#42")
    mock_run.assert_called_once()


def test_ledger_set_prs_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """ledger_set_prs raises RuntimeError on task failure."""

    def mock_run(task_name: str, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise RuntimeError("task ledger:set-prs failed (exit 1): error")

    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    with pytest.raises(RuntimeError, match="task ledger:set-prs failed"):
        ledger_set_prs("ACME-300", "acme/brownfield-ai#1")


# ---------------------------------------------------------------------------
# ledger_filter
# ---------------------------------------------------------------------------


def test_ledger_filter_constructs_correct_positional_and_flag_args(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = '[{"id": "1", "metadata": {}}]'
    mock_run = MagicMock(return_value=_make_completed_process(stdout=payload))
    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    result = ledger_filter("ACME-100", artifact_type="session_exit", sub_plan="A", attempt="2")
    mock_run.assert_called_once_with(
        "filter",
        ["ACME-100"],
        flag_args={"artifact-type": "session_exit", "sub-plan": "A", "attempt": "2"},
    )
    assert result == [{"id": "1", "metadata": {}}]


def test_ledger_filter_omits_empty_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_run = MagicMock(return_value=_make_completed_process(stdout="[]"))
    monkeypatch.setattr("brownfield_ai.tools.ralph.client._run_task", mock_run)

    ledger_filter("ACME-100", artifact_type="step_result")
    mock_run.assert_called_once_with(
        "filter",
        ["ACME-100"],
        flag_args={"artifact-type": "step_result"},
    )


def test_get_latest_session_exit_uses_ledger_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = [
        {"id": "latest", "metadata": {"verdict": "pass"}},
        {"id": "older", "metadata": {"verdict": "fail"}},
    ]
    mock_filter = MagicMock(return_value=artifacts)
    monkeypatch.setattr("brownfield_ai.tools.ralph.client.ledger_filter", mock_filter)

    result = get_latest_session_exit("ACME-100", "A", 1)
    assert result is not None
    assert result["id"] == "latest"
    mock_filter.assert_called_once_with(
        "ACME-100",
        artifact_type="session_exit",
        sub_plan="A",
        attempt="1",
    )
