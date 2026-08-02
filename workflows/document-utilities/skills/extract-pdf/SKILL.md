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

# Example: Output to a temporary text file
mkdir -p tmp/extract-sample
docker compose run --rm python-cli python3 workflows/document-utilities/skills/extract-pdf/scripts/extract_pdf.py docs/sample.pdf > tmp/extract-sample/sample_text.txt
```
