"""Tests for llms-full.txt combine-only behavior when no sources in mapping."""

from pathlib import Path

import pytest

import opencrane.rag.generate_llms_txt as generate_llms_txt
from opencrane.rag.generate_llms_txt import generate_outputs


@pytest.fixture(autouse=True)
def reset_llms_globals():
    """Reset module-level globals that leak between tests."""
    generate_llms_txt._source_mapping = None
    yield
    generate_llms_txt._source_mapping = None


@pytest.fixture()
def llmstxt_workspace(tmp_path, monkeypatch):
    """Create a workspace with pre-existing llms-full.txt files but no config.yaml entries."""
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    config_yaml = opencrane_dir / "config.yaml"
    config_yaml.write_text("sources:\n")

    # Override MAPPING_FILE so get_source_mapping() uses our empty config.yaml
    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))

    llmstxt_dir = opencrane_dir / "llmstxt"

    project_a = llmstxt_dir / "project-a"
    project_a.mkdir(parents=True)
    (project_a / "llms-full.txt").write_text("# Project A docs\n\nSome content about A.")

    project_b = llmstxt_dir / "project-b"
    project_b.mkdir(parents=True)
    (project_b / "llms-full.txt").write_text("# Project B docs\n\nSome content about B.")

    return tmp_path


@pytest.mark.unit
def test_combine_existing_llmstxt_files_when_no_sources(llmstxt_workspace, monkeypatch):
    """When config.yaml is empty but llmstxt subdirs have files, combine them."""
    monkeypatch.chdir(llmstxt_workspace)
    llmstxt_dir = llmstxt_workspace / ".opencrane" / "llmstxt"
    generate_outputs(force=True, llmstxt_dir=llmstxt_dir)

    combined = llmstxt_dir / "llms-full.txt"
    assert combined.exists(), "Root llms-full.txt should be generated from existing subdirectory files"
    content = combined.read_text()
    assert "Project A docs" in content
    assert "Project B docs" in content


@pytest.mark.unit
def test_no_sources_no_llmstxt_files_warns(llmstxt_workspace, monkeypatch, capsys):
    """When config.yaml is empty AND no llmstxt subdirs exist, print warning."""
    import shutil
    shutil.rmtree(llmstxt_workspace / ".opencrane" / "llmstxt")

    monkeypatch.chdir(llmstxt_workspace)
    llmstxt_dir = llmstxt_workspace / ".opencrane" / "llmstxt"
    generate_outputs(force=True, llmstxt_dir=llmstxt_dir)

    captured = capsys.readouterr()
    assert "no sources" in captured.out.lower() or "no existing" in captured.out.lower()
    assert not (llmstxt_dir / "llms-full.txt").exists()


@pytest.mark.unit
def test_combine_llmstxt_source_with_docs_url_leaves_headings_clean(llmstxt_workspace, monkeypatch):
    """External llmstxt sources are no longer modified with URL bracket injections.

    Per-page URLs for external sources are provided via a companion llms.txt
    file fetched in a later pipeline step; the combined llms-full.txt must have
    clean, unmodified headings regardless of whether docs_url is configured.
    """
    config_yaml = llmstxt_workspace / ".opencrane" / "config.yaml"
    config_yaml.write_text(
        "sources:\n"
        "  project-a:\n"
        "    type: llmstxt\n"
        "    url: https://example.com/a.txt\n"
        "    docs_url: https://docs.example.com\n"
        "    manual: true\n"
    )
    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))
    monkeypatch.chdir(llmstxt_workspace)

    llmstxt_dir = llmstxt_workspace / ".opencrane" / "llmstxt"
    generate_outputs(force=True, llmstxt_dir=llmstxt_dir)

    combined = llmstxt_dir / "llms-full.txt"
    content = combined.read_text()
    # Headings must NOT have injected bracket URL tags
    assert "[https://docs.example.com]" not in content
    # Original heading text must be preserved
    assert "# Project A docs" in content


@pytest.mark.unit
def test_combine_no_docs_url_leaves_headings_unchanged(llmstxt_workspace, monkeypatch):
    """Without docs_url, headings are not modified."""
    monkeypatch.chdir(llmstxt_workspace)
    llmstxt_dir = llmstxt_workspace / ".opencrane" / "llmstxt"
    generate_outputs(force=True, llmstxt_dir=llmstxt_dir)

    combined = llmstxt_dir / "llms-full.txt"
    content = combined.read_text()
    assert "# Project A docs" in content
    # Verify no URL prefix brackets in headings
    for line in content.split("\n"):
        if line.startswith("#"):
            assert "[" not in line


@pytest.mark.unit
def test_combine_includes_preexisting_llmstxt_alongside_source_dirs(tmp_path, monkeypatch):
    """When --sources-dir processes some sources AND pre-existing llmstxt files
    exist (e.g., added via opencrane add with type: llmstxt), the combined
    llms-full.txt should include both."""
    from unittest.mock import patch

    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    config_yaml = opencrane_dir / "config.yaml"
    config_yaml.write_text(
        "sources:\n"
        "  likec4:\n"
        "    type: llmstxt\n"
        "    url: https://likec4.dev/llms-full.txt\n"
        "    docs_url: https://likec4.dev/tutorial/\n"
        "    manual: true\n"
    )
    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))

    llmstxt_dir = opencrane_dir / "llmstxt"

    # Pre-existing llmstxt source (added via opencrane add)
    likec4_dir = llmstxt_dir / "likec4"
    likec4_dir.mkdir(parents=True)
    (likec4_dir / "llms-full.txt").write_text("# LikeC4 Tutorial\n\nArchitecture as code.")

    # Source directory with markdown docs
    source_dir = tmp_path / "my-docs"
    (source_dir / "project").mkdir(parents=True)
    (source_dir / "project" / "readme.md").write_text("# My Project\n\nProject docs.")

    monkeypatch.chdir(tmp_path)

    monkeypatch.setenv("AI_DOCS_NO_FILTER", "1")
    generate_outputs(force=True, sources_dirs=[source_dir], llmstxt_dir=llmstxt_dir)

    combined = llmstxt_dir / "llms-full.txt"
    assert combined.exists(), "Root llms-full.txt should be generated"
    content = combined.read_text()
    assert "My Project" in content, "Source-dir content should be in combined output"
    assert "LikeC4 Tutorial" in content, "Pre-existing llmstxt content should be in combined output"
    # Headings must NOT have injected bracket URL tags — docs_url heading injection
    # was removed; per-page URLs come from a companion llms.txt in a later step.
    assert "[https://likec4.dev/tutorial]" not in content
    assert "# LikeC4 Tutorial" in content


@pytest.mark.unit
def test_combine_skips_non_directory_entries(llmstxt_workspace, monkeypatch):
    """The combine logic should only look at subdirectories, not stray files."""
    llmstxt_dir = llmstxt_workspace / ".opencrane" / "llmstxt"
    (llmstxt_dir / "notes.txt").write_text("stray file")

    monkeypatch.chdir(llmstxt_workspace)
    generate_outputs(force=True, llmstxt_dir=llmstxt_dir)

    combined = llmstxt_dir / "llms-full.txt"
    assert combined.exists()
    content = combined.read_text()
    assert "stray file" not in content
    assert "Project A docs" in content


@pytest.mark.unit
def test_combine_existing_llmstxt_base_exists_no_files(tmp_path):
    """When the llmstxt base exists but no subdir holds an llms-full.txt, return []."""
    base = tmp_path / "llmstxt"
    base.mkdir()
    # A subdirectory exists but has no llms-full.txt inside it.
    (base / "empty-project").mkdir()
    assert generate_llms_txt._combine_existing_llmstxt(base) == []


@pytest.mark.unit
def test_no_source_dirs_from_mapping_warns(tmp_path, monkeypatch, capsys):
    """A mapping with only non-local sources that resolve to no directories, and
    no pre-existing llms-full.txt files, prints the 'no source directories' warning."""
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    config_yaml = opencrane_dir / "config.yaml"
    # A non-local source whose directory was never fetched into .opencrane/sources/.
    config_yaml.write_text(
        "sources:\n"
        "  missing-repo:\n"
        "    type: github\n"
        "    url: https://github.com/example/missing-repo\n"
    )
    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))
    monkeypatch.chdir(tmp_path)

    llmstxt_dir = opencrane_dir / "llmstxt"
    generate_outputs(force=True, llmstxt_dir=llmstxt_dir)

    captured = capsys.readouterr()
    assert "no source directories found from mapping file" in captured.out
    assert not (llmstxt_dir / "llms-full.txt").exists()


@pytest.mark.unit
def test_mapped_path_not_resolvable_is_skipped(tmp_path, monkeypatch):
    """A mapped path that exists in the mapping but resolves to no directory on
    disk is skipped (continue), while a sibling source dir is still processed."""
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    config_yaml = opencrane_dir / "config.yaml"
    # 'ghost' has no directory anywhere; 'real' exists under .opencrane/sources/.
    config_yaml.write_text(
        "sources:\n"
        "  ghost:\n"
        "    type: github\n"
        "    url: https://github.com/example/ghost\n"
        "  real:\n"
        "    type: github\n"
        "    url: https://github.com/example/real\n"
    )
    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))

    sources_base = opencrane_dir / "sources"
    real_dir = sources_base / "real"
    real_dir.mkdir(parents=True)
    (real_dir / "readme.md").write_text("# Real Project\n\nReal docs.")

    monkeypatch.chdir(tmp_path)

    llmstxt_dir = opencrane_dir / "llmstxt"
    generate_outputs(force=True, llmstxt_dir=llmstxt_dir)

    combined = llmstxt_dir / "llms-full.txt"
    assert combined.exists()
    content = combined.read_text()
    assert "Real Project" in content
    assert "ghost" not in content.lower()


@pytest.mark.unit
def test_preexisting_sweep_skips_subdir_without_llms_file(tmp_path, monkeypatch):
    """During the pre-existing llmstxt sweep, a subdir lacking llms-full.txt is
    skipped while a valid source dir is still combined into the output."""
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    config_yaml = opencrane_dir / "config.yaml"
    config_yaml.write_text(
        "sources:\n"
        "  likec4:\n"
        "    type: llmstxt\n"
        "    url: https://likec4.dev/llms-full.txt\n"
        "    manual: true\n"
    )
    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))

    llmstxt_dir = opencrane_dir / "llmstxt"

    # Valid pre-existing llmstxt source.
    likec4_dir = llmstxt_dir / "likec4"
    likec4_dir.mkdir(parents=True)
    (likec4_dir / "llms-full.txt").write_text("# LikeC4 Tutorial\n\nArchitecture as code.")

    # A subdirectory in the llmstxt base that has NO llms-full.txt — must be skipped.
    (llmstxt_dir / "incomplete").mkdir(parents=True)

    # A source directory with markdown so the source-dir branch runs and reaches
    # the pre-existing sweep afterwards.
    source_dir = tmp_path / "my-docs"
    (source_dir / "project").mkdir(parents=True)
    (source_dir / "project" / "readme.md").write_text("# My Project\n\nProject docs.")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_DOCS_NO_FILTER", "1")
    generate_outputs(force=True, sources_dirs=[source_dir], llmstxt_dir=llmstxt_dir)

    combined = llmstxt_dir / "llms-full.txt"
    assert combined.exists()
    content = combined.read_text()
    assert "My Project" in content
    assert "LikeC4 Tutorial" in content


@pytest.mark.unit
def test_multi_source_llmstxt_section_order_matches_llms_full_txt(tmp_path, monkeypatch):
    """Regression: llms.txt section order must match the source block order in
    llms-full.txt.  Both files must be sorted by source_dir.as_posix(); if
    llms.txt were sorted by a different key (e.g. source_dir.name) the Nth ##
    section would not correspond to the Nth content block and the chunker would
    map pages to the wrong source_url.

    This test exercises the multi-source ``else`` branch (two external source
    dirs, ``single_source_is_base=False``) with real IndexEntry objects so that
    the top-level llms.txt is actually written.  It asserts that:
      1. Both files are generated.
      2. The relative order of source-a and source-z contributions is the same
         in llms-full.txt and llms.txt.

    Two source dirs are passed in REVERSE alphabetical order so the sort (not
    insertion order) determines output ordering.
    """
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    config_yaml = opencrane_dir / "config.yaml"

    # chdir first so Path.cwd() returns the same fully-resolved path that the
    # generate_outputs workspace_root comparison uses (avoids /private/var vs
    # /var mismatches on macOS).
    monkeypatch.chdir(tmp_path)
    workspace = Path.cwd()

    # Two source dirs:  source-a sorts BEFORE source-z by both .name and
    # .as_posix() (they are siblings).  source-z is passed first so the test
    # exercises the sort, not insertion order.
    source_a = workspace / "source-a"
    source_z = workspace / "source-z"
    (source_a / "proj-a").mkdir(parents=True)
    (source_z / "proj-z").mkdir(parents=True)
    (source_a / "proj-a" / "page.md").write_text("# Source A Page\n\nContent from source-a.")
    (source_z / "proj-z" / "page.md").write_text("# Source Z Page\n\nContent from source-z.")

    # Map with docs_url so process_file emits IndexEntry objects (required for
    # llms.txt to be written).  With AI_DOCS_NO_FILTER the project names
    # discovered from source-a are "source-a/proj-a" and from source-z are
    # "source-z/proj-z" (relative to workspace), so we map them directly.
    config_yaml.write_text(
        "sources:\n"
        "  source-a/proj-a:\n"
        "    type: github\n"
        "    url: https://github.com/example/proj-a\n"
        "    docs_url: https://docs.example.com/proj-a\n"
        "  source-z/proj-z:\n"
        "    type: github\n"
        "    url: https://github.com/example/proj-z\n"
        "    docs_url: https://docs.example.com/proj-z\n"
    )
    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))
    monkeypatch.setenv("AI_DOCS_NO_FILTER", "1")

    llmstxt_dir = opencrane_dir / "llmstxt"

    # Pass in reverse order — the sort must determine output, not insertion order.
    generate_outputs(
        force=True,
        sources_dirs=[source_z, source_a],
        llmstxt_dir=llmstxt_dir,
    )

    combined_path = llmstxt_dir / "llms-full.txt"
    llms_txt_path = llmstxt_dir / "llms.txt"
    assert combined_path.exists(), "llms-full.txt must be generated"
    assert llms_txt_path.exists(), "llms.txt must be generated"

    combined = combined_path.read_text()
    llms_txt = llms_txt_path.read_text()

    a_pos_full = combined.find("Source A Page")
    z_pos_full = combined.find("Source Z Page")
    assert a_pos_full != -1, "source-a content must appear in llms-full.txt"
    assert z_pos_full != -1, "source-z content must appear in llms-full.txt"

    # The section headers use output_name (= project_name with source_dir prefix
    # stripped), so "source-a/proj-a" → "proj-a" and "source-z/proj-z" → "proj-z".
    a_pos_llms = llms_txt.find("## proj-a")
    z_pos_llms = llms_txt.find("## proj-z")
    assert a_pos_llms != -1, "## proj-a section must appear in llms.txt"
    assert z_pos_llms != -1, "## proj-z section must appear in llms.txt"

    # source-a sorts before source-z by as_posix(); both files must agree.
    a_before_z_in_full = a_pos_full < z_pos_full
    a_before_z_in_llms = a_pos_llms < z_pos_llms
    assert a_before_z_in_full == a_before_z_in_llms, (
        "llms.txt section order must match llms-full.txt block order so the "
        "chunker maps each page to the correct source_url"
    )


@pytest.mark.unit
def test_no_h1_external_source_keeps_non_empty_index_section_and_does_not_poison_other_sources(
    tmp_path, monkeypatch
):
    """Regression: an external llmstxt source whose llms-full.txt has ZERO H1
    headings (prose-only content, including a fenced code block with a ``#``
    comment line) must still produce a non-empty ``## {source}`` section in the
    combined llms.txt so the source-block count == index-section count invariant
    holds.  When the invariant breaks, ALL external sources lose their source_url
    ('poison').  This test asserts:

    (a) The no-H1 source's ``## {source}`` section is present in llms.txt.
    (b) A second external source that HAS a companion llms.txt retains its
        correct per-page URLs (not poisoned by the no-H1 source).
    """
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    config_yaml = opencrane_dir / "config.yaml"
    config_yaml.write_text(
        "sources:\n"
        "  no-h1-source:\n"
        "    type: llmstxt\n"
        "    url: https://example.com/no-h1/llms-full.txt\n"
        "    docs_url: https://no-h1.example.com/docs\n"
        "    manual: true\n"
        "  with-companion:\n"
        "    type: llmstxt\n"
        "    url: https://example.com/with-companion/llms-full.txt\n"
        "    docs_url: https://companion.example.com/docs\n"
        "    manual: true\n"
    )
    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))

    llmstxt_dir = opencrane_dir / "llmstxt"

    # Source 1: no H1 headings — prose only, plus a fenced code block with a
    # ``#`` comment line to prove fence-awareness (the ``#`` must NOT be
    # mistaken for a page boundary).
    no_h1_dir = llmstxt_dir / "no-h1-source"
    no_h1_dir.mkdir(parents=True)
    (no_h1_dir / "llms-full.txt").write_text(
        "This source has no H1 headings at all.\n\n"
        "Some introductory prose without any heading markers.\n\n"
        "```python\n"
        "# This is a Python comment, not an H1 heading\n"
        "x = 42\n"
        "```\n\n"
        "More prose after the code block.\n"
    )

    # Source 2: has a companion llms.txt with real per-page URLs.
    companion_dir = llmstxt_dir / "with-companion"
    companion_dir.mkdir(parents=True)
    (companion_dir / "llms-full.txt").write_text(
        "# Getting Started\n\nWelcome to the companion source.\n\n"
        "-----\n\n"
        "# Reference\n\nAPI reference details.\n"
    )
    (companion_dir / "llms.txt").write_text(
        "# Documentation\n\n"
        "## with-companion\n"
        "- [Getting Started](https://companion.example.com/docs/getting-started)\n"
        "- [Reference](https://companion.example.com/docs/reference)\n"
    )

    monkeypatch.chdir(tmp_path)
    generate_outputs(force=True, llmstxt_dir=llmstxt_dir)

    combined_path = llmstxt_dir / "llms-full.txt"
    llms_txt_path = llmstxt_dir / "llms.txt"

    assert combined_path.exists(), "llms-full.txt must be generated"
    assert llms_txt_path.exists(), "llms.txt must be generated"

    llms_txt = llms_txt_path.read_text()

    # (a) The no-H1 source must have a non-empty section in llms.txt.
    assert "## no-h1-source" in llms_txt, (
        "no-H1 source section missing from llms.txt — count invariant broken"
    )
    # The section must have at least one entry line (non-empty).
    lines = llms_txt.splitlines()
    no_h1_section_start = next(
        (i for i, l in enumerate(lines) if l.strip() == "## no-h1-source"), None
    )
    assert no_h1_section_start is not None
    # Find the next line after the heading that is non-empty
    entry_lines = [
        l for l in lines[no_h1_section_start + 1:]
        if l.strip() and not l.strip().startswith("##")
    ]
    assert len(entry_lines) >= 1, (
        "## no-h1-source section is empty — render_llms_txt will skip it and "
        "break the block/section count invariant"
    )

    # (b) The companion source must retain its correct per-page URLs (not poisoned).
    assert "## with-companion" in llms_txt, "companion section missing from llms.txt"
    assert "https://companion.example.com/docs/getting-started" in llms_txt, (
        "companion per-page URL poisoned by no-H1 source"
    )
    assert "https://companion.example.com/docs/reference" in llms_txt, (
        "companion reference URL poisoned by no-H1 source"
    )


@pytest.mark.unit
def test_companion_md_urls_stripped_when_docs_url_set(tmp_path, monkeypatch):
    """A GitBook-style companion llms.txt lists source-file URLs ending in
    ``.md`` (or ``/index.md``).  When the source has a ``docs_url`` configured,
    those must be normalized to the rendered docs-site page path (no ``.md``),
    consistent with ``get_source_url``.  Without ``docs_url`` they stay verbatim.
    """
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    config_yaml = opencrane_dir / "config.yaml"
    config_yaml.write_text(
        "sources:\n"
        "  with-docs-url:\n"
        "    type: llmstxt\n"
        "    url: https://example.com/with-docs-url/llms-full.txt\n"
        "    docs_url: https://docs.opencollective.com\n"
        "    manual: true\n"
        "  no-docs-url:\n"
        "    type: llmstxt\n"
        "    url: https://example.com/no-docs-url/llms-full.txt\n"
        "    manual: true\n"
    )
    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))

    llmstxt_dir = opencrane_dir / "llmstxt"

    with_dir = llmstxt_dir / "with-docs-url"
    with_dir.mkdir(parents=True)
    (with_dir / "llms-full.txt").write_text(
        "# The Foundation\n\nFoundation content.\n\n"
        "-----\n\n"
        "# Overview\n\nSection overview.\n\n"
        "-----\n\n"
        "# Already Clean\n\nNo extension here.\n"
    )
    (with_dir / "llms.txt").write_text(
        "# Docs\n\n"
        "## with-docs-url\n"
        "- [The Foundation](https://docs.opencollective.com/oc-europe-internal-doc/the-foundation.md)\n"
        "- [Overview](https://docs.opencollective.com/oc-europe-internal-doc/section/index.md)\n"
        "- [Already Clean](https://docs.opencollective.com/oc-europe-internal-doc/clean)\n"
    )

    no_dir = llmstxt_dir / "no-docs-url"
    no_dir.mkdir(parents=True)
    (no_dir / "llms-full.txt").write_text("# Home\n\nHome content.\n")
    (no_dir / "llms.txt").write_text(
        "# Docs\n\n"
        "## no-docs-url\n"
        "- [Home](https://raw.example.com/home.md)\n"
    )

    monkeypatch.chdir(tmp_path)
    generate_outputs(force=True, llmstxt_dir=llmstxt_dir)

    llms_txt = (llmstxt_dir / "llms.txt").read_text()

    # docs_url source: .md stripped, /index.md → parent path.
    assert "https://docs.opencollective.com/oc-europe-internal-doc/the-foundation" in llms_txt
    assert "the-foundation.md" not in llms_txt
    assert "https://docs.opencollective.com/oc-europe-internal-doc/section" in llms_txt
    assert "section/index.md" not in llms_txt
    # docs_url source: a URL already without .md is left unchanged.
    assert "https://docs.opencollective.com/oc-europe-internal-doc/clean" in llms_txt
    # no docs_url source: URL left verbatim.
    assert "https://raw.example.com/home.md" in llms_txt


@pytest.mark.unit
def test_generated_source_without_resolvable_url_does_not_poison_mixed_bundle(
    tmp_path, monkeypatch
):
    """Regression: a generated (github/local) source that contributes markdown content
    but resolves NO per-page URL must not drop its ## section from llms.txt.

    When the ## section is dropped, the combined llms.txt has fewer sections than
    the combined llms-full.txt has ====== blocks.  The chunker falls back to legacy
    marker detection (finds nothing in clean content) and sets source_url=None for
    EVERY chunk in the entire bundle — poisoning even correctly-mapped sources.

    Setup:
      - mapped-source:   has a docs_url in the mapping → per-page URLs resolved
      - unmapped-source: markdown files exist on disk but no mapping entry → no URLs

    Expected:
      - mapped-source chunks carry their correct per-page source_url
      - unmapped-source chunks carry source_url=None (acceptable; the source itself
        is unmapped — but it must NOT cause the mapped source to lose its URL)
    """
    import os
    from opencrane.rag.chunker import main as chunker_main
    from opencrane.rag.services.chunk_serializer import ChunkSerializer

    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    config_yaml = opencrane_dir / "config.yaml"

    # mapped-source: has docs_url → get_source_url() will return per-page URLs.
    # no-url-source: in the mapping but has NO url and NO docs_url → get_source_url()
    #   returns None for every file → build_project_output entries list stays empty.
    #   This is the poison scenario: no-url-source contributes a content block but
    #   its ## section gets dropped from llms.txt → block count > section count.
    config_yaml.write_text(
        "sources:\n"
        "  mapped-source:\n"
        "    url: https://github.com/example/mapped-source\n"
        "    docs_url: https://mapped.example.com/docs\n"
        "    manual: true\n"
        "  no-url-source:\n"
        "    manual: true\n"
    )
    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))

    sources_base = opencrane_dir / "sources"
    llmstxt_dir = opencrane_dir / "llmstxt"

    # mapped-source: one markdown file, docs_url will resolve a per-page URL
    mapped_dir = sources_base / "mapped-source"
    mapped_dir.mkdir(parents=True)
    (mapped_dir / "page.md").write_text(
        "# Mapped Page\n\nThis page belongs to the mapped source.\n"
    )

    # no-url-source: markdown files exist, IS in the mapping, but has no url/docs_url
    # → get_source_url() returns None for every file
    no_url_dir = sources_base / "no-url-source"
    no_url_dir.mkdir(parents=True)
    (no_url_dir / "readme.md").write_text(
        "# No-URL Readme\n\nThis source has no url or docs_url in the mapping.\n"
    )
    (no_url_dir / "guide.md").write_text(
        "# No-URL Guide\n\nAnother page from the no-url source.\n"
    )

    orig_cwd = os.getcwd()
    orig_source_mapping = generate_llms_txt._source_mapping
    try:
        os.chdir(tmp_path)
        generate_llms_txt._source_mapping = None

        generate_outputs(
            sources_dirs=[sources_base],
            llmstxt_dir=llmstxt_dir,
            force=True,
        )
    finally:
        os.chdir(orig_cwd)
        generate_llms_txt._source_mapping = orig_source_mapping

    llms_txt_path = llmstxt_dir / "llms.txt"
    assert llms_txt_path.exists(), "llms.txt must be written by generate_outputs"
    llms_txt = llms_txt_path.read_text()

    # The no-url source must still have a section (even if its entry is a placeholder)
    # so block/section counts stay aligned and the mapped source is not poisoned.
    assert "## no-url-source" in llms_txt, (
        "no-url-source section missing from llms.txt — "
        "block/section count mismatch will poison all source_urls"
    )

    # Run the chunker
    chunks_file = tmp_path / "chunks.json"
    try:
        os.chdir(tmp_path)
        generate_llms_txt._source_mapping = None
        chunker_main(llmstxt_dir=llmstxt_dir, chunks_file=chunks_file)
    finally:
        os.chdir(orig_cwd)
        generate_llms_txt._source_mapping = orig_source_mapping

    chunks = ChunkSerializer.deserialize_chunks(chunks_file)
    assert len(chunks) > 0, "No chunks produced"

    # mapped-source chunks must carry their correct per-page source_url
    mapped_chunks = [
        c for c in chunks
        if (c.metadata.get("source_url") or "").startswith("https://mapped.example.com/")
    ]
    assert len(mapped_chunks) > 0, (
        "No chunks with mapped.example.com source_url — "
        "the no-url source poisoned the entire bundle (regression)"
    )
