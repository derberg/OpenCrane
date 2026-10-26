"""Tests for the built-in <details> chunking strategy."""

import pytest

from opencrane.config import OpenCraneConfig
from opencrane.rag.services.details_chunker import DetailsChunkingStrategy
from opencrane.rag.services.file_processor import FileProcessor
from opencrane.shared.models.chunk import declared_metadata_keys, register_metadata_keys

URL = "https://github.com/org/repo/blob/main/a.md"


@pytest.fixture(autouse=True)
def _reset_registry():
    yield
    register_metadata_keys({})


def _chunks(tmp_path, page):
    f = tmp_path / "llms-full.txt"
    f.write_text(f"### {URL}\n\n{page}\n", encoding="utf-8")
    return FileProcessor().process_file(f)


def test_details_is_a_default_strategy():
    assert any(isinstance(s, DetailsChunkingStrategy) for s in OpenCraneConfig.chunking_strategies)
    assert DetailsChunkingStrategy.block_tags == ("details",)


def test_details_body_list_becomes_list_items_with_summary_in_breadcrumb(tmp_path):
    page = (
        "# Page\n\n## Install\n\nInstall the tool first.\n\n"
        "<details>\n<summary>Advanced options</summary>\n\n- first option\n- second option\n\n</details>"
    )
    items = [c for c in _chunks(tmp_path, page) if c.chunk_type == "list_item"]
    assert [c.content.split("\n")[-1] for c in items] == ["first option", "second option"]
    assert all(c.metadata["breadcrumb_path"].endswith("Install > Advanced options") for c in items)
    assert all(c.metadata["details_summary"] == "Advanced options" for c in items)


def test_summary_heading_level_below_context(tmp_path):
    page = (
        "# Page\n\n## Section\n\n### Deep\n\nDeep section text.\n\n"
        "<details>\n<summary>Advanced options</summary>\n\nBody text that explains the options.\n\n</details>"
    )
    prose = [c for c in _chunks(tmp_path, page) if c.metadata.get("details_summary")]
    assert prose[0].content.startswith("#### Advanced options")


def test_summary_level_capped_at_six(tmp_path):
    page = (
        "# Page\n\n###### Six\n\nSix level text.\n\n"
        "<details>\n<summary>Capped</summary>\n\nBody text under the capped summary.\n\n</details>"
    )
    prose = [c for c in _chunks(tmp_path, page) if c.metadata.get("details_summary")]
    assert prose[0].content.startswith("###### Capped")


def test_summary_level_two_without_headings(tmp_path):
    f = tmp_path / "llms-full.txt"
    f.write_text("<details>\n<summary>Top</summary>\n\nBody text without any heading above.\n\n</details>\n")
    prose = [c for c in FileProcessor().process_file(f) if c.metadata.get("details_summary")]
    assert prose[0].content.startswith("## Top")


def test_one_line_details_and_summary(tmp_path):
    page = "# Page\n\n<details><summary>More</summary>\n\nBody text after a one line opening.\n\n</details>"
    prose = [c for c in _chunks(tmp_path, page) if c.metadata.get("details_summary") == "More"]
    assert "Body text after a one line opening." in prose[0].content
    assert "<summary>" not in prose[0].content and "</details>" not in prose[0].content


def test_details_without_summary_has_no_title_metadata(tmp_path):
    page = "# Page\n\nPage text.\n\n<details>\n\nBody text of a details block without a summary.\n\n</details>"
    chunks = _chunks(tmp_path, page)
    body = [c for c in chunks if "without a summary" in c.content]
    assert body and "details_summary" not in body[0].metadata
    assert "<details>" not in body[0].content


def test_empty_details_falls_through(tmp_path):
    page = "# Page\n\nPage text.\n\n<details><summary>Nothing inside here</summary></details>"
    chunks = _chunks(tmp_path, page)
    assert any("Nothing inside here" in c.content for c in chunks)


def test_nested_details_get_their_own_summary(tmp_path):
    page = (
        "# Page\n\n<details>\n<summary>Outer</summary>\n\nOuter body text here.\n\n"
        "<details>\n<summary>Inner</summary>\n\nInner body text here.\n\n</details>\n\n</details>"
    )
    chunks = _chunks(tmp_path, page)
    inner = [c for c in chunks if "Inner body text" in c.content]
    assert inner[0].metadata["details_summary"] == "Inner"


def test_details_summary_listed_in_declared_keys():
    FileProcessor()
    assert "details_summary" in declared_metadata_keys()
