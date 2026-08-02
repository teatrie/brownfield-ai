---
name: knowledge-export
description: Export knowledge base documents as a single text file. Triggered by phrases like "knowledge export", "export knowledge", "chat log export", "recall export", "memory export", "recall memory", or "export memories".
---

# 🚀 Export Knowledge Base

I will now export all architectural patterns and project knowledge from the knowledge base into a single text file named `tmp/chroma_export.txt` by default.

## Steps

0. **Start ChromaDB**: Ensure the chromadb service is running.

    ```bash
    task chromadb:start
    ```

1. **Export**: Run the export utility via task alias.

    ```bash
    task chromadb:export
    ```

## Completion

Knowledge successfully exported to `tmp/chroma_export.txt`.

**Next Step**: Import output to another service for further analysis. For example, go to [NotebookLM](https://notebooklm.google.com/) and upload `tmp/chroma_export.txt` to create a new notebook with all the architectural patterns and project knowledge for easy querying and reference.
