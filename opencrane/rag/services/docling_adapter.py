"""Adapter for Docling document processing."""

import logging
from pathlib import Path
from docling.document_converter import DocumentConverter

# Suppress Docling's verbose logging
logging.getLogger("docling").setLevel(logging.CRITICAL)


class DoclingAdapter:
    """Adapter for processing Markdown and text documents with Docling."""

    def __init__(self):
        self.converter = DocumentConverter()

    def convert_file(self, file_path: Path):
        """Convert a file to a Docling document.

        Args:
            file_path: Path to the file to convert.

        Returns:
            Docling document object.
        """
        result = self.converter.convert(file_path)
        return result.document