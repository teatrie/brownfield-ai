"""Unit tests for the PreToolUse hook: block-stranded-agent.sh.

Feeds simulated Claude Code PreToolUse JSON payloads to the hook via stdin and
asserts the correct exit code (0 = allow, 2 = deny). The hook denies exactly one
shape — a NAMED, backgrounded, in-process ``Agent`` dispatch of a
no-``SendMessage`` agent type (CLAUDE.md Principle 18) — and exempts every other
shape.

Rules tested:
- deny: named + backgrounded (explicit or field-absent) + restricted subagent_type
- allow: synchronous (run_in_background:false), even when named + restricted
- allow: unnamed background subagent (returns via task-notification)
- allow: team_name set (agent-team tmux teammate — full claude, has SendMessage)
- allow: subagent_type claude / empty (full-tools default)
- allow: non-Agent tool_name (matcher defence), empty stdin
- deny: malformed (non-JSON) input — fail-closed
- injection: metacharacter subagent_type is inert data (denied as a restricted
  type, no command execution)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

HOOK = str(Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "block-stranded-agent.sh")

# Representative sample of this repo's no-SendMessage custom agent types. A
# sweep for "SendMessage" across .claude/agents/ returns zero hits, so every
# custom type is a stranding risk — including all four reviewer bridges, which
# are the most expensive place to strand (the bridge CLI has already run and
# billed by the time the dispatch idles).
RESTRICTED_TYPES = [
    "code-review",
    "code-review-high",
    "explore",
    "qa-standards",
    "qa-lint",
    "task",
    "deep-researcher",
    "planner",
    "orchestrator",
    "general-purpose",
    "tdd-green",
    "tdd-red",
    "tdd-refactor",
    "codex-reviewer",
    "copilot-reviewer",
    "gemini-reviewer",
]


def _run_hook(
    tool_input: dict[str, Any] | None,
    *,
    tool_name: str = "Agent",
) -> subprocess.CompletedProcess[str]:
    """Invoke the hook with a simulated PreToolUse payload; return the completed process.

    ``tool_input=None`` sends malformed (non-JSON) stdin to exercise fail-closed.
    """
    if tool_input is None:
        payload = "not json"
    else:
        payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input}, separators=(",", ":"))
    return subprocess.run(
        ["bash", HOOK],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestStrandingShapeDenied:
    """Named + backgrounded + restricted subagent_type is the one denied shape."""

    @pytest.mark.parametrize("subagent", RESTRICTED_TYPES)
    def test_named_explicit_background_denied(self, subagent: str) -> None:
        """Explicit run_in_background:true with a name and restricted type is denied."""
        result = _run_hook({"subagent_type": subagent, "name": "r1", "run_in_background": True})
        assert result.returncode == 2, f"Not blocked: {subagent}"
        assert "DENIED" in result.stderr

    @pytest.mark.parametrize("subagent", RESTRICTED_TYPES)
    def test_named_absent_background_field_denied(self, subagent: str) -> None:
        """An omitted run_in_background field must still deny.

        Not a hypothetical: some Agent tool surfaces expose no
        ``run_in_background`` parameter at all, so every dispatch from those
        harnesses omits the field. ``jq -r`` yields "null", which is not
        "false", so the named+restricted shape stays denied — this is what
        makes the guard bind regardless of tool surface.
        """
        result = _run_hook({"subagent_type": subagent, "name": "r1"})
        assert result.returncode == 2, f"Not blocked (absent bg field): {subagent}"
        assert "DENIED" in result.stderr


class TestExemptShapesAllowed:
    """Every non-stranding shape is allowed (exit 0)."""

    def test_synchronous_allowed(self) -> None:
        """run_in_background:false returns its result inline — always safe."""
        result = _run_hook({"subagent_type": "code-review", "name": "r1", "run_in_background": False})
        assert result.returncode == 0

    def test_unnamed_background_allowed(self) -> None:
        """An unnamed background subagent returns via completion task-notification."""
        result = _run_hook({"subagent_type": "general-purpose", "run_in_background": True})
        assert result.returncode == 0

    def test_unnamed_absent_background_field_allowed(self) -> None:
        """Dropping the name is sufficient on a surface with no background flag."""
        result = _run_hook({"subagent_type": "code-review"})
        assert result.returncode == 0

    def test_team_name_allowed(self) -> None:
        """A tmux teammate (team_name set) is a full claude process with SendMessage."""
        payload = {"subagent_type": "tdd-green", "name": "t1", "team_name": "feat", "run_in_background": True}
        result = _run_hook(payload)
        assert result.returncode == 0

    def test_claude_default_allowed(self) -> None:
        """The full-tools catch-all agent has SendMessage."""
        result = _run_hook({"subagent_type": "claude", "name": "x", "run_in_background": True})
        assert result.returncode == 0

    def test_empty_subagent_type_allowed(self) -> None:
        """Omitted subagent_type resolves to the default claude agent — allowed."""
        result = _run_hook({"name": "x", "run_in_background": True})
        assert result.returncode == 0


class TestMatcherAndInputGuards:
    """Defensive guards: non-Agent tool, empty stdin, malformed input."""

    def test_non_agent_tool_allowed(self) -> None:
        """A mis-registered matcher must not apply this hook to other tools."""
        payload = {"subagent_type": "code-review", "name": "r1", "run_in_background": True}
        result = _run_hook(payload, tool_name="Bash")
        assert result.returncode == 0

    def test_empty_stdin_allowed(self) -> None:
        """Empty payload is a no-op allow."""
        result = subprocess.run(["bash", HOOK], input="", capture_output=True, text=True, timeout=10)
        assert result.returncode == 0

    def test_malformed_json_denied(self) -> None:
        """Non-JSON stdin fails closed."""
        result = _run_hook(None)
        assert result.returncode == 2
        assert "DENIED" in result.stderr


class TestInjectionInert:
    """A metacharacter subagent_type is inert data — denied as restricted, never executed."""

    def test_command_substitution_not_executed(self, tmp_path: Path) -> None:
        """A ``$(...)`` payload in subagent_type must not run."""
        sentinel = tmp_path / "PWNED"
        subagent = f"evil$(touch {sentinel})"
        result = _run_hook({"subagent_type": subagent, "name": "n", "run_in_background": True})
        assert result.returncode == 2
        assert "has no SendMessage tool" in result.stderr, "denied for the wrong reason, not as a restricted type"
        assert not sentinel.exists(), "hook executed injected command — quoting failure"

    def test_backtick_not_executed(self, tmp_path: Path) -> None:
        """A backtick payload in subagent_type must not run."""
        sentinel = tmp_path / "PWNED"
        subagent = f"evil`touch {sentinel}`"
        result = _run_hook({"subagent_type": subagent, "name": "n", "run_in_background": True})
        assert result.returncode == 2
        assert "has no SendMessage tool" in result.stderr, "denied for the wrong reason, not as a restricted type"
        assert not sentinel.exists(), "hook executed injected command — quoting failure"
