import json
import logging
import shutil
from pathlib import Path
from typing import List
from opencrane.shared.config import Config
from opencrane.shared.models.file import File

logger = logging.getLogger(__name__)

# Written by the fetch next to the files of each GitHub source. Records the
# Git ref the files were read from, so page URLs link to the same content.
FETCH_METADATA_FILE = ".opencrane-fetch.json"


def read_fetched_ref(source_dir: Path) -> str | None:
    """Return the Git ref recorded for a fetched source, or ``None``.

    ``None`` means the directory holds no readable record, for example when
    an older OpenCrane version fetched it.
    """
    try:
        data = json.loads((Path(source_dir) / FETCH_METADATA_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ref = data.get("ref") if isinstance(data, dict) else None
    return ref if isinstance(ref, str) and ref else None


class FileManager:
    """Handles local file operations for storing documentation files."""

    def __init__(self, config: Config):
        self.config = config
        self.base_dir = Path(config.target_dir)

    def store_repo_files(self, path_key: str, files: List[File]) -> None:
        """Store files for a repository, removing any existing directory first."""
        repo_dir = self.base_dir / path_key

        # Remove existing directory if it exists
        if repo_dir.exists():
            logger.info(f"Removing existing directory: {repo_dir}")
            shutil.rmtree(repo_dir)

        # Create fresh directory
        repo_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created directory: {repo_dir}")

        # Store each file
        for file_obj in files:
            self._store_file(repo_dir, file_obj)

        logger.info(f"Fetched sources location: {repo_dir.resolve()}")

    def _store_file(self, repo_dir: Path, file_obj: File) -> None:
        """Store a single file in the repository directory."""
        file_path = repo_dir / file_obj.relative_path

        # Create parent directories if needed
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file content
        try:
            with open(file_path, 'wb') as f:
                f.write(file_obj.content)
            logger.debug(f"Stored file: {file_path}")
        except Exception as e:
            logger.error(f"Failed to store file {file_path}: {e}")
            raise

    def write_fetched_ref(self, path_key: str, ref: str | None) -> None:
        """Record the Git ref the files of ``path_key`` were read from.

        Call it after :meth:`store_repo_files`, which deletes the directory.
        Does nothing when ``ref`` is unknown.
        """
        if not isinstance(ref, str) or not ref:
            return
        metadata_file = self.base_dir / path_key / FETCH_METADATA_FILE
        metadata_file.parent.mkdir(parents=True, exist_ok=True)
        metadata_file.write_text(json.dumps({"ref": ref}) + "\n", encoding="utf-8")
