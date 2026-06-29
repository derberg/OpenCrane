import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

import opencrane.shared.utils.git as git_module
from opencrane.shared.utils.git import has_changes, get_repo_subdir


class TestHasChanges:
    def _make_result(self, returncode=0, stdout=""):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        return result

    def test_no_changes_returns_false(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = self._make_result(returncode=0, stdout="")
            assert has_changes([tmp_path]) is False
            assert mock_run.call_count == 2

    def test_tracked_changes_returns_true(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = self._make_result(returncode=1)
            assert has_changes([tmp_path]) is True

    def test_untracked_files_returns_true(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            # git diff returns 0, but git ls-files finds untracked files
            mock_run.side_effect = [
                self._make_result(returncode=0, stdout=""),
                self._make_result(returncode=0, stdout="new_file.md\n"),
            ]
            assert has_changes([tmp_path]) is True

    def test_stops_at_first_changed_path(self, tmp_path):
        path_a = tmp_path / "a"
        path_b = tmp_path / "b"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = self._make_result(returncode=1)
            assert has_changes([path_a, path_b]) is True
            # Should stop after first path with changes
            assert mock_run.call_count == 1

    def test_checks_all_paths_when_no_changes(self, tmp_path):
        path_a = tmp_path / "a"
        path_b = tmp_path / "b"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = self._make_result(returncode=0, stdout="")
            assert has_changes([path_a, path_b]) is False
            # 2 calls per path (diff + ls-files)
            assert mock_run.call_count == 4

    def test_git_not_available_returns_true(self, tmp_path):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert has_changes([tmp_path]) is True

    def test_os_error_returns_true(self, tmp_path):
        with patch("subprocess.run", side_effect=OSError("permission denied")):
            assert has_changes([tmp_path]) is True

    def test_empty_paths_returns_false(self):
        assert has_changes([]) is False


@pytest.fixture(autouse=False)
def reset_repo_subdir_cache():
    """Reset the module-level cache so each test starts fresh."""
    saved = git_module._repo_subdir
    git_module._repo_subdir = None
    try:
        yield
    finally:
        git_module._repo_subdir = saved


class TestGetRepoSubdir:
    def test_returns_subdir_from_git(self, reset_repo_subdir_cache):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "packages/ui/\n"
        with patch("subprocess.run", return_value=result) as mock_run:
            assert get_repo_subdir() == "packages/ui"
            mock_run.assert_called_once()

    def test_caches_result(self, reset_repo_subdir_cache):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "docs/\n"
        with patch("subprocess.run", return_value=result) as mock_run:
            assert get_repo_subdir() == "docs"
            # Second call must use the cache, not call git again
            assert get_repo_subdir() == "docs"
            assert mock_run.call_count == 1

    def test_repo_root_returns_empty_string(self, reset_repo_subdir_cache):
        # At the repo root, --show-prefix prints an empty line
        result = MagicMock()
        result.returncode = 0
        result.stdout = "\n"
        with patch("subprocess.run", return_value=result):
            assert get_repo_subdir() == ""

    def test_non_zero_returncode_returns_empty_string(self, reset_repo_subdir_cache):
        # Not inside a git repo: returncode != 0, falls through to "" default
        result = MagicMock()
        result.returncode = 128
        result.stdout = ""
        with patch("subprocess.run", return_value=result):
            assert get_repo_subdir() == ""

    def test_git_not_available_returns_empty_string(self, reset_repo_subdir_cache):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert get_repo_subdir() == ""

    def test_os_error_returns_empty_string(self, reset_repo_subdir_cache):
        with patch("subprocess.run", side_effect=OSError("boom")):
            assert get_repo_subdir() == ""
