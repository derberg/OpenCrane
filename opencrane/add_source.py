"""Source addition for OpenCrane.

Provides functions to add GitHub repositories or pre-existing llms.txt files
as sources, updating sources.yaml and placing files in the correct locations.
"""

import logging
import shutil
from pathlib import Path
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

from opencrane.rag.services.source_mapping import SourceMapping

OPENCRANE_DIR = Path(".opencrane")
LLMSTXT_DIR = OPENCRANE_DIR / "llmstxt"
SOURCES_FILE = OPENCRANE_DIR / "sources.yaml"


def _get_mapping() -> SourceMapping:
    """Load the source mapping from the current workspace."""
    mapping_file = Path.cwd() / SOURCES_FILE
    return SourceMapping(mapping_file)


def add_github_source(
    name: str,
    github_url: str,
    docs_path: str = "",
    docs_url: str = "",
) -> None:
    """Add a GitHub repository source to sources.yaml.

    Args:
        name: Path key for the source (e.g., "my-docs/repo").
        github_url: Full GitHub URL (e.g., "https://github.com/org/repo").
        docs_path: Subdirectory within the repo containing docs.
        docs_url: Optional published docs URL for source links.
    """
    mapping = _get_mapping()
    mapping.add_source(
        path_key=name,
        github_url=github_url,
        docs_path=docs_path,
        manual=True,
        docs_url=docs_url,
    )
    mapping.save()


def add_llmstxt_source(name: str, location: str) -> Path:
    """Add a pre-existing llms.txt file as a source.

    Downloads from URL or copies from local path into
    .opencrane/llmstxt/<name>/llms-full.txt.

    Args:
        name: Name for this source (used as directory name).
        location: URL (http/https) or local file path.

    Returns:
        Path to the saved llms-full.txt file.

    Raises:
        FileNotFoundError: If the local file doesn't exist.
        urllib.error.URLError: If the URL download fails.
    """
    dest_dir = Path.cwd() / LLMSTXT_DIR / name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / "llms-full.txt"

    if location.startswith("http://") or location.startswith("https://"):
        logger.debug("Downloading %s", location)
        req = Request(location, headers={"User-Agent": "OpenCrane/0.3.0"})
        with urlopen(req) as response:
            content = response.read()
        logger.debug("Downloaded %d bytes", len(content))
        dest_file.write_bytes(content)
    else:
        source_path = Path(location).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"File not found: {source_path}")
        shutil.copy2(source_path, dest_file)

    return dest_file
