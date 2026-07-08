"""Sidecar recording collection-level facts the MCP server needs at startup.

Written once by the ``index`` step and read at server startup so the server can
tailor its tool list to the corpus (which chunk types exist) without scanning
the vector DB or loading the whole corpus into memory.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _meta_path() -> Path:
    return Path(os.environ.get("AI_DOCS_COLLECTION_META_FILE", ".opencrane/collection_meta.json"))


def write_chunk_types(chunk_types) -> None:
    """Persist the distinct chunk types present in the indexed collection."""
    path = _meta_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"chunk_types": sorted(set(chunk_types))}), encoding="utf-8")


def read_chunk_types() -> set:
    """Return the distinct chunk types from the sidecar, or empty set if absent."""
    try:
        data = json.loads(_meta_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            f"Collection-meta sidecar unavailable ({_meta_path()}): {exc}. "
            "Chunk-type-specific tools (yaml/list/table) may not be exposed; "
            "re-run `opencrane index` to regenerate it if the collection has data."
        )
        return set()
    types = data.get("chunk_types", [])
    return set(types) if isinstance(types, list) else set()
