"""
Import knowledge base collections from a text file (created by knowledge_export.py).
"""

import os
import re
import sys
from typing import Any

import chromadb
import defopt
import yaml


def get_client() -> Any:
    """
    Initializes and returns a ChromaDB HTTP client for import operations.

    Returns:
        chromadb.HttpClient: The instantiated ChromaDB client.

    Raises:
        SystemExit: If the connection to ChromaDB fails.
    """
    host = os.environ.get("CHROMADB_HOST", "localhost")
    port = int(os.environ.get("CHROMADB_PORT", "8000"))
    try:
        return chromadb.HttpClient(host=host, port=port)
    except Exception as e:
        print(f"Error initializing client: {e}")
        sys.exit(1)


def parse_and_import(input_file: str, tags: list[str] | None) -> None:
    """
    Parses a previously exported plaintext file and upserts the documents
    back into their respective ChromaDB collections.

    Args:
        input_file (str): The path to the textual export file.
        tags (list[str] | None): Optional list of metadata tags in 'key=value' format to inject.
    """
    print(f"Reading from {input_file}...")

    # Parse tags
    extra_metadata = {}
    if tags:
        for tag in tags:
            try:
                key, value = tag.split("=", 1)
                extra_metadata[key] = value
            except ValueError:
                print(f"Warning: Invalid tag format '{tag}'. Expected key=value")

    if extra_metadata:
        print(f"Adding extra metadata: {extra_metadata}")

    if not os.path.exists(input_file):
        print(f"File not found: {input_file}")
        sys.exit(1)

    client = get_client()

    with open(input_file, encoding="utf-8") as f:
        lines = f.readlines()

    current_collection_name = None
    current_collection = None

    # Buffers
    batch_ids = []
    batch_metadatas = []
    batch_documents = []

    current_doc_id = None
    current_meta_lines = []
    current_content_lines = []

    state = "NONE"  # NONE, METADATA, CONTENT

    def flush_document():
        nonlocal current_doc_id, current_meta_lines, current_content_lines
        if current_doc_id:
            # Parse metadata
            meta = {}
            if current_meta_lines:
                try:
                    meta_text = "".join(current_meta_lines)
                    parsed = yaml.safe_load(meta_text)
                    if isinstance(parsed, dict):
                        meta = parsed
                except Exception as e:
                    print(f"  Warning: Failed to parse metadata for {current_doc_id}: {e}")

            # Merge extra metadata (tags override file metadata if conflict?
            # Usually safer to preserve file, or let tags override?
            # User intent: "tag docs with additional metadata" usually implies adding/overwriting context.
            if extra_metadata:
                meta.update(extra_metadata)

            # Combine content
            content = "".join(current_content_lines).strip()

            batch_ids.append(current_doc_id)
            batch_metadatas.append(meta)
            batch_documents.append(content)

        current_doc_id = None
        current_meta_lines = []
        current_content_lines = []

    def flush_batch():
        nonlocal batch_ids, batch_metadatas, batch_documents
        if current_collection and batch_ids:
            print(f"  Upserting {len(batch_ids)} documents to '{current_collection_name}'...")
            try:
                current_collection.upsert(ids=batch_ids, metadatas=batch_metadatas, documents=batch_documents)
            except Exception as e:
                print(f"  Error upserting batch: {e}")

        batch_ids = []
        batch_metadatas = []
        batch_documents = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 1. Check for Collection Header
        col_match = re.match(r"^## Collection: (.+) \(.*", line)
        if col_match:
            flush_document()
            flush_batch()

            current_collection_name = col_match.group(1).strip()
            print(f"Processing collection: {current_collection_name}")
            try:
                current_collection = client.get_or_create_collection(current_collection_name)
            except Exception as e:
                print(f"Error creating collection {current_collection_name}: {e}")
                current_collection = None

            state = "NONE"
            i += 1
            continue

        # 2. Check for Document Header
        doc_match = re.match(r"^### Document: (.+)", line)
        if doc_match:
            flush_document()
            current_doc_id = doc_match.group(1).strip()
            state = "NONE"
            i += 1
            continue

        # 3. Check for Metadata Section
        if stripped == "#### Metadata":
            state = "METADATA"
            i += 1
            continue

        # 4. Check for Content Section
        if stripped == "#### Content":
            state = "CONTENT"
            i += 1
            continue

        # 5. Check for Separator
        if stripped == "---":
            flush_document()
            state = "NONE"
            i += 1
            continue

        # 6. Process Content based on State
        if state == "METADATA":
            current_meta_lines.append(line)
        elif state == "CONTENT":
            current_content_lines.append(line)

        i += 1

    # Final flush
    flush_document()
    flush_batch()
    print("Import complete.")


def main(*, input_file: str = "chroma_export.txt", tag: list[str] | None = None) -> None:
    """
    Import ChromaDB collections from a text file.

    Args:
        input_file: Input text file path
        tag: Add extra metadata (format: key=value). Can be used multiple times.
    """
    try:
        parse_and_import(input_file, tag)
    except KeyboardInterrupt:
        print("\nImport cancelled.")
        sys.exit(0)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    defopt.run(main)
