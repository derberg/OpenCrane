#!/usr/bin/env python3

import logging
import os
import re
import sys
from pathlib import Path
from opencrane.rag.services.file_processor import FileProcessor
from opencrane.rag.services.chunk_serializer import ChunkSerializer
from opencrane.rag.services.source_mapping import SourceMapping
from opencrane.rag.services.source_resolver import SourceResolver
from opencrane.shared.config import get_config

logger = logging.getLogger(__name__)


# First level>=2 heading in a prose chunk's content — the chunk's own section
# (the page-title H1 is level 1 and ignored, so page-level chunks match nothing).
_SECTION_HEADING_RE = re.compile(r"^#{2,6}[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def _prose_section_heading(content) -> str | None:
    """The first level>=2 heading in prose content, or None."""
    if isinstance(content, str):
        match = _SECTION_HEADING_RE.search(content)
        if match:
            return match.group(1).strip()
    return None


def _chunk_section_heading(chunk) -> str | None:
    """Return the documentation section heading a chunk lives under, or None.

    - ``prose``: the first level>=2 heading in the chunk content.
    - ``list_item`` / ``table_row``: the last ``breadcrumb_path`` segment, but
      only when the breadcrumb has more than the page title (a real section).
    - other (structured YAML) chunk types: None — their breadcrumb is a
      data-tree path, not a documentation heading, and has no page anchor.
    """
    chunk_type = chunk.chunk_type
    if chunk_type == "prose":
        return _prose_section_heading(chunk.content)
    if chunk_type in ("list_item", "table_row"):
        breadcrumb = (chunk.metadata or {}).get("breadcrumb_path")
        if breadcrumb:
            segments = [s.strip() for s in breadcrumb.split(">") if s.strip()]
            if len(segments) >= 2:
                return segments[-1]
    return None


def _annotate_breadcrumb_paths(chunks, index) -> None:
    """Give prose chunks a ``"page title > section"`` breadcrumb_path.

    Unlike list_item/table_row (which build their own breadcrumb), prose chunks
    carry none, so consumers can't label them "Page – Section". The page title
    comes from the llms.txt index (properly capitalised, keyed by the chunk's
    source_url); the section from the chunk's own content heading. Page-level
    prose (no section heading) gets just the page title. No-op without an index
    (legacy marker path) or for chunks whose source_url isn't in the index.
    """
    if index is None:
        return
    url_to_title = {
        entry.url: entry.title
        for source in index.sources()
        for entry in index.entries_for(source)
    }
    for chunk in chunks:
        if chunk.chunk_type != "prose":
            continue
        metadata = chunk.metadata
        if not metadata:
            continue
        title = url_to_title.get(metadata.get("source_url"))
        if not title:
            continue
        section = _prose_section_heading(chunk.content)
        metadata["breadcrumb_path"] = f"{title} > {section}" if section else title


def _annotate_section_anchors(chunks, config) -> None:
    """Record a ``section_anchor`` on each markdown chunk from its section
    heading, so consumers can link to ``{source_url}#{section_anchor}`` while
    ``source_url`` stays a clean page link.

    Only chunks that have a ``source_url`` (something to anchor against) and a
    section heading are annotated; the slug comes from ``config.section_anchor_for``
    (so the style/override is honoured). Page-level and structured chunks are
    left without an anchor.
    """
    for chunk in chunks:
        metadata = chunk.metadata
        if not metadata or not metadata.get("source_url"):
            continue
        heading = _chunk_section_heading(chunk)
        if not heading:
            continue
        anchor = config.section_anchor_for(heading)
        if anchor:
            metadata["section_anchor"] = anchor


_NAV_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")


def _content_headings(content: str) -> tuple[bool, list[tuple[int, str]]]:
    """Return ``(opens_with_heading, [(level, title), ...])`` for prose content.

    Headings inside fenced code blocks are ignored. ``opens_with_heading`` is
    True when the first non-blank line is a heading (the chunk starts its own
    section rather than continuing the previous one).
    """
    headings: list[tuple[int, str]] = []
    opens = False
    seen_text = False
    in_fence = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else _NAV_HEADING_RE.match(stripped)
        if match:
            if not seen_text:
                opens = True
            headings.append((len(match.group(1)), match.group(2).strip()))
        if stripped:
            seen_text = True
    return opens, headings


def _push_heading(stack: list, level: int, title: str, owner: str) -> None:
    """Pop headings at the same or deeper level, then push ``(level, title, owner)``."""
    while stack and stack[-1][0] >= level:
        stack.pop()
    stack.append((level, title, owner))


# Chunk types that get a ``doc_order`` (and, for lists and tables, a section).
_ORDERED_CHUNK_TYPES = ("prose", "list_item", "table_row")


def _member_parent(stack: list, metadata: dict) -> str | None:
    """The chunk holding the section of a list item or table row.

    The heading stack is the one after the previous prose chunk, so it can hold
    headings the list or table is not under, and miss headings that were dropped
    right before it (a heading followed only by a list has no prose chunk). The
    item's own ``breadcrumb_path`` is the truth: walk the stack while its titles
    match the breadcrumb and keep the last heading that has a chunk.
    """
    titles = (metadata.get("breadcrumb_path") or "").split(" > ")
    owner = None
    for (_, title, chunk_id), expected in zip(stack, titles):
        if title != expected:
            break
        owner = chunk_id or owner
    return owner


def _annotate_prose_navigation(chunks, config) -> None:
    """Record heading ancestry, clause id and neighbour links on prose chunks.

    Walks chunks in document order keeping a heading stack per page (reset when
    the ``source_url`` changes or a page-title H1 starts a new page). For each prose chunk it records:

    - ``heading_path``: the heading ancestry of the chunk's section joined by
      `` > `` (the chunk's own first heading when its content opens with one,
      otherwise the section it continues). Omitted before the first heading.
    - ``clause_id``: the clause id of that section's heading, extracted by
      ``config.section_clause_for`` (omitted when the heading has none).
    - ``parent_chunk_id``: the chunk holding the nearest enclosing section's
      heading (``None`` at the top of the page). Headings of sections the
      prose chunker dropped for having no text (``chunk._preceding_headings``)
      appear in ``heading_path`` but hold no chunk, so they are skipped here.
    - ``position``: 1-based order among the page's prose chunks.
    - ``prev_chunk_id`` / ``next_chunk_id``: the adjacent prose chunks of the
      same page (``None`` at the page edges).

    ``list_item`` and ``table_row`` chunks get a ``parent_chunk_id`` too: the
    chunk holding the heading of the section the list or table sits in, or of
    the nearest enclosing section when that heading has no chunk (see
    :func:`_member_parent`). Prose, list item and table row chunks all get a
    ``doc_order``: their order in the document, counted from 1 again whenever
    ``source_url`` changes, so get_section can place lists and tables between
    the prose of a section.

    ``breadcrumb_path`` is left untouched. No-op when ``config.prose_navigation``
    is off.
    """
    if not config.prose_navigation:
        return
    stack: list = []
    page = object()
    previous = None
    position = 0
    order_url = object()
    order = 0
    for chunk in chunks:
        if chunk.chunk_type not in _ORDERED_CHUNK_TYPES or not isinstance(chunk.content, str):
            continue
        metadata = chunk.metadata
        url = metadata.get("source_url")
        if url != order_url:
            order_url, order = url, 0
        order += 1
        metadata["doc_order"] = order
        if chunk.chunk_type != "prose":
            metadata["parent_chunk_id"] = _member_parent(stack, metadata) if url == page else None
            continue
        preceding = [
            (len(m.group(1)), m.group(2).strip())
            for m in map(_NAV_HEADING_RE.match, chunk._preceding_headings) if m
        ]
        opens, headings = _content_headings(chunk.content)
        # An H1 is a page title, so it starts a new page even when the URL does
        # not change (pages missing from llms.txt have none, and a synthesized
        # index repeats the source's docs_url for every page).
        starts_page = any(level == 1 for level, _ in preceding) or (opens and headings[0][0] == 1)
        if url != page or starts_page:
            page, stack, previous, position = url, [], None, 0

        for level, title in preceding:
            _push_heading(stack, level, title, None)

        if opens:
            _push_heading(stack, *headings[0], chunk.chunk_id)
            headings = headings[1:]

        if stack:
            metadata["heading_path"] = " > ".join(title for _, title, _ in stack)
            clause = config.section_clause_for(stack[-1][1])
            if clause:
                metadata["clause_id"] = clause
        # Nearest enclosing section that has a chunk (a dropped heading has none).
        metadata["parent_chunk_id"] = next((o for _, _, o in reversed(stack[:-1]) if o), None)
        position += 1
        metadata["position"] = position
        metadata["prev_chunk_id"] = previous.chunk_id if previous else None
        metadata["next_chunk_id"] = None
        if previous is not None:
            previous.metadata["next_chunk_id"] = chunk.chunk_id
        previous = chunk

        for level, title in headings:
            _push_heading(stack, level, title, chunk.chunk_id)


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

        # Load the companion llms.txt index (if present) so page URLs are
        # assigned by joining clean content to the index instead of inline
        # markers. Absent index → legacy marker-based behavior.
        index = None
        index_file = llmstxt_dir / "llms.txt"
        if index_file.exists():
            from opencrane.rag.services.llms_index import LlmsIndex
            index = LlmsIndex.parse(index_file.read_text())
            logger.info(f"Loaded llms.txt index with {len(index.sources())} source section(s)")
            chunks = processor.process_file(input_file, index=index)
        else:
            chunks = processor.process_file(input_file)

        _annotate_breadcrumb_paths(chunks, index)

        from opencrane.config import OpenCraneConfig
        cfg = config if config is not None else OpenCraneConfig()
        _annotate_section_anchors(chunks, cfg)
        _annotate_prose_navigation(chunks, cfg)

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
