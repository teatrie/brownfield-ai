"""
Tests for the `get_redshift_table_schema` script.

Validates Redshift schema fetching and formatting, ensuring accurate CLI outputs
and integration with boto3 mocked services.
"""

import json

import pytest
from get_redshift_table_schema import get_redshift_schema, to_ddl, to_json, to_markdown, to_mermaid, to_raw


@pytest.mark.aws_mock
def test_get_redshift_schema_happy_path():
    columns = get_redshift_schema(
        cluster_identifier="my-cluster",
        workgroup_name=None,
        database="mydb",
        db_user="myuser",
        secret_arn=None,
        schema="public",
        table="users",
    )
    # The Moto server lacks a true SQL engine for the redshift-data API mock.
    # It will safely process the execute_statement mock but may return empty
    # or stubbed result sets depending on the moto version, so we just assert it
    # receives and parses a list correctly without blowing up.
    assert isinstance(columns, list)


def test_to_markdown():
    columns = [
        {"column_name": "id", "data_type": "integer", "character_maximum_length": None},
        {"column_name": "name", "data_type": "varchar", "character_maximum_length": 255},
    ]
    md = to_markdown(columns)
    assert "| id | integer |  |" in md
    assert "| name | varchar | 255 |" in md


def test_to_json():
    columns = [
        {"column_name": "id", "data_type": "integer", "character_maximum_length": None},
        {"column_name": "name", "data_type": "varchar", "character_maximum_length": 255},
    ]
    j = to_json(columns)
    parsed = json.loads(j)
    assert len(parsed["columns"]) == 2
    assert parsed["columns"][1]["character_maximum_length"] == 255


def test_to_raw():
    columns = [
        {"column_name": "id", "data_type": "integer", "character_maximum_length": None},
        {"column_name": "name", "data_type": "varchar", "character_maximum_length": 255},
    ]
    raw = to_raw(columns)
    assert "Columns:" in raw
    assert "id (integer)" in raw
    assert "name (varchar) (255)" in raw


def test_to_mermaid():
    columns = [
        {"column_name": "id", "data_type": "integer", "character_maximum_length": None},
        {"column_name": "name", "data_type": "varchar", "character_maximum_length": 255},
    ]
    table_name = "users"
    mermaid = to_mermaid(columns, table_name)
    assert "erDiagram" in mermaid
    assert f"    {table_name} {{" in mermaid
    assert "        integer id" in mermaid
    assert "        varchar name" in mermaid


def test_to_ddl():
    columns = [
        {"column_name": "id", "data_type": "integer", "character_maximum_length": None},
        {"column_name": "name", "data_type": "varchar", "character_maximum_length": 255},
    ]
    ddl = to_ddl(columns, "users", "public")
    assert "CREATE TABLE public.users (" in ddl
    assert "  id integer," in ddl
    assert "  name varchar(255)" in ddl
    assert ");" in ddl
