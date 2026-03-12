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