"""Prose chunking strategy."""

import logging
import re
from typing import List
from pathlib import Path
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.shared.models.chunk import Chunk
from opencrane.shared.utils.token_counter import get_token_count

logger = logging.getLogger(__name__)

_HEADING_LINE_RE = re.compile(r'^#{1,6}[ \t]+\S')


def _strip_heading_urls(text: str) -> str:
    """Strip source-URL markers from headings (they're already in source_url metadata)."""
    # Bracketed URL: # [https://...] Title -> # Title
    text = re.sub(r'^(#{1,6})\s+\[https?://[^\]]+\]\s+', r'\1 ', text, flags=re.MULTILINE)
    # Bare URL: # https://github.com/... Title -> # Title
    return re.sub(r'^(#{1,6})\s+https://[^\s]+\s+', r'\1 ', text, flags=re.MULTILINE)


class ProseChunkingStrategy(ProcessingStrategy):
    """Strategy for processing prose/text content."""

    def can_process(self, node) -> bool:
        """Check if node is prose/text content."""
        return hasattr(node, 'text') and getattr(node, 'node_type', 'text') != 'code'

    def process(self, node, source_file: Path) -> List[Chunk]:
        """Process prose node into chunks.
        
        Chunks are created at heading boundaries, preserving complete sections.
        
        Args:
            node: Docling document node to process.
            source_file: Path to source file.
        """
        chunks = []
        self._current_chunk = ""
        self._current_tokens = 0
        self._current_source_url = None
        self._node_source_url = getattr(node, 'source_url', None)
        # Headings of sections dropped for having no text of their own (e.g. a
        # "## 5 Title" directly followed by "### 5.1 ..."). They are handed to the
        # next chunk (never serialized) so its heading ancestry stays complete.
        self._skipped_headings = []
        
        # Get text content
        text = node.text if hasattr(node, 'text') else str(node)
        
        if not text or not text.strip():
            return []  # pragma: no cover
        
        lines = text.split('\n')
        
        for line in lines:
            stripped = line.strip()
            
            # Check for markdown headers
            if stripped.startswith('#') and not stripped.startswith('####'):
                # Save accumulated chunk before starting new section
                if self._current_chunk.strip():
                    chunk = self._create_chunk(source_file) if self._has_content() else None
                    if chunk:
                        chunks.append(chunk)
                    else:
                        self._skip_headings()
                    self._current_chunk = ""
                    self._current_tokens = 0
            
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
        if self._current_chunk.strip() and self._has_content():
            chunk = self._create_chunk(source_file)
            if chunk:
                chunks.append(chunk)
        
        return chunks

    def _create_chunk(self, source_file: Path) -> Chunk | None:
        """Create a prose chunk from accumulated content.
        
        Strips GitHub URLs from heading content since they're already in metadata.
        """
        content = self._current_chunk.strip()
        
        if not content:
            return None  # pragma: no cover
        
        content = _strip_heading_urls(content).strip()
        
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

        chunk = Chunk(
            chunk_id=chunk_id,
            content=content,
            source_file=str(source_file),
            chunk_type="prose",
            metadata=metadata,
            token_count=get_token_count(content),
        )
        chunk._preceding_headings = getattr(self, "_skipped_headings", [])
        self._skipped_headings = []
        return chunk

    def _skip_headings(self) -> None:
        """Remember the heading lines of accumulated text that produced no chunk."""
        for line in _strip_heading_urls(self._current_chunk).split('\n'):
            if _HEADING_LINE_RE.match(line.strip()):
                self._skipped_headings.append(line.strip())

    def _has_content(self) -> bool:
        """Return True when current chunk has non-header content."""
        if not hasattr(self, "_current_chunk") or not self._current_chunk:
            return False

        for line in self._current_chunk.split('\n'):
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                return True
        return False
