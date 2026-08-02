"""Unit tests for brownfield_ai.ledger.artifacts.cli."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import defopt
import pytest

import brownfield_ai.ledger.artifacts.cli as cli_mod
from brownfield_ai.ledger.artifacts import constants
from brownfield_ai.ledger.artifacts.cli import filter_cli, get, query, save, search_epics_cli, timeline
from brownfield_ai.ledger.artifacts.constants import EPICS_COLLECTION_NAME

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
# filter_cli() test
# ---------------------------------------------------------------------------


@patch("brownfield_ai.ledger.artifacts.cli.get_client")
def test_filter_cli_outputs_json_array(
    mock_get_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify filter_cli outputs a JSON array and handles empty results."""
    meta = {**_ARTIFACT_META_BASE}
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["id1"],
        "documents": ["doc1"],
        "metadatas": [meta],
    }
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_get_client.return_value = mock_client

    filter_cli("ACME-100", artifact_type="step_result")
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert isinstance(parsed, list)

    mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
    filter_cli("ACME-100")
    captured_empty = capsys.readouterr()
    assert captured_empty.out == "[]\n"


# ---------------------------------------------------------------------------
# search_epics_cli() tests
# ---------------------------------------------------------------------------


@patch("brownfield_ai.ledger.artifacts.cli.get_client")
def test_search_epics_cli_formats_output(
    mock_get_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify search_epics_cli prints formatted results to stdout."""
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["epic-1"]],
        "documents": [["DX-001 DX Tooling in_progress"]],
        "metadatas": [[{"status": "in_progress", "title": "DX Tooling"}]],
        "distances": [[0.1]],
    }
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_get_client.return_value = mock_client

    search_epics_cli("tooling", n=5)
    mock_client.get_or_create_collection.assert_called_once_with(name=EPICS_COLLECTION_NAME)
    captured = capsys.readouterr()
    assert "ID: epic-1" in captured.out
    assert "Distance: 0.1" in captured.out
    assert "DX-001 DX Tooling" in captured.out


@patch("brownfield_ai.ledger.artifacts.cli.get_client")
def test_search_epics_cli_no_results(
    mock_get_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify 'No results found.' is printed when search returns empty."""
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_get_client.return_value = mock_client

    search_epics_cli("nonexistent")
    captured = capsys.readouterr()
    assert captured.out == "No results found.\n"


# ---------------------------------------------------------------------------
# save() tests
# ---------------------------------------------------------------------------


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_prints_doc_id(
    mock_get_db: MagicMock,
    mock_get_client: MagicMock,
    mock_save_artifact: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_collection = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_get_client.return_value = mock_client
    mock_save_artifact.return_value = "ACME-100|2026-01-01|plan_snapshot|opus||"

    save(
        content="test body",
        fields='{"epic_id":"ACME-100","artifact_type":"plan_snapshot","agent_model":"opus"}',
    )

    captured = capsys.readouterr()
    assert "ACME-100|2026-01-01|plan_snapshot|opus||" in captured.out
    mock_save_artifact.assert_called_once()
    call_args = mock_save_artifact.call_args
    assert call_args[0][0] == (mock_collection, mock_db)
    assert call_args[0][1] == "test body"
    params = call_args[0][2]
    assert params["epic_id"] == "ACME-100"
    assert params["artifact_type"] == "plan_snapshot"
    assert params["agent_model"] == "opus"
    mock_db.close.assert_called_once()


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_exits_on_invalid_fields_json(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        save(content="x", fields="not-json")
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Invalid JSON in --fields" in captured.out


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_exits_on_missing_required_key(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        save(content="x", fields='{"artifact_type":"plan_snapshot"}')
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Missing required key" in captured.out


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_exits_on_invalid_metadata_json(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        save(
            content="x",
            fields='{"epic_id":"ACME-100","artifact_type":"plan_snapshot","agent_model":"opus"}',
            metadata="bad-json",
        )
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Invalid JSON in --metadata" in captured.out


# ---------------------------------------------------------------------------
# save() --content / --content-file migration tests (TODO-0157)
# ---------------------------------------------------------------------------
#
# tmp_root anchoring contract (honored by the Step 2 implementer):
#
#   cli.py MUST expose a module-level ``PROJECT_ROOT`` (a ``pathlib.Path``)
#   and compute ``tmp_root = (PROJECT_ROOT / "tmp").resolve()`` INSIDE
#   ``save()`` at call time. Computing it at call time (not import time) is
#   what makes the monkeypatch below take effect.
#
#   Tests make the containment check hermetic by pointing PROJECT_ROOT at a
#   pytest ``tmp_path`` and creating a ``tmp/`` subdir under it:
#
#       monkeypatch.setattr(cli_mod, "PROJECT_ROOT", tmp_path)
#       (tmp_path / "tmp").mkdir()
#
#   Fixture files placed under ``tmp_path / "tmp"`` resolve INSIDE the
#   containment root; files placed elsewhere (e.g. directly under tmp_path,
#   or via ``..`` traversal / symlink escape) resolve OUTSIDE and must be
#   rejected. ``--content-file`` values are interpreted relative to
#   PROJECT_ROOT (matching the production "tmp/foo.md" call shape).
#
# These tests are RED until Step 2 implements the keyword-only
# --content / --content-file signature + validation. They currently fail
# because production ``save()`` is still positional with no content_file
# parameter and no validation.
# ---------------------------------------------------------------------------

_VALID_FIELDS: str = '{"epic_id":"ACME-100","artifact_type":"plan_snapshot","agent_model":"opus"}'


def test_project_root_layout_sentinel() -> None:
    """PROJECT_ROOT must resolve to the package's repo root (layout-drift guard).

    Asserts the structural invariant ``parents[4]`` encodes rather than the
    bare directory name: the repo root is bind-mounted at ``/app`` inside the
    container and ``brownfield-ai`` on the host, so the name is environment-specific,
    but the package subtree ``src/brownfield_ai/ledger/artifacts/constants.py`` must
    always sit four parents below PROJECT_ROOT. A package-layout change that
    alters the ``parents[4]`` count breaks this guard.
    """
    constants_path = Path(constants.__file__).resolve()
    assert constants_path.parents[4] == constants.PROJECT_ROOT
    assert (constants.PROJECT_ROOT / "src" / "brownfield_ai" / "ledger" / "artifacts" / "constants.py").resolve() == constants_path


def _make_tmp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Anchor cli_mod.PROJECT_ROOT at ``tmp_path`` and create its ``tmp/`` subdir.

    Args:
        tmp_path: pytest-provided temp directory used as the project root.
        monkeypatch: pytest monkeypatch fixture.

    Returns:
        Path: the resolved ``tmp_path / "tmp"`` containment root.
    """
    monkeypatch.setattr(cli_mod, "PROJECT_ROOT", tmp_path)
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    return tmp_root


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_content_flag_forwards_inline_body(
    mock_get_db: MagicMock,
    mock_get_client: MagicMock,
    mock_save_artifact: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--content (inline) forwards the literal string body to save_artifact."""
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_collection = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_get_client.return_value = mock_client
    mock_save_artifact.return_value = "ACME-100|2026-01-01|plan_snapshot|opus||"

    save(content="inline body", fields=_VALID_FIELDS)

    captured = capsys.readouterr()
    assert "ACME-100|2026-01-01|plan_snapshot|opus||" in captured.out
    mock_save_artifact.assert_called_once()
    call_args = mock_save_artifact.call_args
    assert call_args[0][1] == "inline body"


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_content_file_flag_forwards_file_body(
    mock_get_db: MagicMock,
    mock_get_client: MagicMock,
    mock_save_artifact: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--content-file (under tmp/) reads the file and forwards its body."""
    tmp_root = _make_tmp_root(tmp_path, monkeypatch)
    fixture = tmp_root / "body.md"
    fixture.write_text("file body content", encoding="utf-8")

    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_collection = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_get_client.return_value = mock_client
    mock_save_artifact.return_value = "ACME-100|2026-01-01|plan_snapshot|opus||"

    save(content_file="tmp/body.md", fields=_VALID_FIELDS)

    captured = capsys.readouterr()
    assert "ACME-100|2026-01-01|plan_snapshot|opus||" in captured.out
    mock_save_artifact.assert_called_once()
    call_args = mock_save_artifact.call_args
    assert call_args[0][1] == "file body content"


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_rejects_both_content_and_content_file(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
) -> None:
    """Supplying both --content and --content-file is mutually exclusive."""
    with pytest.raises(SystemExit) as exc_info:
        save(content="x", content_file="tmp/body.md", fields=_VALID_FIELDS)
    assert "mutually exclusive" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_rejects_neither_content_nor_content_file(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
) -> None:
    """Supplying neither --content nor --content-file is rejected (presence)."""
    with pytest.raises(SystemExit) as exc_info:
        save(fields=_VALID_FIELDS)
    assert "exactly one of --content / --content-file required" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_content_file_missing_file(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A --content-file path that does not exist is rejected as unreadable."""
    _make_tmp_root(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as exc_info:
        save(content_file="tmp/does-not-exist.md", fields=_VALID_FIELDS)
    assert "not found or unreadable" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_content_file_outside_tmp_rejected(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real file outside tmp/ (directly under project root) is rejected."""
    _make_tmp_root(tmp_path, monkeypatch)
    outside = tmp_path / "outside.md"
    outside.write_text("outside body", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        save(content_file="outside.md", fields=_VALID_FIELDS)
    assert "must resolve inside tmp/" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_content_file_symlink_escape_rejected(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A symlink under tmp/ pointing outside tmp/ is rejected by containment."""
    tmp_root = _make_tmp_root(tmp_path, monkeypatch)
    target = tmp_path / "secret.md"
    target.write_text("escaped content", encoding="utf-8")
    link = tmp_root / "escape"
    link.symlink_to(target)
    with pytest.raises(SystemExit) as exc_info:
        save(content_file="tmp/escape", fields=_VALID_FIELDS)
    assert "must resolve inside tmp/" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_content_file_dotdot_traversal_rejected(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``..`` traversal path that climbs out of tmp/ is rejected."""
    _make_tmp_root(tmp_path, monkeypatch)
    escaped = tmp_path / "climbed.md"
    escaped.write_text("climbed body", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        save(content_file="tmp/../climbed.md", fields=_VALID_FIELDS)
    assert "must resolve inside tmp/" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_content_file_absolute_path_outside_tmp_rejected(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An absolute path resolving outside tmp/ is rejected by containment."""
    _make_tmp_root(tmp_path, monkeypatch)
    outside = tmp_path / "abs-outside.md"
    outside.write_text("abs body", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        save(content_file=str(outside), fields=_VALID_FIELDS)
    assert "must resolve inside tmp/" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_content_file_empty_rejected(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty (zero-byte) file under tmp/ is rejected as whitespace-only."""
    tmp_root = _make_tmp_root(tmp_path, monkeypatch)
    fixture = tmp_root / "empty.md"
    fixture.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        save(content_file="tmp/empty.md", fields=_VALID_FIELDS)
    assert "empty or whitespace-only" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_content_file_whitespace_only_rejected(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A whitespace-only file under tmp/ is rejected."""
    tmp_root = _make_tmp_root(tmp_path, monkeypatch)
    fixture = tmp_root / "blank.md"
    fixture.write_text("   \n\t  \n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        save(content_file="tmp/blank.md", fields=_VALID_FIELDS)
    assert "empty or whitespace-only" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_content_file_oversized_rejected(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file exceeding MAX_CONTENT_FILE_BYTES is rejected by the size cap.

    The file is created sparsely via ``truncate`` so no 10 MiB fixture is
    written byte-by-byte and nothing is committed to the repo.
    """
    tmp_root = _make_tmp_root(tmp_path, monkeypatch)
    fixture = tmp_root / "huge.md"
    oversize = (10 * 1024 * 1024) + 1
    with fixture.open("wb") as handle:
        handle.truncate(oversize)
    with pytest.raises(SystemExit) as exc_info:
        save(content_file="tmp/huge.md", fields=_VALID_FIELDS)
    assert "exceeds" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_content_file_invalid_utf8_rejected(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file with invalid UTF-8 bytes is rejected before forwarding."""
    tmp_root = _make_tmp_root(tmp_path, monkeypatch)
    fixture = tmp_root / "binary.md"
    fixture.write_bytes(b"\xff\xfe\x00\x80 not utf-8")
    with pytest.raises(SystemExit) as exc_info:
        save(content_file="tmp/binary.md", fields=_VALID_FIELDS)
    assert "not valid UTF-8" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_content_file_directory_rejected(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A --content-file pointing at a directory under tmp/ is rejected.

    The path passes containment (it resolves inside tmp/) but is not a
    regular file. The fixed code must reject it with a ``SystemExit`` before
    attempting to read it; without an ``is_file()`` guard the read raises a
    raw ``IsADirectoryError`` that is not a ``SystemExit``.
    """
    tmp_root = _make_tmp_root(tmp_path, monkeypatch)
    subdir = tmp_root / "subdir"
    subdir.mkdir()
    with pytest.raises(SystemExit) as exc_info:
        save(content_file="tmp/subdir", fields=_VALID_FIELDS)
    assert "must be a regular file" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_content_file_read_oserror_rejected(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A --content-file whose read raises OSError is rejected as unreadable.

    The fixture is a valid regular file under tmp/ that clears the
    containment, size, and is_file checks. ``Path.read_text`` is patched at
    the class level to raise ``PermissionError`` (an ``OSError`` subclass),
    isolating the read-error path. The current ``except UnicodeDecodeError``
    clause does not catch ``PermissionError``, so it propagates uncaught
    (not a ``SystemExit``). The fixed code must surface the
    ``not found or unreadable`` message.
    """
    tmp_root = _make_tmp_root(tmp_path, monkeypatch)
    fixture = tmp_root / "unreadable.md"
    fixture.write_text("valid body", encoding="utf-8")

    real_read_text = Path.read_text

    def fake_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        """Raise PermissionError only for the target fixture; delegate otherwise."""
        if self.resolve() == fixture.resolve():
            raise PermissionError("simulated read failure")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    with pytest.raises(SystemExit) as exc_info:
        save(content_file="tmp/unreadable.md", fields=_VALID_FIELDS)
    assert "not found or unreadable" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_content_file_missing_tmp_root_rejected(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A --content-file call when tmp/ itself is absent is rejected gracefully.

    PROJECT_ROOT is anchored at a fresh ``tmp_path`` with NO ``tmp/`` subdir.
    The current code resolves ``(PROJECT_ROOT / "tmp").resolve(strict=True)``
    outside the try/except, so an absent tmp/ raises a raw
    ``FileNotFoundError`` rather than a ``SystemExit``. The fixed code must
    surface the ``not found or unreadable`` message.
    """
    monkeypatch.setattr(cli_mod, "PROJECT_ROOT", tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        save(content_file="tmp/whatever.md", fields=_VALID_FIELDS)
    assert "not found or unreadable" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_inline_content_empty_rejected(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
) -> None:
    """Inline --content of an empty string is rejected as whitespace-only.

    Dispatch: ``content=""`` is not ``None``, so the mutual-exclusion guard
    and the neither-branch ``else`` are both skipped; execution reaches the
    ``elif content is not None`` inline branch with ``body = ""``. The
    current code forwards the empty body to ``save_artifact`` with no strip
    check. The fixed code must reject it before forwarding.
    """
    with pytest.raises(SystemExit) as exc_info:
        save(content="", fields=_VALID_FIELDS)
    assert "empty or whitespace-only" in str(exc_info.value)


@patch("brownfield_ai.ledger.artifacts.cli.save_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
@patch("brownfield_ai.ledger.artifacts.cli.get_db")
def test_save_inline_content_whitespace_rejected(
    _mock_get_db: MagicMock,
    _mock_get_client: MagicMock,
    _mock_save_artifact: MagicMock,
) -> None:
    """Inline --content of a whitespace-only string is rejected.

    Same inline dispatch path as the empty-string case: ``"   "`` is not
    ``None`` so it reaches the ``elif content is not None`` branch. The
    current code has no strip check and forwards the whitespace body. The
    fixed code must reject it with the ``empty or whitespace-only`` message.
    """
    with pytest.raises(SystemExit) as exc_info:
        save(content="   ", fields=_VALID_FIELDS)
    assert "empty or whitespace-only" in str(exc_info.value)


def test_save_defopt_dispatch_content_flag() -> None:
    """defopt dispatches ``--content`` as a flag with no positional content slot.

    Patches the infra/IO dependencies so dispatch reaches the validation +
    forwarding path without touching ChromaDB or the filesystem.
    """
    with (
        patch("brownfield_ai.ledger.artifacts.cli.save_artifact") as mock_save_artifact,
        patch("brownfield_ai.ledger.artifacts.cli.get_client") as mock_get_client,
        patch("brownfield_ai.ledger.artifacts.cli.get_db") as mock_get_db,
    ):
        mock_save_artifact.return_value = "ACME-100|2026-01-01|plan_snapshot|opus||"
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client
        mock_get_db.return_value = MagicMock()

        defopt.run(
            [save],
            argv=["save", "--content", "dispatched body", "--fields", _VALID_FIELDS],
        )

    mock_save_artifact.assert_called_once()
    assert mock_save_artifact.call_args[0][1] == "dispatched body"


def test_save_defopt_dispatch_content_file_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """defopt dispatches ``--content-file`` as a flag (no positional slot)."""
    tmp_root = _make_tmp_root(tmp_path, monkeypatch)
    fixture = tmp_root / "dispatch.md"
    fixture.write_text("dispatched file body", encoding="utf-8")

    with (
        patch("brownfield_ai.ledger.artifacts.cli.save_artifact") as mock_save_artifact,
        patch("brownfield_ai.ledger.artifacts.cli.get_client") as mock_get_client,
        patch("brownfield_ai.ledger.artifacts.cli.get_db") as mock_get_db,
    ):
        mock_save_artifact.return_value = "ACME-100|2026-01-01|plan_snapshot|opus||"
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client
        mock_get_db.return_value = MagicMock()

        defopt.run(
            [save],
            argv=["save", "--content-file", "tmp/dispatch.md", "--fields", _VALID_FIELDS],
        )

    mock_save_artifact.assert_called_once()
    assert mock_save_artifact.call_args[0][1] == "dispatched file body"


# ---------------------------------------------------------------------------
# query() tests
# ---------------------------------------------------------------------------


@patch("brownfield_ai.ledger.artifacts.cli.get_client")
def test_query_prints_results(
    mock_get_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["art-1"]],
        "documents": [["artifact content body"]],
        "metadatas": [[{"epic_id": "ACME-100", "artifact_type": "step_result"}]],
        "distances": [[0.15]],
    }
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_get_client.return_value = mock_client

    query("search text")

    captured = capsys.readouterr()
    assert "ID: art-1" in captured.out
    assert "Distance: 0.15" in captured.out
    assert "artifact content body" in captured.out


@patch("brownfield_ai.ledger.artifacts.cli.get_client")
def test_query_prints_no_results(
    mock_get_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_get_client.return_value = mock_client

    query("search text")

    captured = capsys.readouterr()
    assert captured.out == "No results found.\n"


@patch("brownfield_ai.ledger.artifacts.cli.get_client")
def test_query_exits_on_invalid_filters_json(
    _mock_get_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        query("search", filters="bad-json")
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Invalid JSON in --filters" in captured.out


# ---------------------------------------------------------------------------
# timeline() tests
# ---------------------------------------------------------------------------


@patch("brownfield_ai.ledger.artifacts.cli.get_timeline")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
def test_timeline_prints_formatted_output(
    mock_get_client: MagicMock,
    mock_get_timeline: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_collection = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_get_client.return_value = mock_client
    mock_get_timeline.return_value = [
        {
            "id": "ACME-100|2026-01-01|step_result|opus||",
            "document": "content",
            "metadata": {"artifact_type": "step_result", "version": 1, "verdict": "pass"},
        }
    ]

    timeline("ACME-100")

    captured = capsys.readouterr()
    assert "[step_result]" in captured.out
    assert "v1" in captured.out
    assert "pass" in captured.out


@patch("brownfield_ai.ledger.artifacts.cli.get_timeline")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
def test_timeline_prints_no_artifacts(
    mock_get_client: MagicMock,
    mock_get_timeline: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_collection = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_get_client.return_value = mock_client
    mock_get_timeline.return_value = []

    timeline("ACME-100")

    captured = capsys.readouterr()
    assert captured.out == "No artifacts found.\n"


# ---------------------------------------------------------------------------
# get() tests
# ---------------------------------------------------------------------------


@patch("brownfield_ai.ledger.artifacts.cli.get_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
def test_get_prints_document(
    mock_get_client: MagicMock,
    mock_get_artifact: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_collection = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_get_client.return_value = mock_client
    mock_get_artifact.return_value = {
        "id": "doc-1",
        "document": "full document content here",
        "metadata": {"epic_id": "ACME-100", "artifact_type": "plan_snapshot"},
    }

    get("doc-1")

    captured = capsys.readouterr()
    assert "ID: doc-1" in captured.out
    assert "full document content here" in captured.out
    assert "epic_id" in captured.out


@patch("brownfield_ai.ledger.artifacts.cli.get_artifact")
@patch("brownfield_ai.ledger.artifacts.cli.get_client")
def test_get_exits_when_not_found(
    mock_get_client: MagicMock,
    mock_get_artifact: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_collection = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_get_client.return_value = mock_client
    mock_get_artifact.return_value = None

    with pytest.raises(SystemExit) as exc_info:
        get("missing-id")
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Document not found." in captured.out
