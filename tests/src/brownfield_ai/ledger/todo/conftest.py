"""Shared pytest fixtures for the brownfield_ai.ledger.todo test suite.

Provides ephemeral SQLite databases (via ``chromadb_ledger.get_db``),
mock ChromaDB collections, and a client-mock factory.  Plain helper
functions live in ``helpers.py``.
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
from collections.abc import Callable, Generator
from unittest.mock import MagicMock, patch

import pytest

from brownfield_ai.ledger.infra import get_db
from brownfield_ai.ledger.todo.constants import TODOS_COLLECTION_NAME


@pytest.fixture()
def make_db(tmp_path: pathlib.Path) -> Generator[sqlite3.Connection, None, None]:
    """Create an ephemeral SQLite database with the ledger schema."""
    db_path = str(tmp_path / "test_ledger.db")
    with patch.dict(os.environ, {"LEDGER_DB_PATH": db_path}):
        db: sqlite3.Connection = get_db()
        try:
            yield db
        finally:
            db.close()


@pytest.fixture()
def make_collection() -> MagicMock:
    """Return a mock ChromaDB collection with ``upsert`` and ``query``."""
    collection = MagicMock()
    collection.upsert = MagicMock()
    collection.query = MagicMock()
    return collection


@pytest.fixture()
def make_client_mock() -> Callable[[MagicMock, MagicMock], MagicMock]:
    """Return a factory that builds a mock ChromaDB client dispatching by name."""

    def _factory(
        todos_collection: MagicMock,
        ledger_collection: MagicMock,
    ) -> MagicMock:
        client = MagicMock()

        def _dispatch(name: str) -> MagicMock:
            if name == TODOS_COLLECTION_NAME:
                return todos_collection
            return ledger_collection

        client.get_or_create_collection.side_effect = _dispatch
        return client

    return _factory
