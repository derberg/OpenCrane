"""Find the content blocks that chunking strategies declare by tag name.

A strategy declares the tags of the components it owns, such as ``details``
for a GitHub ``<details>`` section. The page splitter keeps each such block in
one piece, so the strategy sees the whole component.
"""

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

from opencrane.rag.services.utils.markdown_structure import _closes_fence, _fence_run


@dataclass(frozen=True)
class BlockSpan:
    """A declared block: its first and last line (inclusive) and its tag."""

    start: int
    end: int
    tag: str


def _opening_tag(line: str, tags: List[str]) -> Optional[str]:
    """Return the declared tag that ``line`` opens, or None.

    The tag must start the line after leading whitespace, as ``<tag>`` or
    ``<tag `` with attributes, so an inline mention never opens a block.
    """
    stripped = line.lstrip()
    for tag in tags:
        if re.match(rf"<{re.escape(tag)}[\s>]", stripped):
            return tag
    return None


def _depth_change(line: str, tag: str) -> int:
    """Openings minus closings of ``tag`` on ``line``."""
    opens = len(re.findall(rf"<{re.escape(tag)}(?=[\s>])", line))
    closes = line.count(f"</{tag}>")
    return opens - closes


def find_blocks(lines: List[str], tags: Iterable[str]) -> List[BlockSpan]:
    """Return the top-level declared blocks of ``lines`` in page order.

    A block closes at the line that closes its tag, counting nesting of the
    same tag. Lines inside a code fence outside a block never open one, and a
    closing tag inside a fence within a block does not count. A block that
    never closes ends at the last line.
    """
    tags = list(tags)
    spans: List[BlockSpan] = []
    if not tags:
        return spans
    fence: Optional[str] = None
    block_tag: Optional[str] = None
    start = depth = 0
    for i, line in enumerate(lines):
        if fence is not None:
            if _closes_fence(line, fence):
                fence = None
            continue
        run = _fence_run(line)
        if run is not None:
            fence = run
            continue
        if block_tag is None:
            block_tag = _opening_tag(line, tags)
            if block_tag is None:
                continue
            start, depth = i, 0
        depth += _depth_change(line, block_tag)
        if depth <= 0:
            spans.append(BlockSpan(start, i, block_tag))
            block_tag = None
    if block_tag is not None:
        spans.append(BlockSpan(start, len(lines) - 1, block_tag))
    return spans
