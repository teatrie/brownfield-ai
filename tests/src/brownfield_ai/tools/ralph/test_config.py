from __future__ import annotations

from typing import Any

import pytest

from brownfield_ai.tools.ralph.config import bump_floor, default_floor, get_config

# ---------------------------------------------------------------------------
# get_config
# ---------------------------------------------------------------------------


def test_get_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RALPH_SESSION_TIMEOUT_SECS", raising=False)
    monkeypatch.delenv("RALPH_EPIC_MAX_SESSIONS", raising=False)
    monkeypatch.delenv("RALPH_POLL_INTERVAL_SECS", raising=False)

    config = get_config()
    assert config["session_timeout"] == 7200
    assert config["max_sessions"] == 9
    assert config["poll_interval"] == 300


def test_get_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RALPH_SESSION_TIMEOUT_SECS", "3600")
    monkeypatch.setenv("RALPH_EPIC_MAX_SESSIONS", "6")
    monkeypatch.setenv("RALPH_POLL_INTERVAL_SECS", "60")

    config = get_config()
    assert config["session_timeout"] == 3600
    assert config["max_sessions"] == 6
    assert config["poll_interval"] == 60


def test_get_config_partial_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RALPH_SESSION_TIMEOUT_SECS", "1800")
    monkeypatch.delenv("RALPH_EPIC_MAX_SESSIONS", raising=False)
    monkeypatch.delenv("RALPH_POLL_INTERVAL_SECS", raising=False)

    config = get_config()
    assert config["session_timeout"] == 1800
    assert config["max_sessions"] == 9
    assert config["poll_interval"] == 300


# ---------------------------------------------------------------------------
# bump_floor
# ---------------------------------------------------------------------------


def test_bump_floor_attempt_1() -> None:
    assert bump_floor(1) == ""


def test_bump_floor_attempt_2() -> None:
    assert bump_floor(2) == "per-plan,high"


def test_bump_floor_attempt_3() -> None:
    assert bump_floor(3) == "one-tier-up,max"


def test_bump_floor_negative_returns_empty() -> None:
    assert bump_floor(0) == ""
    assert bump_floor(-1) == ""


def test_bump_floor_beyond_max_returns_highest() -> None:
    assert bump_floor(4) == "one-tier-up,max"
    assert bump_floor(100) == "one-tier-up,max"


# ---------------------------------------------------------------------------
# default_floor
# ---------------------------------------------------------------------------


def test_default_floor_returns_empty() -> None:
    sub_plan: dict[str, Any] = {"label": "A", "waves": ["0"]}
    assert default_floor(sub_plan) == ""


def test_default_floor_with_complex_plan() -> None:
    sub_plan: dict[str, Any] = {"label": "C", "waves": ["4", "5", "6", "QA"]}
    assert default_floor(sub_plan) == ""
