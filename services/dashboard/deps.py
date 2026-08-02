"""FastAPI dependency injection for the ledger dashboard.

Provides web-safe connection factories for SQLite and ChromaDB that do NOT
use the CLI-oriented ``get_db()`` from ``brownfield_ai.ledger.infra`` (which calls
``sys.exit(1)`` on failure). All connections are configured for concurrent
access from a long-running server process.
"""

from __future__ import annotations

import functools
import os
import sqlite3
from collections.abc import Generator

import chromadb
from fastapi import HTTPException, Query

LEDGER_DB_PATH: str = os.environ.get("LEDGER_DB_PATH", "/brownfield-ai/ledger_index.db")
CHROMADB_HOST: str = os.environ.get("CHROMADB_HOST", "host.docker.internal")
CHROMADB_PORT: int = int(os.environ.get("CHROMADB_PORT", "8000"))
KB_COLLECTIONS: frozenset[str] = frozenset({"long_term_document", "chat_history"})


@functools.lru_cache(maxsize=1)
def _get_chromadb_client() -> chromadb.ClientAPI:
    """Return a process-scoped ChromaDB HTTP client.

    The client is cached for the lifetime of the process. If ChromaDB
    becomes unreachable after initial connection, a server restart
    (or calling ``_get_chromadb_client.cache_clear()``) is required
    to re-establish connectivity.
    """
    return chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)


def get_chromadb_client() -> chromadb.ClientAPI:
    """Return a web-safe ChromaDB client for dependency injection.

    Wraps the cached ``_get_chromadb_client()`` with HTTP-safe error
    handling so routers never see raw connection errors.

    Returns:
        chromadb.ClientAPI: The cached ChromaDB HTTP client.

    Raises:
        HTTPException: 503 if ChromaDB is unavailable.
    """
    try:
        return _get_chromadb_client()
    except (ConnectionError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"ChromaDB unavailable: {exc}",
        ) from exc


def get_sqlite_db() -> Generator[sqlite3.Connection, None, None]:
    """Yield a web-safe SQLite connection with WAL mode and busy timeout.

    Opens the ledger SQLite database with pragmas suited for concurrent
    access from the dashboard server and CLI containers:

    - ``journal_mode=WAL``: allows concurrent readers with a single writer.
    - ``busy_timeout=5000``: retries for 5 seconds before raising SQLITE_BUSY.
    - ``foreign_keys=ON``: enforces referential integrity.

    Yields:
        sqlite3.Connection: An open database connection.

    Raises:
        HTTPException: 503 if the database cannot be opened.
    """
    try:
        conn = sqlite3.connect(LEDGER_DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail=f"SQLite database unavailable: {exc}",
        ) from exc
    try:
        yield conn
    finally:
        conn.close()


def get_chromadb_collection() -> chromadb.Collection:
    """Return the ``execution_ledger`` ChromaDB collection.

    Connects to the ChromaDB server using ``CHROMADB_HOST`` and
    ``CHROMADB_PORT`` environment variables.

    Returns:
        chromadb.Collection: The execution_ledger collection.

    Raises:
        HTTPException: 503 if ChromaDB is unavailable.
    """
    try:
        client = _get_chromadb_client()
        return client.get_or_create_collection("execution_ledger")
    except (ConnectionError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"ChromaDB unavailable: {exc}",
        ) from exc


def get_todos_collection() -> chromadb.Collection:
    """Return the ``todos`` ChromaDB collection.

    Connects to the ChromaDB server using ``CHROMADB_HOST`` and
    ``CHROMADB_PORT`` environment variables.

    Returns:
        chromadb.Collection: The todos collection.

    Raises:
        HTTPException: 503 if ChromaDB is unavailable.
    """
    try:
        client = _get_chromadb_client()
        return client.get_or_create_collection("todos")
    except (ConnectionError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"ChromaDB unavailable: {exc}",
        ) from exc


def get_epics_collection() -> chromadb.Collection:
    """Return the ``epics`` ChromaDB collection for semantic search.

    Connects to the ChromaDB server using ``CHROMADB_HOST`` and
    ``CHROMADB_PORT`` environment variables.

    Returns:
        chromadb.Collection: The epics collection.

    Raises:
        HTTPException: 503 if ChromaDB is unavailable.
    """
    try:
        client = _get_chromadb_client()
        return client.get_or_create_collection("epics")
    except (ConnectionError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"ChromaDB unavailable: {exc}",
        ) from exc


def get_kb_collection(
    collection: str = Query("long_term_document"),
) -> chromadb.Collection:
    """Return a validated KB ChromaDB collection by name.

    Validates the requested collection name against the ``KB_COLLECTIONS``
    allowlist, then connects to ChromaDB and returns the collection object.

    Args:
        collection: The collection name, defaulting to ``long_term_document``.

    Returns:
        chromadb.Collection: The requested KB collection.

    Raises:
        HTTPException: 400 if ``collection`` is not in ``KB_COLLECTIONS``.
        HTTPException: 503 if ChromaDB is unavailable.
    """
    if collection not in KB_COLLECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid collection '{collection}'. Must be one of: {', '.join(sorted(KB_COLLECTIONS))}",
        )
    try:
        return _get_chromadb_client().get_collection(name=collection)
    except (ConnectionError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"ChromaDB unavailable: {exc}",
        ) from exc
