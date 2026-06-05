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
    def test_inline_github_link_in_prefixed_heading_is_not_a_marker(self, tmp_path):
        """A heading prefixed with the page's docs URL whose text links to a
        GitHub issue/discussion must keep the docs URL as source_url.

        The ``llms`` step prefixes every heading with the page URL
        (``##### <page-url> <heading text>``). On community pages the heading
        text is itself an inline GitHub issue/discussion link, so the line ends
        up containing ``github.com``. That inline link must NOT be mistaken for
        a file-boundary marker — only a heading whose first token after the
        hashes is a GitHub URL is a genuine marker.
        """
        processor = FileProcessor()

        page = "https://www.asyncapi.com/docs/community/microgrant-program.md"
        content = "\n".join([
            f"### {page}",
            "",
            f"# {page} AsyncAPI Microgrant Program",
            "",
            f"## {page} Preface",
            "",
            "The motivation was to redistribute funds directly to maintainers.",
            "",
            # Prefixed heading whose text is an inline GitHub issue link.
            f"##### {page} https://github.com/asyncapi/community/issues/1072",
            "",
            "Follow-up discussion content about the microgrant program.",
        ])
        # Pad past the 100KB threshold so section splitting is triggered.
        large_content = content + "\n" + ("x" * 100001)

        test_file = tmp_path / "microgrant.txt"
        test_file.write_text(large_content, encoding="utf-8")

        with patch.object(processor.docling_adapter, 'convert_file') as mock_convert:
            from docling.exceptions import ConversionError
            mock_convert.side_effect = ConversionError("test")
            chunks = processor.process_file(test_file)

        source_urls = [c.metadata.get('source_url', '') for c in chunks]

        # The inline GitHub issue link must never become a chunk's source_url.
        assert not any('issues/1072' in url for url in source_urls), \
            f"Inline GitHub issue link wrongly used as source_url: {source_urls}"

        # Content following the inline-link heading keeps the docs page URL.
        followup = [c for c in chunks if 'Follow-up discussion' in c.content]
        assert followup, "Should have the follow-up content chunk"
        assert all(c.metadata.get('source_url') == page for c in followup), \
            f"Follow-up content should keep docs page URL, got: " \
            f"{[c.metadata.get('source_url') for c in followup]}"

    def test_bracketed_marker_uses_page_url_not_base_tag(self, tmp_path):
        """Combined bundles tag every heading with the source's base docs_url in
        brackets, followed by the specific page URL: ``### [base] <page-url>``.
        The chunk source_url must be the specific page URL, not the base tag.
        """
        processor = FileProcessor()
        base = "https://www.asyncapi.com/docs"
        page = "https://www.asyncapi.com/docs/community/maintainership-guide/amp-community-values"
        content = "\n".join([
            f"### [{base}] {page}",
            "",
            f"## [{base}] {page} AMP Builds a Safe and Inclusive Culture",
            "",
            "Holds both mentors and mentees accountable for respectful conduct.",
        ])
        large_content = content + "\n" + ("x" * 100001)
        test_file = tmp_path / "amp_bracketed.txt"
        test_file.write_text(large_content, encoding="utf-8")

        with patch.object(processor.docling_adapter, 'convert_file') as mock_convert:
            from docling.exceptions import ConversionError
            mock_convert.side_effect = ConversionError("test")
            chunks = processor.process_file(test_file)

        docs_urls = [
            (c.metadata or {}).get("source_url")
            for c in chunks
            if "asyncapi.com/docs" in ((c.metadata or {}).get("source_url") or "")
        ]
        assert docs_urls, "Expected chunks attributed to the docs page"
        assert all(u == page for u in docs_urls), \
            f"source_url should be the specific page, not the base tag: {set(docs_urls)}"

    def test_bare_non_github_url_marker_recognized(self, tmp_path):
        """A bare standalone docs-site marker (``### <page-url>``, non-GitHub) is
        a genuine file boundary. Its content must be attributed to that page URL,
        not inherit a previous marker (or end up with no source_url)."""
        processor = FileProcessor()
        page = "https://www.asyncapi.com/docs/community/maintainership-guide/amp-community-values"
        content = "\n".join([
            f"### {page}",
            "",
            "## AMP Builds a Safe and Inclusive Culture",
            "",
            "Holds both mentors and mentees accountable for respectful conduct.",
        ])
        large_content = content + "\n" + ("x" * 100001)
        test_file = tmp_path / "amp_bare.txt"
        test_file.write_text(large_content, encoding="utf-8")

        with patch.object(processor.docling_adapter, 'convert_file') as mock_convert:
            from docling.exceptions import ConversionError
            mock_convert.side_effect = ConversionError("test")
            chunks = processor.process_file(test_file)

        body = [c for c in chunks if "mentors and mentees" in c.content]
        assert body, "Expected the body content chunk"
        assert all((c.metadata or {}).get("source_url") == page for c in body), \
            f"Body should be attributed to the page URL, got: {[(c.metadata or {}).get('source_url') for c in body]}"

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