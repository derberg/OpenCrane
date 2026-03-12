import pytest
import time
from unittest.mock import Mock, MagicMock, patch
from github import RateLimitExceededException, GithubException
from opencrane.rag.github_client import GitHubClient
from opencrane.shared.models.file import File


class TestGitHubClient:
    """Unit tests for GitHubClient."""

    def test_init_with_token(self):
        """Test initialization with token."""
        client = GitHubClient("fake_token")
        assert client.client is not None

    def test_init_without_token_raises_error(self, mocker):
        """Test initialization without token raises ValueError."""
        mock_config = mocker.patch('opencrane.rag.github_client.get_config')
        mock_config.return_value.github_token = ""
        with pytest.raises(ValueError, match="GitHub token is required"):
            GitHubClient()

    def test_get_org_repos(self, mocker):
        """Test getting organization repositories."""
        # Mock the Github client and organization
        mock_github = mocker.patch('opencrane.rag.github_client.Github')
        mock_org = Mock()
        mock_repo1 = Mock()
        mock_repo2 = Mock()
        mock_org.get_repos.return_value = [mock_repo1, mock_repo2]
        mock_github.return_value.get_organization.return_value = mock_org

        client = GitHubClient("fake_token")
        repos = client.get_org_repos("test_org")

    def test_get_org_repos_handles_exception(self, mocker):
        """Test that exceptions in get_org_repos are properly handled."""
        mocker.patch('time.sleep')  # Mock sleep to speed up retries
        mock_github = mocker.patch('opencrane.rag.github_client.Github')
        mock_github.return_value.get_organization.side_effect = Exception("API error")

        client = GitHubClient("fake_token")
        with pytest.raises(Exception, match="API error"):
            client.get_org_repos("test_org")

    def test_get_repo(self, mocker):
        """Test getting a specific repository by org and name."""
        # Mock the Github client, organization, and repository
        mock_github = mocker.patch('opencrane.rag.github_client.Github')
        mock_org = Mock()
        mock_repo = Mock()
        mock_repo.name = "cgw"
        mock_org.get_repo.return_value = mock_repo
        mock_github.return_value.get_organization.return_value = mock_org

        client = GitHubClient("fake_token")
        repo = client.get_repo("example-org", "cgw")

        assert repo == mock_repo
        mock_github.return_value.get_organization.assert_called_once_with("example-org")
        mock_org.get_repo.assert_called_once_with("cgw")

    def test_get_repo_handles_exception(self, mocker):
        """Test that exceptions in get_repo are properly handled."""
        mocker.patch('time.sleep')  # Mock sleep to speed up retries
        mock_github = mocker.patch('opencrane.rag.github_client.Github')
        mock_github.return_value.get_organization.side_effect = Exception("API error")

        client = GitHubClient("fake_token")
        with pytest.raises(Exception, match="API error"):
            client.get_repo("example-org", "cgw")

    def test_filter_repos_by_topic(self, mocker):
        """Test filtering repositories by topic."""
        mock_repo1 = Mock()
        mock_repo1.get_topics.return_value = ["documentation", "python"]
        mock_repo2 = Mock()
        mock_repo2.get_topics.return_value = ["javascript"]
        mock_repo3 = Mock()
        mock_repo3.get_topics.return_value = ["documentation", "api"]

        repos = [mock_repo1, mock_repo2, mock_repo3]
        client = GitHubClient("fake_token")
        filtered = client.filter_repos_by_topic(repos, "documentation")

        assert len(filtered) == 2
        assert mock_repo1 in filtered
        assert mock_repo3 in filtered
        assert mock_repo2 not in filtered

    def test_filter_repos_by_topic_handles_exception(self, mocker):
        """Test that exceptions when getting topics are handled gracefully."""
        mocker.patch('time.sleep')  # Mock sleep to speed up retries
        mock_repo1 = Mock()
        mock_repo1.name = "good-repo"
        mock_repo1.get_topics.return_value = ["documentation"]
        
        mock_repo2 = Mock()
        mock_repo2.name = "bad-repo"
        mock_repo2.get_topics.side_effect = Exception("API error")
        
        mock_repo3 = Mock()
        mock_repo3.name = "another-good-repo"
        mock_repo3.get_topics.return_value = ["documentation", "api"]

        repos = [mock_repo1, mock_repo2, mock_repo3]
        client = GitHubClient("fake_token")
        filtered = client.filter_repos_by_topic(repos, "documentation")

        # Should only include repos where get_topics succeeded
        assert len(filtered) == 2
        assert mock_repo1 in filtered
        assert mock_repo3 in filtered
        assert mock_repo2 not in filtered

    def test_get_latest_release_ref(self, mocker):
        """Test getting latest release reference."""
        mock_repo = Mock()
        mock_repo.name = "test-repo"
        
        mock_release = Mock()
        mock_release.tag_name = "v1.0.0"
        mock_repo.get_latest_release.return_value = mock_release
        
        client = GitHubClient("fake_token")
        ref = client.get_latest_release_ref(mock_repo)
        
        assert ref == "tags/v1.0.0"

    def test_get_latest_release_ref_no_releases(self, mocker):
        """Test getting latest release when no releases exist."""
        mocker.patch('time.sleep')  # Mock sleep to speed up retries
        mock_repo = Mock()
        mock_repo.name = "test-repo"
        mock_repo.get_latest_release.side_effect = Exception("Not Found")
        
        client = GitHubClient("fake_token")
        ref = client.get_latest_release_ref(mock_repo)
        
        assert ref is None

    def test_get_repo_files_from_release(self, mocker):
        """Test getting files from repository using latest release."""
        mock_repo = Mock()
        mock_repo.name = "test-repo"
        
        # Mock latest release
        mock_release = Mock()
        mock_release.tag_name = "v1.0.0"
        mock_repo.get_latest_release.return_value = mock_release
        
        # Mock git tree elements
        mock_element1 = Mock()
        mock_element1.path = "docs/README.md"
        mock_element1.type = "blob"
        mock_element1.sha = "sha1"
        mock_element1.size = 11
        
        mock_element2 = Mock()
        mock_element2.path = "docs/api/spec.json"
        mock_element2.type = "blob"
        mock_element2.sha = "sha2"
        mock_element2.size = 17
        
        # Mock git tree
        mock_tree = Mock()
        mock_tree.tree = [mock_element1, mock_element2]
        
        # Mock git refs and commits
        mock_ref = Mock()
        mock_ref.object.sha = "commit_sha"
        mock_commit = Mock()
        mock_commit.tree.sha = "tree_sha"
        
        mock_repo.get_git_ref.return_value = mock_ref
        mock_repo.get_git_commit.return_value = mock_commit
        mock_repo.get_git_tree.return_value = mock_tree
        
        # Mock git blobs
        mock_blob1 = Mock()
        mock_blob1.encoding = "base64"
        mock_blob1.content = "SGVsbG8gV29ybGQ="  # "Hello World" in base64
        
        mock_blob2 = Mock()
        mock_blob2.encoding = "base64"
        mock_blob2.content = "eyJ2ZXJzaW9uIjoiMS4wIn0="  # '{"version":"1.0"}' in base64
        
        mock_repo.get_git_blob.side_effect = [mock_blob1, mock_blob2]
        
        client = GitHubClient("fake_token")
        files = client.get_repo_files(mock_repo)
        
        assert len(files) == 2
        
        # Verify we called get_git_ref with tags reference
        mock_repo.get_git_ref.assert_called_with("tags/v1.0.0")
        
        # Check both files are present (order not guaranteed due to parallel processing)
        file_paths = {f.relative_path for f in files}
        assert "README.md" in file_paths
        assert "api/spec.json" in file_paths

    def test_get_repo_files(self, mocker):
        """Test getting files from repository docs directory using default branch (fallback)."""
        mock_repo = Mock()
        mock_repo.name = "test-repo"
        mock_repo.default_branch = "main"
        
        # Mock no releases available
        mock_repo.get_latest_release.side_effect = Exception("Not Found")
        
        # Mock git tree elements
        mock_element1 = Mock()
        mock_element1.path = "docs/README.md"
        mock_element1.type = "blob"
        mock_element1.sha = "sha1"
        mock_element1.size = 11
        
        mock_element2 = Mock()
        mock_element2.path = "docs/api/spec.json"
        mock_element2.type = "blob"
        mock_element2.sha = "sha2"
        mock_element2.size = 17
        
        # Mock git tree
        mock_tree = Mock()
        mock_tree.tree = [mock_element1, mock_element2]
        
        # Mock git refs and commits
        mock_ref = Mock()
        mock_ref.object.sha = "commit_sha"
        mock_commit = Mock()
        mock_commit.tree.sha = "tree_sha"
        
        mock_repo.get_git_ref.return_value = mock_ref
        mock_repo.get_git_commit.return_value = mock_commit
        mock_repo.get_git_tree.return_value = mock_tree
        
        # Mock git blobs
        mock_blob1 = Mock()
        mock_blob1.encoding = "base64"
        mock_blob1.content = "SGVsbG8gV29ybGQ="  # "Hello World" in base64
        
        mock_blob2 = Mock()
        mock_blob2.encoding = "base64"
        mock_blob2.content = "eyJ2ZXJzaW9uIjoiMS4wIn0="  # '{"version":"1.0"}' in base64
        
        mock_repo.get_git_blob.side_effect = [mock_blob1, mock_blob2]
        
        client = GitHubClient("fake_token")
        files = client.get_repo_files(mock_repo)
        
        assert len(files) == 2
        
        # Verify we called get_git_ref with heads reference (fallback)
        mock_repo.get_git_ref.assert_called_with("heads/main")
        
        # Check both files are present (order not guaranteed due to parallel processing)
        file_paths = {f.relative_path for f in files}
        assert "README.md" in file_paths
        assert "api/spec.json" in file_paths

    def test_get_repo_files_handles_exception(self, mocker):
        """Test that exceptions in get_repo_files are handled gracefully."""
        mocker.patch('time.sleep')  # Mock sleep to speed up retries
        mock_repo = Mock()
        mock_repo.name = "test-repo"
        mock_repo.default_branch = "main"
        mock_repo.get_latest_release.side_effect = Exception("Not Found")
        mock_repo.get_git_ref.side_effect = Exception("No docs directory")
        
        client = GitHubClient("fake_token")
        files = client.get_repo_files(mock_repo)
        
        assert files == []

    def test_fetch_files_parallel_with_blob_exception(self, mocker):
        """Test that blob fetch exceptions are handled gracefully in parallel processing."""
        mocker.patch('time.sleep')  # Mock sleep to speed up retries
        mock_repo = Mock()
        mock_repo.name = "test-repo"
        
        # Mock tree elements
        mock_element1 = Mock()
        mock_element1.path = "docs/README.md"
        mock_element1.type = "blob"
        mock_element1.sha = "sha1"
        mock_element1.size = 11
        
        mock_element2 = Mock()
        mock_element2.path = "docs/broken.md"
        mock_element2.type = "blob"
        mock_element2.sha = "sha2"
        mock_element2.size = 10
        
        # Mock git blobs - one succeeds, one fails
        mock_blob = Mock()
        mock_blob.encoding = "base64"
        mock_blob.content = "VGVzdA=="  # "Test" in base64
        
        mock_repo.get_git_blob.side_effect = [mock_blob, Exception("Blob not found")]
        
        client = GitHubClient("fake_token")
        files = client._fetch_files_parallel(mock_repo, [mock_element1, mock_element2])
        
        # Only successful file should be included
        assert len(files) == 1
        assert files[0].relative_path == "README.md"
        assert files[0].content == b"Test"

    def test_fetch_files_parallel_with_non_base64_encoding(self, mocker):
        """Test handling blobs with non-base64 encoding in parallel fetch."""
        mock_repo = Mock()
        mock_repo.name = "test-repo"
        
        mock_element = Mock()
        mock_element.path = "docs/README.md"
        mock_element.type = "blob"
        mock_element.sha = "sha1"
        mock_element.size = 14
        
        # Mock git blob with utf-8 encoding
        mock_blob = Mock()
        mock_blob.encoding = "utf-8"
        mock_blob.content = "README content"
        
        mock_repo.get_git_blob.return_value = mock_blob
        
        client = GitHubClient("fake_token")
        files = client._fetch_files_parallel(mock_repo, [mock_element])
        
        assert len(files) == 1
        assert files[0].relative_path == "README.md"
        assert files[0].content == b"README content"

    def test_retry_with_backoff_success_on_first_attempt(self, mocker):
        """Test retry logic succeeds on first attempt."""
        client = GitHubClient("fake_token")
        mock_func = Mock(return_value="success")
        
        result = client._retry_with_backoff(mock_func)
        
        assert result == "success"
        assert mock_func.call_count == 1

    def test_retry_with_backoff_success_after_transient_error(self, mocker):
        """Test retry logic succeeds after transient error."""
        mock_sleep = mocker.patch('time.sleep')
        client = GitHubClient("fake_token", max_retries=3)
        
        # Mock function that fails once then succeeds
        mock_func = Mock(side_effect=[Exception("Transient error"), "success"])
        
        result = client._retry_with_backoff(mock_func)
        
        assert result == "success"
        assert mock_func.call_count == 2
        assert mock_sleep.call_count == 1

    def test_retry_with_backoff_rate_limit_exceeded(self, mocker):
        """Test retry logic handles rate limit exceeded."""
        mock_sleep = mocker.patch('time.sleep')
        mock_time = mocker.patch('time.time', return_value=1000.0)
        
        client = GitHubClient("fake_token", max_retries=2)
        
        # Mock rate limit response with datetime-like object
        mock_reset = Mock()
        mock_reset.timestamp = Mock(return_value=1060.0)
        
        mock_rate_limit = Mock()
        mock_core = Mock()
        mock_core.reset = mock_reset
        mock_rate_limit.core = mock_core
        
        mocker.patch.object(client.client, 'get_rate_limit', return_value=mock_rate_limit)
        
        # Mock function that raises RateLimitExceededException then succeeds
        rate_limit_error = RateLimitExceededException(
            status=403,
            data={"message": "API rate limit exceeded"}
        )
        mock_func = Mock(side_effect=[rate_limit_error, "success"])
        
        result = client._retry_with_backoff(mock_func)
        
        assert result == "success"
        assert mock_func.call_count == 2
        assert mock_sleep.call_count == 1

    def test_retry_with_backoff_github_exception_500(self, mocker):
        """Test retry logic handles 500 server errors."""
        mock_sleep = mocker.patch('time.sleep')
        client = GitHubClient("fake_token", max_retries=3)
        
        # Mock function that raises 500 error then succeeds
        github_error = GithubException(status=500, data={"message": "Server error"})
        mock_func = Mock(side_effect=[github_error, "success"])
        
        result = client._retry_with_backoff(mock_func)
        
        assert result == "success"
        assert mock_func.call_count == 2
        assert mock_sleep.call_count == 1

    def test_retry_with_backoff_github_exception_403(self, mocker):
        """Test retry logic handles 403 errors (potential rate limit)."""
        mock_sleep = mocker.patch('time.sleep')
        client = GitHubClient("fake_token", max_retries=2)
        
        # Mock function that raises 403 error then succeeds
        github_error = GithubException(status=403, data={"message": "Forbidden"})
        mock_func = Mock(side_effect=[github_error, "success"])
        
        result = client._retry_with_backoff(mock_func)
        
        assert result == "success"
        assert mock_func.call_count == 2

    def test_retry_with_backoff_github_exception_404_no_retry(self, mocker):
        """Test retry logic doesn't retry on 404 client errors."""
        mock_sleep = mocker.patch('time.sleep')
        client = GitHubClient("fake_token", max_retries=3)
        
        # Mock function that raises 404 error
        github_error = GithubException(status=404, data={"message": "Not found"})
        mock_func = Mock(side_effect=github_error)
        
        with pytest.raises(GithubException) as exc_info:
            client._retry_with_backoff(mock_func)
        
        assert exc_info.value.status == 404
        assert mock_func.call_count == 1  # No retries
        assert mock_sleep.call_count == 0

    def test_retry_with_backoff_exhausted_retries(self, mocker):
        """Test retry logic fails after exhausting all retries."""
        mock_sleep = mocker.patch('time.sleep')
        # Mock _check_rate_limit to avoid API calls
        client = GitHubClient("fake_token", max_retries=3)
        mocker.patch.object(client, '_check_rate_limit')
        
        # Mock function that always fails
        error = Exception("Persistent error")
        mock_func = Mock(side_effect=error)
        
        with pytest.raises(Exception) as exc_info:
            client._retry_with_backoff(mock_func)
        
        assert str(exc_info.value) == "Persistent error"
        assert mock_func.call_count == 3
        assert mock_sleep.call_count == 3

    def test_check_rate_limit_warning_low_remaining(self, mocker):
        """Test rate limit check warns when remaining requests are low."""
        client = GitHubClient("fake_token")
        
        mock_rate_limit = Mock()
        mock_core = Mock()
        mock_core.remaining = 50
        mock_core.limit = 5000
        mock_core.reset = Mock()
        mock_rate_limit.core = mock_core
        
        mocker.patch.object(client.client, 'get_rate_limit', return_value=mock_rate_limit)
        
        # This should log a warning but not raise
        client._check_rate_limit()

    def test_check_rate_limit_waits_when_exhausted(self, mocker):
        """Test rate limit check waits when rate limit is exhausted."""
        mock_sleep = mocker.patch('time.sleep')
        mock_time = mocker.patch('time.time', return_value=1000.0)
        
        client = GitHubClient("fake_token")
        
        # Mock datetime-like reset object
        mock_reset = Mock()
        mock_reset.timestamp = Mock(return_value=1060.0)
        
        mock_rate_limit = Mock()
        mock_core = Mock()
        mock_core.remaining = 0
        mock_core.limit = 5000
        mock_core.reset = mock_reset
        mock_rate_limit.core = mock_core
        
        mocker.patch.object(client.client, 'get_rate_limit', return_value=mock_rate_limit)
        
        client._check_rate_limit()
        
        # Should sleep for ~61 seconds (60 + 1 buffer)
        assert mock_sleep.call_count == 1
        sleep_time = mock_sleep.call_args[0][0]
        assert 60 <= sleep_time <= 62

    def test_get_file_content_base64(self):
        """Test getting file content with base64 encoding."""
        client = GitHubClient("fake_token")
        
        mock_item = Mock()
        mock_item.encoding = "base64"
        mock_item.content = "SGVsbG8gV29ybGQ="  # "Hello World" in base64
        
        content = client._get_file_content(mock_item)
        
        assert content == b"Hello World"

    def test_get_file_content_utf8(self):
        """Test getting file content with UTF-8 encoding."""
        client = GitHubClient("fake_token")

        mock_item = Mock()
        mock_item.encoding = "utf-8"
        mock_item.content = "Hello World"

        content = client._get_file_content(mock_item)

        assert content == b"Hello World"

    def test_get_repo_files_with_annotated_tag(self, mocker):
        """Test getting files when release uses annotated tag."""
        mock_repo = Mock()
        mock_repo.name = "test-repo"

        # Mock latest release with annotated tag
        mock_release = Mock()
        mock_release.tag_name = "v1.0.0"
        mock_repo.get_latest_release.return_value = mock_release

        # Mock git ref pointing to tag object (not commit)
        mock_ref = Mock()
        mock_ref.object.sha = "tag_sha"
        mock_ref.object.type = "tag"  # This triggers the annotated tag path

        # Mock the tag object that points to actual commit
        mock_tag = Mock()
        mock_tag.object.sha = "commit_sha"

        mock_commit = Mock()
        mock_commit.tree.sha = "tree_sha"

        mock_tree = Mock()
        mock_element = Mock()
        mock_element.path = "docs/README.md"
        mock_element.type = "blob"
        mock_element.sha = "sha1"
        mock_element.size = 10
        mock_tree.tree = [mock_element]

        mock_repo.get_git_ref.return_value = mock_ref
        mock_repo.get_git_tag.return_value = mock_tag  # Called for annotated tags
        mock_repo.get_git_commit.return_value = mock_commit
        mock_repo.get_git_tree.return_value = mock_tree

        mock_blob = Mock()
        mock_blob.encoding = "base64"
        mock_blob.content = "SGVsbG8="  # "Hello" in base64
        mock_repo.get_git_blob.return_value = mock_blob

        client = GitHubClient("fake_token")
        files = client.get_repo_files(mock_repo)

        assert len(files) == 1
        assert files[0].relative_path == "README.md"
        # Verify get_git_tag was called for annotated tag
        mock_repo.get_git_tag.assert_called_once_with("tag_sha")

    def test_get_repo_files_release_fallback_on_error(self, mocker):
        """Test fallback to default branch when release fetch fails."""
        from github import GithubException

        mock_repo = Mock()
        mock_repo.name = "test-repo"
        mock_repo.default_branch = "main"

        # Mock latest release exists
        mock_release = Mock()
        mock_release.tag_name = "v1.0.0"
        mock_repo.get_latest_release.return_value = mock_release

        # First call to get_git_ref (for release) fails
        # Second call (for default branch) succeeds
        mock_ref = Mock()
        mock_ref.object.sha = "commit_sha"

        call_count = [0]
        def get_git_ref_side_effect(ref):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call for release tag fails
                raise GithubException(404, {"message": "Not Found"})
            else:
                # Second call for default branch succeeds
                return mock_ref

        mock_repo.get_git_ref.side_effect = get_git_ref_side_effect

        mock_commit = Mock()
        mock_commit.tree.sha = "tree_sha"

        mock_tree = Mock()
        mock_element = Mock()
        mock_element.path = "docs/README.md"
        mock_element.type = "blob"
        mock_element.sha = "sha1"
        mock_element.size = 10
        mock_tree.tree = [mock_element]

        mock_repo.get_git_commit.return_value = mock_commit
        mock_repo.get_git_tree.return_value = mock_tree

        mock_blob = Mock()
        mock_blob.encoding = "base64"
        mock_blob.content = "SGVsbG8="
        mock_repo.get_git_blob.return_value = mock_blob

        client = GitHubClient("fake_token")
        files = client.get_repo_files(mock_repo)

        assert len(files) == 1
        # Verify it fell back to default branch
        assert mock_repo.get_git_ref.call_count == 2
        mock_repo.get_git_ref.assert_any_call("tags/v1.0.0")
        mock_repo.get_git_ref.assert_any_call("heads/main")

    def test_get_repo_files_empty_tree(self, mocker):
        """Test handling of empty tree (no files in docs directory)."""
        mock_repo = Mock()
        mock_repo.name = "test-repo"
        mock_repo.default_branch = "main"

        # Mock no releases
        mock_repo.get_latest_release.side_effect = Exception("Not Found")

        # Mock empty tree
        mock_ref = Mock()
        mock_ref.object.sha = "commit_sha"
        mock_commit = Mock()
        mock_commit.tree.sha = "tree_sha"

        mock_tree = Mock()
        mock_tree.tree = []  # No files in docs/

        mock_repo.get_git_ref.return_value = mock_ref
        mock_repo.get_git_commit.return_value = mock_commit
        mock_repo.get_git_tree.return_value = None  # This triggers line 245-246

        client = GitHubClient("fake_token")
        files = client.get_repo_files(mock_repo)

        assert len(files) == 0

    def test_get_repo_files_default_branch_failure(self, mocker):
        """Test that empty list is returned when default branch fetch fails (no release)."""
        from github import GithubException

        mocker.patch('time.sleep')  # Mock sleep to speed up retries
        mock_repo = Mock()
        mock_repo.name = "test-repo"
        mock_repo.default_branch = "main"

        # Mock no releases (so it uses default branch)
        mock_repo.get_latest_release.side_effect = Exception("Not Found")

        # Mock get_git_ref failure for default branch - this triggers line 240 (raise in else block)
        mock_repo.get_git_ref.side_effect = GithubException(404, {"message": "Branch not found"})

        client = GitHubClient("fake_token")

        # Should return empty list (exception is caught by outer try-except)
        files = client.get_repo_files(mock_repo)
        assert len(files) == 0