"""Breadcrumbs survive the page split at code fences.

The file processor splits a page at each fenced code block before the
strategies run. Regression tests for two bugs in that split:

- Lists and tables after a code block lost the headings above the code block,
  so their ``breadcrumb_path`` was empty (or held only the headings after it).
- A code block inside a list item (an indented fence) split the list, so the
  items after it became a separate list with an empty breadcrumb.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from opencrane.rag.services.code_chunker import CodeChunkingStrategy
from opencrane.rag.services.file_processor import FileProcessor
from opencrane.rag.services.llms_index import LlmsIndex
from opencrane.rag.services.table_chunker import TableChunkingStrategy
from opencrane.rag.services.utils.markdown_structure import (
    HeadingTracker,
    has_fence_outside_list_items,
    list_item_fence_mask,
    update_heading_stack,
)

INDEX = "# D\n## p\n- [Guide](https://x/guide)\n- [Other](https://x/other)\n"


def _chunk_with_index(tmp_path, full: str):
    f = tmp_path / "llms-full.txt"
    f.write_text(full)
    return FileProcessor().process_file(f, index=LlmsIndex.parse(INDEX))


def _chunk_legacy(tmp_path, full: str):
    f = tmp_path / "llms-full.txt"
    f.write_text(full)
    return FileProcessor().process_file(f)


def _of_type(chunks, chunk_type):
    return [c for c in chunks if c.chunk_type == chunk_type]


LIST_AFTER_CODE = (
    "# Guide\n\n## Setup\n\nRun this:\n\n```bash\necho hi\n```\n\n- one\n- two\n"
)
TABLE_AFTER_CODE = (
    "# Guide\n\n## Config\n\nExample:\n\n```bash\necho hi\n```\n\n"
    "| Name | Value |\n|---|---|\n| port | 80 |\n"
)
CODE_IN_LIST_ITEM = (
    "# Guide\n\n## Install\n\n"
    "1. Install the CLI:\n\n   ```bash\n   pip install opencrane\n   ```\n\n"
    "2. Initialize the project:\n\n   ```bash\n   opencrane init\n   ```\n"
)


@pytest.mark.unit
class TestListAfterCodeBlock:
    def test_list_keeps_headings_above_code_block(self, tmp_path):
        items = _of_type(_chunk_with_index(tmp_path, LIST_AFTER_CODE), "list_item")
        assert [c.metadata["breadcrumb_path"] for c in items] == ["Guide > Setup"] * 2
        assert all(c.content.startswith("# Guide > Setup\n") for c in items)
        assert all(c.metadata["source_url"] == "https://x/guide" for c in items)

    def test_legacy_marker_path_keeps_headings(self, tmp_path):
        full = "# [https://x] https://x/guide Guide\n" + LIST_AFTER_CODE.split("\n", 1)[1]
        items = _of_type(_chunk_legacy(tmp_path, full), "list_item")
        assert [c.metadata["breadcrumb_path"] for c in items] == ["Guide > Setup"] * 2
        assert all(c.metadata["source_url"] == "https://x/guide" for c in items)

    def test_heading_after_code_block_replaces_sibling(self, tmp_path):
        full = (
            "# Guide\n\n## A\n\n### B\n\nText.\n\n```bash\necho hi\n```\n\n"
            "- under b\n\n## C\n\nMore text.\n\n- under c\n"
        )
        items = _of_type(_chunk_with_index(tmp_path, full), "list_item")
        crumbs = {c.content.splitlines()[-1]: c.metadata["breadcrumb_path"] for c in items}
        assert crumbs == {"under b": "Guide > A > B", "under c": "Guide > C"}

    def test_ancestry_restarts_on_each_page(self, tmp_path):
        full = (
            "# Guide\n\n## Setup\n\nText.\n\n"
            "<!-- opencrane:page -->\n\n"
            "# Other\n\nIntro.\n\n```bash\necho hi\n```\n\n- item\n"
        )
        items = _of_type(_chunk_with_index(tmp_path, full), "list_item")
        assert [c.metadata["breadcrumb_path"] for c in items] == ["Other"]
        assert items[0].metadata["source_url"] == "https://x/other"

    def test_legacy_ancestry_restarts_on_new_page_url(self, tmp_path):
        full = (
            "# [https://x] https://x/guide Guide\n\n## Setup\n\nText.\n\n"
            "# [https://x] https://x/other Other\n\nIntro.\n\n"
            "```bash\necho hi\n```\n\n- item\n"
        )
        items = _of_type(_chunk_legacy(tmp_path, full), "list_item")
        assert [c.metadata["breadcrumb_path"] for c in items] == ["Other"]
        assert items[0].metadata["source_url"] == "https://x/other"

    def test_legacy_yaml_extraction_keeps_ancestry(self, tmp_path):
        full = (
            "# [https://x] https://x/guide Guide\n\n## Deploy\n\nText.\n\n"
            "```bash\necho hi\n```\n\n"
            "Apply it:\n\n```yaml\nkind: Thing\nname: demo\n```\n\n- check it\n"
        )
        items = _of_type(_chunk_legacy(tmp_path, full), "list_item")
        assert [c.metadata["breadcrumb_path"] for c in items] == ["Guide > Deploy"]


@pytest.mark.unit
class TestTableAfterCodeBlock:
    def test_table_keeps_headings_above_code_block(self, tmp_path):
        rows = _of_type(_chunk_with_index(tmp_path, TABLE_AFTER_CODE), "table_row")
        assert [r.metadata["breadcrumb_path"] for r in rows] == ["Guide > Config"]
        assert rows[0].content.startswith("# Guide > Config\n")
        assert rows[0].metadata["source_url"] == "https://x/guide"

    def test_legacy_marker_path_keeps_full_ancestry(self, tmp_path):
        full = "# [https://x] https://x/guide Guide\n" + TABLE_AFTER_CODE.split("\n", 1)[1]
        rows = _of_type(_chunk_legacy(tmp_path, full), "table_row")
        assert [r.metadata["breadcrumb_path"] for r in rows] == ["Guide > Config"]

    def test_strategy_reads_heading_ancestry(self):
        node = SimpleNamespace(
            text="| Name | Value |\n|---|---|\n| port | 80 |\n",
            node_type="text",
            source_url="https://x/guide",
            heading_ancestry=[(1, "Guide"), (2, "Config")],
        )
        rows = TableChunkingStrategy().process(node, Path("llms-full.txt"))
        assert rows[0].metadata["breadcrumb_path"] == "Guide > Config"


@pytest.mark.unit
class TestCodeBlockInListItem:
    def test_list_stays_one_list_with_code_in_items(self, tmp_path):
        chunks = _chunk_with_index(tmp_path, CODE_IN_LIST_ITEM)
        items = _of_type(chunks, "list_item")
        assert len(items) == 2
        assert len({c.metadata["list_id"] for c in items}) == 1
        assert [c.metadata["position"] for c in items] == [1, 2]
        assert [c.metadata["breadcrumb_path"] for c in items] == ["Guide > Install"] * 2
        assert "pip install opencrane" in items[0].content
        assert "opencrane init" in items[1].content
        assert not _of_type(chunks, "code_snippet")
        assert all(c.metadata["source_url"] == "https://x/guide" for c in items)

    def test_legacy_marker_path_keeps_one_list(self, tmp_path):
        full = "# [https://x] https://x/guide Guide\n" + CODE_IN_LIST_ITEM.split("\n", 1)[1]
        chunks = _chunk_legacy(tmp_path, full)
        items = _of_type(chunks, "list_item")
        assert len({c.metadata["list_id"] for c in items}) == 1
        assert [c.metadata["breadcrumb_path"] for c in items] == ["Guide > Install"] * 2
        assert not _of_type(chunks, "code_snippet")

    def test_legacy_heading_like_lines_in_item_code_are_not_headings(self, tmp_path):
        full = (
            "# [https://x] https://x/guide Guide\n\n## Install\n\n"
            "1. Configure:\n\n   ```bash\n   ### https://github.com/o/r/blob/main/x.md\n"
            "   # a comment\n   ```\n\n2. Run it.\n\n"
            "```bash\necho top\n```\n\n| Name | Value |\n|---|---|\n| port | 80 |\n"
        )
        chunks = _chunk_legacy(tmp_path, full)
        assert {c.metadata["source_url"] for c in chunks} == {"https://x/guide"}
        rows = _of_type(chunks, "table_row")
        assert [r.metadata["breadcrumb_path"] for r in rows] == ["Guide > Install"]

    def test_top_level_code_block_still_splits(self, tmp_path):
        full = CODE_IN_LIST_ITEM + "\nThen:\n\n```bash\necho top\n```\n\n- after\n"
        chunks = _chunk_with_index(tmp_path, full)
        assert [c.content for c in _of_type(chunks, "code_snippet")] == [
            "# Guide > Install\nThen:\n\n```bash\necho top\n```"
        ]
        after = [c for c in _of_type(chunks, "list_item") if c.content.endswith("after")]
        assert after[0].metadata["breadcrumb_path"] == "Guide > Install"

    def test_code_strategy_leaves_list_item_code_to_list_strategy(self):
        strategy = CodeChunkingStrategy()
        node = SimpleNamespace(text=CODE_IN_LIST_ITEM, node_type="text")
        assert strategy.can_process(node) is False
        node.text = "```bash\necho hi\n```\n"
        assert strategy.can_process(node) is True


@pytest.mark.unit
class TestMarkdownStructureHelpers:
    def test_list_item_fence_mask(self):
        lines = [
            "- item",
            "",
            "  ```",
            "  code",
            "  ```",
            "",
            "Paragraph ends the list.",
            "",
            "  ```",
            "  indented code outside a list",
            "  ```",
            "```",
            "top",
            "```",
        ]
        assert list_item_fence_mask(lines) == [False, False, True, True, True] + [False] * 9

    def test_top_level_fence_closes_list(self):
        lines = ["- item", "```", "x", "```", "  ```", "y", "  ```"]
        assert list_item_fence_mask(lines) == [False] * 7

    def test_has_fence_outside_list_items(self):
        assert has_fence_outside_list_items("- a\n\n  ```\n  x\n  ```\n") is False
        assert has_fence_outside_list_items("- a\n\n```\nx\n```\n") is True

    def test_update_heading_stack_skips_fenced_lines(self):
        stack = [(1, "Guide")]
        update_heading_stack(stack, "## A\n\n```bash\n# comment\n```\n\n### B\n\n## C\n")
        assert stack == [(1, "Guide"), (2, "C")]


@pytest.mark.unit
class TestNestedFences:
    """A ```` fence that shows ``` fences inside it is one fence."""

    NESTED = (
        "# Guide\n\n## A\n\n````md\n```yaml\n## not a heading\n```\n````\n\n- item\n"
    )

    def test_heading_like_line_in_nested_fence_is_not_ancestry(self, tmp_path):
        items = _of_type(_chunk_with_index(tmp_path, self.NESTED), "list_item")
        assert [c.metadata["breadcrumb_path"] for c in items] == ["Guide > A"]

    def test_legacy_heading_like_line_in_nested_fence_is_not_ancestry(self, tmp_path):
        full = "# [https://x] https://x/guide Guide\n" + self.NESTED.split("\n", 1)[1]
        items = _of_type(_chunk_legacy(tmp_path, full), "list_item")
        assert [c.metadata["breadcrumb_path"] for c in items] == ["Guide > A"]

    def test_list_inside_nested_fence_is_not_a_list_item_fence(self):
        lines = ["````md", "1. Step:", "", "   ```bash", "   x", "   ```", "````"]
        assert list_item_fence_mask(lines) == [False] * 7

    def test_nested_fence_in_list_item_is_masked_to_its_end(self):
        lines = ["- item", "", "  ````md", "  ```bash", "  x", "  ```", "  ````", "after"]
        assert list_item_fence_mask(lines) == [False, False] + [True] * 5 + [False]

    def test_tracker_carries_fence_state_across_parts(self):
        tracker = HeadingTracker([(1, "Guide")])
        for part in ["````md\n```yaml", "# not a heading", "```\n````", "## B"]:
            tracker.feed(part)
        assert tracker.stack == [(1, "Guide"), (2, "B")]
