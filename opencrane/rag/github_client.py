import logging
import time
from random import uniform
from typing import List, Dict, Any, Callable, TypeVar
from concurrent.futures import ThreadPoolExecutor, as_completed
from github import Github, Auth, RateLimitExceededException, GithubException
from github.Repository import Repository
from opencrane.shared.config import get_config
from opencrane.shared.models.file import File

logger = logging.getLogger(__name__)

T = TypeVar('T')


class GitHubClient:
    """Client for interacting with GitHub API with rate limiting and retry support."""

    def __init__(self, token: str = None, max_retries: int = 3):
        config = get_config()
        token = token or config.github_token
        if not token:
            raise ValueError("GitHub token is required")
        self.client = Github(auth=Auth.Token(token))
        self.max_retries = max_retries
        logger.info("GitHub client initialized")

    def _check_rate_limit(self) -> None:
        """Check rate limit and log current status."""
        try:
            rate_limit = self.client.get_rate_limit()
            core = rate_limit.core
            logger.debug(f"Rate limit: {core.remaining}/{core.limit}, resets at {core.reset}")
            
            # Warn if running low on requests
            if core.remaining < 100:
                logger.warning(f"Low rate limit: {core.remaining} requests remaining")
                
            # If rate limit is exhausted, wait until reset
            if core.remaining == 0:
                # core.reset is a datetime object
                reset_timestamp = core.reset.timestamp() if hasattr(core.reset, 'timestamp') else core.reset
                wait_time = reset_timestamp - time.time() + 1
                logger.warning(f"Rate limit exhausted. Waiting {wait_time:.0f} seconds until reset")
                time.sleep(wait_time)
        except Exception as e:
            logger.warning(f"Failed to check rate limit: {e}")

    def _retry_with_backoff(self, func: Callable[[], T]) -> T:
        """
        Execute a function with exponential backoff retry logic.
        
        Handles rate limiting and transient errors with exponential backoff and jitter.
        Respects GitHub's rate limit headers and waits appropriately.
        
        Args:
            func: Function to execute with retry logic
            
        Returns:
            Result of the function call
            
        Raises:
            Exception: If all retries are exhausted
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                # Check rate limit before making request
                if attempt > 0:  # Skip check on first attempt for performance
                    self._check_rate_limit()
                
                return func()
                
            except RateLimitExceededException as e:
                last_exception = e
                # Get reset time from rate limit
                rate_limit = self.client.get_rate_limit()
                reset_time = rate_limit.core.reset
                # reset_time is a datetime object
                reset_timestamp = reset_time.timestamp() if hasattr(reset_time, 'timestamp') else reset_time
                wait_time = reset_timestamp - time.time() + 1
                
                logger.warning(
                    f"Rate limit exceeded on attempt {attempt + 1}/{self.max_retries}. "
                    f"Waiting {wait_time:.0f} seconds until reset"
                )
                time.sleep(wait_time)
                
            except GithubException as e:
                last_exception = e
                # Retry on server errors (5xx) and some 4xx errors
                if e.status >= 500 or e.status == 403:
                    wait_time = (2 ** attempt) + uniform(0, 1)
                    logger.warning(
                        f"GitHub API error {e.status} on attempt {attempt + 1}/{self.max_retries}. "
                        f"Waiting {wait_time:.2f} seconds before retry"
                    )
                    time.sleep(wait_time)
                else:
                    # Don't retry on client errors (except 403)
                    raise
                    
            except Exception as e:
                last_exception = e
                # Retry on transient errors
                wait_time = (2 ** attempt) + uniform(0, 1)
                logger.warning(
                    f"Transient error on attempt {attempt + 1}/{self.max_retries}: {e}. "
                    f"Waiting {wait_time:.2f} seconds before retry"
                )
                time.sleep(wait_time)
        
        # All retries exhausted
        logger.error(f"All {self.max_retries} retry attempts exhausted")
        raise last_exception

    def get_org_repos(self, org_name: str) -> List[Repository]:
        """Get all repositories for an organization that the token has access to."""
        def _fetch():
            org = self.client.get_organization(org_name)
            repos = org.get_repos()
            return list(repos)
        
        try:
            return self._retry_with_backoff(_fetch)
        except Exception as e:
            logger.error(f"Failed to get repos for org {org_name}: {e}")
            raise

    def get_repo(self, org_name: str, repo_name: str) -> Repository:
        """
        Get a specific repository by organization and name.

        Args:
            org_name: Organization name (e.g., "example-org")
            repo_name: Repository name (e.g., "my-repo")

        Returns:
            Repository object

        Raises:
            Exception: If repository cannot be fetched
        """
        def _fetch():
            org = self.client.get_organization(org_name)
            repo = org.get_repo(repo_name)
            return repo

        try:
            return self._retry_with_backoff(_fetch)
        except Exception as e:
            logger.error(f"Failed to get repo {org_name}/{repo_name}: {e}")
            raise

    def filter_repos_by_topic(self, repos: List[Repository], topic: str) -> List[Repository]:
        """Filter repositories that have the specified topic."""
        filtered = []
        for repo in repos:
            try:
                topics = self._retry_with_backoff(lambda: repo.get_topics())
                if topic in topics:
                    filtered.append(repo)
            except Exception as e:
                logger.warning(f"Failed to get topics for {repo.name}: {e}")
        return filtered

    def get_latest_release_ref(self, repo: Repository) -> str | None:
        """Get the git reference for the latest release.
        
        Args:
            repo: Repository to get the latest release from
            
        Returns:
            Git reference string (e.g., 'tags/v1.0.0') or None if no releases exist
        """
        try:
            def _get_release():
                return repo.get_latest_release()
            
            latest_release = self._retry_with_backoff(_get_release)
            logger.debug(f"Latest release for {repo.name}: {latest_release.tag_name}")
            return f"tags/{latest_release.tag_name}"
        except Exception as e:
            logger.debug(f"No releases found for {repo.name}: {e}")
            return None

    def get_repo_files(self, repo: Repository) -> List[File]:
        """Get all files from the docs directory of a repository using git tree API.
        
        Fetches from the latest release if available, otherwise falls back to default branch.
        """
        files = []
        try:
            # Use get_git_tree for faster traversal
            def _get_tree():
                # Try to get latest release first
                release_ref = self.get_latest_release_ref(repo)

                if release_ref:
                    logger.info(f"Fetching {repo.name} from latest release: {release_ref}")
                    ref = release_ref
                else:
                    # Fallback to default branch if no releases
                    default_branch = repo.default_branch
                    logger.info(f"No releases found for {repo.name}, using default branch: {default_branch}")
                    ref = f"heads/{default_branch}"

                try:
                    # Get the ref object
                    git_ref = repo.get_git_ref(ref)
                    sha = git_ref.object.sha

                    # For annotated tags, the SHA points to a tag object, not a commit
                    # We need to get the commit it points to
                    if git_ref.object.type == "tag":
                        # Get the tag object to find the commit it points to
                        tag = repo.get_git_tag(sha)
                        commit_sha = tag.object.sha
                    else:
                        # For branches and lightweight tags, sha is the commit
                        commit_sha = sha

                    # Get the tree directly from commit SHA
                    commit = repo.get_git_commit(commit_sha)
                    tree = repo.get_git_tree(commit.tree.sha, recursive=True)
                    return tree
                except GithubException as e:
                    # If fetching from release fails, fall back to default branch
                    if release_ref:
                        logger.warning(f"Failed to fetch from release {release_ref} for {repo.name}: {e}. Falling back to default branch")
                        default_branch = repo.default_branch
                        ref = f"heads/{default_branch}"
                        git_ref = repo.get_git_ref(ref)
                        commit_sha = git_ref.object.sha
                        commit = repo.get_git_commit(commit_sha)
                        tree = repo.get_git_tree(commit.tree.sha, recursive=True)
                        return tree
                    else:
                        raise
            
            tree = self._retry_with_backoff(_get_tree)

            if not tree:
                logger.warning(f"No tree found for {repo.name}")
                return []

            # Filter for files in docs/ directory
            doc_files = [
                element for element in tree.tree 
                if element.path.startswith("docs/") and element.type == "blob"
            ]
            
            logger.debug(f"Found {len(doc_files)} files in docs/ for {repo.name}")
            
            # Fetch file contents in parallel
            files = self._fetch_files_parallel(repo, doc_files)
            
        except Exception as e:
            logger.warning(f"Failed to get docs contents for {repo.name}: {e}")
        return files

    def _fetch_files_parallel(self, repo: Repository, doc_files: List, max_workers: int = 5) -> List[File]:
        """Fetch file contents in parallel."""
        files = []
        
        def fetch_file(element):
            try:
                # Get file content using blob API
                blob = self._retry_with_backoff(lambda: repo.get_git_blob(element.sha))
                
                # Decode content
                if blob.encoding == "base64":
                    import base64
                    content = base64.b64decode(blob.content)
                else:
                    content = blob.content.encode('utf-8')
                
                relative_path = element.path.replace("docs/", "", 1)
                return File(
                    repo_name=repo.name,
                    relative_path=relative_path,
                    content=content,
                    size=element.size
                )
            except Exception as e:
                logger.warning(f"Failed to get content for {element.path}: {e}")
                return None
        
        # Fetch files in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_element = {
                executor.submit(fetch_file, element): element 
                for element in doc_files
            }
            
            for future in as_completed(future_to_element):
                file_obj = future.result()
                if file_obj:
                    files.append(file_obj)
        
        return files

    def _get_file_content(self, item) -> bytes:
        """Get file content, handling different encodings."""
        if item.encoding == "base64":
            import base64
            return base64.b64decode(item.content)
        else:
            return item.content.encode('utf-8')