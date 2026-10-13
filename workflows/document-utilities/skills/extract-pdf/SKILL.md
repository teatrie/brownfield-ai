---
name: extract-pdf
description: Extract readable text content from a PDF file using pypdf.
---

# Extract PDF Text

Use this skill when you need to read, analyze, or summarize the text contents of a PDF document.

## Description

This skill utilizes [workflows/document-utilities/skills/extract-pdf/scripts/extract_pdf.py](scripts/extract_pdf.py) to parse a specified PDF file and output the pure text content to standard output.

## Pre-requisites

This script must be executed using the repository's `python-cli python3` Docker container to ensure all dependencies (like `pypdf`) are correctly available without polluting the host environment.

## Usage

```bash
# General extraction
docker compose run --rm python-cli python3 workflows/document-utilities/skills/extract-pdf/scripts/extract_pdf.py <path_to_pdf_file.pdf>
```

The script prints the extracted text to stdout and has no output-file option. To keep the text as a file, write it to `tmp/<context>/` with the Write tool; shell redirection is hook-denied (see [docs/learnings.md](../../../../docs/learnings.md) §PreToolUse Hook Gotchas).
