import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from opencrane.shared.config import Config
from opencrane.rag.fetch_docs import main
from opencrane.shared.models.repository import Repository as RepoModel
from opencrane.shared.models.file import File


class TestFullWorkflow:
    """Integration tests for the full documentation fetch workflow."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def test_config(self, temp_dir):
        """Create a test configuration."""
        # Create a mapping file
        mapping_file = temp_dir / "opencrane-sources.yaml"
        mapping_file.write_text("sources: {}")

        return Config(
            org_name="test_org",
            target_dir=temp_dir / "docs",
            docs_topic="documentation",
            github_token="fake_token",
            mapping_file=mapping_file,
            auto_discovery_orgs=["test_org"]
        )

    @patch('opencrane.rag.fetch_docs.get_current_repo_name', return_value='my-repo')
    @patch('opencrane.rag.fetch_docs.SourceMapping')
    @patch('opencrane.rag.fetch_docs.setup_logging')
    @patch('opencrane.rag.fetch_docs.get_config')
    @patch('opencrane.rag.fetch_docs.GitHubClient')
    @patch('opencrane.rag.fetch_docs.RepoFetcher')
    @patch('opencrane.rag.fetch_docs.FileManager')
    def test_full_workflow_success(self, mock_file_manager, mock_repo_fetcher,
                                   mock_github_client, mock_get_config, mock_setup_logging,
                                   mock_source_mapping, mock_get_repo_name, test_config):
        """Test successful full workflow execution."""
        # Setup mocks
        mock_get_config.return_value = test_config

        # Mock source mapping to return empty manual sources
        mock_mapping_instance = Mock()
        mock_mapping_instance.get_all_sources.return_value = {}
        mock_mapping_instance.cleanup_stale_sources.return_value = []
        mock_mapping_instance.save.return_value = None
        mock_source_mapping.return_value = mock_mapping_instance

        # Mock repositories
        mock_repo = RepoModel(name="test-repo", topics=["documentation"], has_docs_directory=True)
        mock_repo_fetcher.return_value.get_documentation_repos.return_value = [mock_repo]

        # Mock files
        mock_file = File(
            repo_name="test-repo",
            relative_path="README.md",
            content=b"# Test content",
            size=15
        )
        mock_repo_fetcher.return_value.get_repo_files.return_value = [mock_file]

        # Mock file manager
        mock_file_manager.return_value.store_repo_files.return_value = None

        # Run main
        main()

        # Verify calls
        mock_setup_logging.assert_called_once()
        mock_get_config.assert_called_once()
        mock_github_client.assert_called_once()
        mock_repo_fetcher.assert_called_once_with(test_config)
        mock_file_manager.assert_called_once_with(test_config)

        mock_repo_fetcher.return_value.get_documentation_repos.assert_called_once()
        # Verify get_repo_files was called with org_name parameter
        mock_repo_fetcher.return_value.get_repo_files.assert_called_once_with(mock_repo, org_name='test_org', docs_path='docs')
        expected_path_key = f"{test_config.target_dir.as_posix()}/test-repo"
        mock_file_manager.return_value.store_repo_files.assert_called_once_with(expected_path_key, [mock_file])

    @patch('opencrane.rag.fetch_docs.get_current_repo_name', return_value='my-repo')
    @patch('opencrane.rag.fetch_docs.SourceMapping')
    @patch('opencrane.rag.fetch_docs.setup_logging')
    @patch('opencrane.rag.fetch_docs.get_config')
    @patch('opencrane.rag.fetch_docs.GitHubClient')
    @patch('opencrane.rag.fetch_docs.RepoFetcher')
    @patch('opencrane.rag.fetch_docs.FileManager')
    def test_full_workflow_no_repos(self, mock_file_manager, mock_repo_fetcher,
                                    mock_github_client, mock_get_config, mock_setup_logging,
                                    mock_source_mapping, mock_get_repo_name, test_config):
        """Test workflow when no documentation repositories are found."""
        mock_get_config.return_value = test_config

        # Mock source mapping to return empty manual sources
        mock_mapping_instance = Mock()
        mock_mapping_instance.get_all_sources.return_value = {}
        mock_mapping_instance.cleanup_stale_sources.return_value = []
        mock_mapping_instance.save.return_value = None
        mock_source_mapping.return_value = mock_mapping_instance

        mock_repo_fetcher.return_value.get_documentation_repos.return_value = []

        main()

        # Verify repo fetcher was called but file manager was not
        mock_repo_fetcher.return_value.get_documentation_repos.assert_called_once()
        mock_repo_fetcher.return_value.get_repo_files.assert_not_called()
        mock_file_manager.return_value.store_repo_files.assert_not_called()

    @patch('opencrane.rag.fetch_docs.get_current_repo_name', return_value='my-repo')
    @patch('opencrane.rag.fetch_docs.SourceMapping')
    @patch('opencrane.rag.fetch_docs.setup_logging')
    @patch('opencrane.rag.fetch_docs.get_config')
    @patch('opencrane.rag.fetch_docs.GitHubClient')
    @patch('opencrane.rag.fetch_docs.RepoFetcher')
    @patch('opencrane.rag.fetch_docs.FileManager')
    def test_full_workflow_no_files(self, mock_file_manager, mock_repo_fetcher,
                                    mock_github_client, mock_get_config, mock_setup_logging,
                                    mock_source_mapping, mock_get_repo_name, test_config):
        """Test workflow when repository has no files."""
        mock_get_config.return_value = test_config

        # Mock source mapping to return empty manual sources
        mock_mapping_instance = Mock()
        mock_mapping_instance.get_all_sources.return_value = {}
        mock_mapping_instance.cleanup_stale_sources.return_value = []
        mock_mapping_instance.save.return_value = None
        mock_source_mapping.return_value = mock_mapping_instance

        mock_repo = RepoModel(name="test-repo", topics=["documentation"], has_docs_directory=True)
        mock_repo_fetcher.return_value.get_documentation_repos.return_value = [mock_repo]
        mock_repo_fetcher.return_value.get_repo_files.return_value = []

        main()

        # Verify file fetcher was called but file manager was not
        mock_repo_fetcher.return_value.get_repo_files.assert_called_once_with(mock_repo, org_name='test_org', docs_path='docs')
        mock_file_manager.return_value.store_repo_files.assert_not_called()

    @patch('opencrane.rag.fetch_docs.get_current_repo_name', return_value='my-repo')
    @patch('opencrane.rag.fetch_docs.SourceMapping')
    @patch('opencrane.rag.fetch_docs.setup_logging')
    @patch('opencrane.rag.fetch_docs.get_config')
    @patch('opencrane.rag.fetch_docs.GitHubClient')
    @patch('opencrane.rag.fetch_docs.RepoFetcher')
    @patch('opencrane.rag.fetch_docs.FileManager')
    def test_full_workflow_repo_processing_exception(self, mock_file_manager, mock_repo_fetcher,
                                                     mock_github_client, mock_get_config, mock_setup_logging,
                                                     mock_source_mapping, mock_get_repo_name, test_config):
        """Test workflow when a single repo fails but others succeed."""
        mock_get_config.return_value = test_config

        # Mock source mapping to return empty manual sources
        mock_mapping_instance = Mock()
        mock_mapping_instance.get_all_sources.return_value = {}
        mock_mapping_instance.cleanup_stale_sources.return_value = []
        mock_mapping_instance.save.return_value = None
        mock_source_mapping.return_value = mock_mapping_instance

        # Create two repos - one will fail
        mock_repo1 = RepoModel(name="test-repo-1", topics=["documentation"], has_docs_directory=True)
        mock_repo2 = RepoModel(name="test-repo-2", topics=["documentation"], has_docs_directory=True)
        mock_repo_fetcher.return_value.get_documentation_repos.return_value = [mock_repo1, mock_repo2]

        # First repo succeeds, second fails
        mock_file = File(
            repo_name="test-repo-1",
            relative_path="README.md",
            content=b"# Test",
            size=6
        )

        def side_effect(repo, org_name=None, docs_path=None):
            if repo.name == "test-repo-1":
                return [mock_file]
            else:
                raise Exception("Failed to fetch repo-2")

        mock_repo_fetcher.return_value.get_repo_files.side_effect = side_effect

        main()

        # Verify at least one repo was processed successfully
        assert mock_file_manager.return_value.store_repo_files.call_count >= 1

    @patch('opencrane.rag.fetch_docs.sys.exit')
    @patch('opencrane.rag.fetch_docs.setup_logging')
    @patch('opencrane.rag.fetch_docs.get_config')
    @patch('opencrane.rag.fetch_docs.GitHubClient')
    @patch('opencrane.rag.fetch_docs.RepoFetcher')
    @patch('opencrane.rag.fetch_docs.FileManager')
    def test_full_workflow_error_handling(self, mock_file_manager, mock_repo_fetcher,
                                          mock_github_client, mock_get_config, mock_setup_logging, mock_sys_exit, test_config, caplog):
        """Test error handling in the workflow."""
        mock_get_config.return_value = test_config
        mock_repo_fetcher.return_value.get_documentation_repos.side_effect = Exception("API Error")

        main()

        # Verify sys.exit(1) was called
        mock_sys_exit.assert_called_once_with(1)

        # Check that error was logged
        assert "API Error" in caplog.text

    @patch('opencrane.rag.fetch_docs.get_current_repo_name', return_value='my-repo')
    @patch('opencrane.rag.fetch_docs.SourceMapping')
    @patch('opencrane.rag.fetch_docs.setup_logging')
    @patch('opencrane.rag.fetch_docs.get_config')
    @patch('opencrane.rag.fetch_docs.GitHubClient')
    @patch('opencrane.rag.fetch_docs.RepoFetcher')
    @patch('opencrane.rag.fetch_docs.FileManager')
    def test_org_filter_protects_other_org_repos(self, mock_file_manager, mock_repo_fetcher,
                                                  mock_github_client, mock_get_config, mock_setup_logging,
                                                  mock_source_mapping, mock_get_repo_name, temp_dir):
        """Test that filtering by --org does not remove repos from other orgs."""
        # Setup config for other-org
        mapping_file = temp_dir / "opencrane-sources.yaml"
        mapping_file.write_text("sources: {}")

        other_org_config = Config(
            org_name="other-org",
            target_dir=temp_dir / "docs",
            docs_topic="documentation",
            github_token="fake_token",
            mapping_file=mapping_file,
            auto_discovery_orgs=["my-org"]  # Only my-org has auto-discovery
        )
        mock_get_config.return_value = other_org_config

        # Mock source mapping to return repos from multiple orgs
        mock_mapping_instance = Mock()
        mock_mapping_instance.get_all_sources.return_value = {
            "external-sources/my-org-repo-1": {
                "url": "https://github.com/my-org/my-org-repo-1",
                "docs_path": "docs",
                "manual": False
            },
            "external-sources/my-org-repo-2": {
                "url": "https://github.com/my-org/my-org-repo-2",
                "docs_path": "docs",
                "manual": False
            },
            "external-sources/other-org-cgw": {
                "url": "https://github.com/other-org/cgw",
                "docs_path": "docs",
                "manual": True
            }
        }
        mock_mapping_instance.cleanup_stale_sources.return_value = []
        mock_mapping_instance.save.return_value = None
        mock_source_mapping.return_value = mock_mapping_instance

        # Mock repo fetcher - no auto-discovery for other-org
        mock_repo_fetcher.return_value.get_documentation_repos.return_value = []

        # Mock manual repo fetch for other-org
        mock_cgw_repo = RepoModel(name="cgw", topics=["documentation"], has_docs_directory=True)
        mock_repo_fetcher.return_value.get_manual_repo.return_value = mock_cgw_repo

        mock_file = File(
            repo_name="cgw",
            relative_path="README.md",
            content=b"# CGW",
            size=6
        )
        mock_repo_fetcher.return_value.get_repo_files.return_value = [mock_file]

        # Run main
        main()

        # Verify cleanup_stale_sources was called with active_repos that includes:
        # - other-org/cgw (processed in this run)
        # - my-org repos (protected from cleanup)
        cleanup_call_args = mock_mapping_instance.cleanup_stale_sources.call_args
        active_repos = cleanup_call_args[0][0]

        # Verify all repos are in active set (none should be marked stale)
        assert "external-sources/my-org-repo-1" in active_repos, "my-org repos should be protected from cleanup"
        assert "external-sources/my-org-repo-2" in active_repos, "my-org repos should be protected from cleanup"
        assert "external-sources/other-org-cgw" in active_repos, "other-org repo should be in active set"

    @patch('opencrane.rag.fetch_docs.get_current_repo_name', return_value='my-repo')
    @patch('opencrane.rag.fetch_docs.SourceMapping')
    @patch('opencrane.rag.fetch_docs.setup_logging')
    @patch('opencrane.rag.fetch_docs.get_config')
    @patch('opencrane.rag.fetch_docs.GitHubClient')
    @patch('opencrane.rag.fetch_docs.RepoFetcher')
    @patch('opencrane.rag.fetch_docs.FileManager')
    def test_fetch_repo_filter_manual_repos(self, mock_file_manager, mock_repo_fetcher,
                                             mock_github_client, mock_get_config, mock_setup_logging,
                                             mock_source_mapping, mock_get_repo_name, temp_dir):
        """Test that --repo filter restricts processing to a single manual repo by path key."""
        mapping_file = temp_dir / "opencrane-sources.yaml"
        mapping_file.write_text("sources: {}")

        # Use default org (my-org) — --repo should bypass the org filter entirely
        config = Config(
            org_name="my-org",
            target_dir=temp_dir / "docs",
            docs_topic="documentation",
            github_token="fake_token",
            mapping_file=mapping_file,
            auto_discovery_orgs=["my-org"],
            fetch_repo="external-sources/cgw",
        )
        mock_get_config.return_value = config

        mock_mapping_instance = Mock()
        mock_mapping_instance.get_all_sources.return_value = {
            "external-sources/cgw": {
                "url": "https://github.com/other-org/cgw",
                "docs_path": "docs",
                "manual": True,
            },
            "external-sources/tsr": {
                "url": "https://github.com/other-org/tsr",
                "docs_path": "docs",
                "manual": True,
            },
        }
        mock_mapping_instance.cleanup_stale_sources.return_value = []
        mock_mapping_instance.save.return_value = None
        mock_source_mapping.return_value = mock_mapping_instance

        mock_repo_fetcher.return_value.get_documentation_repos.return_value = []

        cgw_repo = RepoModel(name="cgw", topics=[], has_docs_directory=True)
        mock_repo_fetcher.return_value.get_manual_repo.return_value = cgw_repo
        mock_file = File(repo_name="cgw", relative_path="README.md", content=b"# CGW", size=5)
        mock_repo_fetcher.return_value.get_repo_files.return_value = [mock_file]

        main()

        # Only cgw should have been fetched; tsr must not be requested
        calls = [call[0][1] for call in mock_repo_fetcher.return_value.get_manual_repo.call_args_list]
        assert "cgw" in calls
        assert "tsr" not in calls

    @patch('opencrane.rag.fetch_docs.get_current_repo_name', return_value='my-repo')
    @patch('opencrane.rag.fetch_docs.SourceMapping')
    @patch('opencrane.rag.fetch_docs.setup_logging')
    @patch('opencrane.rag.fetch_docs.get_config')
    @patch('opencrane.rag.fetch_docs.GitHubClient')
    @patch('opencrane.rag.fetch_docs.RepoFetcher')
    @patch('opencrane.rag.fetch_docs.FileManager')
    def test_fetch_repo_filter_auto_discovered_repos(self, mock_file_manager, mock_repo_fetcher,
                                                      mock_github_client, mock_get_config, mock_setup_logging,
                                                      mock_source_mapping, mock_get_repo_name, temp_dir):
        """Test that --repo filter restricts processing to a single auto-discovered repo by path key."""
        mapping_file = temp_dir / "opencrane-sources.yaml"
        mapping_file.write_text("sources: {}")

        config = Config(
            org_name="my-org",
            target_dir=Path("external-sources"),
            docs_topic="documentation",
            github_token="fake_token",
            mapping_file=mapping_file,
            auto_discovery_orgs=["my-org"],
            fetch_repo="external-sources/target-repo",
        )
        mock_get_config.return_value = config

        mock_mapping_instance = Mock()
        mock_mapping_instance.get_all_sources.return_value = {}
        mock_mapping_instance.cleanup_stale_sources.return_value = []
        mock_mapping_instance.save.return_value = None
        mock_source_mapping.return_value = mock_mapping_instance

        # Auto-discovery returns two repos; only target-repo should survive the filter
        target_repo = RepoModel(name="target-repo", topics=["documentation"], has_docs_directory=True)
        other_repo = RepoModel(name="other-repo", topics=["documentation"], has_docs_directory=True)
        mock_repo_fetcher.return_value.get_documentation_repos.return_value = [target_repo, other_repo]

        mock_file = File(repo_name="target-repo", relative_path="README.md", content=b"# Target", size=8)
        mock_repo_fetcher.return_value.get_repo_files.return_value = [mock_file]

        main()

        # get_repo_files should only be called once (for target-repo)
        assert mock_repo_fetcher.return_value.get_repo_files.call_count == 1
        call_repo = mock_repo_fetcher.return_value.get_repo_files.call_args[0][0]
        assert call_repo.name == "target-repo"

    @patch('opencrane.rag.fetch_docs.get_current_repo_name', return_value='my-repo')
    @patch('opencrane.rag.fetch_docs.SourceMapping')
    @patch('opencrane.rag.fetch_docs.setup_logging')
    @patch('opencrane.rag.fetch_docs.get_config')
    @patch('opencrane.rag.fetch_docs.GitHubClient')
    @patch('opencrane.rag.fetch_docs.RepoFetcher')
    @patch('opencrane.rag.fetch_docs.FileManager')
    def test_fetch_repo_filter_protects_other_repos_from_cleanup(
            self, mock_file_manager, mock_repo_fetcher,
            mock_github_client, mock_get_config, mock_setup_logging,
            mock_source_mapping, mock_get_repo_name, temp_dir):
        """Test that --repo filter does not cause other repos to be cleaned up."""
        mapping_file = temp_dir / "opencrane-sources.yaml"
        mapping_file.write_text("sources: {}")

        config = Config(
            org_name="my-org",
            target_dir=Path("external-sources"),
            docs_topic="documentation",
            github_token="fake_token",
            mapping_file=mapping_file,
            auto_discovery_orgs=["my-org"],
            fetch_repo="external-sources/cgw",
        )
        mock_get_config.return_value = config

        mock_mapping_instance = Mock()
        mock_mapping_instance.get_all_sources.return_value = {
            "external-sources/cgw": {
                "url": "https://github.com/other-org/cgw",
                "docs_path": "docs",
                "manual": True,
            },
            "external-sources/tsr": {
                "url": "https://github.com/other-org/tsr",
                "docs_path": "docs",
                "manual": True,
            },
            "external-sources/other-my-org-repo": {
                "url": "https://github.com/my-org/other-my-org-repo",
                "docs_path": "docs",
                "manual": False,
            },
        }
        mock_mapping_instance.cleanup_stale_sources.return_value = []
        mock_mapping_instance.save.return_value = None
        mock_source_mapping.return_value = mock_mapping_instance

        mock_repo_fetcher.return_value.get_documentation_repos.return_value = []
        cgw_repo = RepoModel(name="cgw", topics=[], has_docs_directory=True)
        mock_repo_fetcher.return_value.get_manual_repo.return_value = cgw_repo
        mock_file = File(repo_name="cgw", relative_path="README.md", content=b"# CGW", size=5)
        mock_repo_fetcher.return_value.get_repo_files.return_value = [mock_file]

        main()

        active_repos = mock_mapping_instance.cleanup_stale_sources.call_args[0][0]
        # All repos must be protected — only cgw was processed but others must not be removed
        assert "external-sources/cgw" in active_repos
        assert "external-sources/tsr" in active_repos, "tsr must be protected from cleanup"
        assert "external-sources/other-my-org-repo" in active_repos, "other my-org repo must be protected"