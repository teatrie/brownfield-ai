import os
from unittest.mock import patch

from knowledge_base import get_client as collection_get_client
from knowledge_checkpoint import get_client as checkpoint_get_client
from knowledge_export import get_client as export_get_client
from knowledge_import import get_client as import_get_client


@patch("knowledge_checkpoint.chromadb.HttpClient")
@patch.dict(os.environ, {}, clear=True)
def test_checkpoint_get_client_defaults_to_localhost(mock_client):
    checkpoint_get_client()
    mock_client.assert_called_once_with(host="localhost", port=8000)


@patch("knowledge_checkpoint.chromadb.HttpClient")
@patch.dict(os.environ, {"CHROMADB_HOST": "test-host", "CHROMADB_PORT": "1234"}, clear=True)
def test_checkpoint_get_client_respects_env_vars(mock_client):
    checkpoint_get_client()
    mock_client.assert_called_once_with(host="test-host", port=1234)


@patch("knowledge_base.chromadb.HttpClient")
@patch.dict(os.environ, {}, clear=True)
def test_collection_get_client_defaults_to_localhost(mock_client):
    collection_get_client()
    mock_client.assert_called_once_with(host="localhost", port=8000)


@patch("knowledge_base.chromadb.HttpClient")
@patch.dict(os.environ, {"CHROMADB_HOST": "test-host", "CHROMADB_PORT": "1234"}, clear=True)
def test_collection_get_client_respects_env_vars(mock_client):
    collection_get_client()
    mock_client.assert_called_once_with(host="test-host", port=1234)


@patch("knowledge_export.chromadb.HttpClient")
@patch.dict(os.environ, {}, clear=True)
def test_export_get_client_defaults_to_localhost(mock_client):
    export_get_client()
    mock_client.assert_called_once_with(host="localhost", port=8000)


@patch("knowledge_export.chromadb.HttpClient")
@patch.dict(os.environ, {"CHROMADB_HOST": "test-host", "CHROMADB_PORT": "1234"}, clear=True)
def test_export_get_client_respects_env_vars(mock_client):
    export_get_client()
    mock_client.assert_called_once_with(host="test-host", port=1234)


@patch("knowledge_import.chromadb.HttpClient")
@patch.dict(os.environ, {}, clear=True)
def test_import_get_client_defaults_to_localhost(mock_client):
    import_get_client()
    mock_client.assert_called_once_with(host="localhost", port=8000)


@patch("knowledge_import.chromadb.HttpClient")
@patch.dict(os.environ, {"CHROMADB_HOST": "test-host", "CHROMADB_PORT": "1234"}, clear=True)
def test_import_get_client_respects_env_vars(mock_client):
    import_get_client()
    mock_client.assert_called_once_with(host="test-host", port=1234)
