"""Tests for repository name detector utility."""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch
from opencrane.shared.utils.repo_name_detector import get_current_repo_name


class TestGetCurrentRepoName:
    """Tests for get_current_repo_name function."""

    def test_detect_from_git_https_url(self):
        """Test detecting repo name from HTTPS git URL."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "https://github.com/my-org/test-repo.git\n"
                
                result = get_current_repo_name(workspace_root)
                assert result == "test-repo"

    def test_detect_from_git_ssh_url(self):
        """Test detecting repo name from SSH git URL."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "git@github.com:my-org/extension-5g-core.git\n"
                
                result = get_current_repo_name(workspace_root)
                assert result == "extension-5g-core"

    def test_detect_from_git_without_git_suffix(self):
        """Test detecting repo name from URL without .git suffix."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "https://github.com/my-org/product-docs\n"
                
                result = get_current_repo_name(workspace_root)
                assert result == "product-docs"

    def test_fallback_to_directory_name(self):
        """Test falling back to directory name when git is unavailable."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "my-project"
            workspace_root.mkdir()
            
            with patch("subprocess.run") as mock_run:
                mock_run.returncode = 1
                mock_run.side_effect = Exception("Git not found")
                
                result = get_current_repo_name(workspace_root)
                assert result == "my-project"

    def test_fallback_when_git_returns_empty(self):
        """Test falling back when git returns empty output."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "test-repo"
            workspace_root.mkdir()
            
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = ""
                
                result = get_current_repo_name(workspace_root)
                assert result == "test-repo"

    def test_timeout_handled(self):
        """Test that timeout is handled gracefully."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "timeout-test"
            workspace_root.mkdir()
            
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = TimeoutError("Git command timeout")
                
                result = get_current_repo_name(workspace_root)
                assert result == "timeout-test"
