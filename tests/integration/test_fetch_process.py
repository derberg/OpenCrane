import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from opencrane.shared.config import Config
from opencrane.shared.models.repository import Repository as RepoModel
from opencrane.shared.models.file import File


class TestFetchProcess:
    """Integration tests for the complete fetch process."""

    def test_full_fetch_process(self, mocker):
        """Test the complete fetch and store process."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)

            # Create config
            config = Config(target_dir=base_dir / "external-sources" / "product-docs")

            # Mock GitHub client methods
            mock_github_client = mocker.patch('opencrane.rag.repo_fetcher.GitHubClient')
            
            # Mock repo model
            repo_model = RepoModel(name="test-repo", topics=["documentation"], has_docs_directory=True)
            mock_github_client.return_value.get_org_repos.return_value = [Mock()]  # Mock repo object
            mock_github_client.return_value.filter_repos_by_topic.return_value = [Mock()]  # Mock repo object
            
            # Mock the repo_fetcher to return our repo model
            mock_fetcher = mocker.patch('opencrane.rag.repo_fetcher.RepoFetcher')
            mock_fetcher.return_value.get_documentation_repos.return_value = [repo_model]
            
            # Mock files
            files = [
                File(repo_name="test-repo", relative_path="README.md", content=b"# Test README")
            ]
            mock_fetcher.return_value.get_repo_files.return_value = files

            # Import and run components
            from opencrane.rag.repo_fetcher import RepoFetcher
            from opencrane.rag.file_manager import FileManager

            fetcher = RepoFetcher(config)
            file_manager = FileManager(config)

            repos = fetcher.get_documentation_repos()
            for repo in repos:
                files = fetcher.get_repo_files(repo)
                file_manager.store_repo_files(str(config.target_dir / repo.name), files)

            # Verify file was stored
            repo_dir = config.target_dir / "test-repo"
            assert (repo_dir / "README.md").read_bytes() == b"# Test README"