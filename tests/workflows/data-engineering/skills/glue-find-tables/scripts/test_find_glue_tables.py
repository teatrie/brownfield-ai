import json

import pytest
from find_glue_tables import main as find_glue_tables

from tests.helpers.aws_env import setup_glue_catalog


@pytest.fixture
def mock_glue_data():
    """Seed Moto/LocalStack with mock Glue Databases and Tables."""
    # Test DB 1
    setup_glue_catalog(
        database_name="test_db", table_name="users", columns=[{"Name": "id", "Type": "string"}, {"Name": "email", "Type": "string"}]
    )

    # Prod DB 1
    setup_glue_catalog(
        database_name="prod_db",
        table_name="users",
        columns=[{"Name": "id", "Type": "string"}, {"Name": "email", "Type": "string"}, {"Name": "password_hash", "Type": "string"}],
    )

    # Prod DB 2
    setup_glue_catalog(
        database_name="prod_db",
        table_name="transactions",
        columns=[{"Name": "tx_id", "Type": "string"}, {"Name": "amount", "Type": "string"}, {"Name": "user_id", "Type": "string"}],
    )


@pytest.mark.aws_mock
def test_find_glue_tables_no_filters(mock_glue_data, capsys):
    find_glue_tables()
    captured = capsys.readouterr()
    assert "test_db" in captured.out
    assert "prod_db" in captured.out
    assert "users" in captured.out
    assert "transactions" in captured.out


@pytest.mark.aws_mock
def test_find_glue_tables_database_filter(mock_glue_data, capsys):
    find_glue_tables(database_patterns=["^test_.*"])
    captured = capsys.readouterr()
    assert "test_db" in captured.out
    assert "prod_db" not in captured.out


@pytest.mark.aws_mock
def test_find_glue_tables_table_filter(mock_glue_data, capsys):
    find_glue_tables(table_patterns=["transactions"])
    captured = capsys.readouterr()
    assert "transactions" in captured.out
    assert "users" not in captured.out


@pytest.mark.aws_mock
def test_find_glue_tables_column_filter_and_logic(mock_glue_data, capsys):
    find_glue_tables(column_patterns=["password_hash"])
    captured = capsys.readouterr()
    assert "prod_db" in captured.out
    assert "test_db" not in captured.out


@pytest.mark.aws_mock
def test_find_glue_tables_limit(mock_glue_data, capsys):
    find_glue_tables(limit=1)
    captured = capsys.readouterr()
    assert captured.out.count("mock/") == 1


@pytest.mark.aws_mock
def test_find_glue_tables_formatjson(mock_glue_data, capsys):
    find_glue_tables(output_format="json")
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert len(data) == 3
    assert "Database Name" in data[0]


@pytest.mark.aws_mock
def test_find_glue_tables_formatcsv(mock_glue_data, capsys):
    find_glue_tables(output_format="csv")
    captured = capsys.readouterr()
    assert "Database Name,Table Name,Matched Column Names,S3 Location" in captured.out
