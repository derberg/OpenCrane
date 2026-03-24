"""Source addition for OpenCrane.

Provides functions to add GitHub repositories or pre-existing llms.txt files
as sources, updating sources.yaml.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from opencrane.rag.services.source_mapping import SourceMapping

OPENCRANE_DIR = Path(".opencrane")
SOURCES_FILE = OPENCRANE_DIR / "sources.yaml"


def _get_mapping() -> SourceMapping:
    """Load the source mapping from the current workspace."""
    mapping_file = Path.cwd() / SOURCES_FILE
    return SourceMapping(mapping_file)


def add_github_source(
    name: str,
    url: str,
    docs_path: str = "",
    docs_url: str = "",
) -> None:
    """Add a GitHub repository source to sources.yaml."""
    mapping = _get_mapping()
    mapping.add_source(
        path_key=name,
        url=url,
        docs_path=docs_path,
        manual=True,
        docs_url=docs_url,
    )
    mapping.save()


def add_llmstxt_source(
    name: str,
    url: str,
    docs_url: str = "",
) -> None:
    """Register a pre-existing llms.txt file as a source in sources.yaml.

    The actual download/copy happens during `opencrane fetch`.

    Args:
        name: Name for this source (used as path key).
        url: URL (http/https) or local file path.
        docs_url: Optional published docs URL for source links.
    """
    mapping = _get_mapping()
    mapping.add_source(
        path_key=name,
        url=url,
        manual=True,
        docs_url=docs_url,
        type="llmstxt",
    )
    mapping.save()
