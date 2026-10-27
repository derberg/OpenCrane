"""Edge cases of content blocks on real-world Markdown."""

from pathlib import Path

import pytest

from opencrane.config import OpenCraneConfig
from opencrane.rag.chunker import _annotate_prose_navigation, _annotate_section_anchors
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.rag.services.file_processor import FileProcessor
from opencrane.rag.services.utils.blocks import BlockSpan, find_blocks
from opencrane.shared.models.chunk import register_metadata_keys

URL_A = "https://github.com/org/repo/blob/main/a.md"
URL_B = "https://github.com/org/repo/blob/main/b.md"


@pytest.fixture(autouse=True)
def _reset_registry():
    yield
    register_metadata_keys({})


def _process(tmp_path, text, config=None):
    f = tmp_path / "llms-full.txt"
    f.write_text(text, encoding="utf-8")
    chunks = FileProcessor(config).process_file(f)
    cfg = config or OpenCraneConfig()
    _annotate_section_anchors(chunks, cfg)
    _annotate_prose_navigation(chunks, cfg)
    return chunks


# --- C1: depth counting and page boundaries -----------------------------------

def test_inline_mentions_do_not_change_depth():
    lines = [
        "<details>",
        "Wrap long output in a `<details>` element.",
        "Or write <details> in the middle of a sentence.",
        "</details>",
        "after",
    ]
    assert find_blocks(lines, ["details"]) == [BlockSpan(0, 3, "details")]


def test_closing_tag_in_inline_code_does_not_close():
    lines = ["<details>", "Close it with `</details>` at the end.", "more", "</details>"]
    assert find_blocks(lines, ["details"]) == [BlockSpan(0, 3, "details")]


def test_boundary_ends_an_unclosed_block():
    lines = ["<details>", "open", "", "### marker", "next page"]
    assert find_blocks(lines, ["details"], boundaries={3}) == [BlockSpan(0, 2, "details")]


def test_unclosed_block_does_not_swallow_the_next_page(tmp_path):
    text = (
        f"### {URL_A}\n\n# Page A\n\n<details>\n<summary>Tips</summary>\n\nNever closed tips text.\n\n"
        f"### {URL_B}\n\n# Page B\n\nPage B body text that stands alone.\n"
    )
    chunks = _process(tmp_path, text)
    page_b = [c for c in chunks if "Page B body" in c.content]
    assert page_b[0].metadata["source_url"] == URL_B
    assert "details_summary" not in page_b[0].metadata


# --- M3: <details> inside a list item ------------------------------------------

def test_indented_details_in_list_item_keeps_the_list_whole(tmp_path):
    text = (
        f"### {URL_A}\n\n## Steps\n\nFollow these steps.\n\n"
        "1. Step one\n   <details>\n   <summary>More</summary>\n\n   hidden detail\n   </details>\n"
        "2. Step two\n"
    )
    items = [c for c in _process(tmp_path, text) if c.chunk_type == "list_item"]
    assert len(items) == 2
    assert len({c.metadata["list_id"] for c in items}) == 1


# --- I1 and I2: heading right above a block ------------------------------------

_FAQ = (
    f"### {URL_A}\n\n## FAQ\n\n"
    "<details>\n<summary>How do I install it?</summary>\n\nRun the installer from the release page.\n\n</details>\n\n"
    "Text after the FAQ blocks goes here.\n"
)


def test_heading_above_block_stays_in_navigation(tmp_path):
    chunks = _process(tmp_path, _FAQ)
    block = [c for c in chunks if "Run the installer" in c.content][0]
    after = [c for c in chunks if "Text after the FAQ" in c.content][0]
    assert block.metadata["heading_path"] == "FAQ > How do I install it?"
    assert after.metadata["heading_path"] == "FAQ"


def test_block_chunk_anchors_to_heading_above_block(tmp_path):
    chunks = _process(tmp_path, _FAQ)
    block = [c for c in chunks if "Run the installer" in c.content][0]
    assert block.metadata["section_anchor"] == "faq"


# --- I3: real <summary> markup -------------------------------------------------

def _summary_chunk(tmp_path, block):
    chunks = _process(tmp_path, f"### {URL_A}\n\n{block}\n")
    return [c for c in chunks if "Body text of the block" in c.content][0]


def test_summary_with_markdown_heading(tmp_path):
    chunk = _summary_chunk(tmp_path, "<details>\n<summary>\n\n### Big title\n\n</summary>\n\nBody text of the block.\n\n</details>")
    assert chunk.metadata["details_summary"] == "Big title"
    assert chunk.content.startswith("## Big title\n")


def test_summary_with_html_over_two_lines(tmp_path):
    chunk = _summary_chunk(tmp_path, "<details>\n<summary><b>Click</b> to\nexpand</summary>\n\nBody text of the block.\n\n</details>")
    assert chunk.metadata["details_summary"] == "Click to expand"
    assert chunk.content.startswith("## Click to expand\n")


def test_outer_block_without_summary_does_not_take_inner_summary(tmp_path):
    block = (
        "<details>\n\nBody text of the block outside.\n\n"
        "<details>\n<summary>Inner</summary>\n\nInner text of the nested block.\n\n</details>\n\n</details>"
    )
    chunks = _process(tmp_path, f"### {URL_A}\n\n{block}\n")
    outer = [c for c in chunks if "outside" in c.content][0]
    inner = [c for c in chunks if "Inner text" in c.content][0]
    assert "details_summary" not in outer.metadata
    assert inner.metadata["details_summary"] == "Inner"


# --- I4: headings do not leak between parts of one block ------------------------

class Twin(ProcessingStrategy):
    """Chunks the two halves of its block separately, split at <split/>."""

    block_tags = ("Twin",)

    def can_process(self, node) -> bool:
        return False

    def process(self, node, source_file: Path):
        body = "\n".join(node.text.split("\n")[1:-1])
        chunks = []
        for part in body.split("<split/>"):
            chunks.extend(self.chunk_text(part, node, source_file))
        return chunks


class TwinConfig(OpenCraneConfig):
    chunking_strategies = [Twin(), *OpenCraneConfig.chunking_strategies]


def test_headings_do_not_leak_between_parts(tmp_path):
    text = (
        f"### {URL_A}\n\n## Install\n\nInstall text for the section.\n\n"
        "<Twin>\n### First part\n\nFirst part text goes here.\n<split/>\nSecond part text has no heading.\n</Twin>\n"
    )
    chunks = _process(tmp_path, text, TwinConfig())
    second = [c for c in chunks if "Second part text" in c.content][0]
    assert second.metadata["heading_path"] == "Install"


def test_heading_only_start_of_a_part_does_not_leak_after_block(tmp_path):
    text = (
        f"### {URL_A}\n\n## Install\n\nInstall text for the section.\n\n"
        "<Twin>\n### First part\n\n- step one\n- step two\n<split/>\n### Second part\n\n- step three\n</Twin>\n\n"
        "Text after the block belongs to Install.\n"
    )
    chunks = _process(tmp_path, text, TwinConfig())
    after = [c for c in chunks if "Text after the block" in c.content][0]
    assert after.metadata["heading_path"] == "Install"


def test_boundary_does_not_cut_a_block_that_closes():
    lines = ["<details>", "#### https://github.com/o/r/blob/main/a.md CLI", "text", "</details>", "after"]
    assert find_blocks(lines, ["details"], boundaries={1}) == [BlockSpan(0, 3, "details")]


# --- review round 3 -------------------------------------------------------------

def test_heading_between_two_blocks_stays_for_the_rest_of_the_page(tmp_path):
    text = (
        f"### {URL_A}\n\n## A\n\nProse of section A.\n\n"
        "<details><summary>Q1</summary>\n\nAnswer one text here.\n\n</details>\n\n"
        "## X\n\n"
        "<details><summary>Q2</summary>\n\nAnswer two text here.\n\n</details>\n\n"
        "More text under X after Q2.\n\n### Y\n\nUnder Y text goes here.\n"
    )
    chunks = _process(tmp_path, text)
    more = [c for c in chunks if "More text under X" in c.content][0]
    under_y = [c for c in chunks if "Under Y text" in c.content][0]
    assert more.metadata["heading_path"] == "X"
    assert under_y.metadata["heading_path"] == "X > Y"


def test_heading_above_block_that_starts_with_code_is_kept(tmp_path):
    text = (
        f"### {URL_A}\n\n## A\n\nProse of section A.\n\n## X\n\n"
        "<details><summary>Example</summary>\n\n```bash\nrun it\n```\n\nExplanation text of the example.\n\n</details>\n\n"
        "Text after the block goes here.\n"
    )
    chunks = _process(tmp_path, text)
    explanation = [c for c in chunks if "Explanation text" in c.content][0]
    after = [c for c in chunks if "Text after the block" in c.content][0]
    assert explanation.metadata["heading_path"] == "X > Example"
    assert after.metadata["heading_path"] == "X"


def test_indented_nested_details_is_chunked_with_its_summary(tmp_path):
    block = (
        "<details>\n  <summary>Linux</summary>\n\n  Run it on any Linux host.\n\n"
        "  <details>\n  <summary>Debian</summary>\n\n  Install the package with apt.\n\n  </details>\n</details>"
    )
    chunks = _process(tmp_path, f"### {URL_A}\n\n{block}\n")
    inner = [c for c in chunks if "Install the package with apt." in c.content][0]
    assert inner.metadata["details_summary"] == "Debian"
    assert "<summary>" not in inner.content


class Duck:
    """A strategy that does not subclass ProcessingStrategy."""

    def can_process(self, node) -> bool:
        return "DUCK" in getattr(node, "text", "")

    def process(self, node, source_file):
        return []


def test_strategy_without_processing_strategy_base_still_works(tmp_path):
    class DuckConfig(OpenCraneConfig):
        chunking_strategies = [Duck(), *OpenCraneConfig.chunking_strategies]

    chunks = _process(tmp_path, f"### {URL_A}\n\n## A\n\nDUCK text that falls through to prose.\n", DuckConfig())
    assert any("DUCK text" in c.content for c in chunks)
