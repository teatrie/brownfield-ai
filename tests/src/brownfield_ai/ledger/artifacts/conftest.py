"""Shared pytest fixtures for the brownfield_ai.ledger.artifacts test suite.

Provides an ephemeral SQLite database via ``brownfield_ai.ledger.infra.get_db``
for each test that requests the ``make_db`` fixture.
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
from collections.abc import Generator
from unittest.mock import patch

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
