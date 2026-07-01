from pathlib import Path
from unittest.mock import Mock
from opencrane.rag.services.table_chunker import build_table_chunks, _is_table_separator, TableChunkingStrategy


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
    assert [c.chunk_type for c in chunks] == ["table", "table_row", "table_row"]
    overview = chunks[0]
    assert overview.metadata["columns"] == ["AVP", "Code", "Type"]
    assert overview.metadata["total_rows"] == 2
    row = chunks[1]
    assert "AVP: 3GPP-IMSI." in row.content
    assert "Code: 1." in row.content
    assert row.content.startswith("DIAMETER > Applications")
    assert "The following AVP types are used:" in row.content
    assert row.metadata["row_key"] == "3GPP-IMSI"
    assert row.metadata["row_index"] == 1
    assert row.metadata["total_rows"] == 2
    # sibling_previews lists the other row keys
    assert "3GPP-Charging-Id" in row.metadata["sibling_previews"]
    # all rows share one table_id
    assert chunks[1].metadata["table_id"] == chunks[2].metadata["table_id"] == overview.metadata["table_id"]


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
    # List items still produced (delegation), plus table + table_row chunks.
    assert "list_item" in types
    assert types.count("table") == 1
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


def test_build_table_chunks_overview_ellipsis_past_eight_rows():
    lines = ["| K |", "|---|"] + [f"| k{i} |" for i in range(9)]  # 9 data rows
    chunks = build_table_chunks(lines, breadcrumb="", caption="",
                                source_file=Path("d.md"), source_url=None)
    overview = [c for c in chunks if c.chunk_type == "table"][0]
    assert overview.metadata["total_rows"] == 9
    assert overview.content.rstrip().endswith(", ...")


def test_build_table_chunks_second_line_not_separator_returns_empty():
    # Header, then a NON-separator second line, then data: not a valid table.
    assert build_table_chunks(["| A | B |", "| x | y |", "| 1 | 2 |"],
                              breadcrumb="", caption="",
                              source_file=Path("d.md"), source_url=None) == []
