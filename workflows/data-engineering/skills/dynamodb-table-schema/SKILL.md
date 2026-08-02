---
name: dynamodb-table-schema
description: Retrieve the schema, indexes, and metadata for an AWS DynamoDB table. Make sure to use this skill whenever the user asks for the structure, partition keys, sort keys, or global/local secondary indexes of a DynamoDB table.
---

# AWS DynamoDB Table Schema Retrieval

Use this skill to fetch the exact schema definition, key structure, and index information for a table stored in AWS DynamoDB.

## Prerequisites

- **Environment Isolation**: You MUST NEVER execute scripts or tools directly on the host (e.g., do not run `python ...`). You MUST use the [docker-compose.yml](../../../../docker-compose.yml) services.
- **Python Script**: [scripts/get_dynamodb_table_schema.py](../../../../workflows/data-engineering/skills/dynamodb-table-schema/scripts/get_dynamodb_table_schema.py) must be present.
- **Delegation Protocol**: The Orchestrator MUST NOT run terminal commands directly. You MUST use a subagent.

## Workflow

### 1. Preparation and Authentication

#### Pre-flight Authentication

You MUST NOT use `aws-vault exec` wrappers directly anymore. You must first use the `aws-vault-auth` skill to fetch the temporary session tokens, and then prepend those `export AWS_...` strings to any `docker` or `docker compose` command, explicitly passing them into the container.

**Lazy Auth Enforcement**: You must catch `ExpiredToken` or `AccessDenied` errors returned by subagents or scripts and gracefully re-invoke the `aws-vault-auth` skill to refresh credentials and retry the failed command.

## 2. Execution via Delegation

You MUST fetch the table name from the user or the context. If the user didn't specify the table name, prompt them before proceeding.

**CRITICAL DIRECTIVE (Delegation Protocol)**: The Orchestrator MUST NOT run terminal commands directly in a multi-agent team environment. You MUST delegate the execution by spawning a subagent via your platform's native mechanism to run the exact command required based on the environment.

**Standard Execution (AWS / Production):**

```bash
<FETCHED_EXPORT_STRINGS>; docker compose run -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN --rm python-cli python3 workflows/data-engineering/skills/dynamodb-table-schema/scripts/get_dynamodb_table_schema.py --table <TABLE_NAME>
```

 *(Default format is `markdown` if not specified. Allowed formats: `markdown`, `json`)*

### 3. Error Handling and Verification (No Faking Protocol)

**CRITICAL DIRECTIVE (No Faking Protocol)**: Never fabricate or guess table schemas, partition keys, or indexes if the API call fails or if the table is missing.

- The delegated agent MUST surface the exact AWS error (e.g., `ResourceNotFoundException`, `AccessDeniedException`) back to the Orchestrator for root cause diagnosis.
- If the table does not exist or the script fails, do not attempt to guess or create dummy schema outputs to pass checks. You MUST report the failure correctly by returning the EXACT raw error message from the script.
