---
name: todo
description: >-
  Capture, list, and triage orphaned TODOs across workspaces. Triggered
  by: /todo, "capture a todo", "add a todo", "todo list", "todo triage".
---

# TODO Capture & Triage

## Subcommands

### Capture: `/todo <text>`

1. Parse title from arguments.
2. Auto-capture context via `_capture_context()` — runs git commands to
   capture branch, modified files, recent commits.
3. Run `detect_duplicates()` against ChromaDB. If similar TODOs found,
   warn user and ask to confirm.
4. Suggest category from `list_categories()` based on context (branch
   name, modified files). If none fits, propose a new category.
5. Suggest priority based on context.
6. Confirm with user (interactive — not headless).
7. Execute:

```bash
task todo:add -- "<title>" --description "<desc>" --notes "<notes>" \
  --category "<cat>" --priority <N>
```

### List: `/todo list`

Execute:

```bash
task todo:list -- --status open
```

Supports `--verbose`, `--status`, `--category`, `--epic-id` flags
passed through.

### Triage: `/todo triage`

1. Query top 10 open TODOs by priority:

```bash
task todo:list -- --status open --limit 10
```

1. Present to user. User selects one to promote to backlog.
1. Query ChromaDB `todos` collection for semantically related TODOs
   (use `detect_duplicates` or `task chromadb:collection -- query`).
1. Suggest grouping: "These TODOs might belong in the same epic:
   TODO-0005, TODO-0012"
1. User confirms grouping.
1. Prompt for epic ID (e.g., Jira ticket like `ACME-1234`).
1. Create epic:

```bash
task ledger:create -- --epic-id <ID> --title "<title>"
```

1. Assign each selected TODO:

```bash
task todo:assign -- <TODO_ID> --epic-id <ID>
```

### Help: `/todo help`

Display available subcommands with descriptions.

## Headless Mode

Detected via `CI=true` or explicit headless signal from the calling pipeline.

- **`list` / `help`**: No interactive gates. Proceed normally.
- **`capture`**: Auto-accept the suggested category and priority (derived
  from context). For duplicate warnings, log a warning but proceed —
  capture is additive and non-destructive. Skip final user confirmation.
- **`triage`**: **Fail-closed**. Output the open TODO list to a
  `step_result` artifact via `execution-ledger checkpoint` and halt.
  Triage requires human judgment (selection, grouping, epic assignment)
  and has no sensible automated fallback.

## Prerequisites

- ChromaDB must be running: `task chromadb:start`
- Docker must be available for `python-cli` container

## No Bulk CLI

Multi-capture is handled conversationally — the agent loops `add` calls
within a single session. No special bulk command needed.
