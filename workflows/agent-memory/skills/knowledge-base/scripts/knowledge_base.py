"""
CLI tool for managing knowledge base documents.
Supports adding, querying, and listing documents in specified collections.
"""

import hashlib
import json
import os
import sys
from typing import Any

import chromadb
import defopt


def get_client() -> Any:
    """
    Initializes and returns a ChromaDB HTTP client connected to the configured host and port.

    Returns:
        chromadb.HttpClient: The instantiated client.
    """
    host = os.environ.get("CHROMADB_HOST", "localhost")
    port = int(os.environ.get("CHROMADB_PORT", "8000"))
    return chromadb.HttpClient(host=host, port=port)


def generate_id(content: str) -> str:
    """
    Generates a deterministic SHA-256 ID based on the document content.

    Args:
        content (str): The document text.

    Returns:
        str: Hexadecimal SHA-256 hash string.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def add_doc(collection_name: str, content: str, metadata: dict | None = None) -> None:
    """
    Adds a single document to the specified ChromaDB collection.

    Args:
        collection_name (str): Core target collection name.
        content (str): The actual text content to embed and save.
        metadata (dict | None, optional): Optional JSON metadata. Defaults to None.
    """
    client = get_client()
    collection = client.get_or_create_collection(name=collection_name)
    doc_id = generate_id(content)
    if metadata is None:
        metadata = {}

    # Check if exists
    existing = collection.get(ids=[doc_id])
    if existing["ids"]:
        print(f"document already exists with ID: {doc_id}")
        return

    # ChromaDB requires non-empty metadata or None
    metadatas_arg = [metadata] if metadata else None

    collection.add(documents=[content], metadatas=metadatas_arg, ids=[doc_id])
    print(f"Added document to {collection_name} with ID: {doc_id}")


def query_docs(collection_name: str, query_text: str, n_results: int = 5, verbose: bool = False) -> None:
    """
    Queries a collection for similar documents based on text embeddings.

    Args:
        collection_name (str): The name of the collection to search.
        query_text (str): The search prompt text.
        n_results (int, optional): The maximum number of results to return. Defaults to 5.
        verbose (bool, optional): If True, prints entire document content. Defaults to False.
    """
    client = get_client()
    collection = client.get_or_create_collection(name=collection_name)
    results = collection.query(query_texts=[query_text], n_results=n_results)

    # Pretty print
    if results["ids"]:
        for i in range(len(results["ids"][0])):
            doc_id = results["ids"][0][i]
            doc = results["documents"][0][i]
            meta = results["metadatas"][0][i]
            dist = results["distances"][0][i] if results["distances"] else "N/A"

            if not verbose:
                doc = doc[:50] + "..."

            print(f"\nID: {doc_id} (Distance: {dist})")
            print(f"Content: {doc}")
            print(f"Metadata: {meta}")
    else:
        print("No results found.")


def list_docs(collection_name: str, limit: int = 10, verbose: bool = False) -> None:
    """
    Lists the most recent documents in a specific ChromaDB collection.

    Args:
        collection_name (str): The name of the collection to enumerate.
        limit (int, optional): The maximum number of documents to retrieve. Defaults to 10.
        verbose (bool, optional): If True, prints complete document text. Defaults to False.
    """
    client = get_client()
    collection = client.get_or_create_collection(name=collection_name)
    results = collection.get(limit=limit)
    print(f"Total documents in {collection_name}: {len(results['ids'])}")
    for i in range(len(results["ids"])):
        content = results["documents"][i]
        if not verbose:
            content = content[:50] + "..."
        print(f"{results['ids'][i]}: {content}")


def add(content: str, *, collection: str = "long_term_document", metadata: str = "{}") -> None:
    """
    Add a new document.

    Args:
        content: Content of the document
        collection: Collection name
        metadata: JSON metadata string
    """
    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError:
        print("Invalid JSON metadata")
        sys.exit(1)
    add_doc(collection, content, meta)


def query(query: str, *, collection: str = "long_term_document", n: int = 5, verbose: bool = False) -> None:
    """
    Query documents.

    Args:
        query: Query text
        collection: Collection name
        n: Number of results
        verbose: Show full content
    """
    query_docs(collection, query, n, verbose)


def list_docs_cli(*, collection: str = "long_term_document", limit: int = 10, verbose: bool = False) -> None:
    """
    List documents.

    Args:
        collection: Collection name
        limit: Limit results
        verbose: Show full content
    """
    list_docs(collection, limit, verbose)


if __name__ == "__main__":
    defopt.run([add, query, list_docs_cli])
