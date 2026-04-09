"""Service for managing source repository mapping."""
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple
import yaml

logger = logging.getLogger(__name__)


class SourceMapping:
    """Manages mapping between local source directories and GitHub repositories."""

    def __init__(self, mapping_file: Path):
        """
        Initialize source mapping.
        
        Args:
            mapping_file: Path to .opencrane/config.yaml file
        """
        self.mapping_file = mapping_file
        self.data = self._load_mapping()

    def _load_mapping(self) -> Dict:
        """Load mapping from YAML file, or return empty structure if file doesn't exist."""
        if self.mapping_file.exists():
            try:
                with open(self.mapping_file, 'r') as f:
                    content = yaml.safe_load(f)
                    if not content:
                        return {"sources": {}}
                    # Normalize: `sources:` with no value parses as {"sources": None}
                    if content.get("sources") is None:
                        content["sources"] = {}
                    return content
            except Exception as e:
                logger.warning(f"Failed to load mapping file {self.mapping_file}: {e}")
                return {"sources": {}}
        return {"sources": {}}

    def save(self) -> None:
        """Save mapping to YAML file."""
        try:
            self.mapping_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.mapping_file, 'w') as f:
                yaml.dump(self.data, f, default_flow_style=False, sort_keys=False)
            logger.info(f"Saved source mapping to {self.mapping_file}")
        except Exception as e:
            logger.error(f"Failed to save mapping file {self.mapping_file}: {e}")
            raise

    def add_source(
        self,
        path_key: str,
        url: str,
        docs_path: str = "",
        manual: bool = False,
        docs_url: str = "",
        type: str = "github",
        sha: str = "",
        tag: str = "",
        release: str = "",
        branch: str = "",
    ) -> None:
        """
        Add or update a source mapping entry.

        Args:
            path_key: Local path key (e.g., "content-guidelines", "external-sources/extension-5g-core")
            url: Full source URL (e.g., "https://github.com/test/repo" or "https://example.com/llms-full.txt")
            docs_path: Path within repo where docs are stored (e.g., "docs", "")
            manual: When True, the entry is user-managed and must not be overwritten by auto-refresh
            docs_url: Optional base URL of the published documentation site. When set, this is used
                      instead of url when embedding source links in llms-full.txt files.
            type: Source type (e.g., "github", "llmstxt"). Defaults to "github" and is omitted from
                  the entry when it matches the default.
        """
        existing = self.data.get("sources", {}).get(path_key)

        # Preserve manually-added entries when an auto-refresh attempts to update them
        if existing and existing.get("manual") and not manual:
            logger.info(
                "Skipping update for manual mapping %s (auto-refresh)",
                path_key,
            )
            return

        entry = {
            "url": url,
            "docs_path": docs_path,
            "manual": manual,
        }
        if type != "github":
            entry["type"] = type
        if docs_url:
            entry["docs_url"] = docs_url
        if sha:
            entry["sha"] = sha
        if tag:
            entry["tag"] = tag
        if release:
            entry["release"] = release
        if branch:
            entry["branch"] = branch
        self.data["sources"][path_key] = entry
        logger.info(f"Added/updated source mapping for {path_key}")

    def get_source(self, path_key: str) -> Optional[Dict]:
        """
        Get source mapping for a local path.
        
        Args:
            path_key: Local path key
            
        Returns:
            Source mapping dict or None if not found
        """
        sources = self.data.get("sources", {})
        return sources.get(path_key)

    def get_all_sources(self) -> Dict:
        """Get all source mappings."""
        return self.data.get("sources", {})

    def get_ignore_patterns(self, source_key: str | None = None) -> list[str]:
        """Get ignore patterns — global patterns extended by per-source patterns.

        Args:
            source_key: Optional source path key. When provided, the source's
                own ignore_patterns are appended to the global list.

        Returns:
            Combined list of ignore pattern strings.
        """
        global_patterns = list(self.data.get("ignore_patterns") or [])
        if source_key:
            source = self.data.get("sources", {}).get(source_key, {})
            source_patterns = source.get("ignore_patterns") or []
            return global_patterns + list(source_patterns)
        return global_patterns

    def get_extensions_path(self) -> str | None:
        """Get the extensions file path from config, or None if not set."""
        return self.data.get("extensions")

    def remove_source(self, path_key: str) -> bool:
        """
        Remove a source mapping entry.

        Args:
            path_key: Local path key to remove

        Returns:
            True if entry was removed, False if it didn't exist
        """
        sources = self.data.get("sources", {})
        if path_key in sources:
            del sources[path_key]
            logger.info(f"Removed source mapping for {path_key}")
            return True
        return False

    def cleanup_stale_sources(self, active_path_keys: set[str]) -> list[str]:
        """
        Remove stale auto-generated source entries that are not in the active set.
        Manual entries (manual: true) and local entries (local: true) are never removed.

        Args:
            active_path_keys: Set of path keys that are currently active

        Returns:
            List of removed path keys
        """
        sources = self.data.get("sources", {})
        removed = []

        for path_key, source in list(sources.items()):
            # Only remove auto-generated entries that are not active
            if not source.get("manual") and not source.get("local") and path_key not in active_path_keys:
                del sources[path_key]
                removed.append(path_key)
                logger.info(f"Removed stale source mapping for {path_key}")

        return removed

    def find_source_for_file(self, file_path: Path) -> Optional[Tuple[Dict, str]]:
        """
        Find source mapping for a given file path.
        
        Args:
            file_path: File path relative to workspace root
            
        Returns:
            Tuple of (source mapping dict, matched path key) or None if not found
        """
        sources = self.data.get("sources", {})
        file_str = file_path.as_posix()

        # Find the longest matching prefix (most specific match)
        best_match: Optional[Dict] = None
        best_match_key: Optional[str] = None
        best_match_len = -1

        for local_path_str in sources.keys():
            if file_str.startswith(local_path_str):
                if len(local_path_str) > best_match_len:
                    best_match = sources[local_path_str]
                    best_match_key = local_path_str
                    best_match_len = len(local_path_str)

        if best_match is None:
            return None
        return best_match, best_match_key
