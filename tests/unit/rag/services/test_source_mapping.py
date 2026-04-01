"""Tests for source mapping service."""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch
from opencrane.rag.services.source_mapping import SourceMapping


@pytest.fixture
def tmp_mapping(tmp_path):
    """Return a SourceMapping backed by a temp file."""
    return SourceMapping(tmp_path / "sources.yaml")


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
                url="https://github.com/test/repo-a",
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
                url="https://github.com/test/test-repo",
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
                url="https://github.com/test/repo-a",
                docs_path=""
            )

            source = mapping.get_source("source-a")
            assert source["url"] == "https://github.com/test/repo-a"
            assert source["docs_path"] == ""
            assert source["manual"] is False

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping_file = Path(tmp) / "mapping.yaml"

            mapping1 = SourceMapping(mapping_file)
            mapping1.add_source(
                path_key="parent-source/child-source",
                url="https://github.com/test/repo-b",
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
                url="https://github.com/test/repo-a",
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
                url="https://github.com/test/parent-repo",
                docs_path=""
            )
            mapping.add_source(
                path_key="parent-source/child-source",
                url="https://github.com/test/child-repo",
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
                url="https://github.com/test/repo-a",
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
                url="https://github.com/test/repo-a",
                docs_path=""
            )
            mapping.add_source(
                path_key="source-b/subsource",
                url="https://github.com/test/repo-b",
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
                url="https://github.com/test/repo-a",
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
                url="https://github.com/test/repo-a",
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
                url="https://github.com/test/repo-original",
                docs_path="",
                manual=True
            )

            # Try to auto-update (manual=False) - should be skipped
            mapping.add_source(
                path_key="source-a",
                url="https://github.com/test/repo-updated",
                docs_path="docs",
                manual=False
            )

            # Verify original manual entry is preserved
            source = mapping.get_source("source-a")
            assert source["url"] == "https://github.com/test/repo-original"
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
                url="https://github.com/test/repo-a",
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
                url="https://github.com/test/repo-a",
                docs_path="",
                manual=False
            )
            mapping.add_source(
                path_key="source-b",
                url="https://github.com/test/repo-b",
                docs_path="",
                manual=False
            )
            mapping.add_source(
                path_key="source-c",
                url="https://github.com/test/repo-c",
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
                url="https://github.com/test/manual-repo",
                docs_path="",
                manual=True
            )

            # Add auto-generated source
            mapping.add_source(
                path_key="auto-source",
                url="https://github.com/test/auto-repo",
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
                url="https://github.com/test/repo-a",
                docs_path="",
                manual=False
            )
            mapping.add_source(
                path_key="source-b",
                url="https://github.com/test/repo-b",
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
                url="https://github.com/test/repo-a",
                docs_path="",
                manual=False
            )
            mapping.add_source(
                path_key="source-b",
                url="https://github.com/test/repo-b",
                docs_path="",
                manual=False
            )

            # All sources are active
            active_sources = {"source-a", "source-b"}
            removed = mapping.cleanup_stale_sources(active_sources)

            # Nothing should be removed
            assert removed == []
            assert len(mapping.get_all_sources()) == 2


@pytest.mark.unit
def test_local_source_round_trips_through_save_load(tmp_mapping):
    """A hand-written local: true entry survives save/load cycle."""
    import yaml
    tmp_mapping.mapping_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_mapping.mapping_file.write_text(yaml.dump({"sources": {
        "content-guidelines/writing": {"local": True},
        "remote-repo": {"url": "https://github.com/org/repo", "docs_path": "docs", "manual": True},
    }}))
    mapping = SourceMapping(tmp_mapping.mapping_file)
    mapping.add_source(path_key="new-repo", url="https://github.com/org/new", docs_path="")
    mapping.save()
    mapping2 = SourceMapping(tmp_mapping.mapping_file)
    local_entry = mapping2.get_source("content-guidelines/writing")
    assert local_entry is not None
    assert local_entry.get("local") is True


@pytest.mark.unit
def test_cleanup_stale_sources_preserves_local_entries(tmp_mapping):
    """Local entries are never removed by stale cleanup, even if not in active set."""
    import yaml
    tmp_mapping.mapping_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_mapping.mapping_file.write_text(yaml.dump({"sources": {
        "local-source": {"local": True},
        "auto-source": {"url": "https://github.com/org/repo", "docs_path": "", "manual": False},
    }}))
    mapping = SourceMapping(tmp_mapping.mapping_file)
    removed = mapping.cleanup_stale_sources(set())
    assert "auto-source" in removed
    assert "local-source" not in removed
    assert mapping.get_source("local-source") is not None


@pytest.mark.unit
def test_add_source_with_llmstxt_type(tmp_mapping):
    tmp_mapping.add_source(
        path_key="my-llmstxt",
        url="https://example.com/llms-full.txt",
        manual=True,
        type="llmstxt",
    )
    entry = tmp_mapping.get_source("my-llmstxt")
    assert entry["url"] == "https://example.com/llms-full.txt"
    assert entry["type"] == "llmstxt"
    assert entry["manual"] is True


@pytest.mark.unit
def test_add_source_github_type_omitted_from_entry(tmp_mapping):
    tmp_mapping.add_source(path_key="my-repo", url="https://github.com/org/repo")
    entry = tmp_mapping.get_source("my-repo")
    assert "type" not in entry  # github is default, not stored
    assert entry["url"] == "https://github.com/org/repo"


def test_get_ignore_patterns_global_only(tmp_path):
    mapping_file = tmp_path / "config.yaml"
    mapping_file.write_text("ignore_patterns:\n  - devel\n  - .draft\nsources: {}\n")
    mapping = SourceMapping(mapping_file)
    assert mapping.get_ignore_patterns() == ["devel", ".draft"]

def test_get_ignore_patterns_with_source(tmp_path):
    mapping_file = tmp_path / "config.yaml"
    mapping_file.write_text(
        "ignore_patterns:\n  - devel\n"
        "sources:\n  my-repo:\n    url: https://github.com/x/y\n    ignore_patterns:\n      - internal\n"
    )
    mapping = SourceMapping(mapping_file)
    assert mapping.get_ignore_patterns("my-repo") == ["devel", "internal"]

def test_get_ignore_patterns_empty(tmp_path):
    mapping_file = tmp_path / "config.yaml"
    mapping_file.write_text("sources: {}\n")
    mapping = SourceMapping(mapping_file)
    assert mapping.get_ignore_patterns() == []

def test_get_extensions_path(tmp_path):
    mapping_file = tmp_path / "config.yaml"
    mapping_file.write_text("extensions: extensions.py\nsources: {}\n")
    mapping = SourceMapping(mapping_file)
    assert mapping.get_extensions_path() == "extensions.py"

def test_get_extensions_path_none(tmp_path):
    mapping_file = tmp_path / "config.yaml"
    mapping_file.write_text("sources: {}\n")
    mapping = SourceMapping(mapping_file)
    assert mapping.get_extensions_path() is None

def test_save_preserves_non_sources_keys(tmp_path):
    mapping_file = tmp_path / "config.yaml"
    mapping_file.write_text("ignore_patterns:\n  - devel\nextensions: extensions.py\nsources: {}\n")
    mapping = SourceMapping(mapping_file)
    mapping.add_source("test", url="https://github.com/x/y", manual=True)
    mapping.save()
    import yaml
    saved = yaml.safe_load(mapping_file.read_text())
    assert saved["ignore_patterns"] == ["devel"]
    assert saved["extensions"] == "extensions.py"
    assert "test" in saved["sources"]
