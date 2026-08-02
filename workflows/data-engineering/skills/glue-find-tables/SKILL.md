---
name: glue-find-tables
description: Search for tables in AWS Glue Catalog by database, table name, or column name. Use this skill when the user asks "where is table X located", "which tables have columns Y or Z", or similar queries to find data locations.
---

# AWS Glue Catalog Table Search

Use this skill to search for tables and their storage text location across the AWS Glue Catalog using regex patterns.

## Prerequisites

- **Environment Isolation**: You MUST NEVER execute scripts or tools directly on the host (e.g., do not run `python ...`). You MUST use the [docker-compose.yml](../../../../docker-compose.yml) services.
- **Python Script**: [scripts/find_glue_tables.py](../../../../workflows/data-engineering/skills/glue-find-tables/scripts/find_glue_tables.py) must be present.
- **Delegation Protocol**: The Orchestrator MUST NOT run terminal commands directly. You MUST use a subagent.

## Workflow

### 1. Preparation and Authentication

#### Pre-flight Authentication

You MUST NOT use `aws-vault exec` wrappers directly anymore. You must first use the `aws-vault-auth` skill to fetch the temporary session tokens, and then prepend those `export AWS_...` strings to any `docker` or `docker compose` command, explicitly passing them into the container.

**Lazy Auth Enforcement**: You must catch `ExpiredToken` or `AccessDenied` errors returned by subagents or scripts and gracefully re-invoke the `aws-vault-auth` skill to refresh credentials and retry the failed command.

## 2. Execution via Delegation

You must construct the search command based on the user's criteria. Available CLI flags are:

- `--database-patterns`: Regex patterns to filter databases.
- `--table-patterns`: Regex patterns to filter tables.
- `--column-patterns`: Regex patterns to filter columns (e.g., to find which tables contain a specific column).
- `--limit`: Max number of tables to return. **Context Awareness**: If agents are fetching just 1 generic table location, advise them to pass `--limit 1` for maximum speed.
- `--output-format`: Output format (`markdown`, `json`, `csv`). Default is `markdown`.

**CRITICAL DIRECTIVE (Delegation Protocol)**: The Orchestrator MUST NOT run terminal commands directly in a multi-agent team environment. You MUST delegate the execution by spawning a subagent via your platform's native mechanism to run the exact command required based on the environment.

**Standard Execution (AWS):**

```bash
<FETCHED_EXPORT_STRINGS>; docker compose run -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN --rm python-cli python3 workflows/data-engineering/skills/glue-find-tables/scripts/find_glue_tables.py [FLAGS]
```

### 3. Error Handling and Verification (No Faking Protocol)

**CRITICAL DIRECTIVE (No Faking & Verification)**: Never fabricate or guess locations or schemas if the API call fails or if the table is missing.

- The delegated agent MUST surface the exact AWS error back to the Orchestrator for root cause diagnosis. Never swallow error logs.
- If the table does not exist or the script fails, do not attempt to guess or create dummy outputs. You MUST report the failure correctly by returning the EXACT raw error message from the script.
- **Verification Sub-tasks**: At the end of every execution step/phase, append verification sub-tasks to ensure the output aligns with the requested parameters and no simulated/fake data was returned.
