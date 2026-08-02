"""
Export knowledge base collections to a human-readable text file.
Useful for backing up knowledge or transferring context to other tools.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import chromadb
import defopt
import yaml

from brownfield_ai.system.context import get_workspace_root

DEFAULT_OUTPUT = str(get_workspace_root() / "tmp" / "chroma_export.txt")


def get_client() -> Any:
    """
    Initializes and returns a ChromaDB HTTP client for export operations.

    Returns:
        chromadb.HttpClient: The instantiated ChromaDB client.

    Raises:
        SystemExit: If the connection down to ChromaDB fails.
    """
    host = os.environ.get("CHROMADB_HOST", "localhost")
    port = int(os.environ.get("CHROMADB_PORT", "8000"))
    try:
        # Connect to ChromaDB server
        return chromadb.HttpClient(host=host, port=port)
    except Exception as e:
        print(f"Error initializing client: {e}")
        sys.exit(1)


def export_all(output_file: str) -> None:
    """
    Retrieves all collections and documents from ChromaDB and exports them
    into a readable markdown-like text file.

    Args:
        output_file (str): The local path to save the exported data.
    """
    print(f"Exporting to {output_file}...")
    client = get_client()
    try:
        collections = client.list_collections()
    except Exception as e:
        print(f"Error listing collections: {e}")
        return

    print(f"Found {len(collections)} collections.")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# ChromaDB Export\n")
        f.write(f"Date: {datetime.now().isoformat()}\n\n")

        for collection in collections:
            # Handle collection object or string name depending on client version
            col_name = collection.name if hasattr(collection, "name") else collection
            print(f"Exporting collection: {col_name}...")

            try:
                col_obj = client.get_collection(col_name)
                result = col_obj.get()
            except Exception as e:
                print(f"Error getting collection {col_name}: {e}")
                f.write(f"## Collection: {col_name} (Error: {e})\n\n")
                continue

            ids = result.get("ids", [])
            documents = result.get("documents", [])
            metadatas = result.get("metadatas", [])

            f.write(f"## Collection: {col_name} ({len(ids)} documents)\n\n")

            if not ids:
                f.write("(Empty collection)\n\n")
                continue

            for i in range(len(ids)):
                doc_id = ids[i]
                doc_content = documents[i] if documents and i < len(documents) else ""
                doc_meta = metadatas[i] if metadatas and i < len(metadatas) else {}

                f.write(f"### Document: {doc_id}\n")

                if doc_meta:
                    f.write("#### Metadata\n")
                    try:
                        # Dump as YAML block for readability
                        yaml_meta = yaml.dump(doc_meta, default_flow_style=False)
                        indented_meta = "\n".join([f"  {line}" for line in yaml_meta.splitlines()])
                        f.write(f"{indented_meta}\n\n")
                    except Exception:
                        f.write(f"  {json.dumps(doc_meta)}\n\n")

                if doc_content:
                    f.write("#### Content\n")
                    f.write(f"{doc_content}\n\n")

                f.write("---\n\n")

    print(f"Export complete. Saved to {output_file}")


def main(*, output: str = DEFAULT_OUTPUT) -> None:
    """
    Export ChromaDB contents to a text file.

    Args:
        output: Output text file path
    """
    try:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        export_all(output)
    except KeyboardInterrupt:
        print("\nExport cancelled.")
        sys.exit(0)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    defopt.run(main)
