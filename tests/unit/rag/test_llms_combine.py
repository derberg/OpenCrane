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
    """Create a workspace with pre-existing llms-full.txt files but no sources.yaml entries."""
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    sources_yaml = opencrane_dir / "sources.yaml"
    sources_yaml.write_text("sources:\n")

    # Override MAPPING_FILE so get_source_mapping() uses our empty sources.yaml
    monkeypatch.setenv("MAPPING_FILE", str(sources_yaml))

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
    """When sources.yaml is empty but llmstxt subdirs have files, combine them."""
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
    """When sources.yaml is empty AND no llmstxt subdirs exist, print warning."""
    import shutil
    shutil.rmtree(llmstxt_workspace / ".opencrane" / "llmstxt")

    monkeypatch.chdir(llmstxt_workspace)
    llmstxt_dir = llmstxt_workspace / ".opencrane" / "llmstxt"
    generate_outputs(force=True, llmstxt_dir=llmstxt_dir)

    captured = capsys.readouterr()
    assert "no sources" in captured.out.lower() or "no existing" in captured.out.lower()
    assert not (llmstxt_dir / "llms-full.txt").exists()


@pytest.mark.unit
def test_combine_injects_docs_url_into_headings(llmstxt_workspace, monkeypatch):
    """When a llmstxt source has docs_url, headings get URL prefixes."""
    sources_yaml = llmstxt_workspace / ".opencrane" / "sources.yaml"
    sources_yaml.write_text(
        "sources:\n"
        "  project-a:\n"
        "    type: llmstxt\n"
        "    url: https://example.com/a.txt\n"
        "    docs_url: https://docs.example.com\n"
        "    manual: true\n"
    )
    monkeypatch.setenv("MAPPING_FILE", str(sources_yaml))
    monkeypatch.chdir(llmstxt_workspace)

    llmstxt_dir = llmstxt_workspace / ".opencrane" / "llmstxt"
    generate_outputs(force=True, llmstxt_dir=llmstxt_dir)

    combined = llmstxt_dir / "llms-full.txt"
    content = combined.read_text()
    assert "[https://docs.example.com]" in content
    assert "# [https://docs.example.com] Project A docs" in content


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
