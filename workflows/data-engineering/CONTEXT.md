# data-engineering

This domain contains the core Data Engineering workflows.

## Available Skills

- [athena-query-analysis](skills/athena-query-analysis/SKILL.md): An advanced, expert-level skill that performs a rigorous static and architectural review of AWS Athena SQL queries BEFORE they are run, ensuring proper partition optimization, valid JOIN strategies, and identifying missing schemas.
- [athena-query-execute](skills/athena-query-execute/SKILL.md): An orchestrator orchestrating AWS Athena SQL querying and pagination downloading for standard analytics exploration. Use this skill whenever the user asks to "run", "execute", "download", or "query" table data using AWS Athena.
- [dynamodb-table-schema](skills/dynamodb-table-schema/SKILL.md): Retrieve the schema, indexes, and metadata for an AWS DynamoDB table. Make sure to use this skill whenever the user asks for the structure, partition keys, sort keys, or global/local secondary indexes of a DynamoDB table.
- [glue-catalog-schema](skills/glue-catalog-schema/SKILL.md): Retrieve the schema for Datalake (S3, parquet) tables mapped in AWS Glue Catalog. Make sure to use this skill whenever the user asks for the schema, structure, or columns of a datalake table, parquet table, or Glue table. If the user just asks "Show me the schema of table ABC", you must ASK the user clarifying questions to correctly route the request to the right system (e.g. "Is table ABC in the Datalake/Glue, in Redshift, or a service database?").
- [glue-find-tables](skills/glue-find-tables/SKILL.md): Search for tables in AWS Glue Catalog by database, table name, or column name. Use this skill when the user asks "where is table X located", "which tables have columns Y or Z", or similar queries to find data locations.
- [redshift-query-analysis](skills/redshift-query-analysis/SKILL.md): An advanced, expert-level skill that statically analyzes and optimizes AWS Redshift queries based on schemas, distribution keys, and sort keys.
- [redshift-table-schema](skills/redshift-table-schema/SKILL.md): Retrieve the schema for tables stored in LIVE AWS Redshift. This is the DEFAULT skill for any Redshift schema request string. If your Boto3 AWS query fails due to Permission Denied/AccessDenied errors, you MUST surface the exact error to the user rather than guessing a schema.
- [service-db-schema](skills/service-db-schema/SKILL.md): Reconstruct canonical schema from migration files and infra version for an application service database (e.g. MySQL, Postgres). If the user just asks "Show me the schema of table ABC", you must ASK the user clarifying questions to correctly route the request to the right system (e.g. "Is table ABC in the Datalake/Glue, in Redshift, or a service database?").
