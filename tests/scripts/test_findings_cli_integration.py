"""End-to-end integration scenarios for the findings-tracker CLI.

Per TODO-0092 Phase B R_B1 (codex I7 follow-up), five scripted
lifecycle scenarios exercise the full ledger-mutation contract
across multiple CLI invocations. Each scenario uses a ``tmp_path``
fixture for ledger isolation and never touches the workspace
``tmp/`` directory.

These tests MUST fail at commit time — the CLI they describe is
authored in the GREEN phase.
"""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH: str = "scripts/findings_tracker.py"


def _invoke_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    """Run the findings_tracker CLI via runpy and return captured stdout.

    Args:
        argv: Command-line arguments excluding the script name itself.
        capsys: Pytest capsys fixture used to drain stdout after each run.

    Returns:
        The captured stdout from the single CLI run.
    """
    old_argv = sys.argv
    sys.argv = ["findings_tracker.py", *argv]
    try:
        runpy.run_path(_SCRIPT_PATH, run_name="__main__")
    finally:
        sys.argv = old_argv
    return capsys.readouterr().out


# ---------------------------------------------------------------------------
# Scenario 1 — happy path: create → update-status → filter active → load
# ---------------------------------------------------------------------------


def test_integration_happy_path_create_update_filter_load(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text("[]")

    for fid, desc in [("F001", "Issue A"), ("F002", "Issue B"), ("F003", "Issue C")]:
        _invoke_cli(
            [
                "findings:create",
                "--finding-id",
                fid,
                "--reviewer",
                "alice",
                "--severity",
                "minor",
                "--description",
                desc,
                "--round-num",
                "1",
                "--in-path",
                str(ledger),
                "--out-path",
                str(ledger),
            ],
            capsys,
        )

    _invoke_cli(
        [
            "findings:update-status",
            "--finding-id",
            "F002",
            "--new-status",
            "resolved",
            "--in-path",
            str(ledger),
            "--out-path",
            str(ledger),
        ],
        capsys,
    )

    active_out = _invoke_cli(
        ["findings:filter", "--kind", "active", "--in-path", str(ledger)],
        capsys,
    )
    active = json.loads(active_out)
    active_ids = {f["finding_id"] for f in active}
    assert active_ids == {"F001", "F003"}

    load_out = _invoke_cli(
        ["findings:load", "--in-path", str(ledger)],
        capsys,
    )
    loaded = json.loads(load_out)
    assert len(loaded) == 3
    resolved = next(f for f in loaded if f["finding_id"] == "F002")
    assert resolved["status"] == "resolved"


# ---------------------------------------------------------------------------
# Scenario 2 — merge + filter: create 3 → merge 2 → filter active
# ---------------------------------------------------------------------------


def test_integration_merge_then_filter_excludes_merged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text("[]")

    for fid, severity in [("F001", "minor"), ("F002", "significant"), ("F003", "minor")]:
        _invoke_cli(
            [
                "findings:create",
                "--finding-id",
                fid,
                "--reviewer",
                "alice",
                "--severity",
                severity,
                "--description",
                f"Issue {fid}",
                "--round-num",
                "1",
                "--in-path",
                str(ledger),
                "--out-path",
                str(ledger),
            ],
            capsys,
        )

    _invoke_cli(
        [
            "findings:merge-duplicates",
            "--duplicate-ids",
            "F001",
            "--duplicate-ids",
            "F002",
            "--in-path",
            str(ledger),
            "--out-path",
            str(ledger),
        ],
        capsys,
    )

    out = _invoke_cli(
        ["findings:filter", "--kind", "active", "--in-path", str(ledger)],
        capsys,
    )
    active = json.loads(out)
    active_ids = {f["finding_id"] for f in active}
    assert active_ids == {"F001", "F003"}
    # Canonical (F001) had its severity promoted by the merge.
    canonical = next(f for f in active if f["finding_id"] == "F001")
    assert canonical["severity"] == "significant"


# ---------------------------------------------------------------------------
# Scenario 3 — error path: missing file read-only CLI returns empty JSON
# ---------------------------------------------------------------------------


def test_integration_filter_on_missing_file_returns_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "never-written.json"
    out = _invoke_cli(
        ["findings:filter", "--kind", "active", "--in-path", str(missing)],
        capsys,
    )
    assert json.loads(out) == []


# ---------------------------------------------------------------------------
# Scenario 4 — error path: malformed JSON on read is tolerated (load == [])
# ---------------------------------------------------------------------------


def test_integration_malformed_ledger_tolerated_and_rewritten(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text("not json[")

    load_out = _invoke_cli(
        ["findings:load", "--in-path", str(ledger)],
        capsys,
    )
    assert json.loads(load_out) == []

    # A subsequent create on the same path must succeed (replaces the
    # malformed file with a valid ledger).
    _invoke_cli(
        [
            "findings:create",
            "--finding-id",
            "F001",
            "--reviewer",
            "alice",
            "--severity",
            "minor",
            "--description",
            "Recovery",
            "--round-num",
            "1",
            "--in-path",
            str(ledger),
            "--out-path",
            str(ledger),
        ],
        capsys,
    )
    data = json.loads(ledger.read_text())
    assert len(data) == 1
    assert data[0]["finding_id"] == "F001"


# ---------------------------------------------------------------------------
# Scenario 5 — error path: unknown --kind is rejected
# ---------------------------------------------------------------------------


def test_integration_filter_unknown_kind_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text("[]")
    with pytest.raises((ValueError, SystemExit)):
        _invoke_cli(
            [
                "findings:filter",
                "--kind",
                "bogus",
                "--in-path",
                str(ledger),
            ],
            capsys,
        )
