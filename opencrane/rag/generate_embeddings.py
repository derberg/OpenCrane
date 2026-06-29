#!/usr/bin/env python3
"""Generate vector embeddings from RAG chunks."""

import os
import sys
import json
import logging
from pathlib import Path
from opencrane.mcp.services.embeddings import EmbeddingService
from opencrane.shared.logging_config import setup_logging

logger = logging.getLogger(__name__)


def _chunks_sha256(chunks_file: Path) -> str:
    """Compute SHA-256 of the chunks file content."""
    import hashlib
    return hashlib.sha256(chunks_file.read_bytes()).hexdigest()


def _embeddings_up_to_date(chunks_file: Path, embeddings_file: Path) -> bool:
    """Check if embeddings were already generated from the current chunks file."""
    if not embeddings_file.exists():
        return False
    try:
        with open(embeddings_file, 'r') as f:
            data = json.load(f)
        return data.get("chunks_sha256") == _chunks_sha256(chunks_file)
    except Exception:
        return False


def main(chunks_file=None, embeddings_file=None, force=False):
    """Main entry point for embedding generation.

    Args:
        chunks_file: Input chunks JSON file. Falls back to ``AI_DOCS_CHUNKS_FILE``
            env var, then ``.opencrane/chunks.json``.
        embeddings_file: Output embeddings JSON file. Falls back to
            ``AI_DOCS_EMBEDDINGS_FILE`` env var, then ``.opencrane/embeddings.json``.
        force: When True, regenerate even if embeddings are up to date.
    """
    setup_logging()

    chunks_file = chunks_file or Path(os.environ.get("AI_DOCS_CHUNKS_FILE", ".opencrane/chunks.json"))
    embeddings_file = embeddings_file or Path(os.environ.get("AI_DOCS_EMBEDDINGS_FILE", ".opencrane/embeddings.json"))

    if not chunks_file.exists():
        logger.error(f"Chunks file not found: {chunks_file}")
        logger.error("Run 'opencrane chunk' first to generate chunks")
        sys.exit(1)

    if not force and _embeddings_up_to_date(chunks_file, embeddings_file):
        logger.info("⊘ Skipping embedding generation: chunks unchanged since last run")
        logger.info("  To force regeneration, use: --force")
        return

    logger.info(f"Loading chunks from {chunks_file}...")
    with open(chunks_file, 'r') as f:
        chunks = json.load(f)

    logger.info(f"Generating embeddings for {len(chunks)} chunks...")
    service = EmbeddingService()
    embeddings = service.generate_embeddings(chunks)

    logger.info(f"Saving embeddings to {embeddings_file}...")
    service.save_embeddings(embeddings, str(embeddings_file))

    logger.info("✓ Embedding generation completed successfully")
    logger.info(f"Generated {len(embeddings.embeddings)} embeddings")
    logger.info(f"Output: {embeddings_file}")


if __name__ == "__main__":  # pragma: no cover
    main()
