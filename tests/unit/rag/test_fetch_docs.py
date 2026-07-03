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
    mapping_file = tmp_path / ".opencrane" / "config.yaml"
    return Config(
        org_name="",
        mapping_file=mapping_file,
        fetch_repo=fetch_repo,
    )


def setup_sources_yaml(tmp_path, sources: dict):
    """Write a config.yaml with the given sources dict."""
    import yaml
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir(parents=True, exist_ok=True)
    mapping_file = opencrane_dir / "config.yaml"
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

        # The llmstxt entry is listed in config.yaml, so cleanup should not touch it.
        # We verify by checking that the SourceMapping does not remove it.
        source_mapping = SourceMapping(sources_yaml)
        active = {"protected-llmstxt"}
        removed = source_mapping.cleanup_stale_sources(active)

        assert "protected-llmstxt" not in removed
        assert existing_file.exists()
        assert existing_file.read_bytes() == fake_content

    def test_fetch_llmstxt_repo_filter_skips_other(self, tmp_path, caplog):
        """When --source filter is active, other llmstxt entries are skipped."""
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
        assert "--source filter active" in caplog.text

    def test_fetch_source_filter_accepts_comma_separated_list(self, tmp_path, caplog):
        """`--source a,b` fetches both a and b, skips other entries."""
        local_src = tmp_path / "docs.txt"
        local_src.write_text("content")

        setup_sources_yaml(tmp_path, {
            "first-src": {"url": str(local_src), "type": "llmstxt", "manual": True},
            "second-src": {"url": str(local_src), "type": "llmstxt", "manual": True},
            "third-src": {"url": str(local_src), "type": "llmstxt", "manual": True},
        })
        # Whitespace around commas is tolerated; spaces inside names are not
        # part of the spec.
        config = make_config(tmp_path, fetch_repo="first-src, second-src")

        import logging
        with caplog.at_level(logging.DEBUG, logger="opencrane.rag.fetch_docs"):
            run_main_with_mocks(tmp_path, config)

        # both named sources should be fetched
        assert (tmp_path / ".opencrane" / "llmstxt" / "first-src" / "llms-full.txt").exists()
        assert (tmp_path / ".opencrane" / "llmstxt" / "second-src" / "llms-full.txt").exists()
        # the unnamed one should be skipped
        assert not (tmp_path / ".opencrane" / "llmstxt" / "third-src" / "llms-full.txt").exists()
        assert "third-src" in caplog.text

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


@pytest.mark.unit
class TestCompanionLlmsTxtUrl:
    """Tests for _companion_llms_txt_url helper."""

    def test_companion_url_from_full(self):
        from opencrane.rag.fetch_docs import _companion_llms_txt_url
        assert _companion_llms_txt_url("https://x/llms-full.txt", None) == "https://x/llms.txt"

    def test_companion_url_from_docs_url(self):
        from opencrane.rag.fetch_docs import _companion_llms_txt_url
        assert _companion_llms_txt_url("https://x/bundle.txt", "https://x/docs") == "https://x/docs/llms.txt"

    def test_companion_url_docs_url_trailing_slash(self):
        from opencrane.rag.fetch_docs import _companion_llms_txt_url
        assert _companion_llms_txt_url("https://x/bundle.txt", "https://x/docs/") == "https://x/docs/llms.txt"

    def test_companion_url_none(self):
        from opencrane.rag.fetch_docs import _companion_llms_txt_url
        assert _companion_llms_txt_url("https://x/bundle.txt", None) is None

    def test_companion_fetch_writes_llms_txt(self, tmp_path):
        """When companion URL returns content, llms.txt is written next to llms-full.txt."""
        setup_sources_yaml(tmp_path, {
            "my-src": {
                "url": "https://example.com/llms-full.txt",
                "type": "llmstxt",
                "manual": True,
            }
        })
        config = make_config(tmp_path)

        full_content = b"# Full content"
        companion_content = b"# Companion index"

        def fake_urlopen(req):
            mock_response = MagicMock()
            if req.full_url.endswith("llms-full.txt"):
                mock_response.read.return_value = full_content
            elif req.full_url.endswith("llms.txt"):
                mock_response.read.return_value = companion_content
            else:
                from urllib.error import HTTPError
                raise HTTPError(req.full_url, 404, "Not Found", {}, None)
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            return mock_response

        run_main_with_mocks(tmp_path, config, mock_urlopen=fake_urlopen)

        dest_dir = tmp_path / ".opencrane" / "llmstxt" / "my-src"
        assert (dest_dir / "llms-full.txt").read_bytes() == full_content
        assert (dest_dir / "llms.txt").read_bytes() == companion_content

    def test_companion_fetch_404_leaves_only_full(self, tmp_path):
        """When companion URL 404s, only llms-full.txt is present and no exception is raised."""
        from urllib.error import HTTPError

        setup_sources_yaml(tmp_path, {
            "my-src": {
                "url": "https://example.com/llms-full.txt",
                "type": "llmstxt",
                "manual": True,
            }
        })
        config = make_config(tmp_path)

        full_content = b"# Full content"

        def fake_urlopen(req):
            mock_response = MagicMock()
            if req.full_url.endswith("llms-full.txt"):
                mock_response.read.return_value = full_content
                mock_response.__enter__ = lambda s: s
                mock_response.__exit__ = MagicMock(return_value=False)
                return mock_response
            raise HTTPError(req.full_url, 404, "Not Found", {}, None)

        run_main_with_mocks(tmp_path, config, mock_urlopen=fake_urlopen)

        dest_dir = tmp_path / ".opencrane" / "llmstxt" / "my-src"
        assert (dest_dir / "llms-full.txt").read_bytes() == full_content
        assert not (dest_dir / "llms.txt").exists()

    def test_companion_local_sibling_copied(self, tmp_path):
        """For a local llmstxt source, a sibling llms.txt is copied when present."""
        local_full = tmp_path / "my-docs-full.txt"
        local_full.write_text("# Full content")
        local_companion = tmp_path / "llms.txt"
        local_companion.write_text("# Companion index")

        setup_sources_yaml(tmp_path, {
            "local-src": {
                "url": str(local_full),
                "type": "llmstxt",
                "manual": True,
            }
        })
        config = make_config(tmp_path)

        run_main_with_mocks(tmp_path, config)

        dest_dir = tmp_path / ".opencrane" / "llmstxt" / "local-src"
        assert (dest_dir / "llms-full.txt").exists()
        assert (dest_dir / "llms.txt").read_text() == "# Companion index"

    def test_companion_local_sibling_absent_no_crash(self, tmp_path):
        """For a local llmstxt source, no crash when sibling llms.txt is absent."""
        local_full = tmp_path / "my-docs-full.txt"
        local_full.write_text("# Full content")

        setup_sources_yaml(tmp_path, {
            "local-src": {
                "url": str(local_full),
                "type": "llmstxt",
                "manual": True,
            }
        })
        config = make_config(tmp_path)

        run_main_with_mocks(tmp_path, config)

        dest_dir = tmp_path / ".opencrane" / "llmstxt" / "local-src"
        assert (dest_dir / "llms-full.txt").exists()
        assert not (dest_dir / "llms.txt").exists()

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


def make_repo(name):
    """Create a mock GitHub repo object with a name."""
    repo = MagicMock()
    repo.name = name
    return repo


def run_main_github(tmp_path, config, repo_fetcher, mock_urlopen=None,
                    current_repo_name="opencrane"):
    """Run fetch_docs.main() with a custom RepoFetcher mock.

    Returns nothing; assertions are made against the filesystem / SourceMapping
    afterwards. The GitHubClient and FileManager are stubbed.
    """
    with patch("opencrane.rag.fetch_docs.setup_logging"), \
         patch("opencrane.rag.fetch_docs.GitHubClient"), \
         patch("opencrane.rag.fetch_docs.RepoFetcher", return_value=repo_fetcher), \
         patch("opencrane.rag.fetch_docs.FileManager") as mock_fm_cls, \
         patch("opencrane.rag.fetch_docs.get_current_repo_name",
               return_value=current_repo_name), \
         patch("opencrane.rag.fetch_docs.Path.cwd", return_value=tmp_path):
        mock_fm_cls.return_value = MagicMock()
        from opencrane.rag import fetch_docs
        if mock_urlopen is not None:
            with patch("opencrane.rag.fetch_docs.urlopen", mock_urlopen):
                fetch_docs.main(config)
        else:
            fetch_docs.main(config)


@pytest.mark.unit
class TestFetchDocsGitHub:
    """Tests for the GitHub repo fetching / processing paths of main()."""

    def test_config_none_uses_get_config(self, tmp_path):
        """main(None) resolves config via get_config()."""
        setup_sources_yaml(tmp_path, {})
        config = make_config(tmp_path)
        with patch("opencrane.rag.fetch_docs.get_config", return_value=config) as mock_gc:
            repo_fetcher = MagicMock()
            repo_fetcher.get_documentation_repos.return_value = []
            run_main_github(tmp_path, None, repo_fetcher)
            mock_gc.assert_called_once()

    def test_relative_mapping_file_resolved_against_cwd(self, tmp_path):
        """A relative mapping_file is resolved relative to the patched cwd."""
        setup_sources_yaml(tmp_path, {})
        # Relative mapping file — exercises the is_absolute() branch
        config = Config(org_name="", mapping_file=Path(".opencrane/config.yaml"))
        repo_fetcher = MagicMock()
        repo_fetcher.get_documentation_repos.return_value = []
        # Should not raise; config.yaml under tmp_path is found via Path.cwd patch
        run_main_github(tmp_path, config, repo_fetcher)

    def test_auto_discovery_processes_repo(self, tmp_path):
        """Auto-discovered repos are fetched and written to the source mapping."""
        setup_sources_yaml(tmp_path, {})
        config = Config(
            org_name="myorg",
            mapping_file=tmp_path / ".opencrane" / "config.yaml",
            target_dir=tmp_path / ".opencrane" / "sources",
        )
        config.auto_discovery_orgs = ["myorg"]

        repo = make_repo("auto-repo")
        repo_fetcher = MagicMock()
        repo_fetcher.get_documentation_repos.return_value = [repo]
        repo_fetcher.get_repo_files.return_value = [MagicMock()]

        run_main_github(tmp_path, config, repo_fetcher)

        mapping = SourceMapping(tmp_path / ".opencrane" / "config.yaml")
        assert mapping.get_source("auto-repo") is not None
        assert mapping.get_source("auto-repo")["url"].endswith("myorg/auto-repo")

    def test_auto_discovery_filtered_by_source(self, tmp_path):
        """--source filter narrows auto-discovered repos."""
        setup_sources_yaml(tmp_path, {})
        config = Config(
            org_name="myorg",
            mapping_file=tmp_path / ".opencrane" / "config.yaml",
            target_dir=tmp_path / ".opencrane" / "sources",
            fetch_repo="wanted",
        )
        config.auto_discovery_orgs = ["myorg"]

        wanted = make_repo("wanted")
        unwanted = make_repo("unwanted")
        repo_fetcher = MagicMock()
        repo_fetcher.get_documentation_repos.return_value = [wanted, unwanted]
        repo_fetcher.get_repo_files.return_value = [MagicMock()]

        run_main_github(tmp_path, config, repo_fetcher)

        mapping = SourceMapping(tmp_path / ".opencrane" / "config.yaml")
        assert mapping.get_source("wanted") is not None
        assert mapping.get_source("unwanted") is None

    def test_manual_github_repo_fetched_and_processed(self, tmp_path):
        """A manual github source is fetched, processed and stored with ref fields."""
        setup_sources_yaml(tmp_path, {
            "external/cgw": {
                "url": "https://github.com/otherorg/cgw",
                "manual": True,
                "docs_path": "docs",
                "tag": "v1.2.3",
            }
        })
        config = Config(
            org_name="myorg",
            mapping_file=tmp_path / ".opencrane" / "config.yaml",
            target_dir=tmp_path / ".opencrane" / "sources",
        )

        manual_repo = make_repo("cgw")
        repo_fetcher = MagicMock()
        repo_fetcher.get_documentation_repos.return_value = []
        repo_fetcher.get_manual_repo.return_value = manual_repo
        repo_fetcher.get_repo_files.return_value = [MagicMock()]

        run_main_github(tmp_path, config, repo_fetcher)

        # get_manual_repo was called with parsed org/repo
        repo_fetcher.get_manual_repo.assert_called_once_with("otherorg", "cgw")
        # ref_config (tag) is forwarded to get_repo_files
        _, kwargs = repo_fetcher.get_repo_files.call_args
        assert kwargs["ref_config"] == {"tag": "v1.2.3"}

        mapping = SourceMapping(tmp_path / ".opencrane" / "config.yaml")
        entry = mapping.get_source("external/cgw")
        assert entry is not None
        assert entry.get("tag") == "v1.2.3"

    def test_manual_github_skips_self_reference(self, tmp_path, caplog):
        """A manual entry pointing at the current repo in our org is skipped."""
        setup_sources_yaml(tmp_path, {
            "self": {
                "url": "https://github.com/myorg/opencrane",
                "manual": True,
            }
        })
        config = Config(
            org_name="myorg",
            mapping_file=tmp_path / ".opencrane" / "config.yaml",
            target_dir=tmp_path / ".opencrane" / "sources",
        )
        repo_fetcher = MagicMock()
        repo_fetcher.get_documentation_repos.return_value = []

        import logging
        with caplog.at_level(logging.INFO, logger="opencrane.rag.fetch_docs"):
            run_main_github(tmp_path, config, repo_fetcher,
                            current_repo_name="opencrane")

        assert "Skipping self-reference" in caplog.text
        repo_fetcher.get_manual_repo.assert_not_called()

    def test_manual_github_skipped_by_source_filter(self, tmp_path, caplog):
        """A manual github entry not in the --source filter is skipped."""
        setup_sources_yaml(tmp_path, {
            "external/wanted": {
                "url": "https://github.com/otherorg/wanted",
                "manual": True,
            },
            "external/other": {
                "url": "https://github.com/otherorg/other",
                "manual": True,
            },
        })
        config = Config(
            org_name="myorg",
            mapping_file=tmp_path / ".opencrane" / "config.yaml",
            target_dir=tmp_path / ".opencrane" / "sources",
            fetch_repo="external/wanted",
        )
        repo_fetcher = MagicMock()
        repo_fetcher.get_documentation_repos.return_value = []
        repo_fetcher.get_manual_repo.return_value = make_repo("wanted")
        repo_fetcher.get_repo_files.return_value = [MagicMock()]

        import logging
        with caplog.at_level(logging.DEBUG, logger="opencrane.rag.fetch_docs"):
            run_main_github(tmp_path, config, repo_fetcher)

        # Only the wanted repo was fetched
        repo_fetcher.get_manual_repo.assert_called_once_with("otherorg", "wanted")
        assert "Skipping external/other" in caplog.text
        assert "--source filter active" in caplog.text

    def test_manual_entry_no_url_skipped(self, tmp_path, caplog):
        """A manual github entry with no url logs a warning and is skipped."""
        setup_sources_yaml(tmp_path, {
            "no-url": {"manual": True},
        })
        config = make_config(tmp_path)
        repo_fetcher = MagicMock()
        repo_fetcher.get_documentation_repos.return_value = []

        import logging
        with caplog.at_level(logging.WARNING, logger="opencrane.rag.fetch_docs"):
            run_main_github(tmp_path, config, repo_fetcher)

        assert "no-url" in caplog.text
        assert "no url" in caplog.text.lower()

    def test_manual_entry_unparseable_url_skipped(self, tmp_path, caplog):
        """A manual entry whose url cannot be parsed is skipped with a warning."""
        setup_sources_yaml(tmp_path, {
            "bad-url": {"url": "not-a-github-url", "manual": True},
        })
        config = make_config(tmp_path)
        repo_fetcher = MagicMock()
        repo_fetcher.get_documentation_repos.return_value = []

        import logging
        with caplog.at_level(logging.WARNING, logger="opencrane.rag.fetch_docs"):
            run_main_github(tmp_path, config, repo_fetcher)

        assert "Could not parse GitHub URL" in caplog.text
        repo_fetcher.get_manual_repo.assert_not_called()

    def test_manual_fetch_error_logged(self, tmp_path, caplog):
        """An exception while fetching a manual repo is logged, not raised."""
        setup_sources_yaml(tmp_path, {
            "external/boom": {"url": "https://github.com/otherorg/boom", "manual": True},
        })
        config = make_config(tmp_path)
        repo_fetcher = MagicMock()
        repo_fetcher.get_documentation_repos.return_value = []
        repo_fetcher.get_manual_repo.side_effect = RuntimeError("api down")

        import logging
        with caplog.at_level(logging.ERROR, logger="opencrane.rag.fetch_docs"):
            run_main_github(tmp_path, config, repo_fetcher)

        assert "Failed to fetch manual repo otherorg/boom" in caplog.text

    def test_process_repo_no_files_returns_none(self, tmp_path, caplog):
        """When a repo yields no files, it is not added to the source mapping."""
        setup_sources_yaml(tmp_path, {
            "external/empty": {"url": "https://github.com/otherorg/empty", "manual": True},
        })
        config = Config(
            org_name="myorg",
            mapping_file=tmp_path / ".opencrane" / "config.yaml",
            target_dir=tmp_path / ".opencrane" / "sources",
        )
        manual_repo = make_repo("empty")
        repo_fetcher = MagicMock()
        repo_fetcher.get_documentation_repos.return_value = []
        repo_fetcher.get_manual_repo.return_value = manual_repo
        repo_fetcher.get_repo_files.return_value = []  # no files

        import logging
        with caplog.at_level(logging.WARNING, logger="opencrane.rag.fetch_docs"):
            run_main_github(tmp_path, config, repo_fetcher)

        assert "No files found" in caplog.text
        # process_repo returned None -> add_source was not called, so the only
        # entry present is the original manual one from config.yaml (preserved
        # because manual entries are never cleaned up). docs_path is unset
        # because the processing path never reached add_source.
        mapping = SourceMapping(tmp_path / ".opencrane" / "config.yaml")
        entry = mapping.get_source("external/empty")
        assert entry is not None
        assert entry.get("docs_path") is None

    def test_process_repo_exception_logged(self, tmp_path, caplog):
        """An exception during repo processing is logged and yields no source."""
        setup_sources_yaml(tmp_path, {
            "external/err": {"url": "https://github.com/otherorg/err", "manual": True},
        })
        config = Config(
            org_name="myorg",
            mapping_file=tmp_path / ".opencrane" / "config.yaml",
            target_dir=tmp_path / ".opencrane" / "sources",
        )
        manual_repo = make_repo("err")
        repo_fetcher = MagicMock()
        repo_fetcher.get_documentation_repos.return_value = []
        repo_fetcher.get_manual_repo.return_value = manual_repo
        repo_fetcher.get_repo_files.side_effect = RuntimeError("tree error")

        import logging
        with caplog.at_level(logging.ERROR, logger="opencrane.rag.fetch_docs"):
            run_main_github(tmp_path, config, repo_fetcher)

        assert "Failed to process repository otherorg/err" in caplog.text

    def test_different_org_repo_protected_from_cleanup(self, tmp_path):
        """A manual repo from a different org is marked active (not cleaned up)."""
        setup_sources_yaml(tmp_path, {
            "external/keep": {
                "url": "https://github.com/otherorg/keep",
                "manual": True,
            },
        })
        config = Config(
            org_name="myorg",
            mapping_file=tmp_path / ".opencrane" / "config.yaml",
            target_dir=tmp_path / ".opencrane" / "sources",
        )
        manual_repo = make_repo("keep")
        repo_fetcher = MagicMock()
        repo_fetcher.get_documentation_repos.return_value = []
        repo_fetcher.get_manual_repo.return_value = manual_repo
        repo_fetcher.get_repo_files.return_value = [MagicMock()]

        run_main_github(tmp_path, config, repo_fetcher)

        mapping = SourceMapping(tmp_path / ".opencrane" / "config.yaml")
        # manual entries are preserved by cleanup regardless
        assert mapping.get_source("external/keep") is not None

    def test_stale_source_directories_removed(self, tmp_path):
        """Stale (non-manual, inactive) sources have their dirs removed and entry dropped."""
        # A non-manual github entry that will NOT be re-discovered -> stale
        setup_sources_yaml(tmp_path, {
            "stale-repo": {
                "url": "https://github.com/myorg/stale-repo",
                "manual": False,
            },
        })
        config = Config(
            org_name="myorg",
            mapping_file=tmp_path / ".opencrane" / "config.yaml",
            target_dir=tmp_path / ".opencrane" / "sources",
        )
        config.auto_discovery_orgs = ["myorg"]

        # Create source + llmstxt dirs that should be removed
        source_dir = config.target_dir / "stale-repo"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "old.md").write_text("old")
        llmstxt_dir = tmp_path / ".opencrane" / "llmstxt" / "stale-repo"
        llmstxt_dir.mkdir(parents=True, exist_ok=True)
        (llmstxt_dir / "llms-full.txt").write_text("old")

        repo_fetcher = MagicMock()
        # Auto-discovery returns nothing -> stale-repo is not active
        repo_fetcher.get_documentation_repos.return_value = []

        run_main_github(tmp_path, config, repo_fetcher)

        assert not source_dir.exists()
        assert not llmstxt_dir.exists()
        mapping = SourceMapping(tmp_path / ".opencrane" / "config.yaml")
        assert mapping.get_source("stale-repo") is None

    def test_outer_exception_exits(self, tmp_path):
        """An unexpected failure in main() calls sys.exit(1)."""
        config = make_config(tmp_path)
        with patch("opencrane.rag.fetch_docs.setup_logging"), \
             patch("opencrane.rag.fetch_docs.SourceMapping",
                   side_effect=RuntimeError("boom")), \
             patch("opencrane.rag.fetch_docs.Path.cwd", return_value=tmp_path):
            from opencrane.rag import fetch_docs
            with pytest.raises(SystemExit) as exc_info:
                fetch_docs.main(config)
            assert exc_info.value.code == 1
