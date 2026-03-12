"""Tests for GitHub URL parser utility."""
import pytest
from opencrane.shared.utils.github_url_parser import parse_github_url


class TestParseGitHubUrl:
    """Test cases for parse_github_url function."""

    def test_parse_https_url(self):
        """Test parsing HTTPS GitHub URL."""
        result = parse_github_url("https://github.com/my-org/my-repo")
        assert result == ("my-org", "my-repo")

    def test_parse_https_url_with_git_suffix(self):
        """Test parsing HTTPS URL with .git suffix."""
        result = parse_github_url("https://github.com/example-org/cgw.git")
        assert result == ("example-org", "cgw")

    def test_parse_https_url_with_trailing_slash(self):
        """Test parsing HTTPS URL with trailing slash."""
        result = parse_github_url("https://github.com/org/repo/")
        assert result == ("org", "repo")

    def test_parse_https_url_with_git_and_trailing_slash(self):
        """Test parsing HTTPS URL with .git and trailing slash."""
        result = parse_github_url("https://github.com/org/repo.git/")
        assert result == ("org", "repo")

    def test_parse_ssh_url(self):
        """Test parsing SSH GitHub URL."""
        result = parse_github_url("git@github.com:example-org/tp-integration-tests.git")
        assert result == ("example-org", "tp-integration-tests")

    def test_parse_ssh_url_without_git_suffix(self):
        """Test parsing SSH URL without .git suffix."""
        result = parse_github_url("git@github.com:org/repo")
        assert result == ("org", "repo")

    def test_parse_ssh_url_with_trailing_slash(self):
        """Test parsing SSH URL with trailing slash."""
        result = parse_github_url("git@github.com:org/repo/")
        assert result == ("org", "repo")

    def test_parse_http_url(self):
        """Test parsing HTTP GitHub URL (not HTTPS)."""
        result = parse_github_url("http://github.com/org/repo")
        assert result == ("org", "repo")

    def test_parse_empty_string(self):
        """Test parsing empty string returns None."""
        result = parse_github_url("")
        assert result is None

    def test_parse_none(self):
        """Test parsing None returns None."""
        result = parse_github_url(None)
        assert result is None

    def test_parse_invalid_url(self):
        """Test parsing invalid URL returns None."""
        result = parse_github_url("not-a-github-url")
        assert result is None

    def test_parse_gitlab_url(self):
        """Test parsing GitLab URL returns None."""
        result = parse_github_url("https://gitlab.com/org/repo")
        assert result is None

    def test_parse_github_url_with_subdirectory(self):
        """Test parsing GitHub URL with subdirectory returns None."""
        result = parse_github_url("https://github.com/org/repo/tree/main")
        assert result is None

    def test_parse_github_raw_url(self):
        """Test parsing GitHub raw content URL returns None."""
        result = parse_github_url("https://raw.githubusercontent.com/org/repo/main/file.md")
        assert result is None

    def test_parse_url_with_exception(self, mocker):
        """Test that exceptions are handled gracefully."""
        # Mock re.match to raise an exception
        mock_match = mocker.patch('opencrane.shared.utils.github_url_parser.re.match')
        mock_match.side_effect = Exception("Regex error")

        result = parse_github_url("https://github.com/org/repo")
        assert result is None
