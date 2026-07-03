"""Table chunking: one chunk per data row.

Each row is rendered as natural-language ``Column: value.`` lines, prefixed with
the section breadcrumb and the table caption, so a row is self-describing and
embeds like a sentence rather than a wall of pipes. Rows self-organize via
``table_id`` and ``sibling_ids`` (full list_item parity).
"""

import hashlib
import re
from pathlib import Path
from typing import List, Optional

from opencrane.rag.services.utils.chunk_id_generator import generate_unique_chunk_id
from opencrane.shared.models.chunk import Chunk
from opencrane.shared.utils.token_counter import get_token_count
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.rag.services.list_chunker import ListChunkingStrategy, PREVIEW_CAP, TOTAL_CAP
from opencrane.rag.services.prose_chunker import ProseChunkingStrategy


def _is_table_separator(line: str) -> bool:
    """True when a line is a markdown table separator row (for example ``|---|---|``)."""
    stripped = line.strip()
    if "|" not in stripped or "-" not in stripped:
        return False
    return set(stripped) <= set("|-: ")


def _split_row(line: str) -> List[str]:
    """Split a ``| a | b |`` row into stripped cell values."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _table_id(breadcrumb: str, caption: str, columns: List[str], row_keys: List[str]) -> str:
    key = f"{breadcrumb}|{caption}|{'|'.join(columns)}|{'|'.join(row_keys)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _preview_text(row_key: str) -> str:
    if len(row_key) > TOTAL_CAP:
        return row_key[:TOTAL_CAP - 1] + "…"
    return row_key


def _previews(row_keys: List[str], exclude_index: int) -> List[str]:
    others = [k for i, k in enumerate(row_keys) if i != exclude_index]
    kept = [_preview_text(k) for k in others[:PREVIEW_CAP]]
    if len(others) > PREVIEW_CAP:
        kept.append(f"... +{len(others) - PREVIEW_CAP} more")
    return kept


def _render_row(columns: List[str], cells: List[str], breadcrumb: str, caption: str) -> str:
    lines: List[str] = []
    if breadcrumb:
        lines.append(breadcrumb)
    if caption:
        lines.append(caption)
    # A cell containing an unescaped pipe yields more cells than columns; merge
    # the overflow into the last column so no source data is dropped.
    if columns and len(cells) > len(columns):
        cells = cells[:len(columns) - 1] + [" | ".join(cells[len(columns) - 1:])]
    for col, val in zip(columns, cells):
        if val:
            sep = "" if val.endswith(".") else "."
            lines.append(f"{col}: {val}{sep}")
    return "\n".join(lines)


def build_table_chunks(
    table_lines: List[str],
    *,
    breadcrumb: str,
    caption: str,
    source_file: Path,
    source_url: Optional[str],
) -> List[Chunk]:
    """Build one ``table_row`` chunk per data row for a markdown table.

    Returns an empty list when the input is not a valid table (fewer than three
    lines, or the second line is not a separator row).  No overview chunk is
    produced; rows self-organize via ``table_id`` and ``sibling_ids``.
    """
    data_lines = [ln for ln in table_lines if ln.strip()]
    # Need at least a header, a separator, and one data row.
    if len(data_lines) < 3 or not _is_table_separator(data_lines[1]):
        return []
    columns = _split_row(data_lines[0])
    rows = [_split_row(ln) for ln in data_lines[2:]]
    row_keys = [cells[0] for cells in rows]
    table_id = _table_id(breadcrumb, caption, columns, row_keys)

    chunks: List[Chunk] = []

    # Pass 1: render each row and compute a stable chunk_id from a reduced
    # metadata subset (excluding sibling_ids, which depend on other rows' ids).
    row_contents = [_render_row(columns, cells, breadcrumb, caption) for cells in rows]
    row_ids = []
    for i, content in enumerate(row_contents):
        hash_meta = {"table_id": table_id, "row_index": i + 1}
        if source_url:
            hash_meta["source_url"] = source_url
        row_ids.append(generate_unique_chunk_id(content, str(source_file), "table_row", hash_meta))

    # Pass 2: assemble each row chunk, adding sibling_ids referencing the other rows.
    for i, cells in enumerate(rows):
        meta = {
            "table_id": table_id, "columns": columns, "row_index": i + 1,
            "total_rows": len(rows), "row_key": row_keys[i],
            "sibling_ids": [rid for j, rid in enumerate(row_ids) if j != i],
            "sibling_previews": _previews(row_keys, i),
        }
        if breadcrumb:
            meta["breadcrumb_path"] = breadcrumb
        if caption:
            meta["table_caption"] = caption
        if source_url:
            meta["source_url"] = source_url
        chunks.append(Chunk(
            chunk_id=row_ids[i],
            content=row_contents[i], source_file=str(source_file), chunk_type="table_row",
            metadata=meta, token_count=get_token_count(row_contents[i]),
        ))

    return chunks


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


class _SyntheticNode:
    """Minimal node passed to delegated strategies for a non-table region."""

    def __init__(self, text: str, source_url: Optional[str]):
        self.text = text
        self.node_type = "text"
        self.source_url = source_url


class TableChunkingStrategy(ProcessingStrategy):
    """Chunk markdown tables into one `table_row` chunk per data row, and delegate non-table regions to the list and prose strategies."""

    def can_process(self, node) -> bool:
        if not hasattr(node, "text"):
            return False
        if getattr(node, "node_type", "text") == "code":
            return False
        text = node.text
        if not text or not text.strip():
            return False
        return self._has_table_outside_fences(text)

    def process(self, node, source_file: Path) -> List[Chunk]:
        text = node.text
        source_url = getattr(node, "source_url", None)
        chunks: List[Chunk] = []
        heading_stack: List[tuple] = []
        caption = ""
        for kind, lines in self._split_regions(text):
            if kind == "other":
                caption = self._update(heading_stack, lines)
                chunks.extend(self._delegate(lines, source_url, source_file))
            else:
                breadcrumb = " > ".join(t for _, t in heading_stack)
                chunks.extend(build_table_chunks(
                    lines, breadcrumb=breadcrumb, caption=caption,
                    source_file=source_file, source_url=source_url))
        return chunks

    # --- region splitting ---------------------------------------------------

    @staticmethod
    def _fence_mask(lines: List[str]) -> List[bool]:
        mask = [False] * len(lines)
        in_fence = False
        for i, line in enumerate(lines):
            if line.strip().startswith("```"):
                mask[i] = True
                in_fence = not in_fence
            elif in_fence:
                mask[i] = True
        return mask

    @staticmethod
    def _is_row(line: str) -> bool:
        s = line.strip()
        return "|" in s and not _is_table_separator(s)

    def _has_table_outside_fences(self, text: str) -> bool:
        lines = text.split("\n")
        mask = self._fence_mask(lines)
        for i in range(len(lines) - 1):
            if mask[i] or mask[i + 1]:
                continue
            if self._is_row(lines[i]) and _is_table_separator(lines[i + 1]):
                return True
        return False

    def _split_regions(self, text: str):
        lines = text.split("\n")
        mask = self._fence_mask(lines)
        regions = []
        other: List[str] = []
        i = 0
        n = len(lines)
        while i < n:
            starts_table = (
                not mask[i] and i + 1 < n and not mask[i + 1]
                and self._is_row(lines[i]) and _is_table_separator(lines[i + 1])
            )
            if starts_table:
                if other:
                    regions.append(("other", other))
                    other = []
                header_cols = len(_split_row(lines[i]))
                block = [lines[i], lines[i + 1]]
                j = i + 2
                while (
                    j < n and not mask[j] and self._is_row(lines[j])
                    and len(_split_row(lines[j])) == header_cols
                ):
                    block.append(lines[j])
                    j += 1
                regions.append(("table", block))
                i = j
            else:
                other.append(lines[i])
                i += 1
        if other:
            regions.append(("other", other))
        return regions

    # --- breadcrumb + caption ----------------------------------------------

    @staticmethod
    def _update(heading_stack: List[tuple], lines: List[str]) -> str:
        """Update the heading stack from an ``other`` region; return the caption.

        The caption is the last non-blank line of the region, unless that line is
        a heading (then there is no caption sentence).
        """
        caption = ""
        for line in lines:
            m = _HEADING_RE.match(line.strip())
            if m:
                level = len(m.group(1))
                title = m.group(2).strip()
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, title))
        for line in reversed(lines):
            if line.strip():
                stripped = line.strip()
                if _HEADING_RE.match(stripped):
                    caption = ""
                else:
                    caption = re.sub(r"^(?:\d+\.|[-*+])\s+", "", stripped)
                break
        return caption

    # --- delegation ---------------------------------------------------------

    @staticmethod
    def _delegate(lines: List[str], source_url: Optional[str], source_file: Path) -> List[Chunk]:
        text = "\n".join(lines).strip()
        if not text:
            return []
        node = _SyntheticNode(text, source_url)
        list_strategy = ListChunkingStrategy()
        if list_strategy.can_process(node):
            return list_strategy.process(node, source_file)
        prose_strategy = ProseChunkingStrategy()
        if prose_strategy.can_process(node):
            return prose_strategy.process(node, source_file)
        return []  # pragma: no cover
