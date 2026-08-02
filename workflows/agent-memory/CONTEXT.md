# agent-memory

This domain manages the agent long-term memory.

## Available Skills

- [knowledge-checkpoint](skills/knowledge-checkpoint/SKILL.md): Checkpoint the current conversation history into the knowledge base. Triggered by phrases like "knowledge checkpoint", "chat history save", "chat log save", "save conversation", "persist session", "checkpoint", "save chat", or "save history".
- [knowledge-base](skills/knowledge-base/SKILL.md): Manage and interact with the knowledge base by adding, querying, and listing documents. Triggered by phrases like "knowledge add", "knowledge query", "knowledge search", "knowledge list", "recall knowledge", "chat history search", "chat log query", "memory list", "memory add", "memory query", "recall", or "remember".
- [knowledge-export](skills/knowledge-export/SKILL.md): Export knowledge base documents as a single text file. Triggered by phrases like "knowledge export", "export knowledge", "chat log export", "recall export", "memory export", "recall memory", or "export memories".
- [knowledge-import](skills/knowledge-import/SKILL.md): Import knowledge base collections from a text file, with optional metadata tagging. Triggered by phrases like "knowledge import", "import knowledge", "chat log import", "recall import", "restore knowledge", "memory import", "import memory", or "restore memories".
- [execution-ledger](skills/execution-ledger/SKILL.md): Checkpoint and query
execution artifacts (plans, design decisions, gate verdicts, test results)
for epic resumability and audit trails.
