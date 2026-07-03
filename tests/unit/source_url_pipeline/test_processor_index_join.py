"""Tests for FileProcessor page-boundary split + llms.txt index join."""

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


def test_processor_index_keeps_tabs_html_block_intact(tmp_path):
    """A <Tabs> HTML block inside a page is emitted as one sub-section and
    carries the page URL from the index."""
    full = (
        "# Home\nIntro prose for the home page here.\n\n"
        "<Tabs>\n"
        "  <Tab>First tab body content goes here now.</Tab>\n"
        "  <Tab>Second tab body content goes here now.</Tab>\n"
        "</Tabs>\n\n"
        "More prose after the tabs block content.\n"
    )
    idx = LlmsIndex.parse("# D\n## proj\n- [Home](https://x/home)\n")
    f = tmp_path / "llms-full.txt"
    f.write_text(full)
    chunks = FileProcessor().process_file(f, index=idx)
    urls = {c.metadata.get("source_url") for c in chunks if c.metadata.get("source_url")}
    assert urls == {"https://x/home"}
    assert any("<Tabs>" in c.content and "</Tabs>" in c.content for c in chunks)


def test_processor_section_anchors_applies_anchor_for(tmp_path):
    """When config.section_anchors is on, anchor_for is applied per sub-section
    using that sub-section's nearest heading."""
    from opencrane.config import OpenCraneConfig

    class AnchorConfig(OpenCraneConfig):
        section_anchors = True

        def anchor_for(self, page_url, heading):
            if heading:
                slug = heading.strip().lower().replace(" ", "-")
                return f"{page_url}#{slug}"
            return page_url

    full = "# Home\n## Getting Started\nHere is how you get started with it.\n"
    idx = LlmsIndex.parse("# D\n## proj\n- [Home](https://x/home)\n")
    f = tmp_path / "llms-full.txt"
    f.write_text(full)
    chunks = FileProcessor(config=AnchorConfig()).process_file(f, index=idx)
    urls = {c.metadata.get("source_url") for c in chunks if c.metadata.get("source_url")}
    assert any(u.startswith("https://x/home#") for u in urls)
