import logging
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import Request, urlopen
from opencrane.shared.config import get_config
from opencrane.rag.github_client import GitHubClient
from opencrane.rag.repo_fetcher import RepoFetcher
from opencrane.rag.file_manager import FileManager
from opencrane.shared.logging_config import setup_logging
from opencrane.rag.services.source_mapping import SourceMapping
from opencrane.shared.utils.repo_name_detector import get_current_repo_name
from opencrane.shared.utils.github_url_parser import parse_github_url

logger = logging.getLogger(__name__)


def main(config=None):
    """Main entry point for the documentation fetcher."""
    try:
        # Setup logging
        setup_logging()

        # Get configuration
        if config is None:
            config = get_config()
        logger.info("Starting documentation fetch process")

        # Initialize source mapping
        mapping_file = config.mapping_file
        if not mapping_file.is_absolute():
            # If relative path, resolve relative to current working directory
            mapping_file = Path.cwd() / mapping_file
        source_mapping = SourceMapping(mapping_file)

        # Initialize components
        github_client = GitHubClient()
        repo_fetcher = RepoFetcher(config)
        file_manager = FileManager(config)

        # Detect current repository to skip self-references
        workspace_root = Path.cwd()
        current_repo_name = get_current_repo_name(workspace_root)
        logger.info(f"Current repository: {current_repo_name}")

        # Optional single-repo filter (set via --repo flag / FETCH_REPO env var)
        fetch_repo_filter = config.fetch_repo or ""

        # Get auto-discovered documentation repositories from configured org
        # Only auto-discover from orgs configured in auto_discovery_orgs
        if config.org_name in config.auto_discovery_orgs:
            repos = repo_fetcher.get_documentation_repos()
            logger.info(f"Auto-discovered {len(repos)} repos from {config.org_name} org")
            # Filter to specific repo if requested
            if fetch_repo_filter:
                repos = [
                    r for r in repos
                    if r.name == fetch_repo_filter
                ]
                logger.info(f"Filtered auto-discovered repos to {fetch_repo_filter}: {len(repos)} match(es)")
        else:
            logger.info(f"Skipping auto-discovery for {config.org_name} org (not in auto_discovery_orgs: {config.auto_discovery_orgs})")
            repos = []

        # Fetch manual repositories from mapping file
        manual_repos = []
        manual_repo_metadata = {}  # Store org_name for each manual repo

        for path_key, source_config in source_mapping.get_all_sources().items():
            # Skip local sources — they are read directly from the filesystem
            if source_config.get("local"):
                logger.info(f"Skipping local source: {path_key}")
                continue
            if source_config.get("manual"):
                # Skip non-GitHub sources (e.g., llmstxt) — handled separately
                if source_config.get("type", "github") != "github":
                    continue
                # Skip if a repo filter is active and this entry doesn't match
                if fetch_repo_filter and path_key != fetch_repo_filter:
                    logger.debug(f"Skipping {path_key} (--repo filter active: {fetch_repo_filter})")
                    continue
                url = source_config.get("url")
                if not url:
                    logger.warning(f"Manual entry {path_key} has no url, skipping")
                    continue

                parsed = parse_github_url(url)
                if not parsed:
                    logger.warning(f"Could not parse GitHub URL for {path_key}: {url}")
                    continue

                org_name, repo_name = parsed

                # Manual repos are always fetched regardless of --org filter
                # (they are explicitly listed by the user in sources.yaml)

                # Skip self-reference (current repository)
                if repo_name == current_repo_name and org_name == config.org_name:
                    logger.info(f"Skipping self-reference: {org_name}/{repo_name}")
                    continue

                try:
                    logger.info(f"Fetching manual repo: {org_name}/{repo_name}")
                    manual_repo = repo_fetcher.get_manual_repo(org_name, repo_name)
                    manual_repos.append(manual_repo)
                    manual_repo_metadata[manual_repo.name] = {
                        "org_name": org_name,
                        "path_key": path_key,
                        "url": url,
                        "docs_path": source_config.get("docs_path", "docs")
                    }
                except Exception as e:
                    logger.error(f"Failed to fetch manual repo {org_name}/{repo_name}: {e}")

        logger.info(f"Fetched {len(manual_repos)} manual repositories")

        # Combine auto-discovered and manual repos
        all_repos = repos + manual_repos

        # Track ALL repos (whether they fetch successfully or not)
        # This prevents removing repos that temporarily fail to fetch
        active_repos = set()

        # Add auto-discovered repos to active set
        for repo in repos:
            path_key = repo.name
            active_repos.add(path_key)

        # Add manual repos to active set
        for repo in manual_repos:
            metadata = manual_repo_metadata.get(repo.name, {})
            path_key = metadata.get("path_key", repo.name)
            active_repos.add(path_key)

        # Also mark repos from other orgs as active (don't clean them up when filtering by --org)
        # This prevents removing repos from other orgs when filtering by a specific org.
        # When --repo filter is active, protect ALL other repos from cleanup too — we only
        # processed one repo so everything else must be preserved.
        for path_key, source_config in source_mapping.get_all_sources().items():
            if source_config.get("local"):
                active_repos.add(path_key)
                continue
            if fetch_repo_filter and path_key != fetch_repo_filter:
                logger.debug(f"Marking {path_key} as active (--repo filter active, protected from cleanup)")
                active_repos.add(path_key)
                continue
            # Protect all llmstxt entries from stale cleanup — they are always user-managed
            if source_config.get("type", "github") == "llmstxt":
                active_repos.add(path_key)
                continue
            url = source_config.get("url")
            if url:
                parsed = parse_github_url(url)
                if parsed:
                    org_name, repo_name = parsed
                    if org_name != config.org_name:
                        logger.debug(f"Marking {org_name}/{repo_name} as active (different org, protected from cleanup)")
                        active_repos.add(path_key)

        # Fetch llmstxt sources
        for path_key, source_config in source_mapping.get_all_sources().items():
            if source_config.get("local"):
                continue  # already handled above
            if source_config.get("type", "github") != "llmstxt":
                continue
            if fetch_repo_filter and path_key != fetch_repo_filter:
                logger.debug(f"Skipping llmstxt {path_key} (--repo filter active: {fetch_repo_filter})")
                continue

            url = source_config.get("url", "")
            if not url:
                logger.warning(f"llmstxt entry {path_key} has no url, skipping")
                continue

            dest_dir = workspace_root / ".opencrane" / "llmstxt" / path_key
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / "llms-full.txt"

            try:
                if url.startswith("http://") or url.startswith("https://"):
                    logger.info(f"Downloading llmstxt: {path_key} from {url}")
                    req = Request(url, headers={"User-Agent": "OpenCrane"})
                    with urlopen(req) as response:
                        content = response.read()
                    logger.debug(f"Downloaded {len(content)} bytes for {path_key}")
                    dest_file.write_bytes(content)
                else:
                    source_path = Path(url).resolve()
                    if not source_path.exists():
                        logger.error(f"Local file not found for {path_key}: {source_path}")
                        continue
                    logger.info(f"Copying llmstxt: {path_key} from {source_path}")
                    shutil.copy2(source_path, dest_file)

                active_repos.add(path_key)
                logger.info(f"Fetched llmstxt source: {path_key} -> {dest_file}")
            except Exception as e:
                logger.error(f"Failed to fetch llmstxt source {path_key}: {e}")
                active_repos.add(path_key)  # Don't clean up on transient failure

        if not all_repos:
            logger.warning("No documentation repositories found")
        else:
            # Process repositories in parallel
            def process_repo(repo):
                # Check if this is a manual repo
                is_manual = repo in manual_repos
                metadata = manual_repo_metadata.get(repo.name, {}) if is_manual else {}

                org_name = metadata.get("org_name", config.org_name)

                # Determine docs_path, path_key, and url upfront
                if is_manual:
                    url = metadata.get("url")
                    path_key = metadata.get("path_key")
                    docs_path = metadata.get("docs_path", "docs")
                else:
                    url = f"https://github.com/{config.org_name}/{repo.name}"
                    path_key = repo.name
                    docs_path = "docs"

                logger.info(f"Processing repository: {org_name}/{repo.name} (docs_path: {docs_path})")

                try:
                    # Get files for this repository using the configured docs_path
                    files = repo_fetcher.get_repo_files(repo, org_name=org_name, docs_path=docs_path)
                    if not files:
                        logger.warning(f"No files found in {docs_path}/ for {org_name}/{repo.name}")
                        return None

                    # Store files locally using the full path_key so manual entries
                    # with custom directories (e.g. "new/cgw") land in the right place
                    file_manager.store_repo_files(path_key, files)

                    source_mapping.add_source(
                        path_key=path_key,
                        url=url,
                        docs_path=docs_path,
                        manual=is_manual
                    )

                    return path_key
                except Exception as e:
                    logger.error(f"Failed to process repository {org_name}/{repo.name}: {e}")
                    return None

            # Process up to 3 repositories in parallel
            with ThreadPoolExecutor(max_workers=3) as executor:
                future_to_repo = {
                    executor.submit(process_repo, repo): repo
                    for repo in all_repos
                }

                processed_count = 0
                processed_paths = []
                for future in as_completed(future_to_repo):
                    result = future.result()
                    if result:
                        processed_count += 1
                        processed_paths.append(result)
                        logger.info(f"Successfully processed: {result}")

            logger.info(f"Documentation fetch completed. Processed {processed_count}/{len(all_repos)} repositories")
            if processed_paths:
                for p in processed_paths:
                    logger.info(f"  Fetched to: {config.target_dir / p}")

        # Cleanup stale sources - only remove repos that LOST the "documentation" topic
        # NOT repos that failed to fetch or have no files
        removed_sources = source_mapping.cleanup_stale_sources(active_repos)

        if removed_sources:
            logger.info(f"Cleaning up {len(removed_sources)} stale sources")
            workspace_root = Path.cwd()
            llmstxt_base = workspace_root / ".opencrane" / "llmstxt"

            for stale_path_key in removed_sources:
                # Remove from source directory (e.g., .opencrane/sources/repo-name)
                source_path = config.target_dir / stale_path_key
                if source_path.exists() and source_path.is_dir():
                    logger.info(f"Removing stale source directory: {source_path}")
                    shutil.rmtree(source_path)

                # Remove from llmstxt output directory
                # Convert path_key to llmstxt path (e.g., external-sources/repo-name -> llmstxt/external-sources/repo-name)
                llmstxt_path = llmstxt_base / stale_path_key
                if llmstxt_path.exists() and llmstxt_path.is_dir():
                    logger.info(f"Removing stale llmstxt directory: {llmstxt_path}")
                    shutil.rmtree(llmstxt_path)

        # Save source mapping
        source_mapping.save()

    except Exception as e:
        logger.error(f"Documentation fetch process failed: {e}")
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()