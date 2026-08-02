"""
Extract text content from a PDF file.
Prints the extracted text to stdout.
"""

import sys

from pypdf import PdfReader

try:
    reader = PdfReader(sys.argv[1])
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    print(text)
except Exception as e:
    print(f"Error extracting text: {e}")
