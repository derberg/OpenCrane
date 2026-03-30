import logging
import shutil
from pathlib import Path
from typing import List
from opencrane.shared.config import Config
from opencrane.shared.models.file import File

logger = logging.getLogger(__name__)


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
