"""get_section returns the lists and tables of a section, not only its prose."""

import json

import pytest

from opencrane.mcp import server as s
from opencrane.mcp.auth import runtime


def _row(chunk_id, chunk_type, content, source_name="docs", **meta):
    """A Milvus row: metadata as ``metadata_json`` plus the lifted id columns."""
    return {
        "chunk_id": chunk_id, "chunk_type": chunk_type, "content": content,
        "source_file": "page.md", "source_name": source_name,
        "metadata_json": json.dumps(meta),
        **{c: meta.get(c) or "" for c in ("list_id", "table_id", "clause_id", "parent_chunk_id")},
    }


def _prose(chunk_id, content, position, order=None, parent=None, prev=None, next_=None, path="Page > Section"):
    meta = {"heading_path": path, "position": position, "parent_chunk_id": parent,
            "prev_chunk_id": prev, "next_chunk_id": next_}
    if order is not None:
        meta["doc_order"] = order
    return _row(chunk_id, "prose", content, **meta)


def _item(chunk_id, text, position, list_id, parent, order=None, depth=0, parent_item=None,
          breadcrumb="Page > Section", total=2, style="unordered", **extra):
    meta = {"breadcrumb_path": breadcrumb, "list_id": list_id, "list_style": style,
            "position": position, "total_siblings": total, "depth": depth,
            "parent_item_id": parent_item, "parent_chunk_id": parent, **extra}
    if order is not None:
        meta["doc_order"] = order
    return _row(chunk_id, "list_item", f"# {breadcrumb}\n{text}", **meta)


class FakeMilvus:
    def __init__(self, rows):
        self.rows = {r["chunk_id"]: r for r in rows}

    def get_chunk(self, chunk_id):
        return self.rows.get(chunk_id)

    def query_by_values(self, field, values, chunk_type=None, limit=16384):
        return [r for r in self.rows.values()
                if r.get(field) in values and (chunk_type is None or r["chunk_type"] == chunk_type)]


def _use(monkeypatch, rows):
    monkeypatch.setattr(s, "get_milvus_service", lambda: FakeMilvus(rows))


async def _call(args):
    return (await s.get_section(args))[0].text


@pytest.mark.anyio
async def test_unlinked_list_item_and_table_row_point_to_their_member_tools(monkeypatch):
    _use(monkeypatch, [
        _item("i1", "Item.", 1, "L1", parent=None),
        _row("r1", "table_row", "# Page\nA: b.", table_id="T1", row_index=1, parent_chunk_id="gone"),
    ])
    text = await _call({"chunk_id": "i1"})
    assert text.startswith("No prose section found for chunk_id='i1'. The chunk is a list_item")
    assert "Read its list with get_list_members(list_id='L1')" in text
    text = await _call({"chunk_id": "r1"})
    assert "Read its table with get_table_members(table_id='T1')" in text


@pytest.mark.anyio
async def test_member_of_a_forbidden_source_reveals_nothing(monkeypatch):
    _use(monkeypatch, [
        _prose("p", "## Section\n\nText.", 1, order=1),
        _item("i1", "Item.", 1, "L1", parent="p", order=2),
    ])
    monkeypatch.setattr(runtime, "current_allowed_sources", lambda: ("other",))
    assert await _call({"chunk_id": "i1"}) == "No prose section found for chunk_id='i1'."


@pytest.mark.anyio
async def test_member_linked_to_a_section_of_another_source_is_not_followed(monkeypatch):
    _use(monkeypatch, [
        _prose("p", "## Section\n\nText.", 1, order=1),
        {**_item("i1", "Item.", 1, "L1", parent="p", order=2), "source_name": "elsewhere"},
    ])
    text = await _call({"chunk_id": "i1"})
    assert "get_list_members(list_id='L1')" in text


@pytest.mark.anyio
async def test_nested_list_renders_as_one_indented_list(monkeypatch):
    _use(monkeypatch, [
        _prose("p", "## Section\n\nPick a mode:", 1, order=1),
        _item("a", "Fast mode.", 1, "outer", parent="p", order=2),
        _item("a1", "Fast mode.\nSkips checks.", 1, "inner", parent="p", order=3, depth=1, parent_item="a", total=1),
        _item("b", "Safe mode.", 2, "outer", parent="p", order=4),
    ])
    text = await _call({"chunk_id": "a1"})
    assert (
        "Pick a mode:\n\n"
        "List (2 of 2 items, style=unordered)\n"
        "Location: Page > Section\n"
        "[1] Fast mode.\n"
        "  [1] Skips checks.\n"
        "[2] Safe mode.\n"
    ) in text


@pytest.mark.anyio
async def test_table_without_caption_and_without_breadcrumb(monkeypatch):
    _use(monkeypatch, [
        _prose("p", "## Section\n\nText.", 1, order=1),
        _row("r1", "table_row", "Key: a.", table_id="T", row_index=1, total_rows=1,
             parent_chunk_id="p", doc_order=2),
    ])
    text = await _call({"chunk_id": "p"})
    assert text.endswith("Text.\n\nTable (1 of 1 rows)\n[1] Key: a.\n")


@pytest.mark.anyio
async def test_without_doc_order_lists_follow_the_prose(monkeypatch):
    _use(monkeypatch, [
        _prose("p", "## Section\n\nIntro.", 1, next_="p2"),
        _prose("p2", "Outro.", 2, prev="p"),
        _item("i1", "Item.", 1, "L1", parent="p", total=1),
    ])
    text = await _call({"chunk_id": "p"})
    assert text.endswith("Intro.\n\nOutro.\n\nList (1 of 1 items, style=unordered)\nLocation: Page > Section\n[1] Item.\n")


@pytest.mark.anyio
async def test_subsection_cap_counts_list_items(monkeypatch):
    monkeypatch.setattr(s, "_SECTION_MAX_SUBSECTION_CHUNKS", 1)
    _use(monkeypatch, [
        _prose("p", "## Section\n\nIntro.", 1, order=1),
        _prose("c", "### Child\n\nChild text.", 2, order=2, parent="p", path="Page > Section > Child"),
        _item("i1", "One.", 1, "L1", parent="c", order=3, breadcrumb="Page > Section > Child"),
        _item("i2", "Two.", 2, "L1", parent="c", order=4, breadcrumb="Page > Section > Child"),
    ])
    text = await _call({"chunk_id": "p", "include_subsections": True})
    assert "Sub-sections (3 chunks):" in text
    assert "Child text." in text and "One." not in text
    assert "... 2 more sub-section chunks not shown;" in text


@pytest.mark.anyio
async def test_neighbor_sections_carry_their_lists(monkeypatch):
    _use(monkeypatch, [
        _prose("p", "## Section\n\nIntro.", 1, order=1, next_="q"),
        _prose("q", "## Next\n\nNext intro.", 2, order=2, prev="p", path="Page > Next"),
        _item("i1", "Next item.", 1, "L1", parent="q", order=3, breadcrumb="Page > Next", total=1),
    ])
    text = await _call({"chunk_id": "p", "neighbors": 1})
    assert "=== Next section ===" in text
    assert text.endswith("Next intro.\n\nList (1 of 1 items, style=unordered)\nLocation: Page > Next\n[1] Next item.\n")
