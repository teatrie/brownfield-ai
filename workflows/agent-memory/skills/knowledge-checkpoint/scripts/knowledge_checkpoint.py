"""
Import conversation history from a JSONL event log into the knowledge base.

Supports both Copilot and Claude Code event formats.
Parses user and assistant messages to reconstruct the dialogue.
"""

import json
import os
import sys
from datetime import datetime
from typing import Any

import chromadb
import defopt

SKIP_EVENT_TYPES: set[str] = {
    "queue-operation",
    "progress",
    "file-history-snapshot",
    "ai-title",
    "system",
    "last-prompt",
    "permission-mode",
    "attachment",
}


def import_chat(file_path: str) -> None:
    """
    Read a JSONL conversational event log and import the reconstructed chat into ChromaDB.

    CLI entry point that calls ``parse_events`` then pushes the result to the
    ``chat_history`` ChromaDB collection.

    Args:
        file_path: The local path to the events JSONL file.
    """
    print(f"Reading chat history from {file_path}...")

    chat_entries, source_format = parse_events(file_path)

    if not chat_entries:
        print("No chat entries found.")
        return

    full_chat = "\n\n".join(chat_entries)

    client = get_client()
    collection = client.get_or_create_collection("chat_history")

    now = datetime.now()
    checkpoint_id = f"chat_checkpoint_{now.strftime('%Y%m%d_%H%M%S')}"

    collection.add(
        documents=[full_chat],
        metadatas=[
            {
                "type": "chat_history",
                "timestamp": now.isoformat(),
                "source": source_format,
                "line_count": len(chat_entries),
            }
        ],
        ids=[checkpoint_id],
    )

    print(f"Successfully imported chat history as '{checkpoint_id}'.")
    print(f"Document length: {len(full_chat)} characters.")


def parse_events(file_path: str) -> tuple[list[str], str]:
    """
    Read a JSONL event log, auto-detect its format, and return parsed chat entries.

    Args:
        file_path: Path to the JSONL file.

    Returns:
        A tuple of (entries, format_name) where *entries* is a list of formatted
        chat strings and *format_name* is ``"copilot"`` or ``"claude-code"``.
        Returns ``([], "")`` when the file is empty or contains no parseable events.
    """
    events: list[dict[str, Any]] = []
    with open(file_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not events:
        return [], ""

    fmt = detect_format(events[0])
    parser = parse_copilot_event if fmt == "copilot" else parse_claude_code_event

    entries: list[str] = []
    for event in events:
        result = parser(event)
        if result is not None:
            entries.append(result)

    return entries, fmt


def detect_format(event: dict[str, Any]) -> str:
    """
    Determine the event log format from a single event.

    Args:
        event: A parsed JSON event dictionary.

    Returns:
        ``"copilot"`` or ``"claude-code"``.

    Raises:
        ValueError: If the format cannot be determined.
    """
    if event.get("type") in SKIP_EVENT_TYPES:
        return "claude-code"
    if "data" in event:
        return "copilot"
    if "message" in event:
        return "claude-code"
    raise ValueError(f"Unable to detect format from event keys: {sorted(event.keys())}")


def parse_copilot_event(event: dict[str, Any]) -> str | None:
    """
    Parse a single Copilot-format event into a chat string.

    Args:
        event: A Copilot event dictionary.

    Returns:
        A formatted string for user/assistant messages, or ``None`` for other event types.
    """
    evt_type = event.get("type")
    data = event.get("data", {})
    timestamp = event.get("timestamp")

    if evt_type == "user.message":
        content = data.get("content", "")
        return f"User ({timestamp}): {content}"

    if evt_type == "assistant.message":
        content = data.get("content", "")
        tool_calls = data.get("toolRequests", [])
        if tool_calls:
            tools_str = ", ".join(t.get("name") for t in tool_calls)
            content += f"\n[Tool Calls: {tools_str}]"
        if content.strip():
            return f"Assistant ({timestamp}): {content}"

    return None


def parse_claude_code_event(event: dict[str, Any]) -> str | None:
    """
    Parse a single Claude Code-format event into a chat string.

    Args:
        event: A Claude Code event dictionary.

    Returns:
        A formatted string for user/assistant messages, or ``None`` for skipped event types.
    """
    if event.get("type") in SKIP_EVENT_TYPES:
        return None
    if event.get("isMeta"):
        return None

    message = event.get("message", {})
    content = message.get("content")
    timestamp = event.get("timestamp")
    role = message.get("role", event.get("type", ""))

    text_parts: list[str] = []
    tool_names: list[str] = []

    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        has_only_tool_result = True
        for block in content:
            block_type = block.get("type")
            if block_type == "thinking":
                continue
            if block_type == "tool_result":
                continue
            has_only_tool_result = False
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "tool_use":
                tool_names.append(block.get("name", ""))

        if has_only_tool_result and not text_parts and not tool_names:
            return None

    text = " ".join(text_parts) if text_parts else ""

    if role == "user" and text:
        return f"User ({timestamp}): {text}"

    if role == "assistant":
        result = f"Assistant ({timestamp}): {text}"
        if tool_names:
            result += f"\n[Tool Calls: {', '.join(tool_names)}]"
        return result

    if not text and not tool_names:
        return None

    return None


def get_client() -> Any:
    """
    Initializes and returns a ChromaDB HTTP client.

    Returns:
        chromadb.HttpClient: The instantiated ChromaDB client.

    Raises:
        SystemExit: If the connection to ChromaDB fails.
    """
    host = os.environ.get("CHROMADB_HOST", "localhost")
    port = int(os.environ.get("CHROMADB_PORT", "8000"))
    try:
        return chromadb.HttpClient(host=host, port=port)
    except Exception as e:
        print(f"Error connecting to ChromaDB: {e}")
        sys.exit(1)


if __name__ == "__main__":
    defopt.run(import_chat)
