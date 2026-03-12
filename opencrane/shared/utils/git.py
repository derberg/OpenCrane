import logging
import subprocess
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def has_changes(paths: List[Path]) -> bool:
    """Return True if git detects any tracked or untracked changes under any of the given paths.

    Falls back to True (assume changed) when git is unavailable or the directory
    is not a git repository, so callers never silently skip work.
    """
    for path in paths:
        path_str = str(path)
        try:
            # Tracked changes against HEAD
            result = subprocess.run(
                ["git", "diff", "--quiet", "HEAD", "--", path_str],
                capture_output=True,
            )
            if result.returncode != 0:
                return True
            # Untracked files
            result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard", path_str],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                return True
        except (OSError, FileNotFoundError):
            logger.warning("git not available; assuming changes exist")
            return True
    return False
