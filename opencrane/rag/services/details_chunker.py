"""Chunking strategy for GitHub ``<details>`` blocks.

GitHub-flavored Markdown writes a collapsible section as HTML: a
``<details>`` block with a ``<summary>`` title. This strategy turns the title
into a heading on top of the body and chunks the body the normal way, so lists,
tables and code inside the block get their own chunks under that title.
"""

import re
from pathlib import Path
from typing import List

from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.shared.models.chunk import Chunk

_OPENING_RE = re.compile(r"<details(?:\s[^>]*)?>")
_CLOSING = "</details>"
_SUMMARY_RE = re.compile(r"<summary(?:\s[^>]*)?>(.*?)</summary>", re.DOTALL)


class DetailsChunkingStrategy(ProcessingStrategy):
    """Chunk the body of a ``<details>`` block under its ``<summary>`` title."""

    block_tags = ("details",)
    metadata_keys = {
        "details_summary": "Title of the <details> block the chunk comes from, taken from its <summary>.",
    }

    def can_process(self, node) -> bool:
        return getattr(node, "block_tag", None) == "details"

    def process(self, node, source_file: Path) -> List[Chunk]:
        body = self._strip_block_tags(node.text)
        summary = _SUMMARY_RE.search(body)
        title = summary.group(1).strip() if summary else ""
        if summary:
            body = body[:summary.start()] + body[summary.end():]
        if not body.strip():
            return []
        if title:
            body = f"{'#' * self._title_level(node)} {title}\n\n{body.strip()}"
        chunks = self.chunk_text(body, node, source_file)
        if title:
            for chunk in chunks:
                # A nested <details> already named its own chunks.
                chunk.metadata.setdefault("details_summary", title)
        return chunks

    @staticmethod
    def _strip_block_tags(text: str) -> str:
        """Remove the outer opening and closing tags, keeping nested blocks."""
        text = _OPENING_RE.sub("", text, count=1)
        cut = text.rfind(_CLOSING)
        if cut != -1:
            text = text[:cut] + text[cut + len(_CLOSING):]
        return text

    @staticmethod
    def _title_level(node) -> int:
        """One level below the heading above the block, from 2 to 6."""
        ancestry = getattr(node, "heading_ancestry", None) or []
        if not ancestry:
            return 2
        return min(ancestry[-1][0] + 1, 6)
