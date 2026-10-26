"""Find the content blocks that chunking strategies declare by tag name.

A strategy declares the tags of the components it owns, such as ``details``
for a GitHub ``<details>`` section. The page splitter keeps each such block in
one piece, so the strategy sees the whole component.
"""

import re
from dataclasses import dataclass
from typing import Collection, Iterable, List, Optional

from opencrane.rag.services.utils.markdown_structure import _closes_fence, _fence_run


@dataclass(frozen=True)
class BlockSpan:
    """A declared block: its first and last line (inclusive) and its tag."""

    start: int
    end: int
    tag: str


_CODE_SPAN_RE = re.compile(r"(`+).*?\1")


def _starts_with_tag(text: str, tag: str) -> bool:
    return re.match(rf"<{re.escape(tag)}[\s>]", text) is not None


def _opening_tag(line: str, tags: List[str]) -> Optional[str]:
    """Return the declared tag that ``line`` opens, or None.

    The tag must start the line at its first column, as ``<tag>`` or ``<tag ``
    with attributes. An inline mention never opens a block, and neither does an
    indented tag, which belongs to a list item or an indented code block.
    """
    for tag in tags:
        if _starts_with_tag(line, tag):
            return tag
    return None


def _depth_change(line: str, tag: str) -> int:
    """Openings minus closings of ``tag`` on ``line``.

    A nested block of the same tag opens on a line that starts with the tag,
    at any indent. A closing tag counts anywhere on the line. Tags inside
    inline code spans never count.
    """
    text = _CODE_SPAN_RE.sub("", line)
    opens = 1 if _starts_with_tag(text.lstrip(), tag) else 0
    return opens - text.count(f"</{tag}>")


def find_blocks(
    lines: List[str], tags: Iterable[str], boundaries: Collection[int] = ()
) -> List[BlockSpan]:
    """Return the top-level declared blocks of ``lines`` in page order.

    A block closes at the line that closes its tag, counting nesting of the
    same tag. Lines inside a code fence outside a block never open one, and a
    closing tag inside a fence within a block does not count. A block that
    never closes ends at the line before the first index in ``boundaries``
    after it, such as the start of the next page, or at the last line. A
    boundary inside a block that does close has no effect.
    """
    tags = list(tags)
    spans: List[BlockSpan] = []
    begin = 0
    while tags and begin < len(lines):
        found, unclosed = _scan(lines, tags, begin)
        spans.extend(found)
        if unclosed is None:
            break
        cut = min((b for b in boundaries if b > unclosed), default=len(lines))
        spans.append(BlockSpan(unclosed, cut - 1, _opening_tag(lines[unclosed], tags)))
        begin = cut
    return spans


def _scan(lines: List[str], tags: List[str], begin: int):
    """Scan from ``begin``; return the closed blocks and the start of an unclosed one."""
    spans: List[BlockSpan] = []
    fence: Optional[str] = None
    block_tag: Optional[str] = None
    start = depth = 0
    for i in range(begin, len(lines)):
        line = lines[i]
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
    return spans, (start if block_tag is not None else None)
