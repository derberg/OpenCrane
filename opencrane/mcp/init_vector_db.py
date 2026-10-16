#!/usr/bin/env python3
"""Initialize Milvus vector database with chunks and embeddings."""

import sys
import json
import logging
import os
from pathlib import Path
from opencrane.mcp.services.milvus_client import MilvusService
from opencrane.mcp.services.embeddings import EmbeddingService
from opencrane.shared.config import get_config
from opencrane.shared.models.vector_chunk import DEFAULT_EMBEDDING_DIM, VectorChunk
from opencrane.shared.logging_config import setup_logging

# Scalar columns added so the MCP server can serve chunk lookups from Milvus
# instead of an in-memory copy of the corpus. Collections created before these
# existed must be rebuilt.
_REQUIRED_FIELDS = {"list_id", "table_id", "clause_id", "parent_chunk_id"}

logger = logging.getLogger(__name__)

# Recorded settings that change how queries must be embedded. A collection that
# recorded different values is rebuilt so the server reads the current ones.
_EMBEDDING_SETTING_KEYS = ("model", "document_prompt", "query_prompt")


def _embedding_metadata(embeddings, dim: int) -> dict:
    """Settings recorded in the collection so the server embeds queries the same way.

    An embeddings file that predates ``query_prompt`` was written by a version
    that served queries with ``EMBEDDING_QUERY_PROMPT``, or with no prompt when
    it was unset. That rule is recorded, so the server does not add the model's
    default query prompt to queries for documents encoded without one.
    """
    if "query_prompt" in embeddings.model_fields_set:
        query_prompt = embeddings.query_prompt
    else:
        query_prompt = get_config().embedding_query_prompt or ""
    return {
        "model": embeddings.model,
        "document_prompt": embeddings.document_prompt,
        "query_prompt": query_prompt,
        "dim": dim,
    }


def _changed_settings(recorded: dict, metadata: dict) -> list:
    """Names of the embedding settings that differ between the collection and the embeddings."""
    return [key for key in _EMBEDDING_SETTING_KEYS if recorded.get(key) != metadata.get(key)]


def main(chunks_file=None, embeddings_file=None):
    """Main entry point for vector database initialization.

    Args:
        chunks_file: Input chunks JSON file. Falls back to ``AI_DOCS_CHUNKS_FILE``,
            then ``.opencrane/chunks.json``.
        embeddings_file: Input embeddings JSON file. Falls back to
            ``AI_DOCS_EMBEDDINGS_FILE``, then ``.opencrane/embeddings.json``.
    """
    setup_logging()

    chunks_file = Path(chunks_file or os.environ.get("AI_DOCS_CHUNKS_FILE", ".opencrane/chunks.json"))
    embeddings_file = Path(
        embeddings_file or os.environ.get("AI_DOCS_EMBEDDINGS_FILE", ".opencrane/embeddings.json")
    )

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

    # Reading the file needs no model, so the mock backend skips loading one.
    # Loading it would download the model and fail on a host without the
    # EMBEDDING_DEVICE, such as a GPU-less Docker build.
    embeddings_service = EmbeddingService(model_name="mock")
    embeddings = embeddings_service.load_embeddings(str(embeddings_file))
    # The collection's vector size comes from the model that produced the
    # embeddings, not a fixed constant. Prefer the actual vectors over the
    # recorded header; fall back to the default only for an empty file.
    if embeddings.embeddings:
        dim = len(embeddings.embeddings[0].vector)
    else:
        dim = embeddings.dimensions or DEFAULT_EMBEDDING_DIM
    metadata = _embedding_metadata(embeddings, dim)

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
            populated = stats.get('row_count', 0) > 0
            existing_dim = milvus.vector_dim()
            recorded = milvus.embedding_metadata()
            changed = _changed_settings(recorded, metadata) if isinstance(recorded, dict) else []
            # Only real vectors identify the model. Without them the dim is a
            # guess, and a guess must not wipe a populated collection.
            if populated and embeddings.embeddings and existing_dim not in (None, dim):
                # Vector size is fixed by the schema; a different embedding model
                # is a schema change, so rebuild like any other schema upgrade.
                logger.info(
                    f"Collection has {existing_dim}-dimensional vectors but the embeddings "
                    f"are {dim}-dimensional (embedding model changed); dropping and rebuilding."
                )
                milvus.client.drop_collection(milvus.collection_name)
            elif populated and embeddings.embeddings and changed:
                # The collection records how its vectors were made, and the
                # server serves with those settings. Rebuild so it records the
                # embeddings' settings instead of stale ones.
                logger.info(
                    f"Collection was indexed with different embedding settings {changed}; "
                    "dropping and rebuilding."
                )
                milvus.client.drop_collection(milvus.collection_name)
            elif populated:
                if not isinstance(recorded, dict):
                    logger.warning(
                        "Collection does not record its embedding model and prompts, so the "
                        "server takes them from EMBEDDING_MODEL and EMBEDDING_QUERY_PROMPT. "
                        "Run 'DROP_EXISTING=true opencrane index' to record them."
                    )
                logger.info(f"Collection already initialized with {stats['row_count']} vectors")
                logger.info("Skipping initialization (collection already populated)")
                logger.info("To force reinit, set DROP_EXISTING=true")
                return
            else:
                logger.info("Collection exists but is empty, dropping and recreating...")
                milvus.client.drop_collection(milvus.collection_name)

    logger.info("Creating collection...")
    milvus.create_collection(dim=dim, embedding_metadata=metadata)

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
