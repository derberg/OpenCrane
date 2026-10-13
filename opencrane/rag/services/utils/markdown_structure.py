"""Markdown structure helpers shared by the page splitter and the strategies.

The file processor splits a page at its fenced code blocks before the
strategies run. These helpers tell which fences belong to a list item, so the
splitter keeps them inside the list, and track the headings seen so far on a
page, so every part of the page keeps its heading ancestry.
"""

import re
from typing import List, Tuple

_LIST_MARKER_RE = re.compile(r"^\s*(?:\d+\.|[-*+])\s")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _is_fence(line: str) -> bool:
    return line.strip().startswith("```")


def list_item_fence_mask(lines: List[str]) -> List[bool]:
    """Return a per-line mask that is True for fenced blocks inside list items.

    A fence belongs to a list item when it is indented and a list is open: the
    last non-blank line before it, outside fences, is a list marker line or an
    indented continuation of one. The mask covers the opening fence, the code,
    and the closing fence. Top-level fences, and indented fences outside a list,
    are left False.
    """
    mask = [False] * len(lines)
    list_open = False
    fence = None  # None, "item" (inside a list item) or "plain"
    for i, line in enumerate(lines):
        if fence is not None:
            mask[i] = fence == "item"
            if _is_fence(line):
                fence = None
            continue
        if _is_fence(line):
            if list_open and line[:1] in (" ", "\t"):
                fence = "item"
                mask[i] = True
            else:
                fence = "plain"
                list_open = False
            continue
        if _LIST_MARKER_RE.match(line):
            list_open = True
        elif line.strip() and line[:1] not in (" ", "\t"):
            list_open = False
    return mask


def has_fence_outside_list_items(text: str) -> bool:
    """True when ``text`` has a fenced block that is not inside a list item."""
    lines = text.split("\n")
    mask = list_item_fence_mask(lines)
    return any(_is_fence(line) and not mask[i] for i, line in enumerate(lines))


def update_heading_stack(heading_stack: List[Tuple[int, str]], text: str) -> None:
    """Push the headings of ``text`` onto ``heading_stack``, outside fences.

    A heading pops every heading of the same or a deeper level first, so the
    stack holds the ancestry in effect after ``text``.
    """
    in_fence = False
    for line in text.split("\n"):
        if _is_fence(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_RE.match(line.strip())
        if not m:
            continue
        level = len(m.group(1))
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, m.group(2).strip()))
