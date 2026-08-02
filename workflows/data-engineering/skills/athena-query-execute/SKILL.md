---
name: athena-query-execute
description: An orchestrator orchestrating AWS Athena SQL querying and pagination downloading for standard analytics exploration. Use this skill whenever the user asks to "run", "execute", "download", or "query" table data using AWS Athena.
---

# Athena Query Execute

An orchestrator orchestrating AWS Athena SQL querying and pagination downloading for standard analytics exploration.

## Purpose

Use this skill when the user asks to "run", "execute", or "query" table data using AWS Athena. This script automatically handles caching results into standard workspaces, dynamically setting formatted names, and chunking via pagination.

## Context Generation

You MUST generate a short, hyphenated, human-readable title that reflects the business context of the query (e.g., `user-cohorts`, `funnel-analysis`).
You MUST pass this as the `--context` argument to the script. The script will securely append a timestamp or hash so that outputs aren't overwritten and the User can comfortably identify localized results later.

## Pre-flight Authentication

Before executing any AWS-dependent command, you MUST invoke the `aws-vault-auth`
skill to fetch temporary STS credentials and inject them into the Docker
command.

**Lazy Auth Enforcement**: If the script returns `ExpiredToken` or
`AccessDenied`, re-invoke `aws-vault-auth` to refresh credentials and retry.

## Scratch Bucket Configuration

Athena writes every result set to an S3 scratch bucket. The bucket is
account-specific and has no default: export `ATHENA_SCRATCH_BUCKET` (in `.envrc`
or `.env`) or pass `--bucket` per invocation. The script exits with an
explanatory error when neither is set.

## Usage

You must execute the script in the isolated Docker container using the task framework or direct container execution:

```bash
# Wait for the results and download sequentially
docker compose run --rm python-cli python workflows/data-engineering/skills/athena-query-execute/scripts/athena_query_execute.py "SELECT * FROM my_table LIMIT 10" --context "short-readable-title"

# Output as Parquet instead of CSV
docker compose run --rm python-cli python workflows/data-engineering/skills/athena-query-execute/scripts/athena_query_execute.py "SELECT * FROM my_table LIMIT 10" --context "short-readable-title" --format parquet

# Async Mode (Do not wait)
docker compose run --rm python-cli python workflows/data-engineering/skills/athena-query-execute/scripts/athena_query_execute.py "SELECT * FROM my_table LIMIT 10" --context "short-readable-title" --no-wait
```

## Interactive Pagination

1. If the user indicates to pull multiple pages or the query results in multiple pages being available, the script will output the first page (or max_pages) to `tmp/athena/<context>/page-1.csv`.
2. Do NOT blindly fetch all pages if it's deeply paginated. Use `vscode_askQuestions` to interactively present a confirmation modal:
   - Header: "Next Page"
   - Prompt: "Page N downloaded. Would you like to fetch the next page?"
   - Options: "Yes", "No"
3. If they select No, terminate the loop.

**Headless mode** (`CI=true` or explicit pipeline signal): Do NOT prompt for
pagination confirmation. Fetch only the first page (or up to `max_pages` if
specified) and stop. Log the total available pages in the output so the caller
can request additional pages in a subsequent invocation if needed.

## Async Checking Instructions

If you execute the query using `--no-wait`, the script will immediately output an `QueryExecutionId` rather than actual query results. You MUST explicitly provide the user with an exact message string they can use to re-trigger you later to check the status:

> "The query has been dispatched and is currently running asynchronously. When you are ready to check the results, please prompt me with: `Check on the execution status for athena query <QueryExecutionId>`."
