import logging
import subprocess
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


_repo_subdir: str | None = None


def get_repo_subdir() -> str:
    """Return the relative path from git repo root to CWD, or empty string.

    Useful for building GitHub blob URLs when the workspace is in a
    subdirectory of the repository.  The result is cached for the process
    lifetime.
    """
    global _repo_subdir
    if _repo_subdir is not None:
        return _repo_subdir

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-prefix"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            _repo_subdir = result.stdout.strip().rstrip("/")
            return _repo_subdir
    except (OSError, FileNotFoundError):
        logger.debug("git not available; cannot determine repo subdir")

    _repo_subdir = ""
    return ""


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
