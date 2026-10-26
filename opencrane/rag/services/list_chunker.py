"""List-item chunking strategy.

Emits one chunk per markdown list item so semantic search can match individual
items. Each chunk's metadata links it to siblings in the same list, to its
parent (when nested), and carries short previews of the rest of the list so
agents can reconstruct the group without extra tool calls. The prose around the
lists is handed to ``ProseChunkingStrategy``, so it is chunked like any other
prose.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.rag.services.prose_chunker import ProseChunkingStrategy
from opencrane.rag.services.utils.chunk_id_generator import generate_unique_chunk_id
from opencrane.rag.services.utils.markdown_structure import lead_in_line
from opencrane.shared.models.chunk import Chunk
from opencrane.shared.utils.token_counter import get_token_count


_LIST_MARKER_RE = re.compile(r"^(?P<indent>\s*)(?:(?P<ordered>\d+)\.|[-*+])\s")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_MARKER_PREFIX_RE = re.compile(r"^(?P<prefix>\s*(?:\d+\.|[-*+])\s+)(?P<body>.*)$")


TOTAL_CAP = 30       # preview display width (incl. prefix and ellipsis)
PREVIEW_CAP = 15     # max number of sibling previews before overflow marker


@dataclass
class _Item:
    """Parsed representation of a single list item during chunking."""

    style: str                        # "ordered" or "unordered"
    marker: str                       # original marker token ("1.", "-", etc.)
    indent: int                       # leading spaces of marker line
    depth: int                        # nesting depth (0 = top level)
    first_line: str                   # body text after marker on the marker line
    body_lines: List[str] = field(default_factory=list)  # full raw lines of this item (marker line + continuation, excluding nested items)
    content_indent: int = 0           # column where the item's text starts (continuation lines indented at least this far belong to it)
    children: List["_Item"] = field(default_factory=list)
    parent: Optional["_Item"] = None
    position: int = 0                 # 1-indexed within siblings
    chunk_id: Optional[str] = None
    list_id: Optional[str] = None

    @property
    def has_body_continuation(self) -> bool:
        """True when the item body has more than a single line of text."""
        # Count non-blank lines after the marker line
        extra = [ln for ln in self.body_lines[1:] if ln.strip()]
        return bool(extra)


@dataclass
class _ProseNode:
    """A prose segment handed to ``ProseChunkingStrategy``."""

    text: str
    source_url: Optional[str]
    node_type: str = "text"


class ListChunkingStrategy(ProcessingStrategy):
    """Strategy that emits one chunk per list item and hands the prose around
    the lists to ``ProseChunkingStrategy``."""

    def can_process(self, node) -> bool:
        if not hasattr(node, "text"):
            return False
        if getattr(node, "node_type", "text") == "code":
            return False
        text = node.text if hasattr(node, "text") else str(node)
        if not text or not text.strip():
            return False
        return self._has_list_outside_fences(text)

    def process(self, node, source_file: Path) -> List[Chunk]:
        text = node.text
        source_url = getattr(node, "source_url", None)

        segments = self._segment(text)

        chunks: List[Chunk] = []
        heading_stack: List[Tuple[int, str]] = list(getattr(node, "heading_ancestry", None) or [])
        section_breadcrumb = " > ".join(title for _, title in heading_stack)
        list_ordinal_in_section = 0                   # counts top-level lists per section
        prose_strategy = ProseChunkingStrategy()
        # Headings the prose chunker dropped at the end of one prose segment
        # (heading-only or too short), handed to the next prose chunk so its
        # heading ancestry stays complete, as within a single prose node.
        pending_headings: List[str] = []
        # The sentence right before a list that introduces it, such as
        # "Prerequisites:". Every item of that list repeats it.
        lead_in: Optional[str] = None

        for kind, payload in segments:
            if kind == "prose":
                # Update heading stack from prose lines so the breadcrumb
                # reflects the nearest heading ancestry for any following list.
                new_breadcrumb = self._update_breadcrumb(heading_stack, payload)
                if new_breadcrumb != section_breadcrumb:
                    section_breadcrumb = new_breadcrumb
                    list_ordinal_in_section = 0
                prose_chunks = prose_strategy.process(
                    _ProseNode("\n".join(payload), source_url), source_file
                )
                if prose_chunks:
                    first = prose_chunks[0]
                    first._preceding_headings = pending_headings + first._preceding_headings
                    pending_headings = []
                pending_headings += prose_strategy._skipped_headings
                chunks.extend(prose_chunks)
                lead_in = lead_in_line("\n".join(payload))
            elif kind == "list":
                list_ordinal_in_section += 1
                list_chunks = self._make_list_chunks(
                    list_lines=payload,
                    breadcrumb=section_breadcrumb,
                    list_ordinal=list_ordinal_in_section,
                    source_file=source_file,
                    source_url=source_url,
                    lead_in=lead_in,
                )
                lead_in = None
                if list_chunks:
                    # The headings dropped since the last prose chunk sit right
                    # above this list, so they go with its first item.
                    list_chunks[0]._preceding_headings = pending_headings
                    pending_headings = []
                chunks.extend(list_chunks)

        # Headings dropped after the last chunk, for a caller that emits more
        # chunks of the same page (a table that follows this text).
        self._pending_headings = pending_headings
        return chunks

    # --- fence / segmentation helpers ---------------------------------------

    @staticmethod
    def _compute_fence_mask(lines: List[str]) -> List[bool]:
        """Return a per-line mask: True when line is inside a fenced block (markers included)."""
        mask = [False] * len(lines)
        in_fence = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("```"):
                if not in_fence:
                    in_fence = True
                    mask[i] = True
                else:
                    mask[i] = True
                    in_fence = False
                continue
            if in_fence:
                mask[i] = True
        return mask

    def _has_list_outside_fences(self, text: str) -> bool:
        lines = text.split("\n")
        mask = self._compute_fence_mask(lines)
        for i, line in enumerate(lines):
            if mask[i]:
                continue
            if _LIST_MARKER_RE.match(line):
                return True
        return False

    def _segment(self, text: str) -> List[Tuple[str, List[str]]]:
        """Split text into ("prose", lines) and ("list", lines) segments.

        Lines inside fenced code blocks are always assigned to the surrounding
        prose or list segment (fences never start a list).  List segments begin
        at a top-level list marker (indent 0) and continue through all
        continuation / nested lines until a non-indented, non-marker, non-blank
        line is reached.
        """
        lines = text.split("\n")
        mask = self._compute_fence_mask(lines)

        segments: List[Tuple[str, List[str]]] = []
        current_type = "prose"
        current_lines: List[str] = []

        def flush():
            if current_lines:
                segments.append((current_type, list(current_lines)))

        i = 0
        while i < len(lines):
            line = lines[i]
            in_fence = mask[i]

            if not in_fence and _LIST_MARKER_RE.match(line) and self._marker_indent(line) == 0:
                # Start of a top-level list
                if current_type != "list":
                    flush()
                    current_lines = []
                    current_type = "list"
                current_lines.append(line)
                i += 1
                continue

            if current_type == "list":
                # Decide whether this line continues the current list.
                if in_fence:
                    # Fenced content belongs to the list item as continuation.
                    current_lines.append(line)
                    i += 1
                    continue
                stripped = line.strip()
                if not stripped:
                    # Blank line: include tentatively; only terminates list if
                    # followed by a non-indented non-marker non-blank line.
                    # Peek ahead past consecutive blanks.
                    j = i + 1
                    while j < len(lines) and not lines[j].strip() and not mask[j]:
                        j += 1
                    if j >= len(lines):
                        # trailing blanks — list ends here
                        flush()
                        current_lines = []
                        current_type = "prose"
                        # do not include these blanks; move on
                        i = j
                        continue
                    next_line = lines[j]
                    if mask[j]:
                        # next non-blank line is inside a fence (shouldn't happen,
                        # fences have their own markers).  Treat as continuation.
                        current_lines.append(line)
                        i += 1
                        continue
                    if _LIST_MARKER_RE.match(next_line) or next_line.startswith(" ") or next_line.startswith("\t"):
                        # continuation of the list
                        current_lines.append(line)
                        i += 1
                        continue
                    # List ends: flush and reprocess the blank as prose
                    flush()
                    current_lines = []
                    current_type = "prose"
                    continue
                if _LIST_MARKER_RE.match(line) or line.startswith(" ") or line.startswith("\t"):
                    current_lines.append(line)
                    i += 1
                    continue
                # Non-indented, non-marker line ends the list
                flush()
                current_lines = []
                current_type = "prose"
                continue

            # current_type == "prose"
            current_lines.append(line)
            i += 1

        flush()

        # Strip trailing blank lines in each segment and drop empty segments.
        cleaned: List[Tuple[str, List[str]]] = []
        for kind, seg_lines in segments:
            while seg_lines and not seg_lines[0].strip():
                seg_lines = seg_lines[1:]
            while seg_lines and not seg_lines[-1].strip():
                seg_lines = seg_lines[:-1]
            if seg_lines:
                cleaned.append((kind, seg_lines))
        return cleaned

    @staticmethod
    def _marker_indent(line: str) -> int:
        m = _LIST_MARKER_RE.match(line)
        if not m:
            return -1  # pragma: no cover - only called after a positive match
        return len(m.group("indent"))

    # --- breadcrumb tracking -------------------------------------------------

    @staticmethod
    def _update_breadcrumb(heading_stack: List[Tuple[int, str]], lines: List[str]) -> str:
        """Update heading stack from prose lines, return joined breadcrumb path."""
        for line in lines:
            m = _HEADING_RE.match(line.strip())
            if not m:
                continue
            level = len(m.group(1))
            title = m.group(2).strip()
            # Pop any headings at the same or deeper level
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
        return " > ".join(title for _, title in heading_stack)

    # --- list chunk builder --------------------------------------------------

    def _make_list_chunks(
        self,
        list_lines: List[str],
        breadcrumb: str,
        list_ordinal: int,
        source_file: Path,
        source_url: Optional[str],
        lead_in: Optional[str] = None,
    ) -> List[Chunk]:
        top_items = self._parse_items(list_lines)
        if not top_items:
            return []  # pragma: no cover - defensive, can_process guards

        chunks: List[Chunk] = []
        # Fingerprint of this list block's raw lines: tells apart lists that share
        # a page, breadcrumb and ordinal because they sit in separate nodes (e.g.
        # two lists in one section with a code block between them).
        block_fingerprint = hashlib.sha256("\n".join(list_lines).encode("utf-8")).hexdigest()[:16]

        # Walk top-level first, then children — parents need ids for their children's metadata.
        def walk(items: List[_Item], parent: Optional[_Item]):
            for it in items:
                it.parent = parent
            # Generate chunk_ids and list_ids for the whole group.
            for idx, it in enumerate(items, start=1):
                it.position = idx
            # Compute list_id for this sibling group.
            group_list_id = self._compute_list_id(
                breadcrumb=breadcrumb,
                list_ordinal=list_ordinal,
                depth=items[0].depth,
                parent_id=parent.chunk_id if parent else None,
                source_url=source_url,
                block_fingerprint=block_fingerprint,
            )
            for it in items:
                it.list_id = group_list_id
                content = self._build_item_content(it, breadcrumb, lead_in)
                metadata_for_hash = {"breadcrumb_path": breadcrumb, "list_id": group_list_id, "position": it.position}
                if source_url:
                    metadata_for_hash["source_url"] = source_url
                it.chunk_id = generate_unique_chunk_id(
                    content=content,
                    source_file=str(source_file),
                    chunk_type="list_item",
                    metadata=metadata_for_hash,
                )
            for it in items:
                content = self._build_item_content(it, breadcrumb, lead_in)
                chunk = self._build_item_chunk(
                    it=it,
                    siblings=items,
                    breadcrumb=breadcrumb,
                    content=content,
                    source_file=source_file,
                    source_url=source_url,
                )
                if lead_in:
                    chunk.metadata["list_caption"] = lead_in
                chunks.append(chunk)
                if it.children:
                    walk(it.children, it)

        walk(top_items, None)
        return chunks

    # --- parsing list items --------------------------------------------------

    def _parse_items(self, lines: List[str]) -> List[_Item]:
        """Parse a list block's lines into a nested tree of _Item objects.

        A line that is not a list marker is a continuation line. It belongs to
        the deepest open item whose text column it reaches, so text indented
        under a nested item stays with that item and text indented back to a
        parent's column after its nested items stays with the parent. Lines of
        a fenced block go to the item that holds the opening fence, and list
        markers inside a fence never start an item. Blank lines go to the item
        that owns the next non-blank line.
        """
        mask = self._compute_fence_mask(lines)
        top_items: List[_Item] = []
        stack: List[_Item] = []  # open items by increasing indent
        pending_blanks: List[str] = []
        in_fence = False

        for i, line in enumerate(lines):
            m = None if mask[i] else _LIST_MARKER_RE.match(line)
            if m:
                pending_blanks = []
                indent = len(m.group("indent"))
                ordered_num = m.group("ordered")
                style = "ordered" if ordered_num else "unordered"
                marker_token = f"{ordered_num}." if ordered_num else line[indent]
                # Determine depth: count how many ancestors have smaller indent.
                while stack and stack[-1].indent >= indent:
                    stack.pop()
                depth = len(stack)
                parent = stack[-1] if stack else None

                # Body content of marker line: content after marker + space
                prefix = _MARKER_PREFIX_RE.match(line)
                item = _Item(
                    style=style,
                    marker=marker_token,
                    indent=indent,
                    depth=depth,
                    first_line=prefix.group("body"),
                    body_lines=[line],
                    content_indent=len(prefix.group("prefix")),
                )
                if parent is None:
                    top_items.append(item)
                else:
                    parent.children.append(item)
                stack.append(item)
                continue

            if not stack:
                continue  # pragma: no cover - segmentation starts lists at a marker

            if not mask[i] and not line.strip():
                pending_blanks.append(line)
                continue

            if not in_fence:
                # A text line or an opening fence: close nested items whose
                # text column the line does not reach.
                line_indent = len(line) - len(line.lstrip())
                while len(stack) > 1 and line_indent < stack[-1].content_indent:
                    stack.pop()
            if mask[i] and line.strip().startswith("```"):
                in_fence = not in_fence
            owner = stack[-1]
            owner.body_lines.extend(pending_blanks)
            pending_blanks = []
            owner.body_lines.append(line)

        return top_items

    # --- content composition -------------------------------------------------

    def _build_item_content(self, item: _Item, breadcrumb: str, lead_in: Optional[str] = None) -> str:
        """Compose the chunk content for a list item.

        Every item renders its own full body (continuation lines, paragraphs
        and fenced code included, nested items excluded since they get their
        own chunks). Nested items prepend their ancestors' first lines so the
        chunk stays self-contained for embedding. The lead-in sentence of the
        list, when there is one, comes right after the breadcrumb.
        """
        header = f"# {breadcrumb}" if breadcrumb else "#"
        if lead_in:
            header += f"\n{lead_in}"
        lineage: List[str] = []
        cur: Optional[_Item] = item.parent
        while cur is not None:
            lineage.append(self._rendered_first_line(cur))
            cur = cur.parent
        lineage.reverse()
        return "\n".join([header] + lineage + [self._render_body(item)])

    @staticmethod
    def _rendered_first_line(item: _Item) -> str:
        """Render a single item's first line with marker prefix for ordered lists."""
        if item.style == "ordered":
            return f"{item.marker} {item.first_line}".rstrip()
        return item.first_line

    def _render_body(self, item: _Item) -> str:
        """Render an item's own body: its first line plus its continuation lines.

        Continuation lines keep their layout relative to the item's marker (the
        marker's own indent is removed), so a nested item renders like a
        top-level one.
        """
        first = self._rendered_first_line(item)
        # Blank lines are only attached before a following line of the item,
        # so the body never ends with one.
        rest = [self._dedent(ln, item.indent) for ln in item.body_lines[1:]]
        if not rest:
            return first
        return "\n".join([first] + rest)

    @staticmethod
    def _dedent(line: str, width: int) -> str:
        """Remove up to ``width`` leading whitespace characters from ``line``."""
        lead = len(line) - len(line.lstrip())
        return line[min(lead, width):]

    # --- metadata + chunk assembly -------------------------------------------

    @staticmethod
    def _compute_list_id(
        breadcrumb: str,
        list_ordinal: int,
        depth: int,
        parent_id: Optional[str],
        source_url: Optional[str] = None,
        block_fingerprint: str = "",
    ) -> str:
        # source_url scopes the id to its page, so lists under the same breadcrumb
        # on different pages never share an id (get_list_members would merge them).
        key = f"{source_url or ''}|{block_fingerprint}|{breadcrumb}|{list_ordinal}|{depth}|{parent_id or ''}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def _build_item_chunk(
        self,
        it: _Item,
        siblings: List[_Item],
        breadcrumb: str,
        content: str,
        source_file: Path,
        source_url: Optional[str],
    ) -> Chunk:
        others = [s for s in siblings if s is not it]
        sibling_ids = [s.chunk_id for s in others]
        sibling_previews = self._build_previews(others)

        metadata: dict = {
            "breadcrumb_path": breadcrumb,
            "list_id": it.list_id,
            "list_style": it.style,
            "position": it.position,
            "total_siblings": len(siblings),
            "sibling_ids": sibling_ids,
            "sibling_previews": sibling_previews,
            "parent_item_id": it.parent.chunk_id if it.parent else None,
            "depth": it.depth,
        }
        if source_url:
            metadata["source_url"] = source_url

        return Chunk(
            chunk_id=it.chunk_id,
            content=content,
            source_file=str(source_file),
            chunk_type="list_item",
            metadata=metadata,
            token_count=get_token_count(content),
        )

    def _build_previews(self, items: List[_Item]) -> List[str]:
        if not items:
            return []
        total = len(items)
        if total <= PREVIEW_CAP:
            return [self._preview_for(it) for it in items]
        kept = [self._preview_for(it) for it in items[:PREVIEW_CAP]]
        overflow = total - PREVIEW_CAP
        kept.append(f"... +{overflow} more")
        return kept

    @staticmethod
    def _preview_for(item: _Item) -> str:
        prefix = f"{item.marker} " if item.style == "ordered" else ""
        body = item.first_line
        if len(prefix) + len(body) > TOTAL_CAP:
            allowed = TOTAL_CAP - len(prefix) - 1  # -1 reserves a slot for "…"
            body_disp = body[:allowed] + "…"
        elif item.has_body_continuation:
            body_disp = body + " …"
        else:
            body_disp = body
        return prefix + body_disp
