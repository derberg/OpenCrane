import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock
from opencrane.rag.generate_llms_txt import (
    slugify,
    build_anchor,
    strip_images,
    rewrite_links,
    get_github_url,
    prefix_headings_with_path,
    process_file,
    process_fence_blocks,
    build_project_output,
    write_outputs,
    generate_outputs,
    CodeFenceConfig,
)
from opencrane.rag.services.source_mapping import SourceMapping


class TestSlugify:
    """Unit tests for slugify function."""

    def test_basic_slugify(self):
        """Test basic slugification."""
        assert slugify("Hello World") == "hello-world"
        assert slugify("Test Case 123") == "test-case-123"

    def test_special_characters(self):
        """Test handling of special characters."""
        assert slugify("Hello! @#$% World?") == "hello-world"
        assert slugify("C++ & Python") == "c-python"

    def test_multiple_hyphens(self):
        """Test multiple consecutive hyphens are reduced."""
        assert slugify("a--b___c") == "a-b-c"

    def test_empty_and_whitespace(self):
        """Test empty string and whitespace handling."""
        assert slugify("") == "section"
        assert slugify("   ") == "section"
        assert slugify("---") == "section"


class TestBuildAnchor:
    """Unit tests for build_anchor function."""

    def test_anchor_without_heading(self):
        """Test anchor building without heading."""
        path = Path("project/docs/file.md")
        assert build_anchor(path) == "project-docs-file-md"

    def test_anchor_with_heading(self):
        """Test anchor building with heading."""
        path = Path("project/docs/file.md")
        assert build_anchor(path, "Test Heading") == "project-docs-file-md-test-heading"

    def test_anchor_with_special_chars(self):
        """Test anchor with special characters in path and heading."""
        path = Path("project/docs/file-name.md")
        assert build_anchor(path, "Test & Heading!") == "project-docs-file-name-md-test-heading"


class TestStripImages:
    """Unit tests for strip_images function."""

    def test_markdown_images(self):
        """Test removal of markdown image syntax."""
        text = 'Here is an image: ![alt text](image.jpg) and another ![second](path/to/img.png)'
        result = strip_images(text)
        expected = 'Here is an image: [Image removed: alt text] and another [Image removed: second]'
        assert result == expected

    def test_html_images(self):
        """Test removal of HTML img tags."""
        text = '<img src="image.jpg" alt="alt text"> and <img src="path/to/img.png">'
        result = strip_images(text)
        expected = '[Image removed: alt text] and [Image removed: image]'
        assert result == expected

    def test_mixed_images(self):
        """Test removal of both markdown and HTML images."""
        text = 'Markdown: ![alt](img.jpg) HTML: <img src="img.png" alt="test">'
        result = strip_images(text)
        expected = 'Markdown: [Image removed: alt] HTML: [Image removed: test]'
        assert result == expected

    def test_no_images(self):
        """Test text without images remains unchanged."""
        text = "Just regular text without images."
        assert strip_images(text) == text


class TestRewriteLinks:
    """Unit tests for rewrite_links function."""

    def test_relative_markdown_links(self):
        """Test rewriting of relative markdown links - now simplified to just labels."""
        text = '[link](./other.md) and [another](../parent/file.md#section)'
        result = rewrite_links(text, Path("project/current.md"), Path("project/current.md"), Path("project"), "project")
        # Internal markdown links are simplified to just labels for AI agent consumption
        expected = 'link and another'
        assert result == expected

    def test_relative_markdown_links_outside_project(self):
        """Test rewriting of relative markdown links that go outside workspace."""
        text = '[link](../outside/other.md)'
        result = rewrite_links(text, Path("project/current.md"), Path("project/current.md"), Path("project"), "project")
        # All internal markdown links are simplified to labels regardless of path
        expected = 'link'
        assert result == expected

    def test_relative_markdown_links_os_error(self):
        """Test rewriting of relative markdown links - no longer throws OSError."""
        text = '[link](./other.md)'
        # New implementation doesn't resolve paths, just strips URLs
        result = rewrite_links(text, Path("project/current.md"), Path("project/current.md"), Path("project"), "project")
        expected = 'link'
        assert result == expected

    def test_absolute_links_unchanged(self):
        """Test that absolute links remain unchanged."""
        text = '[external](https://example.com) and [absolute](/path/file.md)'
        anchors = {}
        result = rewrite_links(text, Path("current.md"), Path("project/current.md"), Path("project"), "project")
        # External links stay, absolute links get removed
        expected = '[external](https://example.com) and absolute (link removed: /path/file.md)'
        assert result == expected

    def test_links_with_data_url(self):
        """Test links with data URLs."""
        text = '[data](data:image/png;base64,abc123)'
        result = rewrite_links(text, Path("current.md"), Path("project/current.md"), Path("project"), "project")
        # Data URLs are removed
        expected = 'data (inline data removed)'
        assert result == expected

    def test_links_with_hash_only(self):
        """Test links with hash fragments - simplified to labels."""
        text = '[heading](#section)'
        result = rewrite_links(text, Path("current.md"), Path("project/current.md"), Path("project"), "project")
        # Same-file anchors are also simplified to just labels
        expected = 'heading'
        assert result == expected

    def test_links_with_pdf_left_unchanged(self):
        """Non-markdown assets should not be rewritten to anchors."""
        text = '[spec](../files/spec.pdf)'
        result = rewrite_links(text, Path("project/docs/current.md"), Path("project/docs/current.md"), Path("project"), "project")
        assert result == text


class TestGetGithubUrl:
    """Unit tests for get_github_url function."""

    def test_external_product_docs(self):
        """Test GitHub URL generation for external product-docs."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)
            mapping.add_source(
                path_key="external-sources/product-a/extension-b",
                github_url="https://github.com/test/extension-b",
                docs_path="docs"
            )
            mapping.save()
            
            with patch("opencrane.rag.generate_llms_txt._source_mapping", mapping):
                rel_path = Path("external-sources/product-a/extension-b/docs/guide.md")
                result = get_github_url(rel_path, "extension-b")
                assert result == "https://github.com/test/extension-b/blob/main/docs/guide.md"

    def test_internal_content_guidelines(self):
        """Test GitHub URL generation for internal content-guidelines."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)
            mapping.add_source(
                path_key="guidelines-dir",
                github_url="https://github.com/test/main-repo",
                docs_path=""
            )
            mapping.save()
            
            with patch("opencrane.rag.generate_llms_txt._source_mapping", mapping):
                rel_path = Path("guidelines-dir/strategy/component-doc.md")
                result = get_github_url(rel_path, "main-repo")
                assert result == "https://github.com/test/main-repo/blob/main/guidelines-dir/strategy/component-doc.md"

    def test_internal_other_path_with_mapping(self):
        """Test GitHub URL generation for other internal paths."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)
            mapping.add_source(
                path_key="some/other",
                github_url="https://github.com/test/main-repo",
                docs_path=""
            )
            mapping.save()

            with patch("opencrane.rag.generate_llms_txt._source_mapping", mapping):
                rel_path = Path("some/other/path/file.md")
                result = get_github_url(rel_path, "main-repo")
                assert result == "https://github.com/test/main-repo/blob/main/some/other/path/file.md"

    def test_returns_none_when_no_mapping(self):
        """Test that None is returned when no mapping entry exists for the file."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)
            mapping.save()

            with patch("opencrane.rag.generate_llms_txt._source_mapping", mapping):
                rel_path = Path("unmapped/path/file.md")
                result = get_github_url(rel_path, "some-project")
                assert result is None

    def test_docs_url_takes_precedence_over_github_url(self):
        """Test that docs_url is used instead of github_url when set."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)
            mapping.add_source(
                path_key="external-sources/product-a",
                github_url="https://github.com/test/product-a",
                docs_path="docs",
                docs_url="https://docs.example.com/product-a"
            )
            mapping.save()

            with patch("opencrane.rag.generate_llms_txt._source_mapping", mapping):
                rel_path = Path("external-sources/product-a/docs/guide.md")
                result = get_github_url(rel_path, "product-a")
                assert result == "https://docs.example.com/product-a/guide.md"

    def test_docs_url_without_docs_path(self):
        """Test docs_url when no docs_path is set."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)
            mapping.add_source(
                path_key="my-source",
                github_url="https://github.com/test/repo",
                docs_path="",
                docs_url="https://docs.example.com"
            )
            mapping.save()

            with patch("opencrane.rag.generate_llms_txt._source_mapping", mapping):
                rel_path = Path("my-source/guide/intro.md")
                result = get_github_url(rel_path, "my-source")
                assert result == "https://docs.example.com/guide/intro.md"


class TestPrefixHeadingsWithPath:
    """Unit tests for prefix_headings_with_path function."""

    def test_heading_prefixing(self):
        """Test adding GitHub source links to headings."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)
            mapping.add_source(
                path_key="project-a",
                github_url="https://github.com/test/project-a",
                docs_path=""
            )
            mapping.save()
            
            with patch("opencrane.rag.generate_llms_txt._source_mapping", mapping):
                content = "# Main Title\n\nSome content\n\n## Sub Title\n\nMore content"
                rel_path = Path("project-a/docs/file.md")
                result = prefix_headings_with_path(content, rel_path, "project-a")
                expected = "# https://github.com/test/project-a/blob/main/project-a/docs/file.md Main Title\n\nSome content\n\n## https://github.com/test/project-a/blob/main/project-a/docs/file.md Sub Title\n\nMore content"
                assert result == expected

    def test_no_headings(self):
        """Test content without headings."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)
            mapping.add_source(
                path_key="project-a",
                github_url="https://github.com/test/project-a",
                docs_path=""
            )
            mapping.save()

            with patch("opencrane.rag.generate_llms_txt._source_mapping", mapping):
                content = "Just plain text content."
                rel_path = Path("project-a/file.md")
                result = prefix_headings_with_path(content, rel_path, "project-a")
                assert result == content

    def test_no_url_headings_preserved_without_prefix(self):
        """Test that headings are kept as-is when no URL is available."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)
            mapping.save()

            with patch("opencrane.rag.generate_llms_txt._source_mapping", mapping):
                content = "# Main Title\n\nSome content"
                rel_path = Path("unmapped/file.md")
                result = prefix_headings_with_path(content, rel_path, "unmapped")
                assert result == content


class TestProcessFenceBlocks:
    """Unit tests for process_fence_blocks dispatch mechanism."""

    def test_no_fence_types_returns_text_unchanged(self):
        """Text is returned as-is when no fence_types are registered."""
        text = "Regular markdown content."
        result = process_fence_blocks(text, Path("file.md"), Path("project"), "project")
        assert result == text

    def test_handler_called_with_correct_args(self):
        """Handler receives raw content plus file context."""
        calls = []

        def stub_handler(content, file_path, project_dir, project_name):
            calls.append((content, file_path, project_dir, project_name))
            return "REPLACED"

        text = "Before\n\n```crd\nsome/file.yaml\n```\n\nAfter"
        file_path = Path("/proj/docs/page.md")
        project_dir = Path("/proj")
        fence_types = {"crd": CodeFenceConfig(fence_type="crd", handler=stub_handler)}

        result = process_fence_blocks(text, file_path, project_dir, "myproject", fence_types=fence_types)

        assert len(calls) == 1
        assert calls[0] == ("some/file.yaml", file_path, project_dir, "myproject")
        assert "REPLACED" in result

    def test_unregistered_fence_type_left_unchanged(self):
        """Fence blocks whose type is not in fence_types are left as-is."""
        text = "```unknown\nsome content\n```"
        stub = CodeFenceConfig(fence_type="crd", handler=lambda c, f, d, n: "X")
        result = process_fence_blocks(text, Path("f.md"), Path("p"), "p", fence_types={"crd": stub})
        assert result == text


class TestProcessFile:
    """Unit tests for process_file function."""

    def test_process_file(self):
        """Test processing a file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Setup mapping
            mapping_file = Path(temp_dir) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)
            mapping.add_source(
                path_key="project-a",
                github_url="https://github.com/test/project-a",
                docs_path=""
            )
            mapping.save()
            
            with patch("opencrane.rag.generate_llms_txt._source_mapping", mapping):
                project_dir = (Path(temp_dir) / "project-a").resolve()
                project_dir.mkdir()
                docs_dir = project_dir / "docs"
                docs_dir.mkdir()
                file_path = docs_dir / "test.md"
                file_path.write_text("# Test Heading\n\nSome content with [link](./other.md)")

                result = process_file(file_path, project_dir, "project-a")

                assert "### https://github.com/test/project-a/blob/main/project-a/docs/test.md" in result
                assert "# https://github.com/test/project-a/blob/main/project-a/docs/test.md Test Heading" in result
                assert "Some content with" in result

    def test_process_file_no_url(self):
        """Test that process_file omits source link when no mapping exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            mapping_file = Path(temp_dir) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)
            mapping.save()

            with patch("opencrane.rag.generate_llms_txt._source_mapping", mapping):
                project_dir = (Path(temp_dir) / "project-a").resolve()
                project_dir.mkdir()
                file_path = project_dir / "test.md"
                file_path.write_text("# Test Heading\n\nSome content")

                result = process_file(file_path, project_dir, "project-a")

                assert "###" not in result
                assert "# Test Heading" in result
                assert "Some content" in result


class TestBuildProjectOutput:
    """Unit tests for build_project_output function."""
    def test_build_project_output(self):
        """Test building project output from multiple files."""
        # Create temporary directory structure
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "project"
            project_dir.mkdir()

            # Create test files
            (project_dir / "file1.md").write_text("# File 1")
            (project_dir / "file2.md").write_text("# File 2")
            (project_dir / "subdir").mkdir()
            (project_dir / "subdir" / "file3.md").write_text("# File 3")

            result = build_project_output(project_dir)

            # Should have processed all files
            assert "File 1" in result
            assert "File 2" in result
            assert "File 3" in result
            assert "----" in result  # Separator between files


class TestWriteOutputs:
    """Unit tests for write_outputs function."""

    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.write_text")
    def test_write_outputs(self, mock_write, mock_mkdir):
        """Test writing output files."""
        project_outputs = {
            "project1": "Content 1",
            "project2": "Content 2",
            "combined": "Combined content"
        }

        write_outputs(project_outputs)

        # Should create directories and write files
        assert mock_mkdir.call_count >= 3  # At least one for OUTPUT_ROOT and one per project
        assert mock_write.call_count == 4  # 2 per-project + 1 combined + 1 combined header?


class TestGenerateOutputs:
    """Unit tests for generate_outputs function."""

    def test_generate_outputs_missing_env_var(self, tmp_path, capsys):
        """Test that generation is skipped gracefully when no sources are configured."""
        import opencrane.rag.generate_llms_txt as mod
        empty_mapping = tmp_path / "opencrane-sources.yaml"
        empty_mapping.write_text("sources: {}\n")
        original = mod._source_mapping
        mod._source_mapping = None
        try:
            with patch.dict("os.environ", {"OPENCRANE_MAPPING_FILE": str(empty_mapping)}, clear=False):
                with patch("opencrane.rag.generate_llms_txt.get_source_mapping") as mock_mapping:
                    mock_mapping.return_value.data = {"sources": {}}
                    generate_outputs()
            captured = capsys.readouterr()
            assert "No sources configured" in captured.out
        finally:
            mod._source_mapping = original

    def test_generate_outputs_no_source(self):
        """Default path should not depend on SOURCE_ROOT existing."""
        with patch("opencrane.rag.generate_llms_txt.SOURCES_BASE") as mock_sources, \
             patch.dict("os.environ", {"AI_DOCS_SOURCES_DIRS": "test-source"}, clear=False):
            mock_sources.exists.return_value = True
            mock_sources.iterdir.return_value = []
            # Should not raise: default path processes SOURCES_BASE, not SOURCE_ROOT
            generate_outputs()

    def test_generate_outputs_no_sources_base(self):
        """Test generate_outputs when SOURCES_BASE doesn't exist (legacy path)."""
        with patch("opencrane.rag.generate_llms_txt.SOURCE_ROOT") as mock_source, \
             patch("opencrane.rag.generate_llms_txt.SOURCES_BASE") as mock_sources:
            mock_source.exists.return_value = False  # SOURCE_ROOT doesn't exist
            mock_sources.exists.return_value = False
            with pytest.raises(FileNotFoundError):
                generate_outputs(selected_projects=["proj"])

    def test_generate_outputs_legacy_no_source(self):
        """Test legacy path when SOURCE_ROOT doesn't exist."""
        with patch("opencrane.rag.generate_llms_txt.SOURCE_ROOT") as mock_source:
            mock_source.exists.return_value = False
            with pytest.raises(FileNotFoundError):
                generate_outputs(selected_projects=["proj1"])

    @patch.dict(
        "os.environ",
        {"AI_DOCS_SOURCES_DIR": "__SOURCES__", "AI_DOCS_LLMSTXT_DIR": "__LLMSTXT__"},
        clear=False,
    )
    @patch("opencrane.rag.generate_llms_txt.write_outputs")
    def test_generate_outputs_env_overrides_update_output_root(self, mock_write, tmp_path):
        """Test env overrides update SOURCES_BASE/OUTPUT_ROOT for legacy path."""
        sources_dir = tmp_path / "sources"
        llmstxt_dir = tmp_path / "llmstxt"
        (sources_dir / "proj1").mkdir(parents=True)
        (sources_dir / "proj1" / "doc.md").write_text("# Hi", encoding="utf-8")

        with patch.dict(
            "os.environ",
            {"AI_DOCS_SOURCES_DIR": str(sources_dir), "AI_DOCS_LLMSTXT_DIR": str(llmstxt_dir)},
            clear=False,
        ):
            # Exercise the legacy code path so SOURCE_ROOT sync matters
            generate_outputs(selected_projects=[])

        assert mock_write.call_count == 1
        # Signature: write_outputs(project_outputs, output_root, root_projects)
        output_root_arg = mock_write.call_args.args[1]
        assert output_root_arg == llmstxt_dir

    @patch("opencrane.rag.generate_llms_txt.write_outputs")
    @patch("opencrane.rag.generate_llms_txt.build_project_output")
    def test_generate_outputs_legacy_path_with_selected_projects(self, mock_build, mock_write):
        """Test legacy code path with selected_projects parameter."""
        mock_build.return_value = "test output"
        
        with patch("opencrane.rag.generate_llms_txt.SOURCE_ROOT") as mock_source:
            mock_source.exists.return_value = True
            
            # Create mock project directories
            mock_proj1 = MagicMock()
            mock_proj1.is_dir.return_value = True
            mock_proj1.name = "proj1"
            mock_proj1.rglob.return_value = [Path("test.md")]
            
            mock_proj2 = MagicMock()
            mock_proj2.is_dir.return_value = True
            mock_proj2.name = "proj2"
            mock_proj2.rglob.return_value = [Path("test2.md")]
            
            # Mock project with no markdown files (should trigger continue on line 237)
            mock_proj3 = MagicMock()
            mock_proj3.is_dir.return_value = True
            mock_proj3.name = "proj3"
            mock_proj3.rglob.return_value = []  # No markdown files
            
            mock_source.iterdir.return_value = [mock_proj1, mock_proj2, mock_proj3]
            
            # Call with selected projects including one with no files
            generate_outputs(selected_projects=["proj1", "proj3"])
            
            # Should only build proj1 (proj3 has no md files and continues)
            assert mock_build.call_count == 1
            mock_write.assert_called_once()

    def test_generate_outputs_multiple_sources_dirs(self, tmp_path):
        """Test AI_DOCS_SOURCES_DIRS with multiple comma-separated directories."""
        # Create two separate source directories
        source1 = tmp_path / "source1"
        source2 = tmp_path / "source2"
        llmstxt_dir = tmp_path / "llmstxt"
        
        # Create structure: source1/docs/ and source2/docs/
        (source1 / "docs").mkdir(parents=True)
        (source2 / "docs").mkdir(parents=True)
        (source1 / "docs" / "test1.md").write_text("# Test 1", encoding="utf-8")
        (source2 / "docs" / "test2.md").write_text("# Test 2", encoding="utf-8")
        
        # Set environment variable with comma-separated paths
        sources_csv = f"{source1},{source2}"
        
        with patch.dict(
            "os.environ",
            {
                "AI_DOCS_SOURCES_DIRS": sources_csv,
                "AI_DOCS_LLMSTXT_DIR": str(llmstxt_dir)
            },
            clear=False,
        ):
            generate_outputs()
        
        # Verify outputs were created for both sources
        assert (llmstxt_dir / "source1" / "llms-full.txt").exists()
        assert (llmstxt_dir / "source2" / "llms-full.txt").exists()
        assert (llmstxt_dir / "llms-full.txt").exists()
        
        # Verify combined file contains content from both sources
        combined = (llmstxt_dir / "llms-full.txt").read_text(encoding="utf-8")
        assert "Test 1" in combined
        assert "Test 2" in combined

    def test_generate_outputs_sources_dirs_with_nonexistent_dir(self, tmp_path, capsys):
        """Test AI_DOCS_SOURCES_DIRS handles non-existent directories gracefully."""
        source1 = tmp_path / "source1"
        nonexistent = tmp_path / "nonexistent"
        llmstxt_dir = tmp_path / "llmstxt"
        
        (source1 / "docs").mkdir(parents=True)
        (source1 / "docs" / "test.md").write_text("# Test", encoding="utf-8")
        
        sources_csv = f"{source1},{nonexistent}"
        
        with patch.dict(
            "os.environ",
            {
                "AI_DOCS_SOURCES_DIRS": sources_csv,
                "AI_DOCS_LLMSTXT_DIR": str(llmstxt_dir)
            },
            clear=False,
        ):
            generate_outputs()
        
        # Check warning was printed
        captured = capsys.readouterr()
        assert "Warning: Source directory not found" in captured.out

    def test_generate_outputs_sources_under_cwd(self, tmp_path, monkeypatch, isolate_outputs):
        """Test that source directories under cwd use relative paths in output."""
        # Create structure under a fake cwd
        fake_cwd = tmp_path / "workspace"
        fake_cwd.mkdir()
        
        # Change to fake_cwd FIRST so we can create dirs under it
        monkeypatch.chdir(fake_cwd)
        
        # Now create directories using relative paths (they'll be under cwd)
        source_dir = Path("docs")  # Relative path, will be under cwd
        source_dir.mkdir()
        (source_dir / "proj1").mkdir()
        (source_dir / "proj1" / "test.md").write_text("# Test\n\nContent", encoding="utf-8")
        
        llmstxt_dir = Path("llmstxt")  # Relative path, will be under cwd
        
        with patch.dict(
            "os.environ",
            {
                "AI_DOCS_SOURCES_DIRS": str(source_dir.resolve()),  # Use absolute path
                "AI_DOCS_LLMSTXT_DIR": str(llmstxt_dir.resolve()),
                "AI_DOCS_NO_FILTER": "1"  # Disable filtering for this test
            },
            clear=False,
        ):
            generate_outputs()
        
        # Verify output uses relative path structure
        assert (llmstxt_dir / "docs" / "llms-full.txt").exists()
        assert (llmstxt_dir / "docs" / "proj1" / "llms-full.txt").exists()


    def test_generate_outputs_with_source_mapping_filter(self, tmp_path, monkeypatch, isolate_outputs):
        """Test that generation filters based on opencrane-sources.yaml."""
        # Use a directory under workspace root so filtering logic works
        # (filtering is disabled for paths outside workspace root)
        original_cwd = Path.cwd()
        test_artifacts = original_cwd / ".test_artifacts"

        # Clean up any previous test artifacts
        if test_artifacts.exists():
            shutil.rmtree(test_artifacts)

        try:
            # Create test workspace directory and change to it
            test_artifacts.mkdir(parents=True)
            monkeypatch.chdir(test_artifacts)

            # Now create directories using relative paths (they'll be under cwd)
            source_dir = Path("sources")
            source_dir.mkdir()

            # Root markdown file (should be filtered)
            (source_dir / "root.md").write_text("# Root Doc", encoding="utf-8")

            proj_a = source_dir / "proj-a"
            proj_b = source_dir / "proj-b"
            proj_c = source_dir / "proj-c"  # Will be filtered out

            for proj in [proj_a, proj_b, proj_c]:
                proj.mkdir()
                (proj / "doc.md").write_text(f"# {proj.name}", encoding="utf-8")

            # Add subproject under proj-a
            subproj = proj_a / "subproject"
            subproj.mkdir()
            (subproj / "subdoc.md").write_text("# Subproject", encoding="utf-8")

            # Add subproject under proj-b that will be filtered out
            filtered_subproj = proj_b / "filtered-sub"
            filtered_subproj.mkdir()
            (filtered_subproj / "filtered.md").write_text("# Filtered Subproject", encoding="utf-8")

            llmstxt_dir = Path("llmstxt")
            mapping_file = Path("opencrane-sources.yaml")

            # Create source mapping that includes:
            # - sources root (for root markdown)
            # - proj-a and its subproject
            # - proj-b
            # but NOT proj-c or filtered-sub
            mapping_content = """sources:
  sources:
    github_url: https://github.com/test/sources
    docs_path: ''
    manual: false
  sources/proj-a:
    github_url: https://github.com/test/proj-a
    docs_path: ''
    manual: false
  sources/proj-a/subproject:
    github_url: https://github.com/test/subproject
    docs_path: ''
    manual: false
  sources/proj-b:
    github_url: https://github.com/test/proj-b
    docs_path: ''
    manual: false
"""
            mapping_file.write_text(mapping_content, encoding="utf-8")

            # Reset global source mapping and configure to use our mapping file
            # Use relative path for MAPPING_FILE to cover the relative path resolution branch
            # Also patch ROOT to current directory so ROOT / mapping_file resolves correctly
            monkeypatch.setattr('opencrane.rag.generate_llms_txt._source_mapping', None)
            monkeypatch.setattr('opencrane.rag.generate_llms_txt.ROOT', Path.cwd())
            monkeypatch.setenv("MAPPING_FILE", str(mapping_file))  # relative path

            with patch.dict(
                "os.environ",
                {
                    "AI_DOCS_SOURCES_DIRS": str(source_dir.resolve()),
                    "AI_DOCS_LLMSTXT_DIR": str(llmstxt_dir.resolve())
                },
                clear=False,
            ):
                generate_outputs()

            # Verify filtered outputs were generated
            assert (llmstxt_dir / "sources" / "llms-full.txt").exists()  # Root markdown
            assert (llmstxt_dir / "sources" / "proj-a" / "llms-full.txt").exists()
            assert (llmstxt_dir / "sources" / "proj-a" / "subproject" / "llms-full.txt").exists()
            assert (llmstxt_dir / "sources" / "proj-b" / "llms-full.txt").exists()
            # proj-c should be filtered out
            assert not (llmstxt_dir / "sources" / "proj-c" / "llms-full.txt").exists()
            # filtered-sub should be filtered out (not in mapping)
            assert not (llmstxt_dir / "sources" / "proj-b" / "filtered-sub" / "llms-full.txt").exists()
        finally:
            # Change back to original directory before cleanup
            monkeypatch.chdir(original_cwd)
            # Clean up test artifacts
            if test_artifacts.exists():
                shutil.rmtree(test_artifacts)

    def test_write_outputs_with_root_projects(self, tmp_path):
        """Test write_outputs skips root projects in per-project outputs (line 291)."""
        output_root = tmp_path / "output"
        project_outputs = {
            "root-project": "Root content",
            "regular-project": "Regular content"
        }
        root_projects = {"root-project"}

        write_outputs(project_outputs, output_root, root_projects)

        # Root project should NOT have its own directory
        assert not (output_root / "root-project" / "llms-full.txt").exists()
        # Regular project should have its own directory
        assert (output_root / "regular-project" / "llms-full.txt").exists()
        # Combined output should have both
        combined = (output_root / "llms-full.txt").read_text(encoding="utf-8")
        assert "Root content" in combined
        assert "Regular content" in combined

    def test_generate_outputs_with_root_markdown_files(self, tmp_path, isolate_outputs):
        """Test root markdown files are marked as root projects (lines 406, 439)."""
        source_dir = tmp_path / "sources"
        llmstxt_dir = tmp_path / "llmstxt"

        # Create root-level markdown files (not in subdirectory)
        source_dir.mkdir()
        (source_dir / "README.md").write_text("# Root Doc", encoding="utf-8")

        with patch.dict(
            "os.environ",
            {
                "AI_DOCS_SOURCES_DIRS": str(source_dir),
                "AI_DOCS_LLMSTXT_DIR": str(llmstxt_dir),
                "AI_DOCS_NO_FILTER": "1"
            },
            clear=False,
        ):
            generate_outputs()

        # Combined output should exist with root content
        assert (llmstxt_dir / "sources" / "llms-full.txt").exists()
        combined = (llmstxt_dir / "sources" / "llms-full.txt").read_text(encoding="utf-8")
        assert "Root Doc" in combined

    def test_generate_outputs_with_empty_source_directory(self, tmp_path, capsys):
        """Test empty source directory is skipped (line 432)."""
        source_dir = tmp_path / "sources"
        llmstxt_dir = tmp_path / "llmstxt"

        # Create empty source directory with no markdown files
        source_dir.mkdir()
        (source_dir / "empty-dir").mkdir()

        with patch.dict(
            "os.environ",
            {
                "AI_DOCS_SOURCES_DIRS": str(source_dir),
                "AI_DOCS_LLMSTXT_DIR": str(llmstxt_dir),
                "AI_DOCS_NO_FILTER": "1"
            },
            clear=False,
        ):
            generate_outputs()

        # Should handle gracefully without errors
        # Combined file may or may not exist depending on other logic
        assert not (llmstxt_dir / "sources" / "empty-dir" / "llms-full.txt").exists()

    def test_generate_outputs_subproject_relative_to_workspace(self, tmp_path, monkeypatch, isolate_outputs):
        """Test subproject path resolution with ValueError handling (lines 423-429)."""
        # Create a workspace where source is NOT under workspace root
        # This triggers the ValueError path in relative_to()
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        monkeypatch.chdir(workspace_root)

        # Create source directory OUTSIDE workspace root
        external_source = tmp_path / "external_source"
        external_source.mkdir()

        project_dir = external_source / "project"
        project_dir.mkdir()
        (project_dir / "main.md").write_text("# Main", encoding="utf-8")

        # Create subproject
        subproject_dir = project_dir / "subproject"
        subproject_dir.mkdir()
        (subproject_dir / "sub.md").write_text("# Sub", encoding="utf-8")

        llmstxt_dir = tmp_path / "llmstxt"

        with patch.dict(
            "os.environ",
            {
                "AI_DOCS_SOURCES_DIRS": str(external_source),
                "AI_DOCS_LLMSTXT_DIR": str(llmstxt_dir),
                "AI_DOCS_NO_FILTER": "1"
            },
            clear=False,
        ):
            generate_outputs()

        # Should handle the ValueError gracefully and use fallback path
        # Verify subproject output was created
        assert (llmstxt_dir / "external_source" / "llms-full.txt").exists()


class TestGenerateOutputsSkipBehavior:
    """Tests for the git-change-based skip logic in generate_outputs."""

    def test_skips_when_no_changes(self, tmp_path, capsys):
        """generate_outputs returns early without writing files when no git changes."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        (source_dir / "doc.md").write_text("# Doc", encoding="utf-8")
        llmstxt_dir = tmp_path / "llmstxt"

        with patch("opencrane.rag.generate_llms_txt.has_changes", return_value=False):
            with patch.dict("os.environ", {
                "AI_DOCS_SOURCES_DIRS": str(source_dir),
                "AI_DOCS_LLMSTXT_DIR": str(llmstxt_dir),
            }, clear=False):
                generate_outputs()

        assert not llmstxt_dir.exists()
        captured = capsys.readouterr()
        assert "Skipping" in captured.out

    def test_runs_when_changes_detected(self, tmp_path):
        """generate_outputs processes files when git changes are detected."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        (source_dir / "doc.md").write_text("# Doc", encoding="utf-8")
        llmstxt_dir = tmp_path / "llmstxt"

        with patch("opencrane.rag.generate_llms_txt.has_changes", return_value=True):
            with patch.dict("os.environ", {
                "AI_DOCS_SOURCES_DIRS": str(source_dir),
                "AI_DOCS_LLMSTXT_DIR": str(llmstxt_dir),
            }, clear=False):
                generate_outputs()

        assert (llmstxt_dir / "llms-full.txt").exists()

    def test_force_bypasses_skip(self, tmp_path):
        """force=True runs even when has_changes returns False."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        (source_dir / "doc.md").write_text("# Doc", encoding="utf-8")
        llmstxt_dir = tmp_path / "llmstxt"

        with patch("opencrane.rag.generate_llms_txt.has_changes", return_value=False):
            with patch.dict("os.environ", {
                "AI_DOCS_SOURCES_DIRS": str(source_dir),
                "AI_DOCS_LLMSTXT_DIR": str(llmstxt_dir),
            }, clear=False):
                generate_outputs(force=True)

        assert (llmstxt_dir / "llms-full.txt").exists()

    def test_skip_does_not_call_has_changes_for_legacy_path(self, tmp_path):
        """Legacy selected_projects path is unaffected by git-change logic."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        proj = source_dir / "proj1"
        proj.mkdir()
        (proj / "doc.md").write_text("# Doc", encoding="utf-8")

        import opencrane.rag.generate_llms_txt as mod
        orig_source_root = mod.SOURCE_ROOT
        orig_output_root = mod.OUTPUT_ROOT
        try:
            mod.SOURCE_ROOT = source_dir
            mod.OUTPUT_ROOT = tmp_path / "llmstxt"
            with patch("opencrane.rag.generate_llms_txt.has_changes") as mock_gc:
                generate_outputs(selected_projects=["proj1"])
            mock_gc.assert_not_called()
        finally:
            mod.SOURCE_ROOT = orig_source_root
            mod.OUTPUT_ROOT = orig_output_root
