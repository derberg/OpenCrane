import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from opencrane.shared.utils.git import has_changes


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
