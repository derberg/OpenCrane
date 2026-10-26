"""Tests for keeping declared content blocks whole when a page is split."""

from pathlib import Path

import pytest

from opencrane.config import OpenCraneConfig
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.rag.services.file_processor import FileProcessor
from opencrane.rag.services.llms_index import LlmsIndex
from opencrane.shared.models.chunk import register_metadata_keys

URL = "https://github.com/org/repo/blob/main/a.md"


class DetailsOwner(ProcessingStrategy):
    block_tags = ("details",)

    def can_process(self, node) -> bool:
        return False

    def process(self, node, source_file: Path):
        return []  # pragma: no cover - never chosen


class Config(OpenCraneConfig):
    chunking_strategies = [DetailsOwner(), *OpenCraneConfig.chunking_strategies]


@pytest.fixture(autouse=True)
def _reset_registry():
    yield
    register_metadata_keys({})


def _items(tmp_path, content, config=None, index=None):
    f = tmp_path / "llms-full.txt"
    f.write_text(content, encoding="utf-8")
    processor = FileProcessor(config or Config())
    return list(processor._create_fallback_document(f, index).iterate_items())


_BLOCK = "<details>\n<summary>More</summary>\n\nInside text.\n\n```bash\nrun it\n```\n\n</details>"


def test_block_is_one_item_with_tag(tmp_path):
    content = f"### {URL}\n\n# Page\n\nBefore text.\n\n{_BLOCK}\n\nAfter text.\n"
    items = _items(tmp_path, content)
    assert [i.text for i in items] == ["# Page\n\nBefore text.", _BLOCK, "After text."]
    assert [i.block_tag for i in items] == [None, "details", None]
    assert all(i.source_url == URL for i in items)


def test_block_kept_whole_with_index(tmp_path):
    idx = LlmsIndex.parse("# D\n## proj\n- [Home](https://x/home)\n")
    items = _items(tmp_path, f"# Home\n\nBefore text.\n\n{_BLOCK}\n\nAfter text.\n", index=idx)
    assert [i.block_tag for i in items] == [None, "details", None]
    assert items[1].text == _BLOCK
    assert items[1].source_url == "https://x/home"


def test_unclosed_block_stops_at_page_end(tmp_path):
    idx = LlmsIndex.parse("# D\n## proj\n- [One](https://x/one)\n- [Two](https://x/two)\n")
    content = "# One\n\nText.\n\n<details>\nopen forever\n\n# Two\n\nSecond page text.\n"
    items = _items(tmp_path, content, index=idx)
    block = [i for i in items if i.block_tag == "details"]
    assert len(block) == 1
    assert "# Two" not in block[0].text
    assert any(i.source_url == "https://x/two" and "Second page" in i.text for i in items)


def test_small_file_with_block_is_split(tmp_path):
    items = _items(tmp_path, f"# Page\n\nBefore text.\n\n{_BLOCK}\n")
    assert [i.block_tag for i in items] == [None, "details"]


def test_small_file_without_block_stays_one_item(tmp_path):
    items = _items(tmp_path, "# Page\n\nOnly text.\n")
    assert len(items) == 1 and items[0].block_tag is None


def test_yaml_inside_block_not_extracted(tmp_path):
    block = "<details>\n\n```yaml\nkey: value\nother: 1\n```\n\n</details>"
    items = _items(tmp_path, f"### {URL}\n\n# Page\n\nText.\n\n{block}\n")
    assert [i.block_tag for i in items] == [None, "details"]
    assert items[1].text == block


def test_headings_inside_block_do_not_leak(tmp_path):
    content = f"### {URL}\n\n## A\n\nText A.\n\n<details>\n\n### Inner\n\nInner text.\n\n</details>\n\nAfter text.\n"
    items = _items(tmp_path, content)
    assert items[1].block_tag == "details"
    assert items[1].heading_ancestry == [(2, "A")]
    assert items[2].heading_ancestry == [(2, "A")]


def test_tabs_not_special_without_strategy(tmp_path):
    content = f"### {URL}\n\n# Page\n\n<Tabs>\n<Tab>\n\n```bash\nrun it\n```\n\n</Tab>\n</Tabs>\n"
    items = _items(tmp_path, content, config=OpenCraneConfig())
    assert all(i.block_tag is None for i in items)
    assert any(i.text.startswith("```bash") for i in items)
