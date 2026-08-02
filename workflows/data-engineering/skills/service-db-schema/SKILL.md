---
name: service-db-schema
description: Reconstruct canonical schema from migration files and infra version for an application service database (e.g. MySQL, Postgres). If the user just asks "Show me the schema of table ABC", you must ASK the user clarifying questions to correctly route the request to the right system (e.g. "Is table ABC in the Datalake/Glue, in Redshift, or a service database?").
---

# Schema Reconstruction

Use this skill to generate a canonical `current_schema.sql` for a service by replaying its migrations against a Dockerized database matching its RDS version.

## Prerequisites

- **Service Name**: The name of the service (e.g., `writer-labels`).
- **Repositories**:
  - `repos/<service-name>` must be checked out. If the service lives inside a
    monorepo instead, pass `--service-path <path-to-service>`.
  - Optionally, a Terraform checkout for RDS version detection — name it via
    `--infra-dir` or `$BROWNFIELD_INFRA_REPO` (a bare name is resolved under
    `repos/`). When unset, version detection is skipped and MySQL 8.0 is used.

## Workflow

### 1. Execution

Run the reconstruction script. This script handles:

- locating migration files
- determining RDS version from Terraform
- mapping to MySQL version
- starting a Docker container
- running Atlas to generate the schema

```bash
docker compose run --rm python-cli python3 workflows/data-engineering/skills/service-db-schema/scripts/get_service_db_schema.py <SERVICE_NAME> --infra-dir <INFRA_REPO>
```

### 2. Verification

Check if the schema file was generated:

```bash
ls -l repos/<SERVICE_NAME>/current_schema.sql
```

### 3. Review

Briefly inspect the generated schema to ensure it looks correct (e.g., contains expected tables).

```bash
head -n 20 repos/<SERVICE_NAME>/current_schema.sql
```

### 4. Error Handling and Verification (No Faking Protocol)

**CRITICAL DIRECTIVE (No Faking Protocol)**: Never fabricate or guess schemas or migrations if the script fails or if the directory is missing.

- If the script fails, do not attempt to guess, summarize, or create dummy outputs to pass checks. You MUST report the failure correctly by returning the EXACT raw error message from the script.
