#!/usr/bin/env python3
"""Initialize Milvus vector database with chunks and embeddings."""

import sys
import json
import logging
import os
from pathlib import Path
from opencrane.mcp.services.milvus_client import MilvusService
from opencrane.mcp.services.embeddings import EmbeddingService
from opencrane.shared.models.vector_chunk import VectorChunk
from opencrane.shared.logging_config import setup_logging

# Scalar columns added so the MCP server can serve chunk lookups from Milvus
# instead of an in-memory copy of the corpus. Collections created before these
# existed must be rebuilt.
_REQUIRED_FIELDS = {"list_id", "table_id"}

logger = logging.getLogger(__name__)


def main():
    """Main entry point for vector database initialization."""
    setup_logging()

    chunks_file = Path(os.environ.get("AI_DOCS_CHUNKS_FILE", ".opencrane/chunks.json"))
    embeddings_file = Path(os.environ.get("AI_DOCS_EMBEDDINGS_FILE", ".opencrane/embeddings.json"))

    # Validate input files
    if not chunks_file.exists():
        logger.error(f"Chunks file not found: {chunks_file}")
        logger.error("Run 'opencrane chunk' first")
        sys.exit(1)

    if not embeddings_file.exists():
        logger.error(f"Embeddings file not found: {embeddings_file}")
        logger.error("Run 'opencrane embed' first")
        sys.exit(1)

    logger.info("Loading chunks and embeddings...")
    with open(chunks_file, 'r') as f:
        chunks_data = json.load(f)

    embeddings_service = EmbeddingService()
    embeddings = embeddings_service.load_embeddings(str(embeddings_file))

    logger.info(f"Initializing Milvus with {len(chunks_data)} chunks...")
    milvus = MilvusService()

    # Check environment variable to force drop existing collection
    drop_existing = os.getenv('DROP_EXISTING', 'false').lower() == 'true'

    # Check if collection already exists and has data
    if milvus.client.has_collection(milvus.collection_name):
        logger.info(f"Collection '{milvus.collection_name}' already exists")

        missing_fields = _REQUIRED_FIELDS - milvus.field_names()

        if drop_existing:
            logger.info("DROP_EXISTING=true: Dropping existing collection to ensure fresh data...")
            milvus.client.drop_collection(milvus.collection_name)
        elif missing_fields:
            logger.info(
                f"Collection is missing fields {sorted(missing_fields)} (schema upgrade); "
                "dropping and rebuilding so member/definition lookups work."
            )
            milvus.client.drop_collection(milvus.collection_name)
        else:
            stats = milvus.get_collection_stats()
            if stats.get('row_count', 0) > 0:
                logger.info(f"Collection already initialized with {stats['row_count']} vectors")
                logger.info("Skipping initialization (collection already populated)")
                logger.info("To force reinit, set DROP_EXISTING=true")
                return
            else:
                logger.info("Collection exists but is empty, dropping and recreating...")
                milvus.client.drop_collection(milvus.collection_name)

    logger.info("Creating collection...")
    milvus.create_collection()

    logger.info("Building vector chunks...")
    vector_chunks = []
    for i, chunk_data in enumerate(chunks_data):
        # Create a simple object from chunk dict
        chunk = type('Chunk', (), chunk_data)()
        embedding_record = embeddings.embeddings[i]
        vector_chunk = VectorChunk.from_chunk_and_embedding(chunk, embedding_record)
        vector_chunks.append(vector_chunk)

    logger.info(f"Inserting {len(vector_chunks)} vectors into Milvus...")
    milvus.insert_chunks(vector_chunks)

    logger.info("Flushing collection to ensure data persistence...")
    milvus.client.flush(milvus.collection_name)

    logger.info("Loading collection into memory...")
    milvus.load_collection()

    logger.info("✓ Vector database initialized successfully")

    # Display stats
    stats = milvus.get_collection_stats()
    logger.info(f"Collection stats: {stats}")


if __name__ == "__main__":  # pragma: no cover
    main()
