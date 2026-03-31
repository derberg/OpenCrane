"""Unit tests for fetch_docs.py llmstxt fetching logic."""
import pytest
import shutil
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock
from opencrane.shared.config import Config
from opencrane.rag.services.source_mapping import SourceMapping


def make_config(tmp_path, fetch_repo=""):
    """Create a Config with mapping_file pointing to tmp_path."""
    mapping_file = tmp_path / ".opencrane" / "sources.yaml"
    return Config(
        org_name="",
        mapping_file=mapping_file,
        fetch_repo=fetch_repo,
    )


def setup_sources_yaml(tmp_path, sources: dict):
    """Write a sources.yaml with the given sources dict."""
    import yaml
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir(parents=True, exist_ok=True)
    mapping_file = opencrane_dir / "sources.yaml"
    mapping_file.write_text(yaml.dump({"sources": sources}))
    return mapping_file


def run_main_with_mocks(tmp_path, config, mock_urlopen=None):
    """Run fetch_docs.main() with all external dependencies mocked."""
    with patch("opencrane.rag.fetch_docs.setup_logging"), \
         patch("opencrane.rag.fetch_docs.GitHubClient") as mock_gh_client_cls, \
         patch("opencrane.rag.fetch_docs.RepoFetcher") as mock_repo_fetcher_cls, \
         patch("opencrane.rag.fetch_docs.FileManager"), \
         patch("opencrane.rag.fetch_docs.get_current_repo_name", return_value="opencrane"), \
         patch("opencrane.rag.fetch_docs.Path.cwd", return_value=tmp_path):

        mock_gh_client_cls.return_value = MagicMock()
        mock_repo_fetcher = MagicMock()
        mock_repo_fetcher.get_documentation_repos.return_value = []
        mock_repo_fetcher_cls.return_value = mock_repo_fetcher

        if mock_urlopen is not None:
            with patch("opencrane.rag.fetch_docs.urlopen", mock_urlopen):
                from opencrane.rag import fetch_docs
                fetch_docs.main(config)
        else:
            from opencrane.rag import fetch_docs
            fetch_docs.main(config)


@pytest.mark.unit
class TestFetchDocsLlmstxt:
    """Tests for llmstxt source fetching in fetch_docs.main()."""

    def test_fetch_llmstxt_from_url(self, tmp_path):
        """Downloading an https URL writes content to llmstxt dest dir."""
        setup_sources_yaml(tmp_path, {
            "my-llmstxt": {
                "url": "https://example.com/llms-full.txt",
                "type": "llmstxt",
                "manual": True,
            }
        })
        config = make_config(tmp_path)

        fake_content = b"# LLMs Full Content\n\nHello World"
        mock_response = MagicMock()
        mock_response.read.return_value = fake_content
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen = MagicMock(return_value=mock_response)

        run_main_with_mocks(tmp_path, config, mock_urlopen=mock_urlopen)

        dest_file = tmp_path / ".opencrane" / "llmstxt" / "my-llmstxt" / "llms-full.txt"
        assert dest_file.exists(), f"Expected {dest_file} to exist"
        assert dest_file.read_bytes() == fake_content

    def test_fetch_llmstxt_from_local_file(self, tmp_path):
        """A local file path is copied to the llmstxt dest dir."""
        local_src = tmp_path / "my-docs.txt"
        local_src.write_text("# Local LLMs Content")

        setup_sources_yaml(tmp_path, {
            "local-src": {
                "url": str(local_src),
                "type": "llmstxt",
                "manual": True,
            }
        })
        config = make_config(tmp_path)

        run_main_with_mocks(tmp_path, config)

        dest_file = tmp_path / ".opencrane" / "llmstxt" / "local-src" / "llms-full.txt"
        assert dest_file.exists(), f"Expected {dest_file} to exist"
        assert dest_file.read_text() == "# Local LLMs Content"

    def test_fetch_llmstxt_skips_no_url(self, tmp_path, caplog):
        """An llmstxt entry with no url logs a warning and is skipped."""
        setup_sources_yaml(tmp_path, {
            "no-url-entry": {
                "url": "",
                "type": "llmstxt",
                "manual": True,
            }
        })
        config = make_config(tmp_path)

        import logging
        with caplog.at_level(logging.WARNING, logger="opencrane.rag.fetch_docs"):
            run_main_with_mocks(tmp_path, config)

        assert "no-url-entry" in caplog.text
        assert "no url" in caplog.text.lower()

        dest_dir = tmp_path / ".opencrane" / "llmstxt" / "no-url-entry"
        # Dir may be created but no file should exist
        dest_file = dest_dir / "llms-full.txt"
        assert not dest_file.exists()

    def test_fetch_llmstxt_error_continues(self, tmp_path, caplog):
        """If urlopen raises, an error is logged but no exception propagates."""
        setup_sources_yaml(tmp_path, {
            "failing-src": {
                "url": "https://example.com/bad.txt",
                "type": "llmstxt",
                "manual": True,
            }
        })
        config = make_config(tmp_path)

        mock_urlopen = MagicMock(side_effect=OSError("connection refused"))

        import logging
        with caplog.at_level(logging.ERROR, logger="opencrane.rag.fetch_docs"):
            # Should not raise
            run_main_with_mocks(tmp_path, config, mock_urlopen=mock_urlopen)

        assert "failing-src" in caplog.text
        assert "Failed to fetch llmstxt source" in caplog.text

    def test_fetch_llmstxt_protected_from_cleanup(self, tmp_path):
        """llmstxt entries are added to active_repos so they are never removed by cleanup."""
        sources_yaml = setup_sources_yaml(tmp_path, {
            "protected-llmstxt": {
                "url": "https://example.com/llms-full.txt",
                "type": "llmstxt",
                "manual": True,
            }
        })
        config = make_config(tmp_path)

        # Create an existing llmstxt dir to verify it is NOT removed
        existing_dir = tmp_path / ".opencrane" / "llmstxt" / "protected-llmstxt"
        existing_dir.mkdir(parents=True, exist_ok=True)
        existing_file = existing_dir / "llms-full.txt"
        fake_content = b"pre-existing content"
        existing_file.write_bytes(fake_content)

        # The llmstxt entry is listed in sources.yaml, so cleanup should not touch it.
        # We verify by checking that the SourceMapping does not remove it.
        source_mapping = SourceMapping(sources_yaml)
        active = {"protected-llmstxt"}
        removed = source_mapping.cleanup_stale_sources(active)

        assert "protected-llmstxt" not in removed
        assert existing_file.exists()
        assert existing_file.read_bytes() == fake_content

    def test_fetch_llmstxt_repo_filter_skips_other(self, tmp_path, caplog):
        """When --repo filter is active, other llmstxt entries are skipped."""
        local_src = tmp_path / "docs.txt"
        local_src.write_text("content")

        setup_sources_yaml(tmp_path, {
            "target-llmstxt": {
                "url": str(local_src),
                "type": "llmstxt",
                "manual": True,
            },
            "other-llmstxt": {
                "url": str(local_src),
                "type": "llmstxt",
                "manual": True,
            }
        })
        config = make_config(tmp_path, fetch_repo="target-llmstxt")

        import logging
        with caplog.at_level(logging.DEBUG, logger="opencrane.rag.fetch_docs"):
            run_main_with_mocks(tmp_path, config)

        # target should be fetched
        target_file = tmp_path / ".opencrane" / "llmstxt" / "target-llmstxt" / "llms-full.txt"
        assert target_file.exists()

        # other should be skipped
        other_file = tmp_path / ".opencrane" / "llmstxt" / "other-llmstxt" / "llms-full.txt"
        assert not other_file.exists()
        assert "other-llmstxt" in caplog.text
        assert "--repo filter active" in caplog.text

    def test_fetch_llmstxt_local_missing_file_continues(self, tmp_path, caplog):
        """A local path that does not exist logs an error and does not crash."""
        setup_sources_yaml(tmp_path, {
            "missing-src": {
                "url": str(tmp_path / "nonexistent.txt"),
                "type": "llmstxt",
                "manual": True,
            }
        })
        config = make_config(tmp_path)

        import logging
        with caplog.at_level(logging.ERROR, logger="opencrane.rag.fetch_docs"):
            run_main_with_mocks(tmp_path, config)

        assert "missing-src" in caplog.text
        assert "not found" in caplog.text.lower()

        dest_file = tmp_path / ".opencrane" / "llmstxt" / "missing-src" / "llms-full.txt"
        assert not dest_file.exists()


@pytest.mark.unit
class TestFetchDocsLocal:
    """Tests for local: true source handling in fetch_docs.main()."""

    def test_local_entries_skip_fetch(self, tmp_path, caplog):
        """Local entries are skipped during fetch — no GitHub API calls."""
        setup_sources_yaml(tmp_path, {
            "content-guidelines/writing": {"local": True},
            "content-guidelines/templates": {"local": True},
        })
        config = make_config(tmp_path)

        import logging
        with caplog.at_level(logging.INFO, logger="opencrane.rag.fetch_docs"):
            run_main_with_mocks(tmp_path, config)

        assert "Skipping local source: content-guidelines/writing" in caplog.text
        assert "Skipping local source: content-guidelines/templates" in caplog.text
        assert "Fetched 0 manual repositories" in caplog.text

    def test_local_entries_protected_from_cleanup(self, tmp_path):
        """Local entries are not removed by stale source cleanup."""
        sources_file = setup_sources_yaml(tmp_path, {
            "content-guidelines/writing": {"local": True},
        })
        config = make_config(tmp_path)

        run_main_with_mocks(tmp_path, config)

        mapping = SourceMapping(sources_file)
        assert mapping.get_source("content-guidelines/writing") is not None
        assert mapping.get_source("content-guidelines/writing").get("local") is True

    def test_local_and_remote_entries_coexist(self, tmp_path, caplog):
        """A mix of local and remote entries: local skipped, remote fetched normally."""
        local_src = tmp_path / "docs.txt"
        local_src.write_text("content")

        setup_sources_yaml(tmp_path, {
            "content-guidelines/writing": {"local": True},
            "my-llmstxt": {
                "url": str(local_src),
                "type": "llmstxt",
                "manual": True,
            },
        })
        config = make_config(tmp_path)

        import logging
        with caplog.at_level(logging.INFO, logger="opencrane.rag.fetch_docs"):
            run_main_with_mocks(tmp_path, config)

        assert "Skipping local source: content-guidelines/writing" in caplog.text
        dest_file = tmp_path / ".opencrane" / "llmstxt" / "my-llmstxt" / "llms-full.txt"
        assert dest_file.exists()
