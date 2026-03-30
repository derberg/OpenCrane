import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from opencrane.rag.file_manager import FileManager
from opencrane.shared.config import Config
from opencrane.shared.models.file import File


class TestFileManager:
    """Unit tests for FileManager."""

    def test_init(self):
        """Test FileManager initialization."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            config = Config(target_dir=base_dir)
            manager = FileManager(config)
            assert manager.base_dir == base_dir

    def test_store_repo_files_creates_directory(self):
        """Test storing files creates the repository directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            config = Config(target_dir=base_dir)
            manager = FileManager(config)

            files = [
                File(repo_name="test-repo", relative_path="docs/file1.md", content=b"content1"),
                File(repo_name="test-repo", relative_path="docs/subdir/file2.md", content=b"content2")
            ]

            manager.store_repo_files("test-repo", files)

            repo_dir = base_dir / "test-repo"
            assert repo_dir.exists()
            assert (repo_dir / "docs" / "file1.md").read_bytes() == b"content1"
            assert (repo_dir / "docs" / "subdir" / "file2.md").read_bytes() == b"content2"

    def test_store_repo_files_cleans_existing_directory(self):
        """Test that existing directory is removed before storing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            config = Config(target_dir=base_dir)
            manager = FileManager(config)

            repo_dir = base_dir / "test-repo"
            repo_dir.mkdir()
            (repo_dir / "old_file.txt").write_text("old content")

            files = [
                File(repo_name="test-repo", relative_path="docs/new_file.md", content=b"new content")
            ]

            manager.store_repo_files("test-repo", files)

            # Old file should be gone, new file should exist
            assert not (repo_dir / "old_file.txt").exists()
            assert (repo_dir / "docs" / "new_file.md").read_bytes() == b"new content"

    def test_store_repo_files_preserves_relative_paths(self):
        """Test that relative paths are preserved."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            config = Config(target_dir=base_dir)
            manager = FileManager(config)

            files = [
                File(repo_name="test-repo", relative_path="README.md", content=b"# README"),
                File(repo_name="test-repo", relative_path="api/v1/spec.json", content=b'{"version": "1"}')
            ]

            manager.store_repo_files("test-repo", files)

            repo_dir = base_dir / "test-repo"
            assert (repo_dir / "README.md").read_bytes() == b"# README"
            assert (repo_dir / "api" / "v1" / "spec.json").read_bytes() == b'{"version": "1"}'

    def test_store_repo_files_handles_write_error(self):
        """Test that write errors are properly handled and re-raised."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            config = Config(target_dir=base_dir)
            manager = FileManager(config)

            files = [
                File(repo_name="test-repo", relative_path="docs/file.md", content=b"content")
            ]

            # Mock open to raise an exception
            with patch('builtins.open', side_effect=OSError("Disk full")):
                with pytest.raises(OSError, match="Disk full"):
                    manager.store_repo_files("test-repo", files)

    def test_file_model_repr(self):
        """Test File model __repr__ method."""
        file_obj = File(repo_name="test-repo", relative_path="docs/README.md", content=b"content", size=7)
        repr_str = repr(file_obj)
        assert "File(" in repr_str
        assert "repo_name='test-repo'" in repr_str
        assert "relative_path='docs/README.md'" in repr_str

    def test_file_model_full_path_property(self):
        """Test File model full_path property."""
        file_obj = File(repo_name="test-repo", relative_path="README.md", content=b"content", size=7)
        assert file_obj.full_path == Path("docs/README.md")
        
        file_obj2 = File(repo_name="test-repo", relative_path="api/v1/spec.json", content=b"content", size=7)
        assert file_obj2.full_path == Path("docs/api/v1/spec.json")