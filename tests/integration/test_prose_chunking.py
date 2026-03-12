"""Integration tests for prose chunking."""

import pytest
import tempfile
from pathlib import Path
from opencrane.rag.services.file_processor import process_file


class TestProseChunkingIntegration:
    """Integration tests for prose chunking end-to-end."""

    def test_nested_headers_chunking(self):
        """Test chunking a document with nested headers.
        
        Note: This test previously failed because Docling nodes lacked text attributes.
        It now passes due to fallback processing in FileProcessor.
        """
        from pathlib import Path
        test_data_dir = Path(__file__).parent.parent / "fixtures"
        sample_file = test_data_dir / "sample.md"
        
        chunks = process_file(sample_file)

        # Verify we have prose chunks
        prose_chunks = [c for c in chunks if c.chunk_type == "prose"]
        assert len(prose_chunks) > 0
        
        # Verify deterministic output
        chunks2 = process_file(sample_file)
        assert len(chunks) == len(chunks2)
        for c1, c2 in zip(chunks, chunks2):
            assert c1.content == c2.content
            assert c1.metadata == c2.metadata