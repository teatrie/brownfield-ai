"""
Test suite for the Athena query execution tool.

Validates the AWS querying flows including successful data retrieval, parameter handling
for S3 Parquet export formats, and the wait/no-wait polling mechanisms.
"""

import os
from unittest.mock import MagicMock, patch

import athena_query_execute as aqe
import pytest

SCRATCH_ENV = {"USER_EMAIL": "testuser@example.com", "ATHENA_SCRATCH_BUCKET": "my-scratch-bucket"}


@patch("athena_query_execute.get_client")
def test_athena_query_execute_success_csv(mock_get_client, tmp_path):
    mock_athena = MagicMock()
    mock_get_client.return_value = mock_athena
    mock_athena.start_query_execution.return_value = {"QueryExecutionId": "q-123"}
    mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    mock_athena.get_query_results.return_value = {
        "ResultSet": {
            "Rows": [
                {"Data": [{"VarCharValue": "id"}, {"VarCharValue": "name"}]},
                {"Data": [{"VarCharValue": "1"}, {"VarCharValue": "alice"}]},
            ]
        }
    }

    with patch.dict(os.environ, SCRATCH_ENV):
        with patch("athena_query_execute.WORKSPACE_ROOT", str(tmp_path)):
            aqe.main("SELECT 1", context="test-ctx")

    mock_athena.start_query_execution.assert_called_once()
    kwargs = mock_athena.start_query_execution.call_args.kwargs
    assert kwargs["QueryString"] == "SELECT 1"
    output_location = kwargs["ResultConfiguration"]["OutputLocation"]
    assert output_location.startswith("s3://my-scratch-bucket/")
    assert "testuser/test-ctx" in output_location

    out_dir = tmp_path / "tmp" / "athena"
    subdirs = list(out_dir.glob("test-ctx-*"))
    assert len(subdirs) == 1
    assert (subdirs[0] / "page-1.csv").exists()


@patch("athena_query_execute.get_client")
def test_athena_query_execute_no_wait(mock_get_client):
    mock_athena = MagicMock()
    mock_get_client.return_value = mock_athena
    mock_athena.start_query_execution.return_value = {"QueryExecutionId": "q-123"}

    with patch.dict(os.environ, SCRATCH_ENV):
        aqe.main("SELECT 1", context="test-ctx", no_wait=True)
    mock_athena.get_query_execution.assert_not_called()


@patch("athena_query_execute.get_client")
def test_athena_query_execute_requires_scratch_bucket(mock_get_client):
    """The bucket has no default: an unset ATHENA_SCRATCH_BUCKET must fail loudly."""
    with patch.dict(os.environ, {}, clear=True), pytest.raises(SystemExit) as excinfo:
        aqe.main("SELECT 1", context="test-ctx", no_wait=True)

    assert excinfo.value.code == 1
    mock_get_client.assert_not_called()


@patch("athena_query_execute.get_client")
def test_athena_query_execute_bucket_argument_overrides_env(mock_get_client, tmp_path):
    """An explicit --bucket wins over the environment, with or without an s3:// scheme."""
    mock_athena = MagicMock()
    mock_get_client.return_value = mock_athena
    mock_athena.start_query_execution.return_value = {"QueryExecutionId": "q-123"}

    with patch.dict(os.environ, SCRATCH_ENV):
        with patch("athena_query_execute.WORKSPACE_ROOT", str(tmp_path)):
            aqe.main("SELECT 1", context="test-ctx", bucket="s3://override-bucket/", no_wait=True)

    kwargs = mock_athena.start_query_execution.call_args.kwargs
    assert kwargs["ResultConfiguration"]["OutputLocation"].startswith("s3://override-bucket/")


@patch("athena_query_execute.get_client")
def test_athena_query_execute_parquet(mock_get_client, tmp_path):
    mock_athena = MagicMock()
    mock_s3 = MagicMock()

    def get_c(client_type):
        return mock_athena if client_type == "athena" else mock_s3

    mock_get_client.side_effect = get_c

    mock_athena.start_query_execution.return_value = {"QueryExecutionId": "q-123"}
    mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    mock_s3.get_paginator.return_value.paginate.return_value = [{"Contents": [{"Key": "brownfield-ai/testuser/test-ctx-123/test.parquet"}]}]

    with patch("athena_query_execute.WORKSPACE_ROOT", str(tmp_path)):
        with patch.dict(os.environ, SCRATCH_ENV):
            aqe.main("SELECT 1", context="test-ctx", format_="parquet")

    kwargs = mock_athena.start_query_execution.call_args.kwargs
    assert "UNLOAD (SELECT 1)" in kwargs["QueryString"]
    assert "PARQUET" in kwargs["QueryString"]
    mock_s3.download_file.assert_called_once()
