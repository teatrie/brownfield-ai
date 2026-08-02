"""Mechanical guard against stale ledger CLI shapes in verification_protocol.md.

Enforces TODO-0158 / RVW-002 follow-up Req-A02: the legacy
``execution-ledger query`` CLI shape was replaced by
``task ledger:filter -- <id> --artifact-type <type>`` and must not
reappear in this docs file.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "verification_protocol.md"

STALE_CLI_SUBSTRING = "execution-ledger query"


def test_verification_protocol_does_not_reference_stale_ledger_cli() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    assert STALE_CLI_SUBSTRING not in text, (
        f"Stale CLI shape {STALE_CLI_SUBSTRING!r} reappeared in {DOC_PATH}; "
        "use 'task ledger:filter -- <id> --artifact-type <type>' instead."
    )
