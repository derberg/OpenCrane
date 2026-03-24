import pytest
from unittest.mock import Mock
from opencrane.rag.repo_fetcher import RepoFetcher
from opencrane.shared.config import Config
from opencrane.shared.models.repository import Repository as RepoModel


class TestRepoFetcher:
    """Unit tests for RepoFetcher."""

    @pytest.fixture
    def config(self):
        """Create a test config."""
        return Config(org_name="test_org", docs_topic="documentation")

    @pytest.fixture
    def repo_fetcher(self, config, mocker):
        """Create a RepoFetcher with mocked GitHub client."""
        mocker.patch('opencrane.rag.repo_fetcher.GitHubClient')
        return RepoFetcher(config)

    def test_get_documentation_repos_success(self, repo_fetcher, mocker):
        """Test successful retrieval of documentation repositories."""
        # Mock the GitHub client methods
        mock_client = repo_fetcher.github_client
        mock_repo1 = Mock()
        mock_repo1.name = "repo1"
        mock_repo1.get_topics.return_value = ["documentation"]
        mock_repo2 = Mock()
        mock_repo2.name = "repo2"
        mock_repo2.get_topics.return_value = ["other"]

        mock_client.get_org_repos.return_value = [mock_repo1, mock_repo2]
        mock_client.filter_repos_by_topic.return_value = [mock_repo1]

        # Mock _has_docs_directory
        mocker.patch.object(repo_fetcher, '_has_docs_directory', return_value=True)

        repos = repo_fetcher.get_documentation_repos()

        assert len(repos) == 1
        assert repos[0].name == "repo1"
        assert repos[0].topics == ["documentation"]
        assert repos[0].has_docs_directory is True

    def test_get_documentation_repos_no_repos(self, repo_fetcher, mocker):
        """Test when no documentation repositories are found."""
        mock_client = repo_fetcher.github_client
        mock_client.get_org_repos.return_value = []
        mock_client.filter_repos_by_topic.return_value = []

        repos = repo_fetcher.get_documentation_repos()

        assert len(repos) == 0

    def test_get_documentation_repos_error(self, repo_fetcher, mocker):
        """Test error handling when getting repositories fails."""
        mock_client = repo_fetcher.github_client
        mock_client.get_org_repos.side_effect = Exception("API error")

        with pytest.raises(Exception, match="API error"):
            repo_fetcher.get_documentation_repos()

    def test_get_repo_files_success(self, repo_fetcher, mocker):
        """Test successful retrieval of repository files."""
        mock_repo_model = RepoModel(name="test_repo", topics=["documentation"], has_docs_directory=True)

        # Mock the GitHub client methods
        mock_client = repo_fetcher.github_client
        mock_org = Mock()
        mock_repo = Mock()
        mock_org.get_repo.return_value = mock_repo
        mock_client.client.get_organization.return_value = mock_org

        mock_files = [Mock(), Mock()]  # Mock file objects
        mock_client.get_repo_files.return_value = mock_files

        files = repo_fetcher.get_repo_files(mock_repo_model)

        assert len(files) == 2
        mock_client.client.get_organization.assert_called_once_with("test_org")
        mock_org.get_repo.assert_called_once_with("test_repo")
        mock_client.get_repo_files.assert_called_once_with(mock_repo, docs_path="docs")

    def test_get_repo_files_with_custom_docs_path(self, repo_fetcher, mocker):
        """Test retrieval of repository files with custom docs_path."""
        mock_repo_model = RepoModel(name="test_repo", topics=["documentation"], has_docs_directory=True)

        mock_client = repo_fetcher.github_client
        mock_org = Mock()
        mock_repo = Mock()
        mock_org.get_repo.return_value = mock_repo
        mock_client.client.get_organization.return_value = mock_org

        mock_files = [Mock()]
        mock_client.get_repo_files.return_value = mock_files

        files = repo_fetcher.get_repo_files(mock_repo_model, docs_path="styleguide")

        assert len(files) == 1
        mock_client.get_repo_files.assert_called_once_with(mock_repo, docs_path="styleguide")

    def test_get_repo_files_error(self, repo_fetcher, mocker):
        """Test error handling when getting repository files fails."""
        mock_repo_model = RepoModel(name="test_repo", topics=["documentation"], has_docs_directory=True)

        mock_client = repo_fetcher.github_client
        mock_client.client.get_organization.side_effect = Exception("API error")

        files = repo_fetcher.get_repo_files(mock_repo_model)

        assert len(files) == 0

    def test_has_docs_directory_true(self, repo_fetcher, mocker):
        """Test _has_docs_directory returns True when docs exists."""
        mock_repo = Mock()
        mock_repo.get_contents.return_value = [Mock()]  # Mock contents

        result = repo_fetcher._has_docs_directory(mock_repo)

        assert result is True
        mock_repo.get_contents.assert_called_once_with("docs")

    def test_has_docs_directory_false(self, repo_fetcher, mocker):
        """Test _has_docs_directory returns False when docs doesn't exist."""
        mock_repo = Mock()
        mock_repo.get_contents.side_effect = Exception("Not found")

        result = repo_fetcher._has_docs_directory(mock_repo)

        assert result is False
        mock_repo.get_contents.assert_called_once_with("docs")

    def test_get_manual_repo_success(self, repo_fetcher, mocker):
        """Test successful retrieval of a manual repository."""
        # Mock the GitHub client methods
        mock_client = repo_fetcher.github_client
        mock_repo = Mock()
        mock_repo.name = "cgw"
        mock_repo.get_topics.return_value = ["telecom"]
        mock_client.get_repo.return_value = mock_repo

        # Mock _has_docs_directory
        mocker.patch.object(repo_fetcher, '_has_docs_directory', return_value=True)

        repo_model = repo_fetcher.get_manual_repo("example-org", "cgw")

        assert repo_model.name == "cgw"
        assert repo_model.topics == ["telecom"]
        assert repo_model.has_docs_directory is True
        mock_client.get_repo.assert_called_once_with("example-org", "cgw")

    def test_get_manual_repo_error(self, repo_fetcher, mocker):
        """Test error handling when getting manual repository fails."""
        mock_client = repo_fetcher.github_client
        mock_client.get_repo.side_effect = Exception("Repo not found")

        with pytest.raises(Exception, match="Repo not found"):
            repo_fetcher.get_manual_repo("example-org", "nonexistent")

    def test_get_repo_files_with_custom_org(self, repo_fetcher, mocker):
        """Test successful retrieval of repository files with custom org_name."""
        mock_repo_model = RepoModel(name="cgw", topics=["telecom"], has_docs_directory=True)

        # Mock the GitHub client methods
        mock_client = repo_fetcher.github_client
        mock_org = Mock()
        mock_repo = Mock()
        mock_org.get_repo.return_value = mock_repo
        mock_client.client.get_organization.return_value = mock_org

        mock_files = [Mock(), Mock()]  # Mock file objects
        mock_client.get_repo_files.return_value = mock_files

        files = repo_fetcher.get_repo_files(mock_repo_model, org_name="example-org")

        assert len(files) == 2
        mock_client.client.get_organization.assert_called_once_with("example-org")
        mock_org.get_repo.assert_called_once_with("cgw")
        mock_client.get_repo_files.assert_called_once_with(mock_repo, docs_path="docs")

    def test_repository_model_repr(self):
        """Test Repository model __repr__ method."""
        from opencrane.shared.models.repository import Repository
        repo = Repository(name="test-repo", topics=["documentation", "python"], has_docs_directory=True)
        repr_str = repr(repo)
        assert "Repository(" in repr_str
        assert "name='test-repo'" in repr_str
        assert "topics=['documentation', 'python']" in repr_str

    def test_repository_model_has_documentation_topic_property(self):
        """Test Repository model has_documentation_topic property."""
        from opencrane.shared.models.repository import Repository
        
        repo_with_docs = Repository(name="repo1", topics=["documentation", "api"], has_docs_directory=True)
        assert repo_with_docs.has_documentation_topic is True
        
        repo_without_docs = Repository(name="repo2", topics=["api", "python"], has_docs_directory=False)
        assert repo_without_docs.has_documentation_topic is False