---
name: redshift-table-schema
description: Retrieve the schema for tables stored in LIVE AWS Redshift. This is the DEFAULT skill for any Redshift schema request string. If your Boto3 AWS query fails due to Permission Denied/AccessDenied errors, you MUST surface the exact error to the user rather than guessing a schema.
---

# AWS Redshift Table Schema Retrieval

Use this skill to fetch the exact schema definition for a table stored in an AWS Redshift cluster.

## Prerequisites

- **Environment Isolation**: You MUST NEVER execute scripts or tools directly on the host (e.g., do not run `python ...`). You MUST use the [docker-compose.yml](../../../../docker-compose.yml) services.
- **Python Script**: [scripts/get_redshift_table_schema.py](../../../../workflows/data-engineering/skills/redshift-table-schema/scripts/get_redshift_table_schema.py) must be present.
- **Delegation Protocol**: The Orchestrator MUST NOT run terminal commands directly. You MUST use a subagent.

## Workflow

### 1. Preparation and Authentication

#### Pre-flight Authentication

You MUST NOT use `aws-vault exec` wrappers directly anymore. You must first use the `aws-vault-auth` skill to fetch the temporary session tokens, and then prepend those `export AWS_...` strings to any `docker` or `docker compose` command, explicitly passing them into the container.

**Lazy Auth Enforcement**: You must catch `ExpiredToken` or `AccessDenied` errors returned by subagents or scripts and gracefully re-invoke the `aws-vault-auth` skill to refresh credentials and retry the failed command.

### 2. Execution via Delegation

You MUST fetch the cluster identifier, database name, database user, and table name
from the user or the context. There are no defaults — if any of them is missing, ASK
the user rather than guessing. The cluster, workgroup, and database user fall back to
`$AWS_REDSHIFT_CLUSTER`, `$AWS_REDSHIFT_WORKGROUP`, and `$AWS_REDSHIFT_DB_USER`
respectively when the flag is omitted.

You can optionally support different output formats (`markdown`, `json`, `raw`, `mermaid`, `ddl`).

**CRITICAL DIRECTIVE (Delegation Protocol)**: The Orchestrator MUST NOT run terminal commands directly in a multi-agent team environment. You MUST delegate the execution by spawning a subagent via your platform's native mechanism to run the exact command required based on the environment.

**Standard Execution (AWS):**

```bash
<FETCHED_EXPORT_STRINGS>; docker compose run -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN --rm python-cli python3 workflows/data-engineering/skills/redshift-table-schema/scripts/get_redshift_table_schema.py --cluster-identifier <CLUSTER_ID> --database <DATABASE_NAME> --db-user <DB_USER> --table <TABLE_NAME> --output-format <FORMAT>
```

*(Default format is `markdown` if not specified. Allowed formats: `markdown`, `json`, `raw`, `mermaid`, `ddl`)*

### 3. Error Handling and Verification (No Faking Protocol)

**CRITICAL DIRECTIVE (No Faking)**: Never fabricate or guess schemas if the API call fails or if the table is missing.

- The delegated agent MUST surface the exact AWS error (e.g., `ClusterNotFound`, `TableNotFound`) back to the Orchestrator for root cause diagnosis.
- If the table does not exist or the script fails, do not attempt to guess or create dummy schema outputs to pass checks. You MUST report the failure correctly by returning the EXACT raw error message from the script.
