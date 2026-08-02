"""
Athena Query Exection tool.

This module provides a CLI and programmatic interface to safely execute, poll, and download
AWS Athena query results into user-isolated sandboxes. Result formats include CSV and Parquet.
"""

import csv
import os
import sys
import time
from pathlib import Path

import defopt

from brownfield_ai.services.aws import get_client
from brownfield_ai.system.context import get_current_user, get_workspace_root

WORKSPACE_ROOT = str(get_workspace_root())

#: Environment variable holding the S3 scratch bucket Athena writes results to.
#: There is no default — the bucket is account-specific and must be supplied.
SCRATCH_BUCKET_ENV = "ATHENA_SCRATCH_BUCKET"


def resolve_scratch_bucket(bucket: str | None = None) -> str:
    """
    Resolve the S3 scratch bucket name from the CLI argument or the environment.

    Args:
        bucket: Explicit bucket name, or None to read the environment.

    Returns:
        The bucket name, without an ``s3://`` scheme prefix.
    """
    resolved = bucket or os.environ.get(SCRATCH_BUCKET_ENV, "")
    if not resolved:
        print(f"Error: no S3 scratch bucket configured. Pass --bucket or set {SCRATCH_BUCKET_ENV}.")
        sys.exit(1)
    return resolved.removeprefix("s3://").rstrip("/")


def execute_query(
    query: str,
    *,
    context: str,
    bucket: str | None = None,
    format_: str = "csv",
    no_wait: bool = False,
    max_pages: int = 10,
    page_size: int = 1000,
) -> None:
    """Execute Athena query."""
    user = get_current_user()
    timestamp = int(time.time())
    context_folder = f"{context}-{timestamp}"
    bucket = resolve_scratch_bucket(bucket)
    s3_prefix = f"brownfield-ai/{user}/{context_folder}"
    output_location = f"s3://{bucket}/{s3_prefix}/"

    athena = get_client("athena")

    final_query = query
    if format_.lower() == "parquet":
        trimmed_query = query.strip()
        if trimmed_query.endswith(";"):
            trimmed_query = trimmed_query[:-1]
        final_query = f"UNLOAD ({trimmed_query}) TO '{output_location}' WITH (format = 'PARQUET')"

    res = athena.start_query_execution(QueryString=final_query, ResultConfiguration={"OutputLocation": output_location})

    execution_id = res["QueryExecutionId"]
    print(f"Started execution: {execution_id}")

    if no_wait:
        _check_status_prompt(execution_id)
        return

    print("Waiting for completion...")
    state = "RUNNING"
    while state in ["QUEUED", "RUNNING"]:
        time.sleep(1)  # wait less so tests pass quicker if real time or not mocked time
        status_res = athena.get_query_execution(QueryExecutionId=execution_id)
        state = status_res["QueryExecution"]["Status"]["State"]
        if state == "FAILED":
            reason = status_res["QueryExecution"]["Status"].get("StateChangeReason", "Unknown")
            print(f"Query failed: {reason}")
            sys.exit(1)
        elif state == "CANCELLED":
            print("Query cancelled.")
            sys.exit(1)

    print(f"Query {state}.")

    out_dir = Path(WORKSPACE_ROOT) / "tmp" / "athena" / context_folder
    out_dir.mkdir(parents=True, exist_ok=True)

    if format_.lower() == "parquet":
        print("Downloading Parquet files from S3...")
        s3 = get_client("s3")
        paginator = s3.get_paginator("list_objects_v2")
        page_num = 1
        for s3_page in paginator.paginate(Bucket=bucket, Prefix=f"{s3_prefix}/"):
            for obj in s3_page.get("Contents", []):
                if obj["Key"].endswith(".parquet"):
                    target_file = out_dir / f"page-{page_num}.parquet"
                    print(f"Downloading {target_file.name}...")
                    s3.download_file(bucket, obj["Key"], str(target_file))
                    page_num += 1
                    if page_num > max_pages:
                        break
            if page_num > max_pages:
                break
    else:
        print("Downloading CSV results...")
        next_token = None
        page_num = 1
        while page_num <= max_pages:
            kwargs = {"QueryExecutionId": execution_id, "MaxResults": page_size}
            if next_token:
                kwargs["NextToken"] = next_token

            results = athena.get_query_results(**kwargs)
            rows = results.get("ResultSet", {}).get("Rows", [])

            target_file = out_dir / f"page-{page_num}.csv"
            print(f"Writing {target_file.name}...")
            with open(target_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                for row in rows:
                    cols = [col.get("VarCharValue", "") for col in row.get("Data", [])]
                    writer.writerow(cols)

            next_token = results.get("NextToken")
            if not next_token:
                break
            page_num += 1

    print(f"Results saved to {out_dir}")


def _check_status_prompt(execution_id: str) -> None:
    print("\nThe query has been dispatched and is currently running asynchronously.")
    print("When you are ready to check the results, please prompt me ")
    print(f"with: `Check on the execution status for athena query {execution_id}`.")


def main(
    query: str,
    *,
    context: str,
    bucket: str | None = None,
    format_: str = "csv",
    no_wait: bool = False,
    max_pages: int = 10,
    page_size: int = 1000,
) -> None:
    """
    CLI entry point for Athena Query Execution tool.

    Args:
        query: SQL Query to execute
        context: Human-readable context prefix
        bucket: S3 scratch bucket for results (defaults to $ATHENA_SCRATCH_BUCKET)
        format: Output format (csv or parquet)
        no_wait: Do not wait for results
        max_pages: Maximum pages to download
        page_size: Results per page
    """
    execute_query(
        query=query,
        context=context,
        bucket=bucket,
        format_=format_,
        no_wait=no_wait,
        max_pages=max_pages,
        page_size=page_size,
    )


if __name__ == "__main__":
    defopt.run(main)
