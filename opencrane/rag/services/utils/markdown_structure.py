"""Markdown structure helpers shared by the page splitter and the strategies.

The file processor splits a page at its fenced code blocks before the
strategies run. These helpers tell which fences belong to a list item, so the
splitter keeps them inside the list, and track the headings seen so far on a
page, so every part of the page keeps its heading ancestry.
"""

import re
from typing import List, Optional, Tuple

_LIST_MARKER_RE = re.compile(r"^\s*(?:\d+\.|[-*+])\s")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def _is_fence(line: str) -> bool:
    return line.strip().startswith("```")


def _fence_run(line: str) -> Optional[str]:
    """Return the backtick or tilde run that opens a fence on ``line``."""
    m = _FENCE_RE.match(line)
    return m.group(1) if m else None


def _closes_fence(line: str, opening: str) -> bool:
    """True when ``line`` closes the fence that ``opening`` started.

    The closing run must use the same character and be at least as long, so a
    ```` fence that shows ``` fences inside it stays open until its own end.
    """
    run = _fence_run(line)
    return run is not None and run[0] == opening[0] and len(run) >= len(opening)


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
    opening = ""
    for i, line in enumerate(lines):
        if fence is not None:
            mask[i] = fence == "item"
            if _closes_fence(line, opening):
                fence = None
            continue
        run = _fence_run(line)
        if run is not None:
            opening = run
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


class HeadingTracker:
    """Track the headings in effect while reading a page, part by part.

    ``stack`` holds the ancestry as (level, title) pairs. The fence state
    carries over from one part to the next: the page splitter cuts at every
    ``` line, so a ```` fence that shows ``` fences inside it reaches the
    tracker in several parts, and the lines inside it are not headings.
    """

    def __init__(self, stack: Optional[List[Tuple[int, str]]] = None):
        self.stack: List[Tuple[int, str]] = stack if stack is not None else []
        self._fence: Optional[str] = None

    def feed(self, text: str) -> None:
        """Push the headings of ``text`` onto the stack, outside fences.

        A heading pops every heading of the same or a deeper level first, so
        the stack holds the ancestry in effect after ``text``.
        """
        for line in text.split("\n"):
            if self._fence is not None:
                if _closes_fence(line, self._fence):
                    self._fence = None
                continue
            run = _fence_run(line)
            if run is not None:
                self._fence = run
                continue
            m = _HEADING_RE.match(line.strip())
            if not m:
                continue
            level = len(m.group(1))
            while self.stack and self.stack[-1][0] >= level:
                self.stack.pop()
            self.stack.append((level, m.group(2).strip()))


def update_heading_stack(heading_stack: List[Tuple[int, str]], text: str) -> None:
    """Push the headings of ``text`` onto ``heading_stack``, outside fences."""
    HeadingTracker(heading_stack).feed(text)
