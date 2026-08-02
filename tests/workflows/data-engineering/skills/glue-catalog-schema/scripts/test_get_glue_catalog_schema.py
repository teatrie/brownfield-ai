"""
Tests for the `get_glue_catalog_schema` script.

Validates the fetching and formatting of AWS Glue Catalog schemas,
including fallback handling for missing tables and output formatting.
"""

import get_glue_catalog_schema
import pytest

from tests.helpers.aws_env import setup_glue_catalog


class TestGetGlueCatalogSchema:
    """
    Test suite for the AWS Glue Catalog schema retrieval script.

    Tests direct schema fetching via boto3 mock, edge cases, and CLI outputs
    such as Markdown and Mermaid format generation.
    """

    @pytest.mark.aws_mock
    def test_get_glue_schema_real(self):
        setup_glue_catalog(
            database_name="datalake_prod",
            table_name="writer_labels",
            columns=[{"Name": "writer_id", "Type": "bigint"}, {"Name": "label_name", "Type": "string"}],
            partition_keys=[{"Name": "ds", "Type": "string"}],
        )
        columns, partitions, location, metadata = get_glue_catalog_schema.get_glue_schema("datalake_prod", "writer_labels")

        assert len(columns) == 2
        assert columns[0]["Name"] == "writer_id"
        assert columns[0]["Type"] == "bigint"
        assert columns[1]["Name"] == "label_name"
        assert columns[1]["Type"] == "string"

        assert len(partitions) == 1
        assert partitions[0]["Name"] == "ds"
        assert partitions[0]["Type"] == "string"
        assert location == "s3://mock/"

    @pytest.mark.aws_mock
    def test_get_glue_schema_missing(self):
        setup_glue_catalog(
            database_name="datalake_prod", table_name="some_other_table", columns=[{"Name": "id", "Type": "int"}], partition_keys=[]
        )
        with pytest.raises(SystemExit) as excinfo:
            get_glue_catalog_schema.get_glue_schema("datalake_prod", "missing_table")
        assert excinfo.value.code == 1

    def test_to_markdown(self):
        columns = [{"Name": "id", "Type": "int", "Comment": "user id"}]
        partitions = [{"Name": "year", "Type": "int", "Comment": "partition year"}]
        location = "s3://mock_bucket/mock_table/"

        md = get_glue_catalog_schema.to_markdown(columns, partitions, location, None)

        assert "| id | int | user id | False |" in md
        assert "| year | int | partition year | True |" in md
        assert "s3://mock_bucket/mock_table/" in md

    def test_to_mermaid(self):
        columns = [{"Name": "id", "Type": "int", "Comment": "user id"}]
        partitions = [{"Name": "year", "Type": "int", "Comment": "partition year"}]
        location = "s3://mock_bucket/mock_table/"

        mermaid = get_glue_catalog_schema.to_mermaid("users", columns, partitions, location, None)

        assert "erDiagram" in mermaid
        assert "users {" in mermaid
        assert "int id" in mermaid
        assert 'int year "PK"' in mermaid
        assert "s3://mock_bucket/mock_table/" in mermaid

    def test_to_ddl(self):
        columns = [{"Name": "id", "Type": "int", "Comment": "user id"}, {"Name": "name", "Type": "string"}]
        partitions = [{"Name": "year", "Type": "int", "Comment": "partition year"}]
        location = "s3://mock_bucket/mock_table/"

        ddl = get_glue_catalog_schema.to_ddl("users_table", columns, partitions, location, None)

        assert "CREATE EXTERNAL TABLE `users_table` (" in ddl
        assert "`id` int COMMENT 'user id'," in ddl
        assert "`name` string" in ddl
        assert "PARTITIONED BY (" in ddl
        assert "`year` int COMMENT 'partition year'" in ddl
        assert "LOCATION 's3://mock_bucket/mock_table/'" in ddl
        assert ddl.endswith(";")

    def test_to_json(self):
        columns = [{"Name": "id", "Type": "int", "Comment": "user id"}]
        partitions = [{"Name": "year", "Type": "int", "Comment": "partition year"}]
        location = "s3://mock_bucket/mock_table/"

        json_out = get_glue_catalog_schema.to_json(columns, partitions, location, None)

        assert "s3://mock_bucket/mock_table/" in json_out
        assert '"Name": "id"' in json_out

    def test_to_raw(self):
        columns = [{"Name": "id", "Type": "int", "Comment": "user id"}]
        partitions = [{"Name": "year", "Type": "int", "Comment": "partition year"}]
        location = "s3://mock_bucket/mock_table/"

        raw_out = get_glue_catalog_schema.to_raw(columns, partitions, location, None)

        assert "s3://mock_bucket/mock_table/" in raw_out
        assert "id" in raw_out

    @pytest.mark.aws_mock
    def test_main_markdown(self, capsys):
        setup_glue_catalog(
            database_name="datalake_prod",
            table_name="writer_labels",
            columns=[{"Name": "writer_id", "Type": "bigint"}, {"Name": "label_name", "Type": "string"}],
            partition_keys=[{"Name": "ds", "Type": "string"}],
        )

        get_glue_catalog_schema.main(database="datalake_prod", table="writer_labels", output_format="markdown")

        captured = capsys.readouterr()

        assert "| writer_id | bigint |  | False |" in captured.out
        assert "| ds | string |  | True |" in captured.out

    @pytest.mark.aws_mock
    def test_spark_mode_parsing(self):
        # Mocks partitioned JSON parameter string across two parts
        spark_schema_json = (
            '{"type": "struct", "fields": [{"name": "fake_id", "type": "string", "nullable": false, "metadata": {"comment": "test"}}]}'
        )
        setup_glue_catalog(
            database_name="datalake_prod",
            table_name="spark_table",
            columns=[{"Name": "fake_id", "Type": "string"}],
            parameters={
                "spark.sql.sources.schema.part.0": spark_schema_json[:30],
                "spark.sql.sources.schema.part.1": spark_schema_json[30:],
            },
        )
        _, _, _, metadata = get_glue_catalog_schema.get_glue_schema("datalake_prod", "spark_table", mode="spark")
        assert metadata["spark_schema"] is not None
        assert metadata["spark_schema"]["type"] == "struct"
        assert metadata["spark_schema"]["fields"][0]["name"] == "fake_id"

    def test_struct_type_generation(self):
        metadata = {
            "spark_schema": {
                "type": "struct",
                "fields": [
                    {"name": "field_1", "type": "string", "nullable": True, "metadata": {"comment": "..."}},
                    {
                        "name": "complex_f",
                        "type": {"type": "array", "elementType": "string", "containsNull": True},
                        "nullable": False,
                        "metadata": {},
                    },
                ],
            }
        }
        struct_code = get_glue_catalog_schema.to_struct_type(columns=[], partitions=[], location="mock", metadata=metadata, mode="spark")
        assert "import pyspark.sql.types as T" in struct_code
        assert '.add("field_1", \'string\', nullable=True, comment="...")' in struct_code
        assert '.add("complex_f", \'{"type": "array", "elementType": "string", "containsNull": true}\', nullable=False)' in struct_code

    def test_spark_fallback(self):
        columns = [{"Name": "id", "Type": "string"}]
        struct_code = get_glue_catalog_schema.to_struct_type(columns=columns, partitions=[], location="", metadata={}, mode="spark")
        assert '.add("id", "string", nullable=True)' in struct_code
