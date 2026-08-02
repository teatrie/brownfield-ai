---
name: redshift-query-analysis
description: An advanced, expert-level skill that statically analyzes and optimizes AWS Redshift queries based on schemas, distribution keys, and sort keys.
---

# 🔴 Redshift Query Analysis Protocol

When requested to analyze or optimize an AWS Redshift SQL query, you MUST follow this strict multi-phase methodology. Your goal is to maximize performance by leveraging Redshift's distributed architecture.

**NOTE:** Running `EXPLAIN <query>` (without `ANALYZE`) in Redshift only queries the leader node planner. It is safe, does not execute the data scans, and does not incur compute billing.

## Pre-flight Authentication

Before invoking any AWS-dependent skill (e.g., `redshift-table-schema`), you
MUST ensure credentials are available by invoking the `aws-vault-auth` skill. If
any downstream skill returns `ExpiredToken` or `AccessDenied`, re-invoke
`aws-vault-auth` to refresh credentials and retry.

## Phase 1: Schema & Environment Discovery

You cannot analyze a Redshift query accurately without understanding its data distribution and local ordering.

1. Automatically invoke the `redshift-table-schema` skill for every table referenced in the `FROM` or `JOIN` clauses.
2. Note the **Data Types**, specifically looking for potential casting incompatibilities between joined columns.
3. Explicitly identify the **Distribution Key (DISTKEY)** and **Sort Key (SORTKEY)** for all tables.

## Phase 2: Static Heuristic Check (Strict Rules)

Review the provided query against these heuristics based on the discovered schema:

1. **Distribution Alignment (CRITICAL for JOINs):**
   - Are the tables joined on their `DISTKEY`?
   - If large tables are joined on columns other than their `DISTKEY`, it causes expensive network redistributions (`DS_BCAST_INNER` or `DS_DIST_BOTH`). Flag this immediately.
2. **Sort Key Utilization (Zone Maps):**
   - Do the `WHERE` filters or `ORDER BY` clauses use the table's `SORTKEY`?
   - If range queries and filters skip the `SORTKEY`, Redshift cannot use Zone Maps to skip blocks, resulting in full table scans.
3. **Implicit CASTING:**
   - Are there mixed data types being compared (e.g., `VARCHAR` to `INT`)?
   - Implicit casting in join or filter predicates dynamically disables index usage and `SORTKEY` optimizations. Flag these.

## Phase 3: Physical Plan Analysis (Optional/As-Needed)

If evaluating complex queries, instruct the user to run `EXPLAIN <query>` using the AWS CLI or provide the text output. Look for:

- `DS_DIST_NONE`: Optimal. Joins happen locally.
- `DS_BCAST_INNER`: The inner table is broadcasted to all nodes. Okay if the inner table is very small.
- `DS_DIST_BOTH`: Both tables are redistributed. Very expensive. Try to align `DISTKEY` or add filters.

## Phase 4: Translation & Review

Based on findings:

1. Provide the **Critique/Review:** Bulleted points of flaws or omissions mapping to Phase 2. Highlight if a `DISTKEY` or `SORTKEY` was ignored.
2. Output the **Optimized SQL:** Rewrite the query defensively. Add standard explicit comments indicating why structures were changed.

### Example Optimized Output

```sql
-- OPTIMIZED REDSHIFT QUERY
SELECT 
    a.event_id, 
    b.user_name
FROM 
    analytics.events a
JOIN 
    analytics.users b 
-- [Optimization] Joined on user_id which is the established DISTKEY for both tables to enable DS_DIST_NONE
  ON a.user_id = b.user_id
WHERE 
-- [Optimization] Added filter on event_date which is the SORTKEY to utilize Zone Maps
    a.event_date >= '2023-10-01'
-- [Optimization] Quoted the integer lookup to match partition schema typing avoiding implicit casts
    AND b.status = 'active'
ORDER BY 
    a.timestamp DESC
LIMIT 1000;
```
