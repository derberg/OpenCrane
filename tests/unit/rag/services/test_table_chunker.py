from pathlib import Path
from unittest.mock import Mock
from opencrane.rag.services.table_chunker import build_table_chunks, _is_table_separator, TableChunkingStrategy, _render_row


def test_is_table_separator():
    assert _is_table_separator("|---|---|") is True
    assert _is_table_separator("| :-- | --: |") is True
    assert _is_table_separator("| A | B |") is False
    assert _is_table_separator("plain") is False


def test_build_table_chunks_overview_and_rows():
    lines = [
        "| AVP | Code | Type |",
        "|-----|------|------|",
        "| 3GPP-IMSI | 1 | UTF8String |",
        "| 3GPP-Charging-Id | 2 | Unsigned32 |",
    ]
    chunks = build_table_chunks(
        lines, breadcrumb="DIAMETER > Applications",
        caption="The following AVP types are used:",
        source_file=Path("d.md"), source_url="http://x")
    # Every returned chunk must be table_row; count equals number of data rows.
    assert all(c.chunk_type == "table_row" for c in chunks)
    assert len(chunks) == 2
    row = chunks[0]
    assert "AVP: 3GPP-IMSI." in row.content
    assert "Code: 1." in row.content
    assert row.content.startswith("DIAMETER > Applications")
    assert "The following AVP types are used:" in row.content
    assert row.metadata["row_key"] == "3GPP-IMSI"
    assert row.metadata["row_index"] == 1
    assert row.metadata["total_rows"] == 2
    # sibling_previews lists the other row keys
    assert "3GPP-Charging-Id" in row.metadata["sibling_previews"]
    # sibling_ids contains chunk_ids of all other rows
    assert len(row.metadata["sibling_ids"]) == row.metadata["total_rows"] - 1
    assert chunks[1].chunk_id in row.metadata["sibling_ids"]
    # all rows share one table_id
    assert chunks[0].metadata["table_id"] == chunks[1].metadata["table_id"]


def test_build_table_chunks_empty_cells_dropped_and_no_data_returns_empty():
    assert build_table_chunks(["| A | B |", "|---|---|"], breadcrumb="", caption="",
                              source_file=Path("d.md"), source_url=None) == []
    chunks = build_table_chunks(
        ["| A | B |", "|---|---|", "| x |  |"],
        breadcrumb="", caption="", source_file=Path("d.md"), source_url=None)
    row = [c for c in chunks if c.chunk_type == "table_row"][0]
    assert "A: x." in row.content
    assert "B:" not in row.content  # empty cell line dropped


def test_build_table_chunks_preview_cap():
    lines = ["| K |", "|---|"] + [f"| k{i} |" for i in range(10)]
    chunks = build_table_chunks(lines, breadcrumb="", caption="",
                                source_file=Path("d.md"), source_url=None)
    row = [c for c in chunks if c.chunk_type == "table_row"][0]
    previews = row.metadata["sibling_previews"]
    assert previews[-1].startswith("... +")
    assert len([p for p in previews if not p.startswith("... +")]) == 5


def _node(text):
    n = Mock(spec=[]); n.text = text; n.node_type = "text"; n.source_url = None; return n


def test_strategy_table_after_list_delegates_and_builds_rows():
    text = "\n".join([
        "## Load classes",
        "",
        "The classes are:",
        "",
        "- delete for teardown",
        "- create for new sessions. The table maps class to tier:",
        "",
        "| Class | Tier |",
        "|-------|------|",
        "| delete | 0 |",
        "| create | 3 |",
    ])
    strat = TableChunkingStrategy()
    assert strat.can_process(_node(text)) is True
    chunks = strat.process(_node(text), Path("d.md"))
    types = [c.chunk_type for c in chunks]
    # List items still produced (delegation), plus table_row chunks only (no overview).
    assert "list_item" in types
    assert types.count("table") == 0
    assert types.count("table_row") == 2
    row = [c for c in chunks if c.chunk_type == "table_row"][0]
    assert row.metadata["breadcrumb_path"] == "Load classes"


def test_strategy_declines_without_table():
    strat = TableChunkingStrategy()
    assert strat.can_process(_node("## Title\n\nJust prose.\n")) is False


def test_strategy_ignores_table_inside_fence():
    text = "## T\n\n```\n| A | B |\n|---|---|\n| 1 | 2 |\n```\n"
    strat = TableChunkingStrategy()
    assert strat.can_process(_node(text)) is False


def test_build_table_chunks_second_line_not_separator_returns_empty():
    # Header, then a NON-separator second line, then data: not a valid table.
    assert build_table_chunks(["| A | B |", "| x | y |", "| 1 | 2 |"],
                              breadcrumb="", caption="",
                              source_file=Path("d.md"), source_url=None) == []


def test_can_process_declines_code_blank_and_missing_text():
    strat = TableChunkingStrategy()
    code = Mock(spec=[]); code.text = "| A |\n|---|\n| 1 |"; code.node_type = "code"; code.source_url = None
    assert strat.can_process(code) is False          # line 157
    assert strat.can_process(_node("   \n  ")) is False   # line 160 (blank text)
    assert strat.can_process(Mock(spec=[])) is False      # no .text attribute


def test_process_pops_same_level_heading_for_breadcrumb():
    text = "\n".join(["## First", "## Second", "lead-in:", "", "| A |", "|---|", "| 1 |"])
    chunks = TableChunkingStrategy().process(_node(text), Path("d.md"))
    row = [c for c in chunks if c.chunk_type == "table_row"][0]
    assert row.metadata["breadcrumb_path"] == "Second"    # First popped at line 255


def test_process_two_tables_blank_between_delegates_empty():
    text = "\n".join(["| A |", "|---|", "| 1 |", "", "| B |", "|---|", "| 2 |"])
    chunks = TableChunkingStrategy().process(_node(text), Path("d.md"))
    # Two separate tables each produce one table_row chunk; no overview chunks.
    assert [c.chunk_type for c in chunks].count("table") == 0
    assert [c.chunk_type for c in chunks].count("table_row") == 2


def test_table_id_differs_for_different_rows_same_header():
    from opencrane.rag.services.table_chunker import build_table_chunks
    a = build_table_chunks(["| K |", "|---|", "| a |"], breadcrumb="H", caption="c",
                           source_file=Path("d.md"), source_url=None)
    b = build_table_chunks(["| K |", "|---|", "| b |"], breadcrumb="H", caption="c",
                           source_file=Path("d.md"), source_url=None)
    assert a[0].metadata["table_id"] != b[0].metadata["table_id"]


def test_caption_strips_leading_list_marker():
    text = "\n".join(["## H", "", "- see the table below:", "", "| A |", "|---|", "| 1 |"])
    chunks = TableChunkingStrategy().process(_node(text), Path("d.md"))
    row = [c for c in chunks if c.chunk_type == "table_row"][0]
    assert row.metadata["table_caption"] == "see the table below:"
    assert "- see the table below:" not in row.content


def test_prose_with_pipe_and_different_cellcount_not_swallowed():
    text = "\n".join(["| A | B |", "|---|---|", "| 1 | 2 |", "Summary: one | two | three."])
    chunks = TableChunkingStrategy().process(_node(text), Path("d.md"))
    rows = [c for c in chunks if c.chunk_type == "table_row"]
    assert all(c.metadata["total_rows"] == 1 for c in rows)
    assert all("Summary" not in c.content for c in rows)


def test_render_row_merges_overflow_cells():
    out = _render_row(["A", "B"], ["x", "y", "z"], "", "")
    assert "z" in out  # overflow cell not dropped


def test_caption_is_empty_when_last_line_before_table_is_heading():
    # When the last non-blank line before the table is a heading, caption must be "".
    text = "\n".join(["## H", "", "| A |", "|---|", "| 1 |"])
    chunks = TableChunkingStrategy().process(_node(text), Path("d.md"))
    row = [c for c in chunks if c.chunk_type == "table_row"][0]
    assert row.metadata.get("table_caption", "") == ""


def test_render_row_no_double_period_when_cell_ends_with_period():
    out = _render_row(["Description"], ["Ends with a period."], "", "")
    assert "period.." not in out
    assert out.endswith("Ends with a period.")
