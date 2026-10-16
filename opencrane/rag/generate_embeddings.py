#!/usr/bin/env python3
"""Generate vector embeddings from RAG chunks."""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Optional
from opencrane.mcp.services.embeddings import EmbeddingService
from opencrane.shared.config import get_config
from opencrane.shared.logging_config import setup_logging
from opencrane.shared.utils.embedding_prompts import resolve_document_prompt, resolve_query_prompt

logger = logging.getLogger(__name__)


def _chunks_sha256(chunks_file: Path) -> str:
    """Compute SHA-256 of the chunks file content."""
    import hashlib
    return hashlib.sha256(chunks_file.read_bytes()).hexdigest()


def _recorded_model(embeddings_file: Path) -> Optional[str]:
    """The model recorded in an existing embeddings file, or ``None``."""
    try:
        if not embeddings_file.exists():
            return None
        with open(embeddings_file, 'r') as f:
            data = json.load(f)
        model = data.get("model") if isinstance(data, dict) else None
        return model if isinstance(model, str) and model else None
    except Exception:
        return None


def _effective_model(embeddings_file: Path) -> str:
    """The model ``embed`` encodes with.

    ``EMBEDDING_MODEL`` when it is set. Unset, the model recorded in the
    existing embeddings file, so a run without the env var keeps the model the
    corpus was embedded with, as the MCP server does with the index. The default
    model applies only when there is no embeddings file yet.
    """
    env_model = os.getenv("EMBEDDING_MODEL") or None
    recorded = _recorded_model(embeddings_file)
    if env_model:
        if recorded and recorded != env_model:
            logger.info(
                f"EMBEDDING_MODEL is {env_model!r} but {embeddings_file} was embedded with "
                f"{recorded!r}; re-embedding with {env_model!r}"
            )
        return env_model
    return recorded or get_config().embedding_model


def _embeddings_up_to_date(chunks_file: Path, embeddings_file: Path, model: Optional[str] = None) -> bool:
    """Check if embeddings were already generated from the current chunks file, model and document prompt.

    *model* defaults to :func:`_effective_model`. The prompt compared is the
    effective one for that model, so a new default prompt (from the model or the
    known-model table) re-embeds too.
    """
    if not embeddings_file.exists():
        return False
    model = model or _effective_model(embeddings_file)
    try:
        with open(embeddings_file, 'r') as f:
            data = json.load(f)
        return (
            data.get("chunks_sha256") == _chunks_sha256(chunks_file)
            # A real embeddings file always records its model; one that does
            # not is taken to match.
            and data.get("model", model) == model
            and data.get("document_prompt", "") == resolve_document_prompt(model_name=model)
        )
    except Exception:
        return False


def _sync_query_prompt(embeddings_file: Path) -> None:
    """Record the current query prompt in an up-to-date embeddings file.

    The query prompt does not change the vectors, so a new one is written into
    the file header instead of re-encoding. ``opencrane index`` then stores it in
    the collection, where the MCP server reads it.
    """
    try:
        with open(embeddings_file, 'r') as f:
            data = json.load(f)
        if "query_prompt" in data:
            query_prompt = resolve_query_prompt(model_name=data.get("model"))
        else:
            # A file from 0.33 or older: its documents carry no default prompt,
            # so keep the rule those versions served with, as `index` does.
            # The model's default query prompt applies after a real re-embed.
            env_query = get_config().embedding_query_prompt
            query_prompt = env_query if env_query is not None else ""
        if data.get("query_prompt") == query_prompt:
            return
        data["query_prompt"] = query_prompt
        # Write a temp file and swap it in, so an interrupted write never
        # leaves a truncated embeddings file behind.
        tmp_file = Path(embeddings_file).with_name(Path(embeddings_file).name + ".tmp")
        try:
            with open(tmp_file, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_file, embeddings_file)
        finally:
            tmp_file.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"Could not record the query prompt in {embeddings_file}: {e}")
        return
    logger.info(f"Recorded query prompt {query_prompt!r} in {embeddings_file}; run 'opencrane index' to apply it")


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

    model = _effective_model(embeddings_file)
    if not force and _embeddings_up_to_date(chunks_file, embeddings_file, model):
        logger.info("⊘ Skipping embedding generation: chunks, model and document prompt unchanged since last run")
        logger.info("  To force regeneration, use: --force")
        _sync_query_prompt(embeddings_file)
        return

    logger.info(f"Loading chunks from {chunks_file}...")
    with open(chunks_file, 'r') as f:
        chunks = json.load(f)

    logger.info(f"Generating embeddings for {len(chunks)} chunks...")
    service = EmbeddingService(model_name=model)
    embeddings = service.generate_embeddings(chunks)

    logger.info(f"Saving embeddings to {embeddings_file}...")
    service.save_embeddings(embeddings, str(embeddings_file))

    logger.info("✓ Embedding generation completed successfully")
    logger.info(f"Generated {len(embeddings.embeddings)} embeddings")
    logger.info(f"Output: {embeddings_file}")


if __name__ == "__main__":  # pragma: no cover
    main()
