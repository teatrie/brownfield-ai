import json
from pathlib import Path

from knowledge_checkpoint import (
    detect_format,
    parse_claude_code_event,
    parse_copilot_event,
    parse_events,
)

# -- Copilot format test data --

COPILOT_USER_EVENT = {
    "type": "user.message",
    "timestamp": "2026-01-01T00:00:00Z",
    "data": {"content": "hello"},
}

COPILOT_ASSISTANT_EVENT = {
    "type": "assistant.message",
    "timestamp": "2026-01-01T00:00:01Z",
    "data": {"content": "hi", "toolRequests": [{"name": "Read"}]},
}

COPILOT_TOOL_EVENT = {
    "type": "tool.execution_result",
    "timestamp": "2026-01-01T00:00:02Z",
    "data": {},
}


# -- Claude Code format test data --

CC_USER_TEXT_EVENT = {
    "type": "user",
    "timestamp": "2026-01-01T00:00:00Z",
    "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]},
}

CC_USER_PLAIN_STRING_EVENT = {
    "type": "user",
    "timestamp": "2026-01-01T00:00:06Z",
    "message": {"role": "user", "content": "plain string content"},
}

CC_ASSISTANT_TEXT_EVENT = {
    "type": "assistant",
    "timestamp": "2026-01-01T00:00:01Z",
    "message": {"role": "assistant", "content": [{"type": "text", "text": "response"}]},
}

CC_TOOL_USE_EVENT = {
    "type": "assistant",
    "timestamp": "2026-01-01T00:00:02Z",
    "message": {
        "role": "assistant",
        "content": [{"type": "tool_use", "name": "Read", "id": "toolu_1", "input": {}}],
    },
}

CC_PROGRESS_EVENT = {
    "type": "progress",
    "timestamp": "2026-01-01T00:00:03Z",
    "data": {"type": "hook_progress"},
}

CC_THINKING_EVENT = {
    "type": "assistant",
    "timestamp": "2026-01-01T00:00:04Z",
    "message": {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "internal reasoning"},
            {"type": "text", "text": "visible"},
        ],
    },
}

CC_TOOL_RESULT_EVENT = {
    "type": "user",
    "timestamp": "2026-01-01T00:00:05Z",
    "message": {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "file contents"}],
    },
}

CC_META_EVENT = {
    "type": "user",
    "timestamp": "2026-01-01T00:00:07Z",
    "isMeta": True,
    "message": {
        "role": "user",
        "content": [{"type": "text", "text": "skill expansion content"}],
    },
}


# -- Format Detection Tests (Req-001) --


def test_detect_format_copilot():
    assert detect_format(COPILOT_USER_EVENT) == "copilot"


def test_detect_format_claude_code():
    assert detect_format(CC_USER_TEXT_EVENT) == "claude-code"


def test_detect_format_skip_event_implies_claude_code():
    assert detect_format(CC_PROGRESS_EVENT) == "claude-code"


# -- Copilot Parsing Tests (Req-009) --


def test_parse_copilot_user_message():
    result = parse_copilot_event(COPILOT_USER_EVENT)
    assert result == "User (2026-01-01T00:00:00Z): hello"


def test_parse_copilot_assistant_with_tools():
    result = parse_copilot_event(COPILOT_ASSISTANT_EVENT)
    assert result == "Assistant (2026-01-01T00:00:01Z): hi\n[Tool Calls: Read]"


def test_parse_copilot_tool_result_skipped():
    result = parse_copilot_event(COPILOT_TOOL_EVENT)
    assert result is None


# -- Claude Code Parsing Tests --


def test_parse_claude_code_user_text_blocks():
    result = parse_claude_code_event(CC_USER_TEXT_EVENT)
    assert result == "User (2026-01-01T00:00:00Z): hello"


def test_parse_claude_code_user_plain_string():
    result = parse_claude_code_event(CC_USER_PLAIN_STRING_EVENT)
    assert result == "User (2026-01-01T00:00:06Z): plain string content"


def test_parse_claude_code_assistant_text():
    result = parse_claude_code_event(CC_ASSISTANT_TEXT_EVENT)
    assert result == "Assistant (2026-01-01T00:00:01Z): response"


def test_parse_claude_code_tool_use():
    result = parse_claude_code_event(CC_TOOL_USE_EVENT)
    assert result == "Assistant (2026-01-01T00:00:02Z): \n[Tool Calls: Read]"


def test_parse_claude_code_skip_progress():
    result = parse_claude_code_event(CC_PROGRESS_EVENT)
    assert result is None


def test_parse_claude_code_skip_thinking():
    result = parse_claude_code_event(CC_THINKING_EVENT)
    assert result == "Assistant (2026-01-01T00:00:04Z): visible"


def test_parse_claude_code_skip_tool_result():
    result = parse_claude_code_event(CC_TOOL_RESULT_EVENT)
    assert result is None


def test_parse_claude_code_skip_meta():
    result = parse_claude_code_event(CC_META_EVENT)
    assert result is None


# -- Integration Tests (file-based) --


def test_parse_events_copilot_file(tmp_path: Path):
    jsonl_file = tmp_path / "copilot_chat.jsonl"
    events = [COPILOT_USER_EVENT, COPILOT_ASSISTANT_EVENT, COPILOT_TOOL_EVENT]
    jsonl_file.write_text("\n".join(json.dumps(e) for e in events) + "\n")

    entries, fmt = parse_events(str(jsonl_file))
    assert fmt == "copilot"
    assert len(entries) == 2
    assert entries[0] == "User (2026-01-01T00:00:00Z): hello"
    assert "Tool Calls: Read" in entries[1]


def test_parse_events_claude_code_file(tmp_path: Path):
    jsonl_file = tmp_path / "claude_code_chat.jsonl"
    events = [
        CC_USER_TEXT_EVENT,
        CC_ASSISTANT_TEXT_EVENT,
        CC_TOOL_USE_EVENT,
        CC_PROGRESS_EVENT,
        CC_THINKING_EVENT,
        CC_TOOL_RESULT_EVENT,
        CC_META_EVENT,
    ]
    jsonl_file.write_text("\n".join(json.dumps(e) for e in events) + "\n")

    entries, fmt = parse_events(str(jsonl_file))
    assert fmt == "claude-code"
    # Expected: user text, assistant text, tool_use, thinking (text only) = 4
    # Skipped: progress, tool_result, meta
    assert len(entries) == 4
    assert entries[0] == "User (2026-01-01T00:00:00Z): hello"
    assert entries[1] == "Assistant (2026-01-01T00:00:01Z): response"


def test_parse_events_empty_file(tmp_path: Path):
    jsonl_file = tmp_path / "empty.jsonl"
    jsonl_file.write_text("")

    entries, fmt = parse_events(str(jsonl_file))
    assert entries == []
