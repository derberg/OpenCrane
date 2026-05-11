import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch
from opencrane.rag.generate_llms_txt import generate_outputs


class TestGenerateLlmsEndToEnd:
    """Integration tests for end-to-end LLM text generation."""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary sources and llmstxt directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir)
            sources_dir = base_path / "external-sources"
            llmstxt_dir = base_path / "llmstxt"
            sources_dir.mkdir()
            llmstxt_dir.mkdir()
            yield sources_dir, llmstxt_dir

    def test_generate_outputs_with_markdown_files(self, temp_dirs):
        """Test end-to-end generation with sample markdown files."""
        sources_dir, llmstxt_dir = temp_dirs

        # Create a source directory with project subdirectories
        source_dir = sources_dir / "test-source"
        source_dir.mkdir()
        
        project1_dir = source_dir / "project1"
        project1_dir.mkdir()
        (project1_dir / "doc1.md").write_text("# Document 1\n\nThis is the first document.\n\n[Link to doc2](doc2.md)")
        (project1_dir / "doc2.md").write_text("# Document 2\n\nThis is the second document.\n\n![Image](image.png)")

        project2_dir = source_dir / "project2"
        project2_dir.mkdir()
        (project2_dir / "doc3.md").write_text("# Document 3\n\nContent in project2.")

        # Patch the global paths for new multi-source behavior
        with patch('opencrane.rag.generate_llms_txt.SOURCES_BASE', sources_dir), \
             patch('opencrane.rag.generate_llms_txt.SOURCE_ROOT', source_dir), \
             patch.dict('os.environ', {'AI_DOCS_SOURCES_DIRS': str(source_dir), 'AI_DOCS_LLMSTXT_DIR': str(llmstxt_dir)}, clear=False):
            # Run the generation
            generate_outputs()

        # Assert output files are created
        output_dir = llmstxt_dir / "test-source"
        llms_full = output_dir / "llms-full.txt"
        project1_llms = output_dir / "project1" / "llms-full.txt"
        project2_llms = output_dir / "project2" / "llms-full.txt"

        assert llms_full.exists(), "llms-full.txt should be created"
        assert project1_llms.exists(), "project1/llms-full.txt should be created"
        assert project2_llms.exists(), "project2/llms-full.txt should be created"

        # Check content of combined llms-full.txt
        content = llms_full.read_text()
        # Verify both projects' content is included (no artificial metadata headers)
        assert "Document 1" in content
        assert "Document 2" in content
        assert "Document 3" in content
        assert "This is the first document." in content
        assert "This is the second document." in content
        assert "Content in project2." in content

        # Check that images are stripped
        assert "[Image removed:" in content

        # Check per-project content
        project1_content = project1_llms.read_text()
        assert "Document 1" in project1_content
        assert "Document 2" in project1_content
        assert "This is the first document." in project1_content

        project2_content = project2_llms.read_text()
        assert "Document 3" in project2_content
        assert "Content in project2." in project2_content

    def test_generate_outputs_empty_directory(self, temp_dirs):
        """Test generation with no project directories."""
        sources_dir, llmstxt_dir = temp_dirs

        # Create empty source directory
        source_dir = sources_dir / "empty-source"
        source_dir.mkdir()

        # Patch the global paths
        with patch('opencrane.rag.generate_llms_txt.SOURCES_BASE', sources_dir), \
             patch('opencrane.rag.generate_llms_txt.SOURCE_ROOT', source_dir), \
             patch.dict('os.environ', {'AI_DOCS_SOURCES_DIRS': str(source_dir), 'AI_DOCS_LLMSTXT_DIR': str(llmstxt_dir)}, clear=False):
            # Run the generation
            generate_outputs()

        # Assert no output files created for empty source
        output_dir = llmstxt_dir / "empty-source"
        assert not output_dir.exists() or not list(output_dir.iterdir()), "No files should be created for empty source"

    def test_generate_outputs_multi_source_new_path(self, temp_dirs):
        """Test new multi-source code path with multiple sources."""
        sources_dir, llmstxt_dir = temp_dirs

        # Create source1 with projects
        source1_dir = sources_dir / "source1"
        source1_dir.mkdir()
        (source1_dir / "proj-a").mkdir()
        (source1_dir / "proj-a" / "file1.md").write_text("# Source 1 Project A\n\nContent A")
        (source1_dir / "proj-b").mkdir()
        (source1_dir / "proj-b" / "file2.md").write_text("# Source 1 Project B\n\nContent B")
        # Add a project with no markdown files (should be skipped)
        (source1_dir / "proj-empty").mkdir()

        # Create source2 with root markdown only
        source2_dir = sources_dir / "source2"
        source2_dir.mkdir()
        (source2_dir / "ROOT.md").write_text("# Root Level Doc\n\nRoot content")

        # Patch paths to use temp dirs
        with patch('opencrane.rag.generate_llms_txt.SOURCES_BASE', sources_dir), \
             patch('opencrane.rag.generate_llms_txt.SOURCE_ROOT', source1_dir), \
             patch.dict('os.environ', {'AI_DOCS_SOURCES_DIRS': f"{source1_dir},{source2_dir}", 'AI_DOCS_LLMSTXT_DIR': str(llmstxt_dir)}, clear=False):
            # Run generation (will process all sources)
            generate_outputs()

        # Verify source1 outputs
        source1_out = llmstxt_dir / "source1"
        assert (source1_out / "llms-full.txt").exists()
        assert (source1_out / "proj-a" / "llms-full.txt").exists()
        assert (source1_out / "proj-b" / "llms-full.txt").exists()
        # proj-empty should not have output (no markdown files)
        assert not (source1_out / "proj-empty" / "llms-full.txt").exists()
        
        source1_combined = (source1_out / "llms-full.txt").read_text()
        assert "Source 1 Project A" in source1_combined
        assert "Source 1 Project B" in source1_combined

        # Verify source2 outputs (root-level markdown)
        source2_out = llmstxt_dir / "source2"
        assert (source2_out / "llms-full.txt").exists()
        # Root-level projects should NOT create nested folder
        assert not (source2_out / "source2" / "llms-full.txt").exists()
        
        source2_combined = (source2_out / "llms-full.txt").read_text()
        assert "Root Level Doc" in source2_combined  # Should be empty when no projects

    def test_local_source_no_duplicate_in_combined(self):
        """Regression: local sources must not duplicate content in all-projects llms-full.txt.

        When a project uses a local source (local: true in config.yaml), the combined
        llms-full.txt at LLMSTXT_BASE must contain each document exactly once.
        Previously, write_outputs() wrote the combined file to LLMSTXT_BASE and then
        the top-level combiner re-read that file AND the per-source subdir, producing
        content twice (2x token count visible in `opencrane tokens` output).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            # Simulate a project layout: workspace/telna/<docs>.md
            docs_dir = workspace / "telna"
            docs_dir.mkdir()
            (docs_dir / "overview.md").write_text("# Overview\n\nUnique content here.")
            (docs_dir / "api.md").write_text("# API Reference\n\nEndpoint details.")

            # Write a config.yaml with one local source
            opencrane_dir = workspace / ".opencrane"
            opencrane_dir.mkdir()
            (opencrane_dir / "config.yaml").write_text(
                "sources:\n"
                "  telna:\n"
                "    local: true\n"
                "    docs_path: telna\n"
                "    url: https://github.com/example/telna-docs\n"
            )

            orig_dir = os.getcwd()
            try:
                os.chdir(workspace)
                # Override MAPPING_FILE so get_source_mapping() reads the workspace config
                # (conftest.py's isolate_outputs autouse fixture sets MAPPING_FILE to a
                # shared test fixture, which would cause generate_outputs to see no sources).
                import opencrane.rag.generate_llms_txt as gen_mod
                gen_mod._source_mapping = None
                with patch.dict(os.environ, {"MAPPING_FILE": str(opencrane_dir / "config.yaml")}):
                    generate_outputs()
            finally:
                os.chdir(orig_dir)
                gen_mod._source_mapping = None

            llmstxt_base = workspace / ".opencrane" / "llmstxt"
            combined = llmstxt_base / "llms-full.txt"
            per_source = llmstxt_base / "telna" / "llms-full.txt"

            assert combined.exists(), "Combined llms-full.txt must exist"
            assert per_source.exists(), "Per-source telna/llms-full.txt must exist"

            combined_text = combined.read_text()
            per_source_text = per_source.read_text()

            # Each unique phrase must appear exactly once in the combined file
            assert combined_text.count("Unique content here.") == 1, (
                "Content duplicated in combined llms-full.txt — top-level combiner re-added per-source content"
            )
            assert combined_text.count("Endpoint details.") == 1

            # Combined and per-source files should have the same content
            assert combined_text == per_source_text, (
                "Combined llms-full.txt differs from per-source file — unexpected extra content"
            )

