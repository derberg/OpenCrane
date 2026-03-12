"""Tests for source mapping service."""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch
from opencrane.rag.services.source_mapping import SourceMapping


class TestSourceMapping:
    """Tests for SourceMapping class."""

    def test_load_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "nonexistent.yaml"
            mapping = SourceMapping(mapping_file)
            assert mapping.get_all_sources() == {}

    def test_load_invalid_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "invalid.yaml"
            mapping_file.write_text("invalid: yaml: content: ][")
            mapping = SourceMapping(mapping_file)
            assert mapping.data == {"sources": {}}

    def test_save_to_new_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "subdir" / "mapping.yaml"
            mapping = SourceMapping(mapping_file)

            mapping.add_source(
                path_key="source-a",
                github_url="https://github.com/test/repo-a",
                docs_path=""
            )
            mapping.save()
            assert mapping_file.exists()

    def test_save_permission_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)

            mapping.add_source(
                path_key="test",
                github_url="https://github.com/test/test-repo",
                docs_path=""
            )

            with patch("builtins.open", side_effect=PermissionError("Permission denied")):
                with pytest.raises(PermissionError):
                    mapping.save()

    def test_add_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)

            mapping.add_source(
                path_key="source-a",
                github_url="https://github.com/test/repo-a",
                docs_path=""
            )

            source = mapping.get_source("source-a")
            assert source["github_url"] == "https://github.com/test/repo-a"
            assert source["docs_path"] == ""
            assert source["manual"] is False

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"

            mapping1 = SourceMapping(mapping_file)
            mapping1.add_source(
                path_key="parent-source/child-source",
                github_url="https://github.com/test/repo-b",
                docs_path="docs"
            )
            mapping1.save()

            mapping2 = SourceMapping(mapping_file)
            source = mapping2.get_source("parent-source/child-source")
            assert source["docs_path"] == "docs"
            assert source["manual"] is False

    def test_find_source_for_file_exact_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)

            mapping.add_source(
                path_key="source-a",
                github_url="https://github.com/test/repo-a",
                docs_path=""
            )

            found = mapping.find_source_for_file(Path("source-a/subdir/file.md"))
            assert found is not None
            entry, matched = found
            assert matched == "source-a"

    def test_find_source_for_file_longest_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)

            mapping.add_source(
                path_key="parent-source",
                github_url="https://github.com/test/parent-repo",
                docs_path=""
            )
            mapping.add_source(
                path_key="parent-source/child-source",
                github_url="https://github.com/test/child-repo",
                docs_path="docs"
            )

            found = mapping.find_source_for_file(Path("parent-source/child-source/docs/guide.md"))
            assert found is not None
            entry, matched = found
            assert matched == "parent-source/child-source"

    def test_find_source_for_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)

            mapping.add_source(
                path_key="source-a",
                github_url="https://github.com/test/repo-a",
                docs_path=""
            )

            source = mapping.find_source_for_file(Path("nonexistent-source/file.md"))
            assert source is None

    def test_get_all_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)

            mapping.add_source(
                path_key="source-a",
                github_url="https://github.com/test/repo-a",
                docs_path=""
            )
            mapping.add_source(
                path_key="source-b/subsource",
                github_url="https://github.com/test/repo-b",
                docs_path="docs"
            )

            all_sources = mapping.get_all_sources()
            assert len(all_sources) == 2
            assert "source-a" in all_sources
            assert "source-b/subsource" in all_sources

    def test_add_source_with_docs_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)
            mapping.add_source(
                path_key="source-a",
                github_url="https://github.com/test/repo-a",
                docs_path="docs",
                docs_url="https://docs.example.com/product-a"
            )
            source = mapping.get_source("source-a")
            assert source["docs_url"] == "https://docs.example.com/product-a"

    def test_add_source_without_docs_url_omits_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)
            mapping.add_source(
                path_key="source-a",
                github_url="https://github.com/test/repo-a",
                docs_path=""
            )
            source = mapping.get_source("source-a")
            assert "docs_url" not in source

    def test_manual_entry_preservation(self):
        """Test that manual entries are not overwritten by auto-refresh."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)

            # Add manual entry
            mapping.add_source(
                path_key="source-a",
                github_url="https://github.com/test/repo-original",
                docs_path="",
                manual=True
            )

            # Try to auto-update (manual=False) - should be skipped
            mapping.add_source(
                path_key="source-a",
                github_url="https://github.com/test/repo-updated",
                docs_path="docs",
                manual=False
            )

            # Verify original manual entry is preserved
            source = mapping.get_source("source-a")
            assert source["github_url"] == "https://github.com/test/repo-original"
            assert source["docs_path"] == ""
            assert source["manual"] is True

    def test_remove_source_existing(self):
        """Test removing an existing source entry."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)

            # Add a source
            mapping.add_source(
                path_key="source-a",
                github_url="https://github.com/test/repo-a",
                docs_path=""
            )

            # Verify it exists
            assert mapping.get_source("source-a") is not None

            # Remove it
            result = mapping.remove_source("source-a")
            assert result is True

            # Verify it's gone
            assert mapping.get_source("source-a") is None

    def test_remove_source_nonexistent(self):
        """Test removing a nonexistent source entry."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)

            # Try to remove nonexistent source
            result = mapping.remove_source("nonexistent")
            assert result is False

    def test_cleanup_stale_sources_removes_auto_entries(self):
        """Test that cleanup removes stale auto-generated entries."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)

            # Add auto-generated sources
            mapping.add_source(
                path_key="source-a",
                github_url="https://github.com/test/repo-a",
                docs_path="",
                manual=False
            )
            mapping.add_source(
                path_key="source-b",
                github_url="https://github.com/test/repo-b",
                docs_path="",
                manual=False
            )
            mapping.add_source(
                path_key="source-c",
                github_url="https://github.com/test/repo-c",
                docs_path="",
                manual=False
            )

            # Only source-a and source-c are still active
            active_sources = {"source-a", "source-c"}
            removed = mapping.cleanup_stale_sources(active_sources)

            # Verify source-b was removed
            assert removed == ["source-b"]
            assert mapping.get_source("source-a") is not None
            assert mapping.get_source("source-b") is None
            assert mapping.get_source("source-c") is not None

    def test_cleanup_stale_sources_preserves_manual_entries(self):
        """Test that cleanup never removes manual entries."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)

            # Add manual entry
            mapping.add_source(
                path_key="manual-source",
                github_url="https://github.com/test/manual-repo",
                docs_path="",
                manual=True
            )

            # Add auto-generated source
            mapping.add_source(
                path_key="auto-source",
                github_url="https://github.com/test/auto-repo",
                docs_path="",
                manual=False
            )

            # Active sources doesn't include either
            active_sources = set()
            removed = mapping.cleanup_stale_sources(active_sources)

            # Verify only auto-source was removed
            assert removed == ["auto-source"]
            assert mapping.get_source("manual-source") is not None
            assert mapping.get_source("auto-source") is None

    def test_cleanup_stale_sources_empty_active_set(self):
        """Test cleanup with empty active set removes all auto entries."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)

            # Add multiple auto-generated sources
            mapping.add_source(
                path_key="source-a",
                github_url="https://github.com/test/repo-a",
                docs_path="",
                manual=False
            )
            mapping.add_source(
                path_key="source-b",
                github_url="https://github.com/test/repo-b",
                docs_path="",
                manual=False
            )

            # No active sources
            removed = mapping.cleanup_stale_sources(set())

            # All auto entries should be removed
            assert len(removed) == 2
            assert "source-a" in removed
            assert "source-b" in removed

    def test_cleanup_stale_sources_all_active(self):
        """Test cleanup when all sources are active."""
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"
            mapping = SourceMapping(mapping_file)

            # Add sources
            mapping.add_source(
                path_key="source-a",
                github_url="https://github.com/test/repo-a",
                docs_path="",
                manual=False
            )
            mapping.add_source(
                path_key="source-b",
                github_url="https://github.com/test/repo-b",
                docs_path="",
                manual=False
            )

            # All sources are active
            active_sources = {"source-a", "source-b"}
            removed = mapping.cleanup_stale_sources(active_sources)

            # Nothing should be removed
            assert removed == []
            assert len(mapping.get_all_sources()) == 2
