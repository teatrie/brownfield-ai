import json
import sys

import defopt
from botocore.exceptions import ClientError

from brownfield_ai.services import aws


def get_glue_schema(database: str, table: str, mode: str = "spark"):
    """
    Fetch the table schema from the AWS Glue Catalog.

    Args:
        database (str): The name of the Glue database.
        table (str): The name of the Glue table.
        mode (str): Mode for schema fetching.

    Returns:
        tuple[list[dict], list[dict], str, dict]: A tuple containing the list of
            standard columns, the list of partition keys, the S3 location, and schema metadata.
    """
    client = aws.get_client("glue")
    try:
        response = client.get_table(DatabaseName=database, Name=table)
        table_info = response.get("Table", {})
        sd = table_info.get("StorageDescriptor", {})
        columns = sd.get("Columns", [])
        partitions = table_info.get("PartitionKeys", [])
        location = sd.get("Location", "")
        metadata = table_info.get("Parameters", {}).copy()
        if "BucketColumns" in sd:
            metadata["BucketColumns"] = sd["BucketColumns"]
        if "SortColumns" in sd:
            metadata["SortColumns"] = sd["SortColumns"]

        if mode == "spark":
            spark_parts = []
            part_idx = 0
            while True:
                part_key = f"spark.sql.sources.schema.part.{part_idx}"
                if part_key in metadata:
                    spark_parts.append(metadata[part_key])
                    part_idx += 1
                else:
                    break

            if spark_parts:
                try:
                    full_json_str = "".join(spark_parts)
                    metadata["spark_schema"] = json.loads(full_json_str)
                except (json.JSONDecodeError, KeyError):
                    metadata["spark_schema"] = None

        return columns, partitions, location, metadata
    except ClientError as e:
        print(f"AWS Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def to_markdown(columns, partitions, location, metadata=None):
    lines = [f"**Location:** {location}\n"] if location else []
    lines.extend(["| Column Name | Type | Comment | Partition Key |", "| --- | --- | --- | --- |"])
    for col in columns:
        comment = col.get("Comment", "").replace("\n", " ")
        name = col.get("Name", "")
        ctype = col.get("Type", "")
        lines.append(f"| {name} | {ctype} | {comment} | False |")
    for part in partitions:
        comment = part.get("Comment", "").replace("\n", " ")
        name = part.get("Name", "")
        ctype = part.get("Type", "")
        lines.append(f"| {name} | {ctype} | {comment} | True |")
    return "\n".join(lines)


def to_mermaid(table_name, columns, partitions, location, metadata=None):
    lines = []
    if location:
        lines.append(f"%% Location: {location}")
    lines.extend(["erDiagram", f"    {table_name} {{"])
    for col in columns:
        ctype = col.get("Type", "").replace(" ", "_")
        name = col.get("Name", "")
        lines.append(f"        {ctype} {name}")
    for part in partitions:
        ctype = part.get("Type", "").replace(" ", "_")
        name = part.get("Name", "")
        lines.append(f'        {ctype} {name} "PK"')
    lines.append("    }")
    return "\n".join(lines)


def to_json(columns, partitions, location, metadata=None):
    data = {"columns": columns, "partitions": partitions}
    if location:
        data["location"] = location
    return json.dumps(data, indent=2)


def to_raw(columns, partitions, location, metadata=None):
    lines = []
    if location:
        lines.append(f"Location: {location}")
    lines.append("Columns:")
    for col in columns:
        lines.append(f"  {col.get('Name')} ({col.get('Type')}) - {col.get('Comment', '')}")
    lines.append("Partition Keys:")
    for part in partitions:
        lines.append(f"  {part.get('Name')} ({part.get('Type')}) - {part.get('Comment', '')}")
    return "\n".join(lines)


def to_ddl(table_name: str, columns: list, partitions: list, location: str, metadata: dict | None = None, mode: str = "spark") -> str:
    metadata = metadata or {}

    spark_fields = {}
    if mode == "spark" and metadata.get("spark_schema"):
        for f in metadata["spark_schema"].get("fields", []):
            spark_fields[f.get("name")] = f

    metadata = metadata or {}
    lines = [f"CREATE EXTERNAL TABLE `{table_name}` ("]
    for i, col in enumerate(columns):
        name = col.get("Name", "")
        ctype = col.get("Type", "")

        is_nullable = True
        comment = col.get("Comment", "")

        if mode == "spark" and name in spark_fields:
            sf = spark_fields[name]
            is_nullable = sf.get("nullable", True)
            comment = sf.get("metadata", {}).get("comment", comment)

        line = f"  `{name}` {ctype}"
        if not is_nullable and mode == "spark":
            line += " NOT NULL"

        if comment:
            comment = comment.replace("'", "\\'")
            line += f" COMMENT '{comment}'"
        if i < len(columns) - 1:
            line += ","
        lines.append(line)
    lines.append(")")

    if mode == "spark" and metadata.get("spark_schema", {}) and metadata.get("spark_schema", {}).get("metadata", {}).get("comment"):
        table_comment = metadata["spark_schema"]["metadata"]["comment"].replace("'", "\\'")
        lines.append(f"COMMENT '{table_comment}'")

    if partitions:
        lines.append("PARTITIONED BY (")
        for i, part in enumerate(partitions):
            name = part.get("Name", "")
            ctype = part.get("Type", "")

            is_nullable = True
            comment = part.get("Comment", "")

            if mode == "spark" and name in spark_fields:
                sf = spark_fields[name]
                is_nullable = sf.get("nullable", True)
                comment = sf.get("metadata", {}).get("comment", comment)

            line = f"  `{name}` {ctype}"
            if not is_nullable and mode == "spark":
                line += " NOT NULL"

            if comment:
                comment = comment.replace("'", "\\'")
                line += f" COMMENT '{comment}'"
            if i < len(partitions) - 1:
                line += ","
            lines.append(line)
        lines.append(")")

    if mode == "spark":
        bucket_cols = metadata.get("BucketColumns", [])
        if bucket_cols:
            bucket_str = ", ".join([f"`{c}`" for c in bucket_cols])
            num_buckets = metadata.get("NumberOfBuckets")
            line = f"CLUSTERED BY ({bucket_str})"
            if num_buckets:
                line += f" INTO {num_buckets} BUCKETS"
            lines.append(line)

        sort_cols = metadata.get("SortColumns", [])
        if sort_cols:
            sort_items = []
            for sc in sort_cols:
                if isinstance(sc, dict):
                    c_name = sc.get("Column")
                    c_order = "ASC" if sc.get("SortOrder") == 1 else "DESC"
                    sort_items.append(f"`{c_name}` {c_order}")
                else:
                    sort_items.append(f"`{sc}`")
            if sort_items:
                sort_str = ", ".join(sort_items)
                lines.append(f"SORTED BY ({sort_str})")

    if location:
        lines.append(f"LOCATION '{location}'")
    lines[-1] += ";"
    return "\n".join(lines)


def to_struct_type(columns: list, partitions: list, location: str, metadata: dict, mode: str) -> str:
    lines = ["import pyspark.sql.types as T", "", "data_source = {"]

    partition_by = tuple([p.get("Name") for p in partitions])
    try:
        bucket_by = tuple(metadata.get("BucketColumns", []))
    except TypeError:
        bucket_by = ()

    try:
        sort_by = tuple(metadata.get("SortColumns", []))
    except TypeError:
        sort_by = ()

    lines.append(f'    "location": "{location}",')
    lines.append(f'    "partition_by": {partition_by!r},')
    lines.append(f'    "bucket_by": {bucket_by!r},')
    lines.append(f'    "sort_by": {sort_by!r},')
    lines.append('    "schema": T.StructType()')

    if mode == "spark" and metadata.get("spark_schema"):
        spark_schema = metadata["spark_schema"]
        fields = spark_schema.get("fields", [])
        for field in fields:
            name = field.get("name", "")
            field_type = field.get("type", "string")

            if isinstance(field_type, dict):
                field_type_str = json.dumps(field_type)
            else:
                field_type_str = str(field_type)

            nullable = field.get("nullable", True)
            field_metadata = field.get("metadata", {})
            comment = field_metadata.get("comment", "")

            if comment:
                lines.append(f'        .add("{name}", \'{field_type_str}\', nullable={nullable}, comment="{comment}")')
            else:
                lines.append(f"        .add(\"{name}\", '{field_type_str}', nullable={nullable})")
    else:
        # Fallback if no spark_schema
        all_cols = columns + partitions
        for col in all_cols:
            name = col.get("Name", "")
            ctype = col.get("Type", "string").lower()
            lines.append(f'        .add("{name}", "{ctype}", nullable=True)')

    lines.append("}")
    return "\n".join(lines)


def main(*, table: str, database: str, output_format: str = "markdown", mode: str = "spark") -> None:
    """
    Fetch a table schema from the AWS Glue Catalog.

    Args:
        table: Glue table name
        database: Glue database name (required — no account-specific default)
        output_format: Output format (markdown, json, raw, mermaid, ddl, struct-type)
        mode: Mapping mode for struct type (spark, etc.)
    """
    columns, partitions, location, metadata = get_glue_schema(database, table, mode=mode)

    if output_format == "markdown":
        print(to_markdown(columns, partitions, location, metadata))
    elif output_format == "json":
        print(to_json(columns, partitions, location, metadata))
    elif output_format == "mermaid":
        print(to_mermaid(table, columns, partitions, location, metadata))
    elif output_format == "raw":
        print(to_raw(columns, partitions, location, metadata))
    elif output_format == "ddl":
        print(to_ddl(table, columns, partitions, location, metadata, mode))
    elif output_format in ("struct", "struct-type"):
        print(to_struct_type(columns, partitions, location, metadata, mode))


if __name__ == "__main__":
    defopt.run(main)
