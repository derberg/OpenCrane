#!/usr/bin/env python3

import logging
import os
import sys
from pathlib import Path
from opencrane.rag.services.file_processor import FileProcessor
from opencrane.rag.services.chunk_serializer import ChunkSerializer
from opencrane.rag.services.source_mapping import SourceMapping
from opencrane.rag.services.source_resolver import SourceResolver
from opencrane.shared.config import get_config

logger = logging.getLogger(__name__)


def _annotate_source_names(chunks, mapping_file: Path) -> None:
    """Set ``source_name`` on each chunk using its metadata source_url."""
    if not mapping_file.exists():
        return
    mapping = SourceMapping(mapping_file)
    resolver = SourceResolver(mapping.get_all_sources())
    for chunk in chunks:
        url = chunk.metadata.get("source_url") if chunk.metadata else None
        chunk.source_name = resolver.resolve(url)


def main(config=None, llmstxt_dir=None, chunks_file=None):
    """Main entry point for the document chunker.

    Args:
        config: Optional ``OpenCraneConfig`` instance forwarded to
            ``FileProcessor``.
        llmstxt_dir: Directory containing llms-full.txt. Falls back to
            ``AI_DOCS_LLMSTXT_DIR`` env var, then ``.opencrane/llmstxt``.
        chunks_file: Output path for chunks JSON. Falls back to
            ``AI_DOCS_CHUNKS_FILE`` env var, then ``.opencrane/chunks.json``.
    """
    llmstxt_dir = llmstxt_dir or Path(os.getenv("AI_DOCS_LLMSTXT_DIR", ".opencrane/llmstxt"))
    input_file = llmstxt_dir / "llms-full.txt"
    output = chunks_file or Path(os.getenv("AI_DOCS_CHUNKS_FILE", ".opencrane/chunks.json"))

    if not input_file.exists():
        print(f"⊘ Skipping chunking: {input_file} not found.", file=sys.stderr)
        print("  Run 'opencrane llms' first, or add sources with 'opencrane add'.", file=sys.stderr)
        return

    logger.info(f"Starting chunking of {input_file} to {output}")

    try:
        processor = FileProcessor(config=config)
        chunks = processor.process_file(input_file)

        mapping_file = get_config().mapping_file
        if not mapping_file.is_absolute():
            mapping_file = Path.cwd() / mapping_file
        _annotate_source_names(chunks, mapping_file)

        ChunkSerializer.serialize_chunks(chunks, output)

        # Check for chunks missing source URLs
        chunks_without_source = [c for c in chunks if not c.metadata.get('source_url')]
        if chunks_without_source:
            logger.warning(
                f"WARNING: {len(chunks_without_source)} out of {len(chunks)} chunks "
                f"({len(chunks_without_source)/len(chunks)*100:.1f}%) are missing source_url. "
                f"This may indicate incorrect URL marker placement in the source file."
            )
            print(
                f"⚠️  WARNING: {len(chunks_without_source)} chunks missing source_url "
                f"({len(chunks_without_source)/len(chunks)*100:.1f}%)",
                file=sys.stderr
            )

        logger.info(f"Successfully processed {len(chunks)} chunks")
        print(f"Processed {len(chunks)} chunks to {output}")

    except Exception as e:
        logger.error(f"Failed to chunk file: {e}")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':  # pragma: no cover
    import argparse
    parser = argparse.ArgumentParser(description='Chunk documentation files')
    parser.add_argument('input_file', nargs='?', type=Path,
                        default=Path(os.getenv("AI_DOCS_LLMSTXT_DIR", ".opencrane/llmstxt")) / "llms-full.txt",
                        help='Input file to chunk (default: $AI_DOCS_LLMSTXT_DIR/llms-full.txt)')
    parser.add_argument('--output', type=Path,
                        default=Path(os.getenv("AI_DOCS_CHUNKS_FILE", ".opencrane/chunks.json")),
                        help='Output JSON file for chunks (default: $AI_DOCS_CHUNKS_FILE)')
    args = parser.parse_args()
    os.environ.setdefault("AI_DOCS_LLMSTXT_DIR", str(args.input_file.parent))
    os.environ.setdefault("AI_DOCS_CHUNKS_FILE", str(args.output))
    main()
