"""Table chunking: one overview chunk per table plus one chunk per row.

Each row is rendered as natural-language ``Column: value.`` lines, prefixed with
the section breadcrumb and the table caption, so a row is self-describing and
embeds like a sentence rather than a wall of pipes.
"""

import hashlib
import re
from pathlib import Path
from typing import List, Optional

from opencrane.rag.services.utils.chunk_id_generator import generate_unique_chunk_id
from opencrane.shared.models.chunk import Chunk
from opencrane.shared.utils.token_counter import get_token_count

_PREVIEW_CAP = 5
_OVERVIEW_KEYS = 8


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


def _table_id(breadcrumb: str, caption: str, columns: List[str]) -> str:
    key = f"{breadcrumb}|{caption}|{'|'.join(columns)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _previews(row_keys: List[str], exclude_index: int) -> List[str]:
    others = [k for i, k in enumerate(row_keys) if i != exclude_index]
    if len(others) <= _PREVIEW_CAP:
        return others
    return others[:_PREVIEW_CAP] + [f"... +{len(others) - _PREVIEW_CAP} more"]


def _render_row(columns: List[str], cells: List[str], breadcrumb: str, caption: str) -> str:
    lines: List[str] = []
    if breadcrumb:
        lines.append(breadcrumb)
    if caption:
        lines.append(caption)
    for col, val in zip(columns, cells):
        if val:
            lines.append(f"{col}: {val}.")
    return "\n".join(lines)


def _render_overview(columns: List[str], row_keys: List[str], breadcrumb: str, caption: str) -> str:
    lines: List[str] = []
    if breadcrumb:
        lines.append(f"# {breadcrumb}")
    if caption:
        lines.append(caption)
    shown = ", ".join(row_keys[:_OVERVIEW_KEYS])
    tail = ", ..." if len(row_keys) > _OVERVIEW_KEYS else "."
    lines.append(f"Columns: {', '.join(columns)}. {len(row_keys)} rows: {shown}{tail}")
    return "\n".join(lines)


def build_table_chunks(
    table_lines: List[str],
    *,
    breadcrumb: str,
    caption: str,
    source_file: Path,
    source_url: Optional[str],
) -> List[Chunk]:
    """Build the overview chunk and one chunk per data row for a markdown table."""
    data_lines = [ln for ln in table_lines if ln.strip()]
    # Need at least a header, a separator, and one data row.
    if len(data_lines) < 3 or not _is_table_separator(data_lines[1]):
        return []
    columns = _split_row(data_lines[0])
    rows = [_split_row(ln) for ln in data_lines[2:]]
    row_keys = [cells[0] if cells else "" for cells in rows]
    table_id = _table_id(breadcrumb, caption, columns)

    chunks: List[Chunk] = []

    overview_content = _render_overview(columns, row_keys, breadcrumb, caption)
    overview_meta = {"table_id": table_id, "columns": columns, "total_rows": len(rows)}
    if breadcrumb:
        overview_meta["breadcrumb_path"] = breadcrumb
    if caption:
        overview_meta["table_caption"] = caption
    if source_url:
        overview_meta["source_url"] = source_url
    chunks.append(Chunk(
        chunk_id=generate_unique_chunk_id(overview_content, str(source_file), "table", overview_meta),
        content=overview_content, source_file=str(source_file), chunk_type="table",
        metadata=overview_meta, token_count=get_token_count(overview_content),
    ))

    for i, cells in enumerate(rows):
        content = _render_row(columns, cells, breadcrumb, caption)
        meta = {
            "table_id": table_id, "columns": columns, "row_index": i + 1,
            "total_rows": len(rows), "row_key": row_keys[i],
            "sibling_previews": _previews(row_keys, i),
        }
        if breadcrumb:
            meta["breadcrumb_path"] = breadcrumb
        if caption:
            meta["table_caption"] = caption
        if source_url:
            meta["source_url"] = source_url
        chunks.append(Chunk(
            chunk_id=generate_unique_chunk_id(content, str(source_file), "table_row", meta),
            content=content, source_file=str(source_file), chunk_type="table_row",
            metadata=meta, token_count=get_token_count(content),
        ))

    return chunks
