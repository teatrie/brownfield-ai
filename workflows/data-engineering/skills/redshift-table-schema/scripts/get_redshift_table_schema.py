import json
import os
import re
import sys
import time

import defopt
from botocore.exceptions import ClientError

from brownfield_ai.services import aws

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def get_redshift_schema(
    cluster_identifier: str, workgroup_name: str, database: str, db_user: str, secret_arn: str, schema: str, table: str
):
    """
    Fetch schema for a Redshift table using the redshift-data API.

    Args:
        cluster_identifier: The Redshift cluster identifier for provisioned clusters.
        workgroup_name: The Redshift Serverless workgroup name.
        database: The target database name.
        db_user: The database user to run the query as (for provisioned).
        secret_arn: The Secrets Manager ARN for authentication.
        schema: The database schema containing the table.
        table: The name of the table to inspect.

    Returns:
        list[dict]: A list of dictionaries representing the columns and their definitions.
    """
    client = aws.get_client("redshift-data")

    if not _IDENTIFIER_RE.match(schema) or not _IDENTIFIER_RE.match(table):
        raise ValueError(f"Invalid identifier: schema={schema!r}, table={table!r}")
    query = (
        "SELECT column_name, data_type, character_maximum_length "
        "FROM information_schema.columns "
        f"WHERE table_schema = '{schema}' AND table_name = '{table}'"
    )

    try:
        kwargs = {
            "Database": database,
            "Sql": query,
        }
        if cluster_identifier:
            kwargs["ClusterIdentifier"] = cluster_identifier
        if workgroup_name:
            kwargs["WorkgroupName"] = workgroup_name
        if db_user:
            kwargs["DbUser"] = db_user
        if secret_arn:
            kwargs["SecretArn"] = secret_arn

        response = client.execute_statement(**kwargs)
        statement_id = response["Id"]

        while True:
            desc = client.describe_statement(Id=statement_id)
            status = desc["Status"]
            if status == "FINISHED":
                break
            elif status == "STARTED" and os.environ.get("AWS_ENDPOINT_URL"):
                # LocalStack / Moto usually stays in STARTED state and allows immediate get_statement_result
                break
            elif status in ("FAILED", "ABORTED"):
                print(f"Query {status}: {desc.get('Error', 'Unknown error')}", file=sys.stderr)
                sys.exit(1)
            time.sleep(1)

        result_resp = client.get_statement_result(Id=statement_id)
        records = result_resp.get("Records", [])
        columns = []
        for row in records:
            column_name = row[0].get("stringValue", "")
            data_type = row[1].get("stringValue", "")
            max_len = row[2].get("longValue", None)

            columns.append({"column_name": column_name, "data_type": data_type, "character_maximum_length": max_len})

        return columns

    except ClientError as e:
        print(f"AWS Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def to_markdown(columns):
    lines = ["| Column Name | Data Type | Max Length |", "| --- | --- | --- |"]
    for col in columns:
        max_len = col.get("character_maximum_length")
        max_len_str = str(max_len) if max_len is not None else ""
        lines.append(f"| {col['column_name']} | {col['data_type']} | {max_len_str} |")
    return "\n".join(lines)


def to_json(columns):
    return json.dumps({"columns": columns}, indent=2)


def to_raw(columns):
    lines = ["Columns:"]
    for col in columns:
        max_len = col.get("character_maximum_length")
        max_len_str = f" ({max_len})" if max_len is not None else ""
        lines.append(f"  {col['column_name']} ({col['data_type']}){max_len_str}")
    return "\n".join(lines)


def to_mermaid(columns, table_name):
    lines = ["```mermaid", "erDiagram", f"    {table_name} {{"]
    for col in columns:
        lines.append(f"        {col['data_type']} {col['column_name']}")
    lines.append("    }")
    lines.append("```")
    return "\n".join(lines)


def to_ddl(columns, table_name, schema="public"):
    lines = [f"CREATE TABLE {schema}.{table_name} ("]
    for i, col in enumerate(columns):
        col_name = col.get("column_name", "")
        data_type = col.get("data_type", "")
        max_len = col.get("character_maximum_length")

        # Append length if relevant
        max_len_str = f"({max_len})" if max_len else ""

        line = f"  {col_name} {data_type}{max_len_str}"
        if i < len(columns) - 1:
            line += ","
        lines.append(line)
    lines.append(");")
    return "\n".join(lines)


def main(
    *,
    table: str,
    database: str = "public",
    cluster_identifier: str | None = None,
    workgroup_name: str | None = None,
    db_user: str | None = None,
    secret_arn: str | None = None,
    schema: str = "public",
    output_format: str = "markdown",
) -> None:
    """
    Fetch table schema from AWS Redshift.

    Args:
        table: Table name
        database: Redshift database name
        cluster_identifier: Redshift cluster identifier (defaults to $AWS_REDSHIFT_CLUSTER)
        workgroup_name: Redshift Serverless workgroup name (defaults to $AWS_REDSHIFT_WORKGROUP)
        db_user: Redshift database user (defaults to $AWS_REDSHIFT_DB_USER)
        secret_arn: Secret ARN for database authentication
        schema: Database schema name
        output_format: Output format (markdown, json, raw, mermaid, ddl)
    """
    if db_user is None:
        db_user = os.environ.get("AWS_REDSHIFT_DB_USER")
    if cluster_identifier is None:
        cluster_identifier = os.environ.get("AWS_REDSHIFT_CLUSTER")
    if workgroup_name is None:
        workgroup_name = os.environ.get("AWS_REDSHIFT_WORKGROUP")

    # Require either cluster or workgroup
    if not cluster_identifier and not workgroup_name:
        print("Error: Must provide either --cluster-identifier or --workgroup-name")
        sys.exit(1)

    # Require either db-user or secret-arn for auth
    if not db_user and not secret_arn:
        print("Error: Must provide either --db-user or --secret-arn for authentication")
        sys.exit(1)

    columns = get_redshift_schema(
        cluster_identifier=cluster_identifier or "",
        workgroup_name=workgroup_name or "",
        database=database,
        db_user=db_user or "",
        secret_arn=secret_arn or "",
        schema=schema,
        table=table,
    )

    if output_format == "markdown":
        print(to_markdown(columns))
    elif output_format == "json":
        print(to_json(columns))
    elif output_format == "raw":
        print(to_raw(columns))
    elif output_format == "mermaid":
        print(to_mermaid(columns, table))
    elif output_format == "ddl":
        print(to_ddl(columns, table, schema))


if __name__ == "__main__":
    defopt.run(main)
