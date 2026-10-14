"""`opencrane llms --sources-dir` runs that rebuild only some sources.

Covers two regressions:

- The combined ``llms.txt`` must keep the real per-page URLs of the sources the
  run did not rebuild. Their bundles are re-appended from ``.opencrane/llmstxt``
  and their index sections come from the per-source companion ``llms.txt``.
- A Git-ignored source directory (``.opencrane/sources/`` usually is) must be
  regenerated when its files change, without ``--force``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import opencrane.rag.generate_llms_txt as gen_mod
from opencrane.rag.chunker import main as chunker_main
from opencrane.rag.generate_llms_txt import FINGERPRINT_FILE_NAME, generate_outputs, write_outputs
from opencrane.rag.services.chunk_serializer import ChunkSerializer
from opencrane.rag.services.llms_index import IndexEntry, LlmsIndex

CONFIG_YAML = (
    "sources:\n"
    "  proj-a:\n"
    "    url: https://github.com/example/proj-a\n"
    "    docs_path: docs\n"
    "    manual: false\n"
    "  proj-b:\n"
    "    url: https://github.com/example/proj-b\n"
    "    docs_path: docs\n"
    "    manual: false\n"
)


@pytest.fixture(autouse=True)
def reset_llms_globals():
    gen_mod._source_mapping = None
    yield
    gen_mod._source_mapping = None


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """Two fetched GitHub sources under .opencrane/sources, cwd set to the workspace."""
    ws = tmp_path / "ws"
    opencrane_dir = ws / ".opencrane"
    sources = opencrane_dir / "sources"
    for name in ("proj-a", "proj-b"):
        (sources / name).mkdir(parents=True)
        (sources / name / "intro.md").write_text(f"# {name} Intro\n\nIntro page of {name}.\n")
        (sources / name / "guide.md").write_text(f"# {name} Guide\n\nGuide page of {name}.\n")
    (opencrane_dir / "config.yaml").write_text(CONFIG_YAML)
    monkeypatch.setenv("MAPPING_FILE", str(opencrane_dir / "config.yaml"))
    monkeypatch.delenv("AI_DOCS_SOURCES_DIRS", raising=False)
    monkeypatch.delenv("AI_DOCS_LLMSTXT_DIR", raising=False)
    monkeypatch.delenv("AI_DOCS_SOURCES_DIR", raising=False)
    monkeypatch.chdir(ws)
    return ws


def _blob(project: str, page: str) -> str:
    return f"https://github.com/example/{project}/blob/main/docs/{page}.md"


@pytest.mark.unit
def test_sources_dir_run_keeps_page_urls_of_other_sources(workspace):
    llmstxt = workspace / ".opencrane" / "llmstxt"
    sources = workspace / ".opencrane" / "sources"

    generate_outputs(force=True)
    gen_mod._source_mapping = None
    generate_outputs(force=True, sources_dirs=[sources / "proj-a"])

    index = LlmsIndex.parse((llmstxt / "llms.txt").read_text())
    assert index.sources() == ["proj-a", "proj-b"]
    assert [e.url for e in index.entries_for("proj-b")] == [
        _blob("proj-b", "guide"),
        _blob("proj-b", "intro"),
    ]
    # One ====== block per ## section, so the chunker's positional join holds.
    assert (llmstxt / "llms-full.txt").read_text().count("\n======\n") == 1

    gen_mod._source_mapping = None
    chunks_file = workspace / ".opencrane" / "chunks.json"
    chunker_main(llmstxt_dir=llmstxt, chunks_file=chunks_file)
    urls = {c.metadata.get("source_url") for c in ChunkSerializer.deserialize_chunks(chunks_file)}
    assert {
        _blob("proj-a", "guide"),
        _blob("proj-a", "intro"),
        _blob("proj-b", "guide"),
        _blob("proj-b", "intro"),
    } <= urls


@pytest.mark.unit
def test_write_outputs_writes_companion_index_per_project(tmp_path):
    entries = [IndexEntry(source="proj", title="Page", url="https://example.com/page")]
    write_outputs(
        {"proj": "# Page\n", "root": "# Root\n", "no-entries": "# Bare\n"},
        tmp_path,
        root_projects={"root"},
        project_entries={"proj": entries, "root": entries},
    )
    companion = LlmsIndex.parse((tmp_path / "proj" / "llms.txt").read_text())
    assert companion.sources() == ["proj"]
    assert companion.entries_for("proj") == entries
    # Root-level markdown has no per-project bundle, so no companion either.
    assert not (tmp_path / "root").exists()
    # Without entries there is nothing to index; the sweep synthesizes them.
    assert (tmp_path / "no-entries" / "llms-full.txt").exists()
    assert not (tmp_path / "no-entries" / "llms.txt").exists()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.mark.unit
def test_ignored_sources_dir_regenerates_when_files_change(workspace, capsys):
    _git(workspace, "init", "-q")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Test")
    (workspace / ".gitignore").write_text(".opencrane/\n")
    _git(workspace, "add", ".gitignore")
    _git(workspace, "commit", "-q", "-m", "init")

    llmstxt = workspace / ".opencrane" / "llmstxt"
    src = workspace / ".opencrane" / "sources" / "proj-a"
    bundle = llmstxt / "llms-full.txt"

    # First run: nothing recorded yet, so the ignored files count as changed.
    generate_outputs(sources_dirs=[src])
    assert "Intro page of proj-a." in bundle.read_text()
    assert (llmstxt / FINGERPRINT_FILE_NAME).exists()

    # Second run without changes: skipped.
    capsys.readouterr()
    gen_mod._source_mapping = None
    generate_outputs(sources_dirs=[src])
    assert "Skipping" in capsys.readouterr().out

    # A changed ignored file triggers regeneration without --force.
    (src / "intro.md").write_text("# proj-a Intro\n\nRewritten intro.\n")
    gen_mod._source_mapping = None
    generate_outputs(sources_dirs=[src])
    assert "Rewritten intro." in bundle.read_text()


@pytest.mark.unit
def test_project_root_as_sources_dir_skips_unchanged_run(workspace, capsys):
    """With ``--sources-dir .`` the output and fingerprint sit inside the hashed tree."""
    _git(workspace, "init", "-q")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Test")
    (workspace / ".gitignore").write_text(".opencrane/\n.venv/\n")
    _git(workspace, "add", ".gitignore")
    _git(workspace, "commit", "-q", "-m", "init")
    (workspace / ".venv" / "lib").mkdir(parents=True)
    (workspace / ".venv" / "lib" / "site.py").write_text("x = 1\n")

    bundle = workspace / ".opencrane" / "llmstxt" / "llms-full.txt"
    generate_outputs(sources_dirs=[Path(".")])
    assert "Intro page of proj-a." in bundle.read_text()

    # Second run without changes: skipped, although the first run wrote the
    # bundles and the fingerprint file under the source dir.
    capsys.readouterr()
    gen_mod._source_mapping = None
    generate_outputs(sources_dirs=[Path(".")])
    assert "Skipping" in capsys.readouterr().out

    # A changed ignored doc file still triggers regeneration.
    (workspace / ".opencrane" / "sources" / "proj-a" / "intro.md").write_text("# proj-a Intro\n\nRewritten intro.\n")
    gen_mod._source_mapping = None
    generate_outputs(sources_dirs=[Path(".")])
    assert "Skipping" not in capsys.readouterr().out
    assert "Rewritten intro." in bundle.read_text()
