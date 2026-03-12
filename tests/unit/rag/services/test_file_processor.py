"""Tests for FileProcessor."""

import tempfile
from unittest.mock import MagicMock, patch, Mock
from pathlib import Path
from opencrane.rag.services.file_processor import FileProcessor


class TestFileProcessor:
    """Test cases for FileProcessor."""

    def test_process_file_uses_relative_source_file_when_under_cwd(self, tmp_path, monkeypatch):
        """Chunks should store a repo-relative source_file when possible."""
        processor = FileProcessor()

        # Make cwd the temp dir so relative_to(cwd) succeeds.
        monkeypatch.chdir(tmp_path)
        file_path = tmp_path / "llms-full.txt"
        file_path.write_text("# Header\n\nHello world.\n", encoding="utf-8")

        with patch.object(processor.docling_adapter, 'convert_file') as mock_convert:
            from docling.exceptions import ConversionError
            mock_convert.side_effect = ConversionError("test")

            chunks = processor.process_file(file_path)

        assert len(chunks) > 0
        assert all(chunk.source_file == "llms-full.txt" for chunk in chunks)

    def test_process_large_file_with_code_blocks(self):
        """Test processing large file that gets split into sections."""
        processor = FileProcessor()
        
        # Create large content with code blocks (>100KB)
        large_content = "# Section 1\n\n" + ("x" * 50000) + "\n\n```python\ncode\n```\n\n# Section 2\n\n" + ("y" * 50001)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(large_content)
            temp_path = Path(f.name)
        
        try:
            with patch.object(processor.docling_adapter, 'convert_file') as mock_convert:
                from docling.exceptions import ConversionError
                mock_convert.side_effect = ConversionError("test")
                
                chunks = processor.process_file(temp_path)
                
                # Should produce chunks from sections
                assert len(chunks) > 0
        finally:
            temp_path.unlink()

    def test_process_file_with_many_code_blocks(self):
        """Test processing file with many code blocks (>100)."""
        processor = FileProcessor()
        
        # Create content with many code blocks
        code_blocks = "\n\n".join([f"```python\ncode{i}\n```" for i in range(101)])
        content = f"# Header\n\n{code_blocks}"
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            temp_path = Path(f.name)
        
        try:
            with patch.object(processor.docling_adapter, 'convert_file') as mock_convert:
                from docling.exceptions import ConversionError
                mock_convert.side_effect = ConversionError("test")
                
                chunks = processor.process_file(temp_path)
                
                # Should produce chunks
                assert len(chunks) > 0
        finally:
            temp_path.unlink()

    def test_fallback_sections_track_source_url_from_markers(self, tmp_path, monkeypatch):
        """Sections should track source_url from URL markers and pass to chunks."""
        processor = FileProcessor()
        monkeypatch.chdir(tmp_path)

        url = "https://github.com/my-org/proj/blob/main/docs/a.md"
        # Create many code fences to trigger splitting
        # First section has URL in header
        # "between" sections have no URL - they should NOT inherit the URL
        content = f"### {url}\n\nIntroduction paragraph with enough content.\n\n" + ("```python\nprint(1)\n```\n\nThis is between content.\n\n" * 101)
        file_path = tmp_path / "llms-full.txt"
        file_path.write_text(content, encoding="utf-8")

        with patch.object(processor.docling_adapter, 'convert_file') as mock_convert:
            from docling.exceptions import ConversionError
            mock_convert.side_effect = ConversionError("test")
            chunks = processor.process_file(file_path)

        # Find prose chunks: "Introduction" should have URL, "between" chunks should also have URL from marker
        intro_chunks = [c for c in chunks if c.chunk_type == "prose" and "Introduction" in c.content]
        between_chunks = [c for c in chunks if c.chunk_type == "prose" and "between" in c.content and "Introduction" not in c.content]
        
        assert intro_chunks, "Should have intro chunk"
        assert between_chunks, "Should have between chunks"
        
        # All chunks after the URL marker should have source_url from the marker
        assert all(c.metadata.get("source_url") == url for c in intro_chunks), "Intro should have source_url from marker"
        
        # \"between\" sections appear AFTER the URL marker, so they SHOULD have source_url from marker
        # This ensures all chunks have proper attribution to their source file
        assert all(c.metadata.get("source_url") == url for c in between_chunks), "Between chunks should have source_url from marker"

    def test_section_splitting_with_nested_code_blocks(self):
        """Test section splitting correctly handles code blocks."""
        processor = FileProcessor()
        
        content = """# Prose section
Some text here.

```python
def foo():
    pass
```

More prose after code.

```bash
echo "test"
```

Final prose."""
        
        # Make it large enough to trigger splitting
        large_content = content * 1000
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(large_content)
            temp_path = Path(f.name)
        
        try:
            with patch.object(processor.docling_adapter, 'convert_file') as mock_convert:
                from docling.exceptions import ConversionError
                mock_convert.side_effect = ConversionError("test")
                
                chunks = processor.process_file(temp_path)
                
                # Should produce chunks
                assert len(chunks) > 0
        finally:
            temp_path.unlink()

    def test_inline_html_mentions_dont_block_section_splitting(self, tmp_path):
        """Test that inline mentions of HTML tags (e.g., text mentioning '<Tabs>') don't prevent section detection."""
        processor = FileProcessor()
        
        # Create content where <Tabs> is mentioned inline, not as an actual HTML block
        # This should NOT trigger HTML block detection - sections should still be created
        content = """Some text mentioning the <Tabs> component in documentation.

### https://github.com/example/repo/blob/main/section1.md

Content for section 1.

### https://github.com/example/repo/blob/main/section2.md

Content for section 2."""
        
        # Make it large enough to trigger splitting (>100KB)
        large_content = content + ("x" * 100001)
        
        test_file = tmp_path / "test.txt"
        test_file.write_text(large_content, encoding="utf-8")
        
        with patch.object(processor.docling_adapter, 'convert_file') as mock_convert:
            from docling.exceptions import ConversionError
            mock_convert.side_effect = ConversionError("test")
            
            chunks = processor.process_file(test_file)
        
        # Verify sections were created (inline <Tabs> mention didn't block section detection)
        source_urls = [c.metadata.get('source_url', '') for c in chunks]
        
        # Should have chunks from both sections
        assert any('section1.md' in url for url in source_urls), \
            "Section 1 marker should have created chunks with source_url"
        assert any('section2.md' in url for url in source_urls), \
            "Section 2 marker should have created chunks with source_url (not blocked by inline <Tabs> mention)"

    def test_source_url_tracking_across_multiple_markers(self, tmp_path):
        """Test that source URLs are correctly tracked across multiple URL markers."""
        processor = FileProcessor()
        
        # Create content large enough to trigger section splitting (>100 code fences)
        content_parts = ["# Initial content", "Content before first marker.", ""]
        
        # Add first section with code blocks
        content_parts.extend([
            "### https://github.com/org/repo1/blob/main/file1.md",
            "",
            "# Section 1",
            "Content from file1.",
            ""
        ])
        # Add 101 code blocks to trigger section splitting
        for i in range(101):
            content_parts.extend([
                f"```python",
                f"# code block {i} from file1",
                f"print('file1 block {i}')",
                "```",
                ""
            ])
        
        # Add second section
        content_parts.extend([
            "### https://github.com/org/repo2/blob/main/file2.md",
            "",
            "# Section 2",
            "Content from file2.",
            "",
            "```yaml",
            "apiVersion: v1",
            "kind: ConfigMap",
            "```",
            ""
        ])
        
        # Add third section
        content_parts.extend([
            "### https://github.com/org/repo3/blob/main/file3.md",
            "",
            "# Section 3",
            "Content from file3.",
            ""
        ])
        
        content = "\n".join(content_parts)
        test_file = tmp_path / "test_multi_marker.txt"
        test_file.write_text(content)
        
        chunks = processor.process_file(test_file)
        
        # Initial content should have URL from first marker (look-ahead)
        initial_chunks = [c for c in chunks if 'Initial content' in c.content]
        assert len(initial_chunks) > 0, "Should have initial content chunk"
        assert all(c.metadata.get('source_url') == 'https://github.com/org/repo1/blob/main/file1.md' 
                   for c in initial_chunks), "Initial content should use first marker URL"
        
        # Section 1 content should have URL from repo1
        file1_chunks = [c for c in chunks if 'Section 1' in c.content or 'file1' in c.content.lower()]
        assert len(file1_chunks) > 0, "Should have file1 chunks"
        assert all(c.metadata.get('source_url') == 'https://github.com/org/repo1/blob/main/file1.md' 
                   for c in file1_chunks), "File1 content should have repo1 URL"
        
        # Section 2 content should have URL from repo2
        file2_chunks = [c for c in chunks if 'Section 2' in c.content or 'ConfigMap' in c.content]
        assert len(file2_chunks) > 0, "Should have file2 chunks"
        assert all(c.metadata.get('source_url') == 'https://github.com/org/repo2/blob/main/file2.md' 
                   for c in file2_chunks), "File2 content should have repo2 URL"
        
        # Section 3 content should have URL from repo3
        file3_chunks = [c for c in chunks if 'Section 3' in c.content]
        assert len(file3_chunks) > 0, "Should have file3 chunks"
        assert all(c.metadata.get('source_url') == 'https://github.com/org/repo3/blob/main/file3.md' 
                   for c in file3_chunks), "File3 content should have repo3 URL"
    def test_small_plain_text_file_without_section_markers(self, tmp_path):
        """Test processing small plain text file with no section markers or YAML blocks."""
        processor = FileProcessor()
        
        # Create a small plain text file with NO section markers and NO code blocks
        test_file = tmp_path / "plain.txt"
        test_file.write_text("Just some plain text content.\nNo markers, no code blocks.\n", encoding="utf-8")
        
        chunks = processor.process_file(test_file)
        
        # Should create at least one chunk from the plain text
        assert len(chunks) >= 1
        # Content should be preserved
        assert any("plain text content" in chunk.content for chunk in chunks)