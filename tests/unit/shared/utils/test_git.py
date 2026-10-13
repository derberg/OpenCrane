import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

import opencrane.shared.utils.git as git_module
from opencrane.shared.utils.git import (
    get_repo_subdir,
    has_changes,
    ignored_fingerprint,
    load_fingerprint,
    save_fingerprint,
)


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
            # diff + ls-files untracked + ls-files ignored (empty: no fingerprint needed)
            assert mock_run.call_count == 3

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
            # 3 calls per path (diff + ls-files untracked + ls-files ignored)
            assert mock_run.call_count == 6

    def test_git_not_available_returns_true(self, tmp_path):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert has_changes([tmp_path]) is True

    def test_os_error_returns_true(self, tmp_path):
        with patch("subprocess.run", side_effect=OSError("permission denied")):
            assert has_changes([tmp_path]) is True

    def test_empty_paths_returns_false(self):
        assert has_changes([]) is False


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def ignored_repo(tmp_path, monkeypatch):
    """A real Git repository whose ``sources/`` directory is Git-ignored.

    Mirrors ``.opencrane/sources/``, which projects usually ignore. The test
    process runs inside the repository, like ``opencrane llms`` does.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / ".gitignore").write_text("sources/\n")
    (repo / "tracked.md").write_text("# Tracked\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    src = repo / "sources" / "proj"
    (src / "sub").mkdir(parents=True)
    (src / "page.md").write_text("# Page\n")
    (src / "sub" / "deep.md").write_text("# Deep\n")
    monkeypatch.chdir(repo)
    return repo


class TestIgnoredDirectories:
    """Git reports nothing for ignored files, so has_changes compares digests."""

    def test_ignored_files_without_record_count_as_changed(self, ignored_repo):
        src = ignored_repo / "sources" / "proj"
        assert has_changes([src], ignored_repo / "fp.json") is True

    def test_ignored_files_without_fingerprint_file_count_as_changed(self, ignored_repo):
        assert has_changes([ignored_repo / "sources" / "proj"]) is True

    def test_unchanged_since_record_returns_false(self, ignored_repo):
        src = ignored_repo / "sources" / "proj"
        fp_file = ignored_repo / "fp.json"
        save_fingerprint(fp_file, [src], ignored_fingerprint([src]))
        assert has_changes([src], fp_file) is False

    def test_changed_content_returns_true(self, ignored_repo):
        src = ignored_repo / "sources" / "proj"
        fp_file = ignored_repo / "fp.json"
        save_fingerprint(fp_file, [src], ignored_fingerprint([src]))
        (src / "sub" / "deep.md").write_text("# Deep\nEdited.\n")
        assert has_changes([src], fp_file) is True

    def test_added_file_returns_true(self, ignored_repo):
        src = ignored_repo / "sources" / "proj"
        fp_file = ignored_repo / "fp.json"
        save_fingerprint(fp_file, [src], ignored_fingerprint([src]))
        (src / "new.md").write_text("# New\n")
        assert has_changes([src], fp_file) is True

    def test_deleted_files_return_true(self, ignored_repo):
        src = ignored_repo / "sources" / "proj"
        fp_file = ignored_repo / "fp.json"
        save_fingerprint(fp_file, [src], ignored_fingerprint([src]))
        (src / "page.md").unlink()
        (src / "sub" / "deep.md").unlink()
        assert has_changes([src], fp_file) is True

    def test_tracked_dir_keeps_fast_path(self, ignored_repo):
        # Nothing under the repo root's tracked file is ignored, so no record is needed.
        assert ignored_fingerprint([ignored_repo / "tracked.md"]) == {}
        assert has_changes([ignored_repo / "tracked.md"], ignored_repo / "fp.json") is False

    def test_fingerprint_keys_are_absolute_file_paths(self, ignored_repo):
        src = ignored_repo / "sources" / "proj"
        fp = ignored_fingerprint([src])
        assert set(fp) == {
            str((src / "page.md").resolve()),
            str((src / "sub" / "deep.md").resolve()),
        }

    def test_symlink_to_file_outside_dir_does_not_count_as_changed(self, ignored_repo, tmp_path):
        # A symlink whose target sits outside the source dir is keyed by its own
        # path, so the record of the dir still covers it and an unchanged run skips.
        src = ignored_repo / "sources" / "proj"
        target = tmp_path / "outside.md"
        target.write_text("# Outside\n")
        (src / "linked.md").symlink_to(target)
        fp_file = ignored_repo / "fp.json"
        save_fingerprint(fp_file, [src], ignored_fingerprint([src]))
        assert has_changes([src], fp_file) is False
        target.write_text("# Outside\nEdited.\n")
        assert has_changes([src], fp_file) is True

    def test_given_fingerprint_is_used(self, ignored_repo):
        src = ignored_repo / "sources" / "proj"
        fp_file = ignored_repo / "fp.json"
        save_fingerprint(fp_file, [src], ignored_fingerprint([src]))
        with patch("opencrane.shared.utils.git.ignored_fingerprint") as mock_fp:
            # A caller-supplied digest set that differs from the record wins.
            assert has_changes([src], fp_file, fingerprint={}) is True
            mock_fp.assert_not_called()


class TestIgnoredFingerprint:
    def _result(self, returncode=0, stdout=""):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        return result

    def test_git_not_available_returns_none(self, tmp_path):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert ignored_fingerprint([tmp_path]) is None

    def test_git_failure_returns_none(self, tmp_path):
        with patch("subprocess.run", return_value=self._result(returncode=128)):
            assert ignored_fingerprint([tmp_path]) is None

    def test_listed_path_that_is_not_a_file_is_skipped(self, tmp_path):
        missing = tmp_path / "gone.md"
        with patch("subprocess.run", return_value=self._result(stdout=f"{missing}\0")):
            assert ignored_fingerprint([tmp_path]) == {}

    def test_has_changes_true_when_fingerprint_fails(self, tmp_path):
        results = [self._result(), self._result(stdout=""), self._result(returncode=128)]
        with patch("subprocess.run", side_effect=results):
            assert has_changes([tmp_path], tmp_path / "fp.json") is True


class TestFingerprintStore:
    def test_load_missing_file_returns_none(self, tmp_path):
        assert load_fingerprint(tmp_path / "missing.json", [tmp_path]) is None

    def test_load_corrupt_file_returns_none(self, tmp_path):
        fp_file = tmp_path / "fp.json"
        fp_file.write_text("{not json")
        assert load_fingerprint(fp_file, [tmp_path]) is None

    def test_load_non_dict_returns_none(self, tmp_path):
        fp_file = tmp_path / "fp.json"
        fp_file.write_text("[1, 2]")
        assert load_fingerprint(fp_file, [tmp_path]) is None

    def test_save_keeps_digests_of_other_paths(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        fp_file = tmp_path / "state" / "fp.json"
        a_key = str(a.resolve() / "x.md")
        b_key = str(b.resolve() / "y.md")
        save_fingerprint(fp_file, [a, b], {a_key: "1", b_key: "2"})
        # Re-recording only path a replaces a's digests and keeps b's.
        save_fingerprint(fp_file, [a], {})
        assert load_fingerprint(fp_file, [a]) == {}
        assert load_fingerprint(fp_file, [b]) == {b_key: "2"}

    def test_save_over_non_dict_file(self, tmp_path):
        fp_file = tmp_path / "fp.json"
        fp_file.write_text("[]")
        key = str(tmp_path.resolve() / "x.md")
        save_fingerprint(fp_file, [tmp_path], {key: "1"})
        assert load_fingerprint(fp_file, [tmp_path]) == {key: "1"}


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
