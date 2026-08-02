---
name: athena-query-analysis
description: An advanced, expert-level skill that performs a rigorous static and architectural review of AWS Athena SQL queries BEFORE they are run, ensuring proper partition optimization, valid JOIN strategies, and identifying missing schemas.
---

# 🔎 Athena Query Analysis Protocol

When requested to analyze or optimize an AWS Athena query, you MUST follow this strict multi-phase methodology. Act as a Staff Data Engineer guarding production infrastructure against runaway costs and full table scans.

**WARNING:** DO NOT attempt to run `EXPLAIN ANALYZE <query>`. It actually executes the SQL and can incur massive query charges if the original query is missing partition limits. Only logical `EXPLAIN` runs without execution.

## Pre-flight Authentication

Before invoking any AWS-dependent skill (e.g., `glue-catalog-schema`), you MUST
ensure credentials are available by invoking the `aws-vault-auth` skill. If any
downstream skill returns `ExpiredToken` or `AccessDenied`, re-invoke
`aws-vault-auth` to refresh credentials and retry.

## Phase 1: Schema & Environment Discovery

You cannot analyze an Athena query accurately without understanding the underlying data layout.

1. Automatically invoke the `glue-catalog-schema` skill or script for every table referenced in the `FROM` or `JOIN` clauses.
2. Note the **Data Types**, specifically checking for `bigint` vs `string` casting.
3. Explicitly identify the **Partition Keys** for all tables.
4. Note if tables are stored in Parquet/ORC versus raw JSON/CSV.

## Phase 2: Static Heuristic Check (Strict Rules)

Review the provided query against these heuristics based on the discovered schema:

1. **Partition Pruning (CRITICAL):**
   - Does the `WHERE` clause explicitly filter by the discovered partition keys?
   - If a table is partitioned by `year`, `month`, `day` but the query only says `WHERE event_type = 'login'`, it will execute a full table scan.
   - You MUST flag any query against a partitioned table missing its partition keys.
2. **Explicit CASTING vs Implicit Checks:**
   - Athena is strictly typed. If a partition key is a `string` (e.g., `year='2023'`), filtering like `WHERE year = 2023` (int) without quotes often disables partition pruning. Check if strings are properly quoted.
3. **Cross Joins / Unbounded Joins:**
   - If an `ON` clause is omitted or a `CROSS JOIN` is used, flag it.
   - If joining two massively partitioned event tables, ensure BOTH table sides of the join have partition bounds in the `WHERE` or `ON` clause.
4. **Un-Limited Aggregations on Scans:**
   - Is `ORDER BY` used without a `LIMIT` at the end of the query?
   - In distributed engines, `ORDER BY` with no limit forces all data into a single worker node memory space and causes crashes.

## Phase 3: Translation & Review

Based on findings:

1. Provide the **Critique/Review:** Bulleted points of flaws or omissions mapping to Phase 2.
2. Output the **Optimized SQL:** Rewrite the query defensively. Add standard explicit comments indicating why structures were changed.

### Example Optimized Output

```sql
-- OPTIMIZED ATHENA QUERY
SELECT 
    a.event_id, 
    b.user_name
FROM 
    datalake.events a
JOIN 
    datalake.users b 
  ON a.user_id = b.user_id
-- [Optimization] Added bounded partition filters to prevent 15TB full table scan
WHERE 
    a.year = '2023' 
    AND a.month = '10'
-- [Optimization] Quoted the integer lookup to match partition schema typing
    AND b.status = 'active'
-- [Optimization] Limit explicitly added to bounded order by
ORDER BY 
    a.timestamp DESC
LIMIT 1000;
```
