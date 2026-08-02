import json
import sys

import defopt
from botocore.exceptions import ClientError

from brownfield_ai.services import aws


def format_schema(schema_data, output_format):
    if output_format == "json":
        return json.dumps(schema_data, indent=2, default=str)

    if output_format == "mermaid":
        table_name = schema_data.get("TableName", "Table")
        lines = ["erDiagram", f"    {table_name} {{"]

        # Track defined attributes to avoid duplicates
        defined_attrs = {}
        for attr in schema_data.get("AttributeDefinitions", []):
            defined_attrs[attr.get("AttributeName")] = attr.get("AttributeType")

        # Keys
        for key in schema_data.get("KeySchema", []):
            attr_name = key.get("AttributeName")
            key_type = "PK" if key.get("KeyType") == "HASH" else "SK"
            attr_type = defined_attrs.get(attr_name, "String")
            lines.append(f"        {attr_type} {attr_name} {key_type}")
            if attr_name in defined_attrs:
                del defined_attrs[attr_name]

        # Remaining attributes
        for attr_name, attr_type in defined_attrs.items():
            lines.append(f"        {attr_type} {attr_name}")

        lines.append("    }")
        return "\n".join(lines)

    # default to markdown
    lines = ["# DynamoDB Table Schema\n"]

    lines.append("## Key Schema")
    lines.append("| Attribute Name | Key Type |")
    lines.append("| --- | --- |")
    for key in schema_data.get("KeySchema", []):
        lines.append(f"| {key.get('AttributeName')} | {key.get('KeyType')} |")
    lines.append("")

    lines.append("## Attribute Definitions")
    lines.append("| Attribute Name | Attribute Type |")
    lines.append("| --- | --- |")
    for attr in schema_data.get("AttributeDefinitions", []):
        lines.append(f"| {attr.get('AttributeName')} | {attr.get('AttributeType')} |")
    lines.append("")

    if "GlobalSecondaryIndexes" in schema_data:
        lines.append("## Global Secondary Indexes")
        for gsi in schema_data.get("GlobalSecondaryIndexes", []):
            lines.append(f"### {gsi.get('IndexName')}")
            lines.append("| Attribute Name | Key Type |")
            lines.append("| --- | --- |")
            for key in gsi.get("KeySchema", []):
                lines.append(f"| {key.get('AttributeName')} | {key.get('KeyType')} |")
            lines.append("")

    return "\n".join(lines)


def main(*, table: str, output_format: str = "markdown"):
    """
    Get DynamoDB Table Schema

    Args:
        table: Name of the DynamoDB table
        output_format: Output format (markdown, json, mermaid)
    """
    client = aws.get_client("dynamodb")
    try:
        response = client.describe_table(TableName=table)
        table_info = response.get("Table", {})

        schema_data = {
            "TableName": table_info.get("TableName"),
            "KeySchema": table_info.get("KeySchema", []),
            "AttributeDefinitions": table_info.get("AttributeDefinitions", []),
            "GlobalSecondaryIndexes": table_info.get("GlobalSecondaryIndexes", []),
            "LocalSecondaryIndexes": table_info.get("LocalSecondaryIndexes", []),
            "BillingModeSummary": table_info.get("BillingModeSummary", {}),
        }

        print(format_schema(schema_data, output_format))

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"Error: Table '{table}' not found.", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"AWS Error: {e}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"Unexpected Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    defopt.run(main)
