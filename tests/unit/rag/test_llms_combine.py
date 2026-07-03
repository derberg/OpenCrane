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
