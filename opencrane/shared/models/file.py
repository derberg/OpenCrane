from dataclasses import dataclass
from pathlib import Path
from typing import Union


@dataclass
class File:
    """Represents a file to be extracted."""
    repo_name: str
    relative_path: str  # Path relative to docs/ directory
    content: bytes
    size: int = 0

    @property
    def full_path(self) -> Path:
        """Get the full path including docs/ prefix."""
        return Path("docs") / self.relative_path

class FetchedFiles(list):
    """Files read from a repository, plus the Git ref they were read from.

    ``ref`` is the branch name, tag name or commit SHA that page URLs should
    link to, or ``None`` when the fetch could not tell.
    """

    def __init__(self, files=(), ref: str | None = None):
        super().__init__(files)
        self.ref = ref
