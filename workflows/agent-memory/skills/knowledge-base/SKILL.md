---
name: knowledge-base
description: Manage and interact with the knowledge base by adding, querying, and listing documents. Triggered by phrases like "knowledge add", "knowledge query", "knowledge search", "knowledge list", "recall knowledge", "chat history search", "chat log query", "memory list", "memory add", "memory query", "recall", or "remember".
---

# Knowledge Base Manager

This skill provides a simple command-line interface to interact with the knowledge base. You can use it to add documents with optional metadata, semantically structure queries for similar documents, and list existing documents inside collections.

## Usage

All commands use the `task chromadb:collection` alias which routes through `python-cli` for correct environment and networking.

### 0. Start ChromaDB

Before running any command, ensure the chromadb service is started.

```bash
task chromadb:start
```

### 1. Add a Document

Add a new document to a specified collection. If the collection does not exist, it will be created.

```bash
# Basic usage
task chromadb:collection -- add "Your document content here"

# With specific collection and metadata
task chromadb:collection -- add "Your document content here" --collection "my_custom_collection" --metadata '{"source": "user", "topic": "documentation"}'
```

### 2. Query Documents

Retrieve documents similar to a query string.

```bash
# Basic query (default 5 results)
task chromadb:collection -- query "How do I add a memory?"

# With specific collection, result count, and detailed output
task chromadb:collection -- query "How do I add a memory?" --collection "my_custom_collection" --n 3 --verbose
```

### 3. List Documents

List the documents currently residing in a collection.

```bash
# Basic list (default 10 results)
task chromadb:collection -- list

# With specific collection and result limit
task chromadb:collection -- list --collection "my_custom_collection" --limit 20 --verbose
```

## Available Arguments

- `--collection`: The name of the collection to target (defaults to `long_term_document`).
- `--metadata`: A JSON string of key-value pairs to store alongside the document (e.g., `'{"key" : "value"}'`). Valid only in `add`.
- `--n`: Number of query results to fetch. Default is 5. Valid only in `query`.
- `--limit`: Number of documents to display. Default is 10. Valid only in `list`.
- `--verbose`: Show full document content instead of truncating it. Valid in `query` and `list`.

## Notes

- To ensure data persistence across sessions, make sure the global `chromadb` service is running correctly via Docker Compose and that your data directory (`~/.brownfield-ai/chroma_data`) is mounted properly (this is the underlying storage for the knowledge base).
