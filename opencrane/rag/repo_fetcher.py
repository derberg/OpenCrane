import logging
from typing import List
from github import Repository
from opencrane.shared.config import Config
from opencrane.rag.github_client import GitHubClient
from opencrane.shared.models.repository import Repository as RepoModel
from opencrane.shared.models.file import File

logger = logging.getLogger(__name__)


class RepoFetcher:
    """Handles fetching repositories and their documentation files."""

    def __init__(self, config: Config):
        self.config = config
        self.github_client = GitHubClient()

    def get_documentation_repos(self) -> List[RepoModel]:
        """Get all repositories with documentation topic."""
        try:
            repos = self.github_client.get_org_repos(self.config.org_name)
            filtered_repos = self.github_client.filter_repos_by_topic(repos, self.config.docs_topic)

            repo_models = []
            for repo in filtered_repos:
                repo_model = RepoModel(
                    name=repo.name,
                    topics=repo.get_topics(),
                    has_docs_directory=self._has_docs_directory(repo)
                )
                repo_models.append(repo_model)

            logger.info(f"Found {len(repo_models)} documentation repositories")
            return repo_models
        except Exception as e:
            logger.error(f"Failed to get documentation repos: {e}")
            raise

    def get_manual_repo(self, org_name: str, repo_name: str) -> RepoModel:
        """
        Get a specific repository by organization and name (for manual entries).

        Args:
            org_name: Organization name (e.g., "example-org")
            repo_name: Repository name (e.g., "my-repo")

        Returns:
            RepoModel for the specified repository

        Raises:
            Exception: If repository cannot be fetched
        """
        try:
            repo = self.github_client.get_repo(org_name, repo_name)
            repo_model = RepoModel(
                name=repo.name,
                topics=repo.get_topics(),
                has_docs_directory=self._has_docs_directory(repo)
            )
            logger.info(f"Fetched manual repo: {org_name}/{repo_name}")
            return repo_model
        except Exception as e:
            logger.error(f"Failed to get manual repo {org_name}/{repo_name}: {e}")
            raise

    def get_repo_files(self, repo_model: RepoModel, org_name: str = None) -> List[File]:
        """
        Get all files from a repository's docs directory.

        Args:
            repo_model: Repository model
            org_name: Organization name (defaults to config.org_name if not provided)

        Returns:
            List of files from the repository
        """
        try:
            # Use provided org_name or fall back to config
            org_name = org_name or self.config.org_name

            # Get the actual GitHub repo object
            org = self.github_client.client.get_organization(org_name)
            repo = org.get_repo(repo_model.name)

            files = self.github_client.get_repo_files(repo)
            logger.info(f"Retrieved {len(files)} files from {org_name}/{repo_model.name}")
            return files
        except Exception as e:
            logger.error(f"Failed to get files for {org_name}/{repo_model.name}: {e}")
            return []

    def _has_docs_directory(self, repo: Repository) -> bool:
        """Check if repository has a docs directory."""
        try:
            repo.get_contents("docs")
            return True
        except:
            return False