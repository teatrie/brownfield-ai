---
name: knowledge-import
description: Import knowledge base collections from a text file, with optional metadata tagging. Triggered by phrases like "knowledge import", "import knowledge", "chat log import", "recall import", "restore knowledge", "memory import", "import memory", or "restore memories".
---

# Knowledge Import

Import collections and documents into the knowledge base from a text export file.

## Usage

1. **Start ChromaDB**: First, ensure the chromadb service is running.

    ```bash
    task chromadb:start
    ```

Run the import via the `task chromadb:import` alias.
You MUST replace `{input_file}` with the file path (default: `tmp/chroma_export.txt`).
You CAN add `--tag key=value` arguments to attach metadata to all imported documents.

```bash
task chromadb:import -- --input {input_file} {tags}
```

## Examples

**Default import:**

```bash
task chromadb:import -- --input tmp/chroma_export.txt
```

**Import with metadata tags:**

```bash
task chromadb:import -- --input tmp/chroma_export.txt --tag source=johnny --tag env=prod
```
