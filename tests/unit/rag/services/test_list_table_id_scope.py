"""list_id / table_id must be unique per page, not just per breadcrumb.

Regression tests for a collision where lists (or tables) under the same
breadcrumb on different pages, for example every list directly after a code
block (empty breadcrumb), shared one id, so ``get_list_members`` /
``get_table_members`` merged them.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from opencrane.rag.services.file_processor import FileProcessor
from opencrane.rag.services.list_chunker import ListChunkingStrategy
from opencrane.rag.services.llms_index import LlmsIndex
from opencrane.rag.services.table_chunker import build_table_chunks
from opencrane.rag.services.utils.chunk_id_generator import reset_collision_tracking


def _mk_node(text: str, source_url=None):
    node = Mock(spec=[])
    node.text = text
    node.node_type = "text"
    node.source_url = source_url
    return node


def _list_ids(chunks):
    return {c.metadata["list_id"] for c in chunks if c.chunk_type == "list_item"}


@pytest.mark.unit
def test_same_list_on_two_pages_gets_distinct_list_ids():
    reset_collision_tracking()
    strategy = ListChunkingStrategy()
    text = "- first\n- second\n"
    a = strategy.process(_mk_node(text, "https://x/a"), Path("llms-full.txt"))
    b = strategy.process(_mk_node(text, "https://x/b"), Path("llms-full.txt"))
    assert len(_list_ids(a)) == 1
    assert len(_list_ids(b)) == 1
    assert _list_ids(a) != _list_ids(b)


@pytest.mark.unit
def test_different_lists_same_page_empty_breadcrumb_get_distinct_list_ids():
    """Two lists on one page, each in its own node (e.g. after a code block)."""
    reset_collision_tracking()
    strategy = ListChunkingStrategy()
    a = strategy.process(_mk_node("- one\n- two\n", "https://x/p"), Path("llms-full.txt"))
    b = strategy.process(_mk_node("- three\n- four\n", "https://x/p"), Path("llms-full.txt"))
    assert _list_ids(a) != _list_ids(b)


@pytest.mark.unit
def test_list_id_is_stable_across_runs():
    text = "## Setup\n\n- one\n  - nested\n- two\n"
    reset_collision_tracking()
    first = ListChunkingStrategy().process(_mk_node(text, "https://x/p"), Path("llms-full.txt"))
    reset_collision_tracking()
    second = ListChunkingStrategy().process(_mk_node(text, "https://x/p"), Path("llms-full.txt"))
    ids = [c.metadata["list_id"] for c in first if c.chunk_type == "list_item"]
    assert ids and ids == [c.metadata["list_id"] for c in second if c.chunk_type == "list_item"]


@pytest.mark.unit
def test_same_table_on_two_pages_gets_distinct_table_ids():
    lines = ["| Name | Value |", "|---|---|", "| port | 80 |"]
    a = build_table_chunks(lines, breadcrumb="", caption="", source_file=Path("f"), source_url="https://x/a")
    b = build_table_chunks(lines, breadcrumb="", caption="", source_file=Path("f"), source_url="https://x/b")
    assert a[0].metadata["table_id"] != b[0].metadata["table_id"]


@pytest.mark.unit
def test_tables_differing_outside_first_column_get_distinct_table_ids():
    a = build_table_chunks(["| K | V |", "|---|---|", "| port | 80 |"], breadcrumb="", caption="",
                           source_file=Path("f"), source_url="https://x/p")
    b = build_table_chunks(["| K | V |", "|---|---|", "| port | 443 |"], breadcrumb="", caption="",
                           source_file=Path("f"), source_url="https://x/p")
    assert a[0].metadata["table_id"] != b[0].metadata["table_id"]


@pytest.mark.unit
def test_pipeline_lists_after_code_blocks_do_not_share_list_id(tmp_path):
    """End to end through FileProcessor with an llms.txt index."""
    full = (
        "# Alpha\n\nIntro alpha.\n\n```bash\necho a\n```\n\n- alpha one\n- alpha two\n\n"
        "<!-- opencrane:page -->\n\n"
        "# Beta\n\nIntro beta.\n\n```bash\necho b\n```\n\n- beta one\n- beta two\n\n"
        "```bash\necho c\n```\n\n- beta three\n- beta four\n\n"
        "```bash\necho d\n```\n\n| Name | Value |\n|---|---|\n| port | 80 |\n\n"
        "<!-- opencrane:page -->\n\n"
        "# Gamma\n\n```bash\necho g\n```\n\n| Name | Value |\n|---|---|\n| port | 80 |\n"
    )
    idx = LlmsIndex.parse(
        "# D\n## p\n- [Alpha](https://x/alpha)\n- [Beta](https://x/beta)\n- [Gamma](https://x/gamma)\n"
    )
    f = tmp_path / "llms-full.txt"
    f.write_text(full)
    chunks = FileProcessor().process_file(f, index=idx)

    by_item = {
        c.content.splitlines()[-1]: c.metadata["list_id"]
        for c in chunks if c.chunk_type == "list_item"
    }
    # Members of one list still share an id.
    assert by_item["alpha one"] == by_item["alpha two"]
    assert by_item["beta one"] == by_item["beta two"]
    assert by_item["beta three"] == by_item["beta four"]
    # Distinct lists never do, across pages or within one.
    assert len({by_item["alpha one"], by_item["beta one"], by_item["beta three"]}) == 3

    table_ids = {
        c.metadata["source_url"]: c.metadata["table_id"]
        for c in chunks if c.chunk_type == "table_row"
    }
    assert set(table_ids) == {"https://x/beta", "https://x/gamma"}
    assert table_ids["https://x/beta"] != table_ids["https://x/gamma"]
