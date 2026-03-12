"""Helper function to detect the current repository name from git config."""
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def get_current_repo_name(workspace_root: Path) -> str:
    """
    Detect current repository name from git remote origin URL.
    
    Falls back to workspace root directory name if git is not available.
    
    Args:
        workspace_root: Root directory of the workspace
        
    Returns:
        Repository name (e.g., "test-repo")
    """
    try:
        # Try to get repo name from git remote origin URL
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout.strip():
            git_url = result.stdout.strip()
            # Extract repo name from URLs like:
            # https://github.com/example-org/test-repo.git
            # git@github.com:example-org/test-repo.git
            if "/" in git_url:
                repo_name = git_url.split("/")[-1]
                if repo_name.endswith(".git"):
                    repo_name = repo_name[:-4]
                return repo_name
    except Exception as e:
        logger.debug(f"Failed to get repo name from git: {e}")
    
    # Fallback to workspace directory name
    fallback = workspace_root.name
    logger.debug(f"Using fallback repo name: {fallback}")
    return fallback
