"""Page URLs link to the Git ref the fetch read, not always to ``main``.

The fetch records the ref it used (latest release tag, pinned sha/tag/
release/branch, or the default branch) next to the fetched files, and
``get_source_url`` builds ``/blob/<ref>/`` URLs from that record. A source
without a record keeps linking to ``main``.
"""
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
import yaml
from github import GithubException

from opencrane.rag.file_manager import (
    FETCH_METADATA_FILE,
    FileManager,
    read_fetched_ref,
)
from opencrane.rag.generate_llms_txt import get_source_url
from opencrane.rag.github_client import GitHubClient
from opencrane.rag.services.source_mapping import SourceMapping
from opencrane.shared.config import Config
from opencrane.shared.models.file import FetchedFiles, File


def _repo_with_one_doc(default_branch="main"):
    """A mocked PyGithub repository holding a single ``docs/README.md``."""
    repo = Mock()
    repo.name = "test-repo"
    repo.default_branch = default_branch

    ref = Mock()
    ref.object.sha = "commit_sha"
    ref.object.type = "commit"
    repo.get_git_ref.return_value = ref

    commit = Mock()
    commit.sha = "commit_sha"
    commit.tree.sha = "tree_sha"
    repo.get_git_commit.return_value = commit

    element = Mock()
    element.path = "docs/README.md"
    element.type = "blob"
    element.sha = "blob_sha"
    element.size = 5
    tree = Mock()
    tree.tree = [element]
    repo.get_git_tree.return_value = tree

    blob = Mock()
    blob.encoding = "base64"
    blob.content = "SGVsbG8="
    repo.get_git_blob.return_value = blob
    return repo


def _with_latest_release(repo, tag_name):
    release = Mock()
    release.tag_name = tag_name
    repo.get_latest_release.return_value = release
    return repo


def _without_releases(repo):
    repo.get_latest_release.side_effect = Exception("Not Found")
    return repo


@pytest.mark.unit
class TestGitHubClientReportsRef:
    """``get_repo_files`` tells which ref the files were read from."""

    def test_latest_release_tag(self):
        repo = _with_latest_release(_repo_with_one_doc(), "v1.4.0")
        files = GitHubClient("fake_token").get_repo_files(repo)
        assert len(files) == 1
        assert files.ref == "v1.4.0"

    def test_default_branch_master_when_no_release(self):
        repo = _without_releases(_repo_with_one_doc(default_branch="master"))
        files = GitHubClient("fake_token").get_repo_files(repo)
        assert files.ref == "master"
        repo.get_git_ref.assert_called_once_with("heads/master")

    def test_default_branch_when_release_cannot_be_read(self):
        repo = _with_latest_release(_repo_with_one_doc(default_branch="master"), "v1.0.0")
        good_ref = repo.get_git_ref.return_value
        repo.get_git_ref.side_effect = [GithubException(404, {"message": "Not Found"}), good_ref]
        files = GitHubClient("fake_token").get_repo_files(repo)
        assert files.ref == "master"

    def test_sha_pin(self):
        repo = _repo_with_one_doc()
        files = GitHubClient("fake_token").get_repo_files(repo, ref_config={"sha": "0123abc"})
        assert files.ref == "0123abc"

    def test_tag_pin(self):
        repo = _repo_with_one_doc()
        files = GitHubClient("fake_token").get_repo_files(repo, ref_config={"tag": "v2.0.0"})
        assert files.ref == "v2.0.0"

    def test_release_pin(self):
        repo = _repo_with_one_doc()
        release = Mock()
        release.tag_name = "v3.1.0"
        repo.get_release.return_value = release
        files = GitHubClient("fake_token").get_repo_files(repo, ref_config={"release": "v3.1.0"})
        assert files.ref == "v3.1.0"

    def test_branch_pin(self):
        repo = _repo_with_one_doc()
        files = GitHubClient("fake_token").get_repo_files(repo, ref_config={"branch": "release/2.x"})
        assert files.ref == "release/2.x"


@pytest.mark.unit
class TestFetchedRefRecord:
    """The record ``FileManager`` writes next to the fetched files."""

    def test_round_trip(self, tmp_path):
        manager = FileManager(Config(target_dir=tmp_path))
        manager.store_repo_files("org/repo", [File(repo_name="repo", relative_path="a.md", content=b"x")])
        manager.write_fetched_ref("org/repo", "v1.0.0")
        assert read_fetched_ref(tmp_path / "org/repo") == "v1.0.0"

    def test_unknown_ref_writes_nothing(self, tmp_path):
        manager = FileManager(Config(target_dir=tmp_path))
        manager.write_fetched_ref("repo", None)
        assert not (tmp_path / "repo" / FETCH_METADATA_FILE).exists()

    def test_missing_record(self, tmp_path):
        assert read_fetched_ref(tmp_path / "never-fetched") is None

    @pytest.mark.parametrize("content", ["not json", '["v1"]', '{"ref": ""}', '{"ref": 3}'])
    def test_unusable_record(self, tmp_path, content):
        (tmp_path / FETCH_METADATA_FILE).write_text(content, encoding="utf-8")
        assert read_fetched_ref(tmp_path) is None


def _run_fetch(tmp_path, sources, files):
    """Run fetch_docs.main() with a real FileManager and a mocked GitHub."""
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir(parents=True, exist_ok=True)
    (opencrane_dir / "config.yaml").write_text(yaml.dump({"sources": sources}))
    config = Config(
        org_name="myorg",
        mapping_file=opencrane_dir / "config.yaml",
        target_dir=opencrane_dir / "sources",
    )
    repo = MagicMock()
    repo.name = "proj"
    repo_fetcher = MagicMock()
    repo_fetcher.get_documentation_repos.return_value = []
    repo_fetcher.get_manual_repo.return_value = repo
    repo_fetcher.get_repo_files.return_value = files
    with patch("opencrane.rag.fetch_docs.setup_logging"), \
         patch("opencrane.rag.fetch_docs.GitHubClient"), \
         patch("opencrane.rag.fetch_docs.RepoFetcher", return_value=repo_fetcher), \
         patch("opencrane.rag.fetch_docs.get_current_repo_name", return_value="opencrane"), \
         patch("opencrane.rag.fetch_docs.Path.cwd", return_value=tmp_path):
        from opencrane.rag import fetch_docs
        fetch_docs.main(config)
    return config


def _url_for(config, path_key, rel_path):
    mapping = SourceMapping(config.mapping_file)
    with patch("opencrane.rag.generate_llms_txt._source_mapping", mapping), \
         patch("opencrane.rag.generate_llms_txt.get_config", return_value=config):
        return get_source_url(Path(rel_path), path_key)


SOURCE = {"proj": {"url": "https://github.com/org/proj", "manual": True, "docs_path": "docs"}}


@pytest.mark.unit
class TestPageUrlsUseFetchedRef:
    """From fetch to page URL: links point at the content the fetch read."""

    @pytest.mark.parametrize("ref", ["v1.4.0", "0123abc", "release/2.x", "master"])
    def test_url_uses_recorded_ref(self, tmp_path, ref):
        """Release tag, sha pin, branch pin and a ``master`` default branch."""
        files = FetchedFiles([File(repo_name="proj", relative_path="guide.md", content=b"# G")], ref=ref)
        config = _run_fetch(tmp_path, SOURCE, files)
        assert read_fetched_ref(config.target_dir / "proj") == ref
        assert _url_for(config, "proj", "proj/guide.md") == \
            f"https://github.com/org/proj/blob/{ref}/docs/guide.md"

    def test_url_uses_recorded_ref_for_repo_root(self, tmp_path):
        sources = {"proj": {**SOURCE["proj"], "docs_path": ""}}
        files = FetchedFiles([File(repo_name="proj", relative_path="guide.md", content=b"# G")], ref="v2.0.0")
        config = _run_fetch(tmp_path, sources, files)
        assert _url_for(config, "proj", "proj/guide.md") == \
            "https://github.com/org/proj/blob/v2.0.0/guide.md"

    def test_missing_record_falls_back_to_main(self, tmp_path):
        """A source fetched before this change has no record and keeps ``main``."""
        config = _run_fetch(tmp_path, SOURCE, [File(repo_name="proj", relative_path="guide.md", content=b"# G")])
        assert not (config.target_dir / "proj" / FETCH_METADATA_FILE).exists()
        assert _url_for(config, "proj", "proj/guide.md") == \
            "https://github.com/org/proj/blob/main/docs/guide.md"

    def test_local_source_ignores_record(self, tmp_path):
        """A local source is never fetched, so it keeps linking to ``main``."""
        opencrane_dir = tmp_path / ".opencrane"
        (opencrane_dir / "sources" / "local-docs").mkdir(parents=True)
        (opencrane_dir / "sources" / "local-docs" / FETCH_METADATA_FILE).write_text('{"ref": "v9"}')
        (opencrane_dir / "config.yaml").write_text(yaml.dump({"sources": {
            "local-docs": {"url": "https://github.com/org/self", "local": True},
        }}))
        config = Config(mapping_file=opencrane_dir / "config.yaml", target_dir=opencrane_dir / "sources")
        with patch("opencrane.rag.generate_llms_txt.get_repo_subdir", return_value=""):
            assert _url_for(config, "local-docs", "local-docs/guide.md") == \
                "https://github.com/org/self/blob/main/local-docs/guide.md"


@pytest.mark.unit
def test_url_escapes_special_characters_in_ref(tmp_path):
    """Git allows ``#`` and ``%`` in ref names; they must not cut the URL."""
    files = FetchedFiles([File(repo_name="proj", relative_path="guide.md", content=b"# G")], ref="v1#2%x")
    config = _run_fetch(tmp_path, SOURCE, files)
    assert _url_for(config, "proj", "proj/guide.md") == \
        "https://github.com/org/proj/blob/v1%232%25x/docs/guide.md"
