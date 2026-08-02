"""Shared pytest fixtures for the brownfield_ai.ledger.epics test suite.

Provides an ephemeral SQLite database via ``brownfield_ai.ledger.infra.get_db``
for each test that requests the ``make_db`` fixture, and mock ChromaDB
client/collection factories for CLI-layer tests.
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
from collections.abc import Callable, Generator
from unittest.mock import MagicMock, patch

import pytest

from brownfield_ai.ledger.infra import get_db


@pytest.fixture()
def make_db(tmp_path: pathlib.Path) -> Generator[sqlite3.Connection, None, None]:
    """Create an ephemeral SQLite database with the ledger schema.

    Yields:
        sqlite3.Connection: An open database connection backed by a
        temporary file; closed after the test completes.
    """
    db_path = str(tmp_path / "test_ledger.db")
    with patch.dict(os.environ, {"LEDGER_DB_PATH": db_path}):
        db: sqlite3.Connection = get_db()
        try:
            yield db
        finally:
            db.close()


@pytest.fixture()
def make_collection() -> MagicMock:
    """Return a bare mock ChromaDB collection."""
    return MagicMock()


@pytest.fixture()
def make_client_mock() -> Callable[[MagicMock], MagicMock]:
    """Factory that builds a mock ChromaDB client returning the given collection."""

    def _factory(collection: MagicMock) -> MagicMock:
        client = MagicMock()
        client.get_or_create_collection.return_value = collection
        return client

    return _factory
