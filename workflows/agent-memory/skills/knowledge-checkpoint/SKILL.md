---
name: knowledge-checkpoint
description: Checkpoint the current conversation history into the knowledge base. Triggered by phrases like "knowledge checkpoint", "chat history save", "chat log save", "save conversation", "persist session", "checkpoint", "save chat", or "save history".
---

# 💾 Checkpoint Chat History

I will import the current session's conversation history into the knowledge base for long-term memory.

## Steps

0. **Start ChromaDB**: Ensure the chromadb service is running.

    ```bash
    task chromadb:start
    ```

1. **Locate Log**: Identify the current session's conversation log.
   The log location varies by platform:
   - **Claude Code**: `~/.claude/projects/<project-path>/<session-uuid>.jsonl`
   - **Gemini CLI**: `~/.gemini/history/` (check platform docs for exact path)
   - **Copilot**: `~/.copilot/session-state/<UUID>/workflows/agent-memory/skills/knowledge-checkpoint/scripts/events.jsonl`

   If the log path cannot be determined:
   - **Interactive**: Ask the user to provide it.
   - **Headless** (`CI=true`): Fail-closed. Do not guess or skip — checkpoint
     a `step_result` artifact with `verdict: fail` and
     `reason: "log path undetermined in headless mode"`, then halt.

   > The import script auto-detects the input format (Copilot or Claude Code). No manual format flag is needed.

2. **Stage**: Copy the log file to `tmp/<CURRENT_SESSION_ID>/chat_history.jsonl` to make it accessible to the Docker container.

    ```bash
    mkdir -p tmp/<CURRENT_SESSION_ID>
    cp <SESSION_LOG_PATH> tmp/<CURRENT_SESSION_ID>/chat_history.jsonl
    ```

3. **Import**: Run the import script via the task alias.

    ```bash
    task chromadb:checkpoint -- tmp/<CURRENT_SESSION_ID>/chat_history.jsonl
    ```

4. **Cleanup**: Remove the temporary file.

    ```bash

    rm -rf tmp/<CURRENT_SESSION_ID>
    ```

## Completion

The current conversation has been indexed in the `chat_history` collection.
