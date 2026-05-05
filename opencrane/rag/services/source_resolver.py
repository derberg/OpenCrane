"""Resolve a chunk's source URL back to its configured source name.

The source name is the path key in ``.opencrane/config.yaml`` (e.g.
``MicrosoftDocs/microsoft-style-guide``). It lets callers filter search
results by source.
"""

from __future__ import annotations

from typing import Dict, Optional


class SourceResolver:
    """Map chunk source_url values to source mapping path keys.

    The resolver is built from a ``SourceMapping``: each entry's ``url`` and
    optional ``docs_url`` become URL prefixes that resolve to the entry's path
    key. The longest matching prefix wins so nested entries resolve correctly.
    """

    def __init__(self, sources: Dict[str, Dict]):
        prefixes: list[tuple[str, str]] = []
        for path_key, source in sources.items():
            for field in ("docs_url", "url"):
                value = source.get(field)
                if value:
                    prefixes.append((value.rstrip("/"), path_key))
        prefixes.sort(key=lambda item: len(item[0]), reverse=True)
        self._prefixes = prefixes

    def resolve(self, source_url: Optional[str]) -> Optional[str]:
        """Return the source path key whose url/docs_url prefix matches."""
        if not source_url:
            return None
        for prefix, name in self._prefixes:
            if source_url == prefix or source_url.startswith(prefix + "/"):
                return name
        return None

    def known_names(self) -> list[str]:
        """Return all source names known to this resolver, sorted."""
        return sorted({name for _, name in self._prefixes})
