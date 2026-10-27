"""Tests for FileProcessor page-boundary split + llms.txt index join."""

from opencrane.config import OpenCraneConfig
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.rag.services.file_processor import FileProcessor
from opencrane.rag.services.llms_index import LlmsIndex


def test_processor_assigns_page_urls_via_index_single_source(tmp_path):
    full = "# Home\nWelcome home.\n\n-----\n\n# Setup\nInstall steps here now."
    idx = LlmsIndex.parse(
        "# D\n## proj\n- [Home](https://x/home)\n- [Setup](https://x/setup)\n"
    )
    f = tmp_path / "llms-full.txt"
    f.write_text(full)
    chunks = FileProcessor().process_file(f, index=idx)
    urls = {c.metadata.get("source_url") for c in chunks}
    assert "https://x/home" in urls
    assert "https://x/setup" in urls


def test_processor_assigns_page_urls_via_index_multi_source(tmp_path):
    full = (
        "# Home\nWelcome to source A home page.\n\n-----\n\n"
        "# Setup\nSetup docs for source A here.\n"
        "\n\n======\n\n"
        "# Intro\nIntroduction for source B goes here.\n"
    )
    idx = LlmsIndex.parse(
        "# D\n"
        "## src-a\n- [Home](https://a/home)\n- [Setup](https://a/setup)\n"
        "## src-b\n- [Intro](https://b/intro)\n"
    )
    f = tmp_path / "llms-full.txt"
    f.write_text(full)
    chunks = FileProcessor().process_file(f, index=idx)
    urls = {c.metadata.get("source_url") for c in chunks}
    assert "https://a/home" in urls
    assert "https://a/setup" in urls
    assert "https://b/intro" in urls


def test_processor_h1_split_when_no_dashes(tmp_path):
    """External llmstxt blob: pages delimited by H1 lines, no ----- separators."""
    full = (
        "# Home\nWelcome to the home page content here.\n"
        "# Setup\nSetup instructions live on this page.\n"
    )
    idx = LlmsIndex.parse(
        "# D\n## proj\n- [Home](https://x/home)\n- [Setup](https://x/setup)\n"
    )
    f = tmp_path / "llms-full.txt"
    f.write_text(full)
    chunks = FileProcessor().process_file(f, index=idx)
    urls = {c.metadata.get("source_url") for c in chunks}
    assert "https://x/home" in urls
    assert "https://x/setup" in urls


def test_processor_source_count_mismatch_falls_back_to_legacy(tmp_path, caplog):
    """When ====== block count != index.sources() count, fall back to legacy markers."""
    # Two ====== blocks but index has one source → mismatch.
    url = "https://github.com/org/repo/blob/main/a.md"
    full = f"### {url}\n\nLegacy marker content here.\n\n======\n\nSecond block content."
    idx = LlmsIndex.parse("# D\n## only-one\n- [A](https://x/a)\n")
    f = tmp_path / "llms-full.txt"
    f.write_text(full)
    chunks = FileProcessor().process_file(f, index=idx)
    urls = {c.metadata.get("source_url") for c in chunks}
    # Legacy marker path should have been used, so the github marker URL appears.
    assert url in urls


def test_processor_page_title_not_in_index_leaves_url_none(tmp_path):
    full = "# Ghost\nThis page title is not in the index at all.\n"
    idx = LlmsIndex.parse("# D\n## proj\n- [Home](https://x/home)\n")
    f = tmp_path / "llms-full.txt"
    f.write_text(full)
    chunks = FileProcessor().process_file(f, index=idx)
    urls = {c.metadata.get("source_url") for c in chunks}
    assert urls == {None} or None in urls
    assert "https://x/home" not in urls


def test_processor_index_preserves_code_and_yaml_subsplit(tmp_path):
    """Code fences and YAML inside a page still dispatch to their strategies,
    each carrying the page URL from the index."""
    full = (
        "# Home\nIntro prose paragraph for the home page.\n\n"
        "```yaml\napiVersion: v1\nkind: ConfigMap\n```\n\n"
        "More prose after the yaml block content.\n"
    )
    idx = LlmsIndex.parse("# D\n## proj\n- [Home](https://x/home)\n")
    f = tmp_path / "llms-full.txt"
    f.write_text(full)
    chunks = FileProcessor().process_file(f, index=idx)
    # Every chunk that has a source_url should be the page URL.
    urls = {c.metadata.get("source_url") for c in chunks if c.metadata.get("source_url")}
    assert urls == {"https://x/home"}
    # The YAML block was extracted and dispatched to the YAML strategy.
    assert any("yaml" in c.chunk_type for c in chunks)


def test_processor_index_keeps_declared_block_intact(tmp_path):
    """A declared block inside a page is emitted as one sub-section and
    carries the page URL from the index."""
    full = (
        "# Home\nIntro prose for the home page here.\n\n"
        "<Panel>\n"
        "  First panel body content goes here now.\n"
        "  Second panel body content goes here now.\n"
        "</Panel>\n\n"
        "More prose after the panel block content.\n"
    )
    idx = LlmsIndex.parse("# D\n## proj\n- [Home](https://x/home)\n")
    f = tmp_path / "llms-full.txt"
    f.write_text(full)
    chunks = FileProcessor(_PanelConfig()).process_file(f, index=idx)
    urls = {c.metadata.get("source_url") for c in chunks if c.metadata.get("source_url")}
    assert urls == {"https://x/home"}
    assert any("<Panel>" in c.content and "</Panel>" in c.content for c in chunks)


def test_processor_h1_split_ignores_fenced_hash_comments(tmp_path):
    """Fenced code block containing '# comment' must NOT be treated as a page boundary.

    A single-source blob (no -----) with two real H1 pages where the first
    page body contains a fenced code block with a shell comment line that
    matches ^#\\s+.  That fenced line must NOT create a third page, and both
    real pages must receive their correct index URLs (no alignment drift).
    """
    full = (
        "# Installation\n"
        "Install the package as shown below:\n\n"
        "```bash\n"
        "# not a real heading\n"
        "pip install mypackage\n"
        "```\n\n"
        "Now you are ready to use it.\n"
        "# Usage\n"
        "Use the package like this.\n"
    )
    idx = LlmsIndex.parse(
        "# D\n## proj\n"
        "- [Installation](https://x/install)\n"
        "- [Usage](https://x/usage)\n"
    )
    f = tmp_path / "llms-full.txt"
    f.write_text(full)
    chunks = FileProcessor().process_file(f, index=idx)
    all_urls = {c.metadata.get("source_url") for c in chunks}
    # Both real pages get their correct URLs — no drift.
    assert "https://x/install" in all_urls
    assert "https://x/usage" in all_urls
    # The fenced '# not a real heading' must NOT create a spurious third page,
    # so every chunk must carry a real URL (None would indicate a drifted/
    # unmatched page caused by the false boundary).
    assert None not in all_urls


def test_processor_leaves_source_url_a_clean_page_link(tmp_path):
    """FileProcessor assigns plain page URLs; section anchors are added later by
    the chunker, so no source_url carries a #fragment here."""
    full = "# Home\n## Getting Started\nHere is how you get started with it.\n"
    idx = LlmsIndex.parse("# D\n## proj\n- [Home](https://x/home)\n")
    f = tmp_path / "llms-full.txt"
    f.write_text(full)
    chunks = FileProcessor().process_file(f, index=idx)
    urls = {c.metadata.get("source_url") for c in chunks if c.metadata.get("source_url")}
    assert urls == {"https://x/home"}


_BLOCK_PAGE = (
    "# Home\n\n"
    "BEFORE_TABS prose paragraph explains the install.\n\n"
    "<Panel>\n\n"
    "```bash\nnpm install thing\n```\n\n"
    "```bash\npip install thing\n```\n\n"
    "</Panel>\n\n"
    "AFTER_TABS prose paragraph explains next steps.\n"
)


class _PanelOwner(ProcessingStrategy):
    """Declares <Panel> blocks but leaves them to the built-in strategies."""

    block_tags = ("Panel",)

    def can_process(self, node) -> bool:
        return False

    def process(self, node, source_file):
        return []  # pragma: no cover - never chosen


class _PanelConfig(OpenCraneConfig):
    chunking_strategies = [_PanelOwner(), *OpenCraneConfig.chunking_strategies]


def test_processor_index_keeps_prose_around_declared_block(tmp_path):
    """Prose before and after a declared block becomes prose chunks, in page
    order, with the page URL; the code in the block stays code_snippet chunks."""
    idx = LlmsIndex.parse("# D\n## proj\n- [Home](https://x/home)\n")
    f = tmp_path / "llms-full.txt"
    f.write_text(_BLOCK_PAGE)
    chunks = FileProcessor(_PanelConfig()).process_file(f, index=idx)

    assert [c.chunk_type for c in chunks] == [
        "prose", "code_snippet", "code_snippet", "prose",
    ]
    assert "BEFORE_TABS" in chunks[0].content
    assert chunks[0].content.startswith("# Home")
    assert "npm install thing" in chunks[1].content
    assert "pip install thing" in chunks[2].content
    assert "AFTER_TABS" in chunks[3].content
    assert {c.metadata.get("source_url") for c in chunks} == {"https://x/home"}


_BLOCK_WITH_TEXT_PAGE = (
    "# Home\n\n"
    "BEFORE_TABS prose paragraph explains the install.\n\n"
    "<Panel>\n\n"
    "NPM_EXPLAIN install the package with npm.\n\n"
    "```bash\nnpm install thing\n```\n\n"
    "PIP_EXPLAIN install the package with pip.\n\n"
    "```bash\npip install thing\n```\n\n"
    "</Panel>\n\n"
    "AFTER_TABS prose paragraph explains next steps.\n"
)


def test_processor_index_keeps_text_inside_declared_block(tmp_path):
    """The text inside a declared block that its strategy leaves alone becomes
    prose chunks next to the block's code, in page order, with the page URL;
    nothing is emitted twice."""
    idx = LlmsIndex.parse("# D\n## proj\n- [Home](https://x/home)\n")
    f = tmp_path / "llms-full.txt"
    f.write_text(_BLOCK_WITH_TEXT_PAGE)
    chunks = FileProcessor(_PanelConfig()).process_file(f, index=idx)

    assert [c.chunk_type for c in chunks] == [
        "prose", "prose", "code_snippet", "prose", "code_snippet", "prose",
    ]
    assert "BEFORE_TABS" in chunks[0].content
    assert "NPM_EXPLAIN" in chunks[1].content
    assert chunks[2].content == "# Home\n\n```bash\nnpm install thing\n```"
    assert "PIP_EXPLAIN" in chunks[3].content
    assert chunks[4].content == "# Home\n\n```bash\npip install thing\n```"
    assert "AFTER_TABS" in chunks[5].content
    assert {c.metadata.get("source_url") for c in chunks} == {"https://x/home"}
    joined = "\n".join(c.content for c in chunks)
    for marker in ("NPM_EXPLAIN", "PIP_EXPLAIN", "npm install thing"):
        assert joined.count(marker) == 1
