"""Prose chunking strategy."""

import logging
import re
from typing import List
from pathlib import Path
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.shared.config import get_config
from opencrane.shared.models.chunk import Chunk
from opencrane.shared.utils.token_counter import get_token_count

logger = logging.getLogger(__name__)


def _heading_level(stripped: str) -> int:
    """Return the number of leading ``#`` characters (0 for a non-heading line)."""
    return len(stripped) - len(stripped.lstrip('#'))


_FENCE_RE = re.compile(r'^\s*(`{3,}|~{3,})')


def _fence_state(line: str, fence: str | None) -> str | None:
    """Return the open fence marker after ``line`` (``None`` outside a fence).

    A fence opens on a line starting with three or more backticks or tildes and
    closes on a bare line of the same character that is at least as long.
    """
    match = _FENCE_RE.match(line)
    if not match:
        return fence
    marker = match.group(1)
    if fence is None:
        return marker
    if marker[0] == fence[0] and len(marker) >= len(fence) and line.strip() == marker:
        return None
    return fence


def _paragraphs(lines: List[str]) -> List[List[str]]:
    """Group lines into blank-line separated paragraphs.

    Blank lines inside a code fence do not end a paragraph, so a fenced block
    always stays within one paragraph.
    """
    paragraphs: List[List[str]] = []
    current: List[str] = []
    fence = None
    for line in lines:
        if fence is None and not line.strip():
            if current:
                paragraphs.append(current)
                current = []
            continue
        current.append(line)
        fence = _fence_state(line, fence)
    if current:
        paragraphs.append(current)
    return paragraphs


def _atoms(paragraph: List[str]) -> List[str]:
    """Split a paragraph into its lines, keeping each fenced block as one atom."""
    atoms: List[str] = []
    fence_lines: List[str] = []
    fence = None
    for line in paragraph:
        new_fence = _fence_state(line, fence)
        if fence is None and new_fence is None:
            atoms.append(line)
        else:
            fence_lines.append(line)
            if new_fence is None:
                atoms.append('\n'.join(fence_lines))
                fence_lines = []
        fence = new_fence
    if fence_lines:
        atoms.append('\n'.join(fence_lines))
    return atoms


class ProseChunkingStrategy(ProcessingStrategy):
    """Strategy for processing prose/text content."""

    def can_process(self, node) -> bool:
        """Check if node is prose/text content."""
        return hasattr(node, 'text') and getattr(node, 'node_type', 'text') != 'code'

    def process(self, node, source_file: Path) -> List[Chunk]:
        """Process prose node into chunks.
        
        Chunks are created at heading boundaries, preserving complete sections.
        The deepest heading level that starts a new chunk, an optional token
        cap per chunk and whether heading-only sections are kept come from
        ``PROSE_SPLIT_HEADING_DEPTH``, ``PROSE_MAX_CHUNK_TOKENS`` and
        ``PROSE_KEEP_HEADING_ONLY_SECTIONS``.
        
        Args:
            node: Docling document node to process.
            source_file: Path to source file.
        """
        chunks = []
        self._current_chunk = ""
        self._current_tokens = 0
        self._current_source_url = None
        self._node_source_url = getattr(node, 'source_url', None)
        config = get_config()
        self._split_depth = config.prose_split_heading_depth
        self._max_tokens = config.prose_max_chunk_tokens
        self._keep_heading_only = config.prose_keep_heading_only_sections
        
        # Get text content
        text = node.text if hasattr(node, 'text') else str(node)
        
        if not text or not text.strip():
            return []  # pragma: no cover
        
        lines = text.split('\n')
        
        for line in lines:
            stripped = line.strip()
            
            # Check for markdown headers
            if 0 < _heading_level(stripped) <= self._split_depth:
                # Save accumulated chunk before starting new section
                if self._current_chunk.strip():
                    self._flush(source_file, chunks)
            
            # Source separator resets URL context so content from one source
            # does not inherit the previous source's URL.
            if stripped == '======':
                self._current_source_url = None

            # Update source URL from heading markers.
            # Matches both GitHub URLs (# https://github.com/...) and
            # bracketed docs URLs (# [https://docs.example.com] Title)
            # injected by the llms step.
            if 'https://' in line and stripped.startswith('#'):
                # Bracketed marker: # [base] <page-url> Title. The combine step
                # tags headings with the source's base docs_url in brackets; the
                # specific page URL follows it. Track the page URL, not the base.
                bracket_match = re.search(r'\[https?://[^\]]+\]', line)
                if bracket_match:
                    after_bracket = line[line.index(']') + 1:]
                    page = re.search(r'https?://[^\s\]]+', after_bracket)
                    self._current_source_url = page.group(0) if page else bracket_match.group(0).strip('[]')
                else:
                    # Bare URL: # https://github.com/... Title
                    match = re.search(r'https://[^\s\]]+', line)
                    if match:
                        self._current_source_url = match.group(0)
            
            # Accumulate line
            self._current_chunk += line + '\n'
            self._current_tokens += get_token_count(line)
        
        # Save final chunk
        if self._current_chunk.strip():
            self._flush(source_file, chunks)
        
        return chunks

    def _flush(self, source_file: Path, chunks: List[Chunk]) -> None:
        """Emit the accumulated section as one or more chunks, then reset it.

        A heading-only section is dropped unless heading-only sections are
        kept; a section over the token cap is split by ``_split_oversized``.
        """
        if self._keep_heading_only or self._has_content():
            for piece in self._split_oversized(self._current_chunk):
                chunk = self._create_chunk(source_file, piece)
                if chunk:
                    chunks.append(chunk)
        self._current_chunk = ""
        self._current_tokens = 0

    def _split_oversized(self, text: str) -> List[str]:
        """Split a section larger than the token cap at paragraph/line boundaries.

        Paragraphs (blank-line separated) are packed greedily up to the cap; a
        paragraph that alone exceeds it is packed line by line. Lines and fenced
        code blocks are never cut, so a single line or code block longer than
        the cap becomes its own piece. A cap of zero or less turns this off. When
        the section starts with a heading, every piece is prefixed with it so
        each piece carries the same heading context as a normal chunk.
        """
        if self._max_tokens <= 0 or get_token_count(text.strip()) <= self._max_tokens:
            return [text]

        lines = text.strip().split('\n')
        heading = lines[0] if _heading_level(lines[0].strip()) else None
        prefix = f"{heading}\n\n" if heading else ""
        body = lines[1:] if heading else lines

        def fits(candidate: str) -> bool:
            return get_token_count(prefix + candidate) <= self._max_tokens

        # Units are (text, starts_paragraph); a paragraph over the cap
        # contributes one unit per line (or per fenced block) instead of one
        # for the whole paragraph.
        units = []
        for paragraph in _paragraphs(body):
            joined = '\n'.join(paragraph)
            if fits(joined):
                units.append((joined, True))
            else:
                units.extend((atom, i == 0) for i, atom in enumerate(_atoms(paragraph)))

        pieces: List[str] = []
        current = ""
        for unit_text, starts_paragraph in units:
            candidate = current + ('\n\n' if starts_paragraph else '\n') + unit_text if current else unit_text
            if current and not fits(candidate):
                pieces.append(current)
                candidate = unit_text
            current = candidate
        if current:
            pieces.append(current)

        return [prefix + piece for piece in pieces] or [text]

    def _create_chunk(self, source_file: Path, text: str | None = None) -> Chunk | None:
        """Create a prose chunk from accumulated content (or ``text`` when given).
        
        Strips GitHub URLs from heading content since they're already in metadata.
        """
        content = (self._current_chunk if text is None else text).strip()
        
        if not content:
            return None  # pragma: no cover
        
        # Strip source URLs from headings (they're already in source_url metadata)
        # Bracketed URL: # [https://...] Title -> # Title
        content = re.sub(r'^(#{1,6})\s+\[https?://[^\]]+\]\s+', r'\1 ', content, flags=re.MULTILINE)
        # Bare URL: # https://github.com/... Title -> # Title
        content = re.sub(r'^(#{1,6})\s+https://[^\s]+\s+', r'\1 ', content, flags=re.MULTILINE)
        content = content.strip()
        
        # Garbage filtering
        if len(content) < 15:
            logger.debug(f"Skipping garbage chunk (< 15 chars): {content[:30]}")
            return None
        
        if content == "...":
            logger.debug("Skipping '...' placeholder chunk")  # pragma: no cover
            return None  # pragma: no cover
        
        if re.match(r'^[^\w\s]+$', content):  # pragma: no cover
            logger.debug(f"Skipping punctuation-only chunk: {content[:30]}")  # pragma: no cover
            return None  # pragma: no cover
        
        # Use source URL from node or current tracking
        source_url = self._node_source_url or self._current_source_url
        
        metadata = {}
        if source_url:
            metadata["source_url"] = source_url
        
        from opencrane.rag.services.utils.chunk_id_generator import generate_unique_chunk_id

        chunk_id = generate_unique_chunk_id(
            content=content,
            source_file=str(source_file),
            chunk_type="prose",
            metadata=metadata
        )

        return Chunk(
            chunk_id=chunk_id,
            content=content,
            source_file=str(source_file),
            chunk_type="prose",
            metadata=metadata,
            token_count=get_token_count(content),
        )

    def _has_content(self) -> bool:
        """Return True when current chunk has non-header content."""
        if not hasattr(self, "_current_chunk") or not self._current_chunk:
            return False

        for line in self._current_chunk.split('\n'):
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                return True
        return False
