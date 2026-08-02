"""
AWS Glue Catalog Table Search Script.

This module provides functionality to search the AWS Glue Catalog for databases,
tables, and columns using various pattern matching techniques (exact, regex,
starts_with, etc.). It outputs the results in markdown, json, or csv formats.
"""

import csv
import json
import re
import sys
from typing import Literal

import defopt

from brownfield_ai.services.aws import get_client


def matches_any(value: str, patterns: list[str] | None) -> bool:
    if not patterns:
        return True
    for p in patterns:
        try:
            if re.search(p, value):
                return True
        except re.error:
            if p in value:
                return True
    return False


def main(
    *,
    database_patterns: list[str] | None = None,
    table_patterns: list[str] | None = None,
    column_patterns: list[str] | None = None,
    limit: int | None = None,
    output_format: Literal["markdown", "json", "csv"] = "markdown",
) -> None:
    """
    Search AWS Glue Catalog for databases, tables, and columns matching given patterns.

    Args:
        database_patterns: Optional list of regex patterns to filter databases.
        table_patterns: Optional list of regex patterns to filter tables.
        column_patterns: Optional list of regex patterns to filter columns.
        limit: Optional maximum number of tables to return. Stops scanning early if reached.
        output_format: Output format for the results ('markdown', 'json', or 'csv').
    """
    client = get_client("glue")
    db_paginator = client.get_paginator("get_databases")
    table_paginator = client.get_paginator("get_tables")

    results = []

    for db_page in db_paginator.paginate():
        for db in db_page.get("DatabaseList", []):
            db_name = db["Name"]
            if not matches_any(db_name, database_patterns):
                continue

            for table_page in table_paginator.paginate(DatabaseName=db_name):
                for table in table_page.get("TableList", []):
                    table_name = table["Name"]
                    if not matches_any(table_name, table_patterns):
                        continue

                    if table.get("DatabaseName", db_name) != db_name:
                        continue

                    sd = table.get("StorageDescriptor", {})
                    columns = sd.get("Columns", [])
                    col_names = [c["Name"] for c in columns]

                    matched_cols = []
                    if column_patterns:
                        for col in col_names:
                            if matches_any(col, column_patterns):
                                matched_cols.append(col)
                        if not matched_cols:
                            continue
                    else:
                        matched_cols = col_names

                    location = sd.get("Location", "")

                    results.append({
                        "Database Name": db_name,
                        "Table Name": table_name,
                        "Matched Column Names": ", ".join(matched_cols),
                        "S3 Location": location,
                    })

                    if limit is not None and len(results) >= limit:
                        _output_results(results, output_format)
                        return

    _output_results(results, output_format)


def _output_results(results: list[dict], output_format: str) -> None:
    if not results:
        return

    if output_format == "json":
        print(json.dumps(results, indent=2))
    elif output_format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=["Database Name", "Table Name", "Matched Column Names", "S3 Location"])
        writer.writeheader()
        writer.writerows(results)
    else:
        # markdown
        print("| Database Name | Table Name | Matched Column Names | S3 Location |")
        print("|---|---|---|---|")
        for r in results:
            print(f"| {r['Database Name']} | {r['Table Name']} | {r['Matched Column Names']} | {r['S3 Location']} |")


if __name__ == "__main__":
    defopt.run(main)
