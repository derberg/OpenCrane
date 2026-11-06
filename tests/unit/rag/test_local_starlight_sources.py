"""Tests for reading a local Starlight docs folder directly.

Covers the ``markdown_extensions`` setting, the ``markdown_preprocessors``
extension point, a local source named apart from its directory, and the
``trailing_slash`` page URL option.
"""
import json
import re
from pathlib import Path

import pytest
import yaml

from opencrane.config import OpenCraneConfig
from opencrane.rag import generate_llms_txt as gen
from opencrane.rag.chunker import main as chunker_main
from opencrane.rag.services.llms_index import LlmsIndex
from opencrane.rag.services.source_mapping import SourceMapping

DOCS_URL = "https://opensourceeurope.org/docs"


def _use_mapping(monkeypatch, tmp_path: Path, data: dict) -> Path:
    mapping_file = tmp_path / ".opencrane" / "config.yaml"
    mapping_file.parent.mkdir(parents=True, exist_ok=True)
    mapping_file.write_text(yaml.dump(data))
    monkeypatch.setenv("MAPPING_FILE", str(mapping_file))
    monkeypatch.setattr(gen, "_source_mapping", SourceMapping(mapping_file))
    return mapping_file


def rewrite_notes(content: str, file_path: Path, project_name: str) -> str:
    """Turn Starlight ``:::note`` asides into blockquotes."""
    return re.sub(
        r"^:::note\n(.*?)\n:::$",
        lambda m: f"> **Note:** {m.group(1)}",
        content,
        flags=re.M | re.S,
    )


class TestMarkdownExtensions:
    def test_default_is_md_only(self, monkeypatch, tmp_path):
        _use_mapping(monkeypatch, tmp_path, {"sources": {}})
        assert gen.markdown_extensions() == (".md",)

    def test_normalizes_entries(self, monkeypatch, tmp_path):
        _use_mapping(monkeypatch, tmp_path, {"markdown_extensions": ["md", ".MDX", ".md"]})
        assert gen.markdown_extensions() == (".md", ".mdx")

    @pytest.mark.parametrize("value", [".mdx", [], [""], [".md", 3]])
    def test_rejects_invalid_values(self, monkeypatch, tmp_path, value):
        _use_mapping(monkeypatch, tmp_path, {"markdown_extensions": value})
        with pytest.raises(ValueError, match="markdown_extensions"):
            gen.markdown_extensions()

    def test_find_markdown_files_uses_setting(self, monkeypatch, tmp_path):
        _use_mapping(monkeypatch, tmp_path, {"markdown_extensions": [".md", ".mdx"]})
        docs = tmp_path / "docs"
        (docs / "faq").mkdir(parents=True)
        for name in ("index.mdx", "about.md", "notes.txt", "faq/general.mdx"):
            (docs / name).write_text("# x\n")
        assert gen.find_markdown_files(docs) == [
            docs / "about.md", docs / "faq/general.mdx", docs / "index.mdx",
        ]
        assert gen.find_markdown_files(docs, recursive=False) == [docs / "about.md", docs / "index.mdx"]

    def test_index_mdx_maps_to_folder_url(self, monkeypatch, tmp_path):
        _use_mapping(monkeypatch, tmp_path, {
            "markdown_extensions": [".md", ".mdx"],
            "sources": {"site": {"local": True, "docs_url": DOCS_URL}},
        })
        assert gen.get_source_url(Path("site/index.mdx"), "site") == DOCS_URL
        assert gen.get_source_url(Path("site/faq/index.mdx"), "site") == f"{DOCS_URL}/faq"
        assert gen.get_source_url(Path("site/faq/general-faqs.mdx"), "site") == f"{DOCS_URL}/faq/general-faqs"

    def test_link_to_mdx_page_keeps_only_label(self, monkeypatch, tmp_path):
        _use_mapping(monkeypatch, tmp_path, {"markdown_extensions": [".md", ".mdx"]})
        text = "See [the FAQ](faq/general.mdx#fees) and [the PDF](terms.pdf)."
        result = gen.rewrite_links(text, Path("a.md"), Path("p/a.md"), Path("p"), "p")
        assert result == "See the FAQ and [the PDF](terms.pdf)."

    def test_link_to_mdx_page_untouched_by_default(self, monkeypatch, tmp_path):
        _use_mapping(monkeypatch, tmp_path, {"sources": {}})
        text = "See [the FAQ](faq/general.mdx)."
        assert gen.rewrite_links(text, Path("a.md"), Path("p/a.md"), Path("p"), "p") == text


class TestTrailingSlash:
    def test_appends_slash_to_page_and_root_once(self, monkeypatch, tmp_path):
        _use_mapping(monkeypatch, tmp_path, {
            "sources": {"site": {"local": True, "docs_url": DOCS_URL + "/", "trailing_slash": True}},
        })
        assert gen.get_source_url(Path("site/faq/general-faqs.md"), "site") == f"{DOCS_URL}/faq/general-faqs/"
        assert gen.get_source_url(Path("site/index.md"), "site") == f"{DOCS_URL}/"


class TestMarkdownPreprocessors:
    def test_config_default_is_empty(self):
        assert OpenCraneConfig.markdown_preprocessors == []

    def test_applied_in_order_after_frontmatter(self, monkeypatch, tmp_path):
        _use_mapping(monkeypatch, tmp_path, {"sources": {}})
        page = tmp_path / "p" / "page.md"
        page.parent.mkdir()
        page.write_text("---\ntitle: From Frontmatter\n---\n:::note\nKeep receipts.\n:::\n")
        calls = []

        def record(content, file_path, project_name):
            calls.append((content, file_path, project_name))
            return content + "\nappended"

        content, _ = gen.process_file(page, page.parent, "p", [rewrite_notes, record])
        assert content.startswith("# From Frontmatter\n")
        assert "> **Note:** Keep receipts." in content
        assert ":::" not in content
        assert content.endswith("appended")
        assert calls == [("> **Note:** Keep receipts.\n", page, "p")]

    def test_non_string_result_raises(self, tmp_path):
        with pytest.raises(TypeError, match="must return a string, got NoneType"):
            gen.apply_markdown_preprocessors("x", tmp_path / "a.md", "p", [lambda *a: None])


class TestNamedLocalSource:
    """A local source whose key is its name and whose files live elsewhere."""

    @pytest.fixture
    def project(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        for var in ("AI_DOCS_SOURCES_DIRS", "AI_DOCS_SOURCES_DIR", "AI_DOCS_LLMSTXT_DIR", "AI_DOCS_NO_FILTER"):
            monkeypatch.delenv(var, raising=False)
        docs = tmp_path / "src" / "content" / "docs" / "docs"
        (docs / "faq").mkdir(parents=True)
        (docs / "index.mdx").write_text(
            "---\ntitle: Open Source Europe docs\n---\nimport { LinkCard } from '@astrojs/starlight/components';\n\n"
            "Start here.\n"
        )
        (docs / "faq" / "general-faqs.md").write_text(
            "---\ntitle: General FAQs\n---\n## Fees\n\n:::note\nFees are listed per collective.\n:::\n"
        )
        _use_mapping(monkeypatch, tmp_path, {
            "markdown_extensions": [".md", ".mdx"],
            "sources": {"open-source-europe": {
                "local": True,
                "docs_path": "src/content/docs/docs",
                "docs_url": DOCS_URL,
                "url": "https://github.com/org/site",
            }},
        })
        return tmp_path

    def test_llms_txt_section_and_urls_use_the_key(self, project):
        class Config(OpenCraneConfig):
            markdown_preprocessors = [rewrite_notes]

        gen.generate_outputs(config=Config(), force=True)

        llmstxt = project / ".opencrane" / "llmstxt"
        index = LlmsIndex.parse((llmstxt / "llms.txt").read_text())
        assert index.sources() == ["open-source-europe"]
        assert [(e.title, e.url) for e in index.entries_for("open-source-europe")] == [
            ("General FAQs", f"{DOCS_URL}/faq/general-faqs"),
            ("Open Source Europe docs", DOCS_URL),
        ]
        full = (llmstxt / "llms-full.txt").read_text()
        assert "> **Note:** Fees are listed per collective." in full
        assert "src/content" not in full

        chunks_file = project / ".opencrane" / "chunks.json"
        chunker_main(config=Config(), llmstxt_dir=llmstxt, chunks_file=chunks_file)
        chunks = json.loads(chunks_file.read_text())
        chunks = chunks["chunks"] if isinstance(chunks, dict) else chunks
        assert chunks
        assert {c["source_name"] for c in chunks} == {"open-source-europe"}

    def test_github_blob_fallback_points_at_the_directory(self, project, monkeypatch):
        monkeypatch.setattr(gen, "get_repo_subdir", lambda: "")
        data = gen.get_source_mapping().data
        del data["sources"]["open-source-europe"]["docs_url"]
        assert gen.get_source_url(Path("open-source-europe/faq/general-faqs.md"), "open-source-europe") == (
            "https://github.com/org/site/blob/main/src/content/docs/docs/faq/general-faqs.md"
        )
