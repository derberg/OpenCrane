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


def main(chunks_file=None, embeddings_file=None):
    """Main entry point for embedding generation.

    Args:
        chunks_file: Input chunks JSON file. Falls back to ``AI_DOCS_CHUNKS_FILE``
            env var, then ``.opencrane/chunks.json``.
        embeddings_file: Output embeddings JSON file. Falls back to
            ``AI_DOCS_EMBEDDINGS_FILE`` env var, then ``.opencrane/embeddings.json``.
    """
    setup_logging()

    chunks_file = chunks_file or Path(os.environ.get("AI_DOCS_CHUNKS_FILE", ".opencrane/chunks.json"))
    embeddings_file = embeddings_file or Path(os.environ.get("AI_DOCS_EMBEDDINGS_FILE", ".opencrane/embeddings.json"))
    
    if not chunks_file.exists():
        logger.error(f"Chunks file not found: {chunks_file}")
        logger.error("Run './setup.sh --chunk-docs' first to generate chunks")
        sys.exit(1)
    
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


if __name__ == "__main__":
    main()
