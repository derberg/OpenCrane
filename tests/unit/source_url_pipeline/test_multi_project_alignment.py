"""Regression test for the real-world multi-project alignment failure.

A single source_dir containing multiple mapped projects must emit one ``======``
content block PER project so the block count equals the number of
``## {source}`` sections in the companion ``llms.txt``.  Otherwise the chunker's
count-based join detects a mismatch, warns, and falls back to the legacy marker
path — which finds nothing in clean content and drops every ``source_url``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

import opencrane.rag.generate_llms_txt as gen_mod
from opencrane.rag.chunker import main as chunker_main
from opencrane.rag.services.chunk_serializer import ChunkSerializer


def run_pipeline(workspace: Path, config_yaml: str, monkeypatch):
    """Generate + chunk in *workspace*; return (chunks, llms_full, llms_txt)."""
    opencrane_dir = workspace / ".opencrane"
    (opencrane_dir / "config.yaml").write_text(config_yaml)
    sources_base = opencrane_dir / "sources"
    llmstxt_base = opencrane_dir / "llmstxt"

    orig_cwd = os.getcwd()
    orig_mapping = gen_mod._source_mapping
    try:
        os.chdir(workspace)
        gen_mod._source_mapping = None
        monkeypatch.setenv("MAPPING_FILE", str(opencrane_dir / "config.yaml"))
        gen_mod.generate_outputs(
            sources_dirs=[sources_base],
            llmstxt_dir=llmstxt_base,
            force=True,
        )
        gen_mod._source_mapping = None
        chunks_file = opencrane_dir / "chunks.json"
        chunker_main(llmstxt_dir=llmstxt_base, chunks_file=chunks_file)
    finally:
        os.chdir(orig_cwd)
        gen_mod._source_mapping = orig_mapping

    chunks = ChunkSerializer.deserialize_chunks(chunks_file)
    llms_full = (llmstxt_base / "llms-full.txt").read_text()
    llms_txt = (llmstxt_base / "llms.txt").read_text()
    return chunks, llms_full, llms_txt


@pytest.mark.unit
def test_multiple_projects_in_one_source_dir_align(tmp_path, caplog):
    """One source_dir, two mapped projects → two ====== blocks, no legacy fallback.

    Reproduces the 20-sources-but-4-blocks failure in miniature: two projects
    under a single .opencrane/sources dir must produce two ``======`` content
    blocks matching the two ``## {source}`` index sections, so the chunker's
    positional join succeeds and each chunk carries its own per-project URL.
    """
    workspace = tmp_path / "workspace"
    sources_base = workspace / ".opencrane" / "sources"
    (sources_base / "proj-a").mkdir(parents=True)
    (sources_base / "proj-b").mkdir(parents=True)
    (sources_base / "proj-a" / "home.md").write_text(
        "# Alpha Home\nAlpha home page content for testing purposes here.\n"
    )
    (sources_base / "proj-b" / "home.md").write_text(
        "# Beta Home\nBeta home page content for testing purposes here.\n"
    )

    config_yaml = (
        "sources:\n"
        "  proj-a:\n"
        "    url: https://github.com/example/proj-a\n"
        "    docs_url: https://a.example.com/docs\n"
        "    manual: true\n"
        "  proj-b:\n"
        "    url: https://github.com/example/proj-b\n"
        "    docs_url: https://b.example.com/docs\n"
        "    manual: true\n"
    )

    caplog.set_level(logging.WARNING)
    chunks, llms_full, llms_txt = run_pipeline(
        workspace, config_yaml, pytest.MonkeyPatch()
    )

    # (a) The count-mismatch warning must NOT fire (index join path used).
    assert "does not match content" not in caplog.text, (
        "chunker fell back to legacy marker path due to block/section mismatch"
    )
    # There must be a ====== separator between the two projects.
    assert "======" in llms_full, "no ====== separator between per-project blocks"

    # (b) Chunks carry distinct per-project source_urls.
    urls = {c.metadata.get("source_url") for c in chunks}
    assert "https://a.example.com/docs/home" in urls, f"alpha url missing: {urls}"
    assert "https://b.example.com/docs/home" in urls, f"beta url missing: {urls}"
