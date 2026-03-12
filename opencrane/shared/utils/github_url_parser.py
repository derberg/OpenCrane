"""Utility for parsing GitHub repository URLs."""
import logging
from typing import Optional, Tuple
import re

logger = logging.getLogger(__name__)


def parse_github_url(github_url: str) -> Optional[Tuple[str, str]]:
    """
    Parse GitHub URL to extract organization and repository name.

    Supports both HTTPS and SSH formats:
    - https://github.com/org/repo
    - https://github.com/org/repo.git
    - git@github.com:org/repo.git

    Args:
        github_url: GitHub repository URL

    Returns:
        Tuple of (org_name, repo_name) or None if parsing fails

    Examples:
        >>> parse_github_url("https://github.com/example-org/my-repo")
        ('example-org', 'my-repo')
        >>> parse_github_url("https://github.com/example-org/my-repo.git")
        ('example-org', 'my-repo')
        >>> parse_github_url("git@github.com:example-org/my-repo.git")
        ('example-org', 'my-repo')
    """
    if not github_url:
        return None

    try:
        # Pattern for HTTPS URLs: https://github.com/org/repo(.git)?
        https_pattern = r'https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$'
        match = re.match(https_pattern, github_url)
        if match:
            org_name = match.group(1)
            repo_name = match.group(2)
            return (org_name, repo_name)

        # Pattern for SSH URLs: git@github.com:org/repo(.git)?
        ssh_pattern = r'git@github\.com:([^/]+)/([^/]+?)(?:\.git)?/?$'
        match = re.match(ssh_pattern, github_url)
        if match:
            org_name = match.group(1)
            repo_name = match.group(2)
            return (org_name, repo_name)

        logger.warning(f"Could not parse GitHub URL: {github_url}")
        return None
    except Exception as e:
        logger.error(f"Error parsing GitHub URL {github_url}: {e}")
        return None


__all__ = ["parse_github_url"]
