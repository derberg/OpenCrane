"""Prose navigation metadata: heading path, clause id, parent and neighbour links."""

import json

import pytest

from opencrane import cli
from opencrane.config import OpenCraneConfig
from opencrane.rag import chunker
from opencrane.rag.chunker import _annotate_prose_navigation, _content_headings
from opencrane.shared.models.chunk import Chunk


def _prose(chunk_id, content, url="https://d/x"):
    metadata = {"source_url": url} if url else {}
    return Chunk(chunk_id=chunk_id, content=content, source_file="f", chunk_type="prose",
                 metadata=metadata, token_count=1)


def _code(chunk_id):
    return Chunk(chunk_id=chunk_id, content="echo", source_file="f", chunk_type="code_snippet",
                 metadata={"language": "bash"}, token_count=1)


# --- clause extraction ---------------------------------------------------------

@pytest.mark.parametrize("heading,expected", [
    ("5.4.1.2.2.8 Title", "5.4.1.2.2.8"),
    ("4c.4.3 Something", "4c.4.3"),
    ("6.1.1.2a Something", "6.1.1.2a"),
    ("16.1.4B.1 Something", "16.1.4B.1"),
    ("Annex C (informative): Extras", "Annex C"),
    ("C.4.4.2 Annex clause", "C.4.4.2"),
    ("5 General", "5"),
    ("5.4:", "5.4"),
    ("1. Install", "1"),
    ("Introduction", None),
    ("E.g. an example", None),
    ("3GPP overview", None),
    ("", None),
    (None, None),
])
def test_default_clause_pattern(heading, expected):
    assert OpenCraneConfig().section_clause_for(heading) == expected


def test_clause_pattern_can_be_disabled_or_replaced():
    cfg = OpenCraneConfig()
    cfg.section_clause_pattern = "none"
    assert cfg.section_clause_for("5.4 Title") is None
    cfg.section_clause_pattern = ""
    assert cfg.section_clause_for("5.4 Title") is None
    # Without a capture group the whole match is the id.
    cfg.section_clause_pattern = r"Step \d+"
    assert cfg.section_clause_for("Step 3: install") == "Step 3"
    assert cfg.section_clause_for("5.4 Title") is None
    # An optional group that did not participate yields no id.
    cfg.section_clause_pattern = r"(\d+)?x"
    assert cfg.section_clause_for("x marks") is None


def test_load_config_applies_section_clause_pattern_from_yaml(tmp_path, monkeypatch):
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "config.yaml").write_text("section_clause_pattern: none\n")
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config(None)
    assert cfg.section_clause_pattern == "none"
    assert cfg.section_anchor_style == "generic"


# --- heading scan --------------------------------------------------------------

def test_content_headings_ignores_fenced_lines_and_detects_opening():
    opens, headings = _content_headings("## 5 A\ntext\n```\n# not a heading\n```\n#### 5.1 B")
    assert opens is True
    assert headings == [(2, "5 A"), (4, "5.1 B")]

    opens, headings = _content_headings("\nintro\n### 6 C")
    assert opens is False
    assert headings == [(3, "6 C")]


# --- annotation ----------------------------------------------------------------

def test_annotation_builds_paths_parents_and_links():
    chunks = [
        _prose("h1", "# Spec title\n\nIntro."),
        _prose("c5", "## 5 Functional description\n\nText."),
        _prose("c51", "### 5.1 General\n\nText.\n\n#### 5.1.1 Inner\n\nInner text."),
        _code("code"),
        _prose("cont", "Continuation after the code block."),
        _prose("deep", "##### 5.1.1.1 Deeper\n\nText."),
        _prose("c52", "### 5.2 Next\n\nText."),
        _prose("annex", "## Annex C (informative): Extras\n\nText."),
    ]
    _annotate_prose_navigation(chunks, OpenCraneConfig())
    meta = {c.chunk_id: c.metadata for c in chunks}

    assert meta["h1"]["heading_path"] == "Spec title"
    assert "clause_id" not in meta["h1"]
    assert meta["h1"]["parent_chunk_id"] is None
    assert meta["h1"]["prev_chunk_id"] is None

    assert meta["c5"]["heading_path"] == "Spec title > 5 Functional description"
    assert meta["c5"]["clause_id"] == "5"
    assert meta["c5"]["parent_chunk_id"] == "h1"

    assert meta["c51"]["heading_path"] == "Spec title > 5 Functional description > 5.1 General"
    assert meta["c51"]["parent_chunk_id"] == "c5"

    # The continuation chunk sits under the last heading seen (the inner 5.1.1,
    # held by c51), skipping the code chunk in the links.
    assert meta["cont"]["heading_path"].endswith("5.1 General > 5.1.1 Inner")
    assert meta["cont"]["clause_id"] == "5.1.1"
    assert meta["cont"]["parent_chunk_id"] == "c51"
    assert meta["cont"]["prev_chunk_id"] == "c51"
    assert meta["c51"]["next_chunk_id"] == "cont"
    assert "position" not in meta["code"]

    # A heading nested under an inner heading links to the chunk holding it.
    assert meta["deep"]["clause_id"] == "5.1.1.1"
    assert meta["deep"]["parent_chunk_id"] == "c51"

    assert meta["c52"]["heading_path"] == "Spec title > 5 Functional description > 5.2 Next"
    assert meta["c52"]["parent_chunk_id"] == "c5"

    assert meta["annex"]["clause_id"] == "Annex C"
    assert meta["annex"]["parent_chunk_id"] == "h1"
    assert meta["annex"]["next_chunk_id"] is None

    assert [meta[c]["position"] for c in ("h1", "c5", "c51", "cont", "deep", "c52", "annex")] == list(range(1, 8))
    # breadcrumb_path is not touched by the navigation pass.
    assert all("breadcrumb_path" not in m for m in meta.values())


def test_annotation_resets_per_page_and_handles_headingless_prose():
    chunks = [
        _prose("a1", "## 1 First page section\n\nText.", url="https://d/a"),
        _prose("b0", "Preamble without any heading.", url="https://d/b"),
        _prose("b1", "## 2 Second page\n\nText.", url="https://d/b"),
    ]
    _annotate_prose_navigation(chunks, OpenCraneConfig())
    a1, b0, b1 = (c.metadata for c in chunks)
    assert a1["next_chunk_id"] is None
    assert b0["prev_chunk_id"] is None and b0["position"] == 1
    assert "heading_path" not in b0 and b0["parent_chunk_id"] is None
    assert b1["heading_path"] == "2 Second page"
    assert b1["parent_chunk_id"] is None
    assert b1["prev_chunk_id"] == "b0"


def test_annotation_can_be_turned_off():
    chunks = [_prose("a", "## 1 Title\n\nText.")]
    cfg = OpenCraneConfig()
    cfg.prose_navigation = False
    _annotate_prose_navigation(chunks, cfg)
    assert chunks[0].metadata == {"source_url": "https://d/x"}


def test_annotation_without_clause_ids():
    chunks = [_prose("a", "## 1 Title\n\nText.")]
    cfg = OpenCraneConfig()
    cfg.section_clause_pattern = "none"
    _annotate_prose_navigation(chunks, cfg)
    assert chunks[0].metadata["heading_path"] == "1 Title"
    assert "clause_id" not in chunks[0].metadata


def test_annotated_prose_chunk_passes_model_validation():
    chunks = [_prose("a", "# T\n\nIntro."), _prose("b", "## 1 Title\n\nText.")]
    _annotate_prose_navigation(chunks, OpenCraneConfig())
    for c in chunks:
        Chunk(**c.model_dump())


def test_chunker_main_writes_navigation_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    llm = tmp_path / "llm"
    llm.mkdir()
    (llm / "llms-full.txt").write_text(
        "# Spec title\n\nIntro.\n\n## 5 Description\n\nText.\n\n### 5.1 General\n\nMore text.\n"
    )
    (llm / "llms.txt").write_text("# Docs\n\n## spec\n\n- [Spec title](https://d/spec.md)\n")
    out = tmp_path / "chunks.json"
    chunker.main(llmstxt_dir=llm, chunks_file=out)
    prose = [c for c in json.loads(out.read_text()) if c["chunk_type"] == "prose"]
    by_clause = {c["metadata"].get("clause_id"): c for c in prose}
    sub = by_clause["5.1"]["metadata"]
    assert sub["heading_path"] == "Spec title > 5 Description > 5.1 General"
    assert sub["parent_chunk_id"] == by_clause["5"]["chunk_id"]
    # Existing two-level breadcrumb is unchanged.
    assert sub["breadcrumb_path"] == "Spec title > 5.1 General"
