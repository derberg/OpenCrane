"""End-to-end fixture test: markdown → llms-full.txt + llms.txt → chunk (with source_url).

This test runs the real generate_outputs + chunker pipeline over committed input
fixtures and compares the results against committed expected outputs.

REGEN mode
----------
Set REGEN=1 in the environment to regenerate the ``expected/`` files from the
current pipeline output:

    REGEN=1 ./pytest.sh tests/unit/source_url_pipeline/test_end_to_end.py --no-cov -v

After regeneration, open the expected files and eyeball them:
  - expected/llms.txt should list correct per-page URLs for each source section
  - expected/llms-full.txt should have clean H1-delimited pages with ====== between
    source blocks
  - expected/chunks.projection.json should show {content_prefix, source_url} per chunk

Fixture cases covered
---------------------
  source-alpha/home.md         — leading ``# H1`` → title from H1
  source-alpha/setup.md        — YAML frontmatter ``title: Setup Guide`` + different body H1
                                 → frontmatter title wins; synthetic H1 prepended
  source-alpha/no-heading.md   — no heading → filename-derived title ("No Heading")
                                 + synthetic H1 prepended
  source-alpha/overview.md     — duplicate title "Overview" appears in BOTH sources;
                                 each page is scoped to its own source section and gets
                                 its own distinct URL, not the other source's URL
  source-beta/overview.md      — same title "Overview" as source-alpha/overview.md;
                                 verifies ordered/scoped join, no URL collision

  external-with-companion      — pre-existing llmstxt dir whose companion llms.txt is
                                 merged into the top-level index; verifies that the
                                 chunker assigns per-page URLs from the merged companion

  test_no_companion_chunks_have_no_source_url (separate standalone test)
                               — llms-full.txt with one source block and llms.txt with
                                 NO matching section; verifies that chunks from a source
                                 without a companion index entry carry source_url=None.
                                 (Tests external-without-companion in isolation to avoid
                                 the block-count mismatch that would cause the combined
                                 pipeline to fall back to legacy-marker mode.)

Pipeline note for external sources
-----------------------------------
``generate_outputs`` assembles the combined llms-full.txt (appending external
content) but does NOT merge companion llms.txt entries into the top-level
llms.txt — that merge happens in a separate step once the external companion
llms.txt has been fetched (Task 5).  The main fixture simulates the post-merge
state by manually appending the companion entries to the generated llms.txt
before running the chunker, matching the expected production pipeline behaviour.

Block-count alignment note
---------------------------
``_split_into_pages`` in the file processor requires the number of ``======``
content blocks to match the number of source sections in the llms.txt index.
Sources with no companion entries are skipped by ``render_llms_txt``, so a
no-companion external bundle CANNOT be safely included in the same combined
file without causing a block-count mismatch and triggering legacy-marker
fallback.  The no-companion case is therefore tested in isolation in
``test_no_companion_chunks_have_no_source_url``.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

import opencrane.rag.generate_llms_txt as gen_mod
from opencrane.rag.chunker import main as chunker_main
from opencrane.rag.services.llms_index import LlmsIndex, render_llms_txt

# Paths to committed fixture files
_FIXTURE_ROOT = Path(__file__).parent.parent.parent / "fixtures" / "source_url_pipeline"
_INPUT_ROOT = _FIXTURE_ROOT / "input"
_EXPECTED_DIR = _FIXTURE_ROOT / "expected"

# Content-prefix length for readable projection entries
_PREFIX_LEN = 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _content_prefix(text: str) -> str:
    """First N chars of stripped content — enough to identify the chunk."""
    return text.strip()[:_PREFIX_LEN]


def _build_projection(chunks) -> list[dict]:
    """Build a deterministic (sorted) projection from a list of Chunk objects."""
    rows = [
        {
            "content_prefix": _content_prefix(c.content),
            "source_url": c.metadata.get("source_url") if c.metadata else None,
        }
        for c in chunks
        if c.content and c.content.strip()
    ]
    # Sort for determinism — chunk order inside a page can vary by strategy
    return sorted(rows, key=lambda r: (r["source_url"] or "", r["content_prefix"]))


# ---------------------------------------------------------------------------
# Module-scoped monkeypatch
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch (pytest's default monkeypatch is function-scoped)."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


# ---------------------------------------------------------------------------
# Main fixture that sets up the workspace and runs the pipeline
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pipeline_outputs(tmp_path_factory, monkeypatch_module):
    """Run the full generate_outputs + chunker pipeline in a clean temp workspace.

    Workspace layout:
      workspace/
        .opencrane/
          config.yaml              ← source mapping
          sources/
            source-alpha/          ← markdown files for source-alpha
            source-beta/           ← markdown files for source-beta
          llmstxt/
            external-with-companion/  ← pre-placed external bundle + companion
    """
    workspace = tmp_path_factory.mktemp("e2e_workspace")

    # Build directory structure
    sources_base = workspace / ".opencrane" / "sources"
    llmstxt_base = workspace / ".opencrane" / "llmstxt"

    alpha_src = sources_base / "source-alpha"
    beta_src = sources_base / "source-beta"
    alpha_src.mkdir(parents=True)
    beta_src.mkdir(parents=True)

    # Copy input markdown fixtures (from /docs/ subdir in fixtures, flat in workspace)
    for fname in ("home.md", "setup.md", "no-heading.md", "overview.md"):
        shutil.copy(_INPUT_ROOT / "source-alpha" / "docs" / fname, alpha_src / fname)
    shutil.copy(_INPUT_ROOT / "source-beta" / "docs" / "overview.md", beta_src / "overview.md")

    # Pre-place external llmstxt bundle with companion (simulates files placed by fetch step)
    ext_with = llmstxt_base / "external-with-companion"
    ext_with.mkdir(parents=True)
    shutil.copy(_INPUT_ROOT / "external-with-companion" / "llms-full.txt", ext_with / "llms-full.txt")
    shutil.copy(_INPUT_ROOT / "external-with-companion" / "llms.txt", ext_with / "llms.txt")

    # Source mapping — flat keys (no docs/ subdir) with docs_url for per-page URLs
    config_yaml = (
        "sources:\n"
        "  source-alpha:\n"
        "    url: https://github.com/example/source-alpha\n"
        "    docs_url: https://alpha.example.com/docs\n"
        "    manual: true\n"
        "  source-beta:\n"
        "    url: https://github.com/example/source-beta\n"
        "    docs_url: https://beta.example.com/docs\n"
        "    manual: true\n"
    )
    opencrane_dir = workspace / ".opencrane"
    (opencrane_dir / "config.yaml").write_text(config_yaml)

    orig_cwd = os.getcwd()
    orig_source_mapping = gen_mod._source_mapping
    try:
        os.chdir(workspace)
        gen_mod._source_mapping = None
        monkeypatch_module.setenv("MAPPING_FILE", str(opencrane_dir / "config.yaml"))

        # Two explicit source dirs → single_source_is_base=False → pre-existing
        # llmstxt subdirs are swept and appended in the final combine step.
        gen_mod.generate_outputs(
            sources_dirs=[alpha_src, beta_src],
            llmstxt_dir=llmstxt_base,
            force=True,
        )
    finally:
        os.chdir(orig_cwd)
        gen_mod._source_mapping = orig_source_mapping

    # --- Merge companion llms.txt into the top-level index ---
    # generate_outputs writes llms.txt covering the markdown sources (source-alpha,
    # source-beta).  The external companion llms.txt (placed by the fetch step /
    # Task 5) carries per-page URLs for the external bundle; merge it in before
    # the chunker runs so the combined index covers all three source blocks.
    top_llms_path = llmstxt_base / "llms.txt"
    companion_llms_path = ext_with / "llms.txt"
    if companion_llms_path.exists() and top_llms_path.exists():
        companion_index = LlmsIndex.parse(companion_llms_path.read_text())
        top_index = LlmsIndex.parse(top_llms_path.read_text())

        merged_sections: list[tuple[str, list]] = []
        for src in top_index.sources():
            merged_sections.append((src, top_index.entries_for(src)))
        for src in companion_index.sources():
            if src:
                merged_sections.append((src, companion_index.entries_for(src)))

        merged_text = render_llms_txt("Documentation", merged_sections)
        top_llms_path.write_text(merged_text)

    # Run the chunker
    chunks_file = workspace / ".opencrane" / "chunks.json"
    orig_cwd = os.getcwd()
    try:
        os.chdir(workspace)
        gen_mod._source_mapping = None
        monkeypatch_module.setenv("MAPPING_FILE", str(opencrane_dir / "config.yaml"))
        chunker_main(
            llmstxt_dir=llmstxt_base,
            chunks_file=chunks_file,
        )
    finally:
        os.chdir(orig_cwd)
        gen_mod._source_mapping = orig_source_mapping

    llms_full = (llmstxt_base / "llms-full.txt").read_text()
    llms_txt = top_llms_path.read_text() if top_llms_path.exists() else ""

    from opencrane.rag.services.chunk_serializer import ChunkSerializer
    chunks = ChunkSerializer.deserialize_chunks(chunks_file)

    return {
        "llms_full": llms_full,
        "llms_txt": llms_txt,
        "chunks": chunks,
        "workspace": workspace,
    }


# ---------------------------------------------------------------------------
# REGEN helper
# ---------------------------------------------------------------------------

def _regen(outputs):
    """Overwrite expected/ files with current pipeline output (REGEN=1 mode)."""
    _EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
    (_EXPECTED_DIR / "llms-full.txt").write_text(outputs["llms_full"])
    (_EXPECTED_DIR / "llms.txt").write_text(outputs["llms_txt"])
    projection = _build_projection(outputs["chunks"])
    (_EXPECTED_DIR / "chunks.projection.json").write_text(
        json.dumps(projection, indent=2, ensure_ascii=False) + "\n"
    )


# ---------------------------------------------------------------------------
# Tests: combined pipeline (source-alpha, source-beta, external-with-companion)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_end_to_end_pipeline(pipeline_outputs):
    """Full pipeline: markdown → llms-full.txt + llms.txt → chunks with source_url.

    In REGEN=1 mode, regenerates expected/ files instead of asserting.
    After regeneration, inspect the generated files manually before committing.
    """
    if os.environ.get("REGEN"):
        _regen(pipeline_outputs)
        return  # Nothing to assert — regeneration complete

    expected_llms_full = (_EXPECTED_DIR / "llms-full.txt").read_text()
    expected_llms_txt = (_EXPECTED_DIR / "llms.txt").read_text()
    expected_projection = json.loads((_EXPECTED_DIR / "chunks.projection.json").read_text())

    assert pipeline_outputs["llms_full"] == expected_llms_full, (
        "Generated llms-full.txt does not match expected.\n"
        "Run with REGEN=1 to update expected files."
    )
    assert pipeline_outputs["llms_txt"] == expected_llms_txt, (
        "Generated llms.txt does not match expected.\n"
        "Run with REGEN=1 to update expected files."
    )

    actual_projection = _build_projection(pipeline_outputs["chunks"])
    assert actual_projection == expected_projection, (
        "Chunk source_url projection does not match expected.\n"
        "Run with REGEN=1 to update expected files."
    )


@pytest.mark.unit
def test_llms_full_contains_all_pages(pipeline_outputs):
    """llms-full.txt must contain content from every input fixture page."""
    content = pipeline_outputs["llms_full"]
    # source-alpha pages
    assert "Welcome to the home page." in content, "home.md content missing"
    assert "Setup Guide" in content, "setup.md frontmatter title missing"
    assert "This page has no heading at all." in content, "no-heading.md content missing"
    assert "No Heading" in content, "synthetic H1 for no-heading.md missing"
    # source-beta page
    assert "Source beta provides complementary functionality" in content, "source-beta overview missing"
    # external bundle
    assert "Welcome to the external documentation home page." in content, "external-with-companion home missing"


@pytest.mark.unit
def test_llms_txt_lists_per_page_urls_for_github_sources(pipeline_outputs):
    """llms.txt must contain per-page URLs for the markdown-derived sources."""
    llms_txt = pipeline_outputs["llms_txt"]
    assert "https://alpha.example.com/docs/home" in llms_txt, "alpha home URL missing from llms.txt"
    assert "https://alpha.example.com/docs/setup" in llms_txt, "alpha setup URL missing from llms.txt"
    assert "https://alpha.example.com/docs/no-heading" in llms_txt, "alpha no-heading URL missing from llms.txt"
    assert "https://alpha.example.com/docs/overview" in llms_txt, "alpha overview URL missing from llms.txt"
    assert "https://beta.example.com/docs/overview" in llms_txt, "beta overview URL missing from llms.txt"


@pytest.mark.unit
def test_llms_txt_per_page_urls_for_external_companion(pipeline_outputs):
    """llms.txt must contain the external-with-companion per-page URLs after merge."""
    llms_txt = pipeline_outputs["llms_txt"]
    assert "https://external.example.com/docs/home" in llms_txt, "external home URL missing"
    assert "https://external.example.com/docs/reference" in llms_txt, "external reference URL missing"


@pytest.mark.unit
def test_setup_md_frontmatter_title_takes_precedence(pipeline_outputs):
    """Frontmatter title: Setup Guide overrides body H1 Installation Instructions.

    The llms.txt index entry must use the frontmatter title; the llms-full.txt
    must open with ``# Setup Guide`` (the synthetic H1) so that the chunker
    page-split matches the title in the index.
    """
    llms_txt = pipeline_outputs["llms_txt"]
    assert "[Setup Guide]" in llms_txt, "Frontmatter title not used for setup.md"
    content = pipeline_outputs["llms_full"]
    assert "# Setup Guide\n" in content, "llms-full.txt should have # Setup Guide (frontmatter title)"


@pytest.mark.unit
def test_no_heading_md_gets_synthetic_h1(pipeline_outputs):
    """no-heading.md has no headings → title derived from filename, H1 prepended."""
    content = pipeline_outputs["llms_full"]
    # Filename "no-heading" → title "No Heading" → prepended as # No Heading
    assert "# No Heading\n" in content, "Synthetic H1 not prepended for no-heading.md"


@pytest.mark.unit
def test_duplicate_title_overview_gets_distinct_urls(pipeline_outputs):
    """Both source-alpha and source-beta have overview.md — each gets its own URL."""
    llms_txt = pipeline_outputs["llms_txt"]
    assert "https://alpha.example.com/docs/overview" in llms_txt
    assert "https://beta.example.com/docs/overview" in llms_txt


@pytest.mark.unit
def test_chunks_from_alpha_carry_per_page_source_urls(pipeline_outputs):
    """Every page in source-alpha produces chunks that carry the correct per-page URL."""
    alpha_chunks = [
        c for c in pipeline_outputs["chunks"]
        if (c.metadata.get("source_url") or "").startswith("https://alpha.example.com/docs/")
    ]
    assert len(alpha_chunks) > 0, "No chunks with alpha.example.com source_url"
    alpha_urls = {c.metadata["source_url"] for c in alpha_chunks}
    assert "https://alpha.example.com/docs/home" in alpha_urls
    assert "https://alpha.example.com/docs/setup" in alpha_urls
    assert "https://alpha.example.com/docs/no-heading" in alpha_urls
    assert "https://alpha.example.com/docs/overview" in alpha_urls


@pytest.mark.unit
def test_chunks_from_external_companion_carry_per_page_source_urls(pipeline_outputs):
    """Chunks from external-with-companion get per-page URLs from the companion llms.txt."""
    ext_chunks = [
        c for c in pipeline_outputs["chunks"]
        if (c.metadata.get("source_url") or "").startswith("https://external.example.com/")
    ]
    assert len(ext_chunks) > 0, "No chunks with external.example.com source_url"
    ext_urls = {c.metadata["source_url"] for c in ext_chunks}
    assert "https://external.example.com/docs/home" in ext_urls
    assert "https://external.example.com/docs/reference" in ext_urls


# ---------------------------------------------------------------------------
# Standalone test: external source WITHOUT companion → source_url=None
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_no_companion_chunks_have_no_source_url(tmp_path):
    """An external llmstxt bundle with no companion llms.txt index entry yields
    chunks with source_url=None.

    This is tested in isolation (separate from the main combined pipeline) to
    avoid the source-block/index-section count mismatch that would occur if the
    no-companion bundle were combined with other sources:  ``_split_into_pages``
    falls back to legacy markers when the counts don't match, making it
    impossible to verify the no-URL outcome deterministically.
    """
    llmstxt_dir = tmp_path / "llmstxt"
    llmstxt_dir.mkdir()

    # Copy the no-companion bundle as the sole content
    shutil.copy(
        _INPUT_ROOT / "external-without-companion" / "llms-full.txt",
        llmstxt_dir / "llms-full.txt",
    )

    # Provide a llms.txt that has NO section for the no-companion content
    # (only a completely different source) so the block count == index count
    # but the page titles don't match → source_url comes back None.
    (llmstxt_dir / "llms.txt").write_text(
        "# Documentation\n\n"
        "## external-without-companion\n"
        "- [Some Other Page](https://other.example.com/page)\n"
    )

    chunks_file = tmp_path / "chunks.json"
    chunker_main(llmstxt_dir=llmstxt_dir, chunks_file=chunks_file)

    from opencrane.rag.services.chunk_serializer import ChunkSerializer
    chunks = ChunkSerializer.deserialize_chunks(chunks_file)

    # All chunks should have source_url=None: the index has an entry for a
    # different title ("Some Other Page") so no title match occurs.
    no_companion_chunks = [
        c for c in chunks
        if "This external bundle has no companion llms.txt" in (c.content or "")
    ]
    assert len(no_companion_chunks) > 0, "No chunks from external-without-companion fixture"
    for chunk in no_companion_chunks:
        assert chunk.metadata.get("source_url") is None, (
            f"Expected source_url=None for no-companion chunk, got {chunk.metadata.get('source_url')}"
        )
