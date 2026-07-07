"""Tests for the chunker main module."""

import json
import logging
import os
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from types import SimpleNamespace

from opencrane.config import OpenCraneConfig
from opencrane.rag.chunker import (
    _annotate_section_anchors,
    _annotate_source_names,
    _chunk_section_heading,
    main,
)
from opencrane.shared.models.chunk import Chunk


def _stub(chunk_type, content="", metadata=None):
    return SimpleNamespace(chunk_type=chunk_type, content=content, metadata=metadata or {})


class TestChunkSectionHeading:
    """The per-chunk heading used to build the section anchor."""

    def test_prose_uses_first_section_heading(self):
        c = _stub("prose", content="## Who We Serve\nbody text goes here now.")
        assert _chunk_section_heading(c) == "Who We Serve"

    def test_prose_ignores_page_title_h1(self):
        c = _stub("prose", content="# About Page\nintro paragraph without a section.")
        assert _chunk_section_heading(c) is None

    def test_prose_non_string_content_returns_none(self):
        assert _chunk_section_heading(_stub("prose", content={"k": "v"})) is None

    def test_list_item_uses_last_breadcrumb_segment(self):
        c = _stub("list_item", metadata={"breadcrumb_path": "About > Who We Serve"})
        assert _chunk_section_heading(c) == "Who We Serve"

    def test_list_item_single_segment_breadcrumb_returns_none(self):
        c = _stub("list_item", metadata={"breadcrumb_path": "About"})
        assert _chunk_section_heading(c) is None

    def test_list_item_without_breadcrumb_returns_none(self):
        assert _chunk_section_heading(_stub("list_item", metadata={})) is None

    def test_structured_chunk_type_returns_none(self):
        c = _stub("json_schema", metadata={"breadcrumb_path": "properties > config"})
        assert _chunk_section_heading(c) is None


class TestAnnotateSectionAnchors:
    """The pass that records section_anchor on chunks with a source_url."""

    def test_sets_anchor_from_prose_heading(self):
        c = _stub("prose", content="## Who We Serve\nbody",
                  metadata={"source_url": "https://x/about"})
        _annotate_section_anchors([c], OpenCraneConfig())
        assert c.metadata["section_anchor"] == "who-we-serve"

    def test_skips_chunk_without_source_url(self):
        c = _stub("prose", content="## Who We Serve\nbody", metadata={})
        _annotate_section_anchors([c], OpenCraneConfig())
        assert "section_anchor" not in c.metadata

    def test_skips_page_level_prose(self):
        c = _stub("prose", content="# About\nintro",
                  metadata={"source_url": "https://x/about"})
        _annotate_section_anchors([c], OpenCraneConfig())
        assert "section_anchor" not in c.metadata

    def test_style_none_sets_no_anchor(self):
        cfg = OpenCraneConfig()
        cfg.section_anchor_style = "none"
        c = _stub("prose", content="## Who We Serve\nbody",
                  metadata={"source_url": "https://x/about"})
        _annotate_section_anchors([c], cfg)
        assert "section_anchor" not in c.metadata


class TestAnnotateSectionAnchorsEndToEnd:
    """Full chunk pipeline: prose sections get per-chunk anchors, page clean."""

    def test_prose_sections_get_distinct_anchors(self, tmp_path, monkeypatch):
        llms_dir = tmp_path / "llmstxt"
        llms_dir.mkdir()
        (llms_dir / "llms-full.txt").write_text(
            "# About Open Source Europe\nIntro paragraph with enough real text here.\n\n"
            "## Who We Serve\nWe serve open source communities across Europe today.\n\n"
            "## Eligibility Requirements\nYou must meet several requirements to qualify now.\n"
        )
        (llms_dir / "llms.txt").write_text(
            "# Docs\n## ose\n- [About Open Source Europe](https://x/about)\n"
        )
        out = tmp_path / "chunks.json"
        monkeypatch.setenv("AI_DOCS_LLMSTXT_DIR", str(llms_dir))
        monkeypatch.setenv("AI_DOCS_CHUNKS_FILE", str(out))
        main()

        chunks = json.loads(out.read_text())
        by_anchor = {c["metadata"].get("section_anchor") for c in chunks}
        assert "who-we-serve" in by_anchor
        assert "eligibility-requirements" in by_anchor
        # The intro (page-title H1) chunk carries no anchor.
        assert None in by_anchor
        # source_url stays a clean page link (no #fragment) everywhere.
        assert all("#" not in c["metadata"].get("source_url", "") for c in chunks)


class TestChunkerWarnings:
    """Test warning functionality for chunks missing source URLs."""

    def test_warning_when_chunks_missing_source_url(self, tmp_path, caplog):
        """Test that warning is logged and printed when chunks lack source URLs."""
        # Create test input as llms-full.txt in a temp dir
        llms_dir = tmp_path / "llmstxt"
        llms_dir.mkdir()
        (llms_dir / "llms-full.txt").write_text("""# Some content
This is test content without URL markers.

```python
print("hello")
```
""")

        test_output = tmp_path / "test_output.json"

        with patch.dict(os.environ, {
            'AI_DOCS_LLMSTXT_DIR': str(llms_dir),
            'AI_DOCS_CHUNKS_FILE': str(test_output),
        }):
            # Capture stderr
            captured_stderr = StringIO()
            with patch('sys.stderr', captured_stderr):
                # Run with logging at WARNING level
                with caplog.at_level(logging.WARNING):
                    main()

        # Check that warning was logged
        warning_logs = [record for record in caplog.records if record.levelname == 'WARNING']
        assert len(warning_logs) > 0, "Should have warning log"

        warning_message = warning_logs[0].message
        assert 'missing source_url' in warning_message.lower(), "Warning should mention missing source_url"

        # Check that warning was printed to stderr
        stderr_output = captured_stderr.getvalue()
        assert '⚠️' in stderr_output or 'WARNING' in stderr_output, "Should print warning to stderr"
        assert 'missing source_url' in stderr_output.lower(), "stderr should mention missing source_url"

    def test_no_warning_when_all_chunks_have_source_url(self, tmp_path, caplog):
        """Test that no warning is logged when all chunks have source URLs."""
        llms_dir = tmp_path / "llmstxt"
        llms_dir.mkdir()
        lines = ["### https://github.com/org/repo/blob/main/file.md", "", "# Section 1"]
        # Add 60 lines of prose to ensure it's not treated as pure code
        for i in range(60):
            lines.append(f"Line {i+1} of prose content with proper URL marker.")
        lines.extend(["", "```python", "print('hello')", "```", ""])
        (llms_dir / "llms-full.txt").write_text("\n".join(lines))

        test_output = tmp_path / "test_output.json"

        with patch.dict(os.environ, {
            'AI_DOCS_LLMSTXT_DIR': str(llms_dir),
            'AI_DOCS_CHUNKS_FILE': str(test_output),
        }):
            # Capture stderr
            captured_stderr = StringIO()
            with patch('sys.stderr', captured_stderr):
                # Run with logging at WARNING level
                with caplog.at_level(logging.WARNING):
                    main()

        # Check that NO warning was logged about missing source URLs
        warning_logs = [record for record in caplog.records
                        if record.levelname == 'WARNING' and 'missing source_url' in record.message.lower()]
        assert len(warning_logs) == 0, "Should not have warning when all chunks have source_url"

        # Check stderr
        stderr_output = captured_stderr.getvalue()
        assert 'missing source_url' not in stderr_output.lower(), "stderr should not mention missing source_url"

    def test_warning_percentage_calculation(self, tmp_path, caplog):
        """Test that warning includes correct percentage of missing source URLs."""
        llms_dir = tmp_path / "llmstxt"
        llms_dir.mkdir()
        (llms_dir / "llms-full.txt").write_text("""# Before marker
Content without marker.

### https://github.com/org/repo/blob/main/file.md

# After marker
Content with marker.
""")

        test_output = tmp_path / "test_output.json"

        with patch.dict(os.environ, {
            'AI_DOCS_LLMSTXT_DIR': str(llms_dir),
            'AI_DOCS_CHUNKS_FILE': str(test_output),
        }):
            with caplog.at_level(logging.WARNING):
                main()

        # Load the output to check actual chunk count
        with open(test_output) as f:
            chunks = json.load(f)

        # Count chunks without source_url
        chunks_without_source = [c for c in chunks if not c.get('metadata', {}).get('source_url')]

        if chunks_without_source:
            # Check that warning includes percentage
            warning_logs = [record for record in caplog.records if record.levelname == 'WARNING']
            assert len(warning_logs) > 0, "Should have warning"

            warning_message = warning_logs[0].message
            expected_percentage = len(chunks_without_source) / len(chunks) * 100
            # Check that percentage is mentioned (allow for rounding differences)
            assert '%' in warning_message, "Warning should include percentage"
            assert f"{len(chunks_without_source)} out of {len(chunks)}" in warning_message, \
                "Warning should include counts"


class TestChunkerLoadsLlmsIndex:
    """Cover the companion llms.txt index-loading + join branch in main()."""

    def test_index_join_assigns_page_urls(self, tmp_path, caplog):
        """When a companion llms.txt exists, page URLs come from the index join."""
        llms_dir = tmp_path / "llmstxt"
        llms_dir.mkdir()
        (llms_dir / "llms-full.txt").write_text(
            "# Home\nWelcome to the home page content here.\n\n"
            "<!-- opencrane:page -->\n\n"
            "# Setup\nSetup instructions live on this page now.\n"
        )
        (llms_dir / "llms.txt").write_text(
            "# Docs\n## proj\n- [Home](https://x/home)\n- [Setup](https://x/setup)\n"
        )

        test_output = tmp_path / "out.json"
        with patch.dict(os.environ, {
            'AI_DOCS_LLMSTXT_DIR': str(llms_dir),
            'AI_DOCS_CHUNKS_FILE': str(test_output),
        }):
            with caplog.at_level(logging.INFO):
                main()

        with open(test_output) as f:
            chunks = json.load(f)
        urls = {c.get("metadata", {}).get("source_url") for c in chunks}
        assert "https://x/home" in urls
        assert "https://x/setup" in urls
        assert any("Loaded llms.txt index" in r.message for r in caplog.records)


class TestAnnotateSourceNames:
    """Verify chunks pick up source_name from the source mapping."""

    def test_sets_source_name_from_metadata_url(self, tmp_path):
        mapping_file = tmp_path / "config.yaml"
        mapping_file.write_text(yaml.safe_dump({
            "sources": {
                "Org/repo-a": {"url": "https://github.com/Org/repo-a"},
            }
        }))
        chunks = [
            Chunk(
                content="alpha",
                source_file="llms-full.txt",
                chunk_type="prose",
                metadata={"source_url": "https://github.com/Org/repo-a/blob/main/x.md"},
                token_count=1,
            ),
            Chunk(
                content="beta",
                source_file="llms-full.txt",
                chunk_type="prose",
                metadata={"source_url": "https://other.example/foo"},
                token_count=1,
            ),
        ]
        _annotate_source_names(chunks, mapping_file)
        assert chunks[0].source_name == "Org/repo-a"
        assert chunks[1].source_name is None

    def test_no_op_when_mapping_file_missing(self, tmp_path):
        chunk = Chunk(
            content="alpha",
            source_file="llms-full.txt",
            chunk_type="prose",
            metadata={"source_url": "https://github.com/Org/repo-a/x"},
            token_count=1,
        )
        _annotate_source_names([chunk], tmp_path / "missing.yaml")
        assert chunk.source_name is None


class TestChunkerRelativeMappingFile:
    """Cover the relative mapping_file resolution branch in main()."""

    def test_relative_mapping_file_resolved_against_cwd(self, tmp_path, monkeypatch):
        """A relative MAPPING_FILE is joined with cwd before annotation (line 55)."""
        # Work entirely inside a temp dir used as the cwd.
        monkeypatch.chdir(tmp_path)

        llms_dir = tmp_path / "llmstxt"
        llms_dir.mkdir()
        lines = ["### https://github.com/org/repo/blob/main/file.md", "", "# Section 1"]
        for i in range(60):
            lines.append(f"Line {i+1} of prose content with proper URL marker.")
        (llms_dir / "llms-full.txt").write_text("\n".join(lines))

        # A relative mapping file that resolves under cwd and actually exists,
        # so the is_absolute() guard is False and Path.cwd() is prepended.
        rel_mapping = Path(".opencrane") / "config.yaml"
        (tmp_path / ".opencrane").mkdir()
        (tmp_path / rel_mapping).write_text(yaml.safe_dump({
            "sources": {
                "org/repo": {"url": "https://github.com/org/repo"},
            }
        }))

        test_output = tmp_path / "out.json"

        monkeypatch.setenv("MAPPING_FILE", str(rel_mapping))
        monkeypatch.setenv("AI_DOCS_LLMSTXT_DIR", str(llms_dir))
        monkeypatch.setenv("AI_DOCS_CHUNKS_FILE", str(test_output))

        main()

        with open(test_output) as f:
            chunks = json.load(f)
        # Source name should be resolved from the relative mapping file.
        assert any(c.get("source_name") == "org/repo" for c in chunks)
