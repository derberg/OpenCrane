"""Tests for opencrane.visualize."""

import io
import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import plotly.graph_objects as go
from click.testing import CliRunner

from opencrane import visualize as viz
from opencrane.cli import main as cli_main


# ---------------------------------------------------------------------------
# Fixtures: tiny realistic corpus + paragraph vector
# ---------------------------------------------------------------------------

CORPUS_SIZE = 6
DIM = 5


@pytest.fixture
def tiny_vectors():
    rng = np.random.default_rng(0)
    return rng.standard_normal((CORPUS_SIZE, DIM)).astype(np.float32)


@pytest.fixture
def tiny_new_vec():
    rng = np.random.default_rng(1)
    return rng.standard_normal(DIM).astype(np.float32)


@pytest.fixture
def tiny_corpus(tiny_vectors):
    sources = ["repo-a", "repo-a", "repo-b", "repo-b", "repo-c", "repo-c"]
    snippets = [f"snippet {i}" for i in range(CORPUS_SIZE)]
    urls = [f"https://example.com/{i}" for i in range(CORPUS_SIZE)]
    return viz.CorpusData(
        model_name="dummy-model",
        vectors=tiny_vectors,
        sources=sources,
        snippets=snippets,
        urls=urls,
    )


@pytest.fixture
def workspace_files(tmp_path, tiny_vectors):
    """Write a minimal embeddings.json + chunks.json to a temp dir."""
    embeddings_data = {
        "model": "dummy-model",
        "dimensions": DIM,
        "created_at": "2026-01-01T00:00:00Z",
        "chunks_sha256": "x" * 64,
        "embeddings": [
            {"chunk_index": i, "chunk_id": f"id{i}", "vector": tiny_vectors[i].tolist()}
            for i in range(CORPUS_SIZE)
        ],
    }
    chunks_data = [
        {
            "chunk_id": "id0",
            "content": "plain string content",
            "source_name": "repo-a",
            "metadata": {"source_url": "https://example.com/0"},
        },
        {
            "chunk_id": "id1",
            "content": {"description": "dict content"},  # dict → JSON-serialized
            "source_name": "repo-a",
            "metadata": {"source_url": "https://example.com/1"},
        },
        {
            "chunk_id": "id2",
            "content": ["list", "content"],
            "source_name": "repo-b",
            "metadata": {"source_url": "https://example.com/2"},
        },
        {
            "chunk_id": "id3",
            "content": None,
            "source_name": "repo-b",
            "metadata": {},
        },
        {
            "chunk_id": "id4",
            "content": "x" * 500,  # exceeds 160-char snippet limit
            "source_name": "repo-c",
            "metadata": {"source_url": "https://example.com/4"},
        },
        # id5 intentionally missing — exercises missing-chunk_id fallback path
    ]
    emb_file = tmp_path / "embeddings.json"
    chunks_file = tmp_path / "chunks.json"
    emb_file.write_text(json.dumps(embeddings_data))
    chunks_file.write_text(json.dumps(chunks_data))
    return emb_file, chunks_file


# ---------------------------------------------------------------------------
# _require: helpful error when a viz dep is missing
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_require_returns_module():
    mod = viz._require("json")
    assert mod is json


@pytest.mark.unit
def test_require_missing_dep_exits():
    with pytest.raises(SystemExit) as exc:
        viz._require("definitely_not_a_real_module_xyz")
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# read_paragraph
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_read_paragraph_inline():
    assert viz.read_paragraph("hello", None) == "hello"


@pytest.mark.unit
def test_read_paragraph_from_file(tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("from file")
    assert viz.read_paragraph(None, str(f)) == "from file"


@pytest.mark.unit
def test_read_paragraph_from_stdin(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("piped paragraph"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    # io.StringIO has no isatty -> attach one
    sys.stdin.isatty = lambda: False  # type: ignore[method-assign]
    try:
        assert viz.read_paragraph(None, None) == "piped paragraph"
    finally:
        # Restore — pytest captures stdin per test anyway
        pass


@pytest.mark.unit
def test_read_paragraph_no_input_raises(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    sys.stdin.isatty = lambda: True  # type: ignore[method-assign]
    with pytest.raises(SystemExit, match="Provide a paragraph"):
        viz.read_paragraph(None, None)


# ---------------------------------------------------------------------------
# load_corpus
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_load_corpus(workspace_files):
    emb_file, chunks_file = workspace_files
    c = viz.load_corpus(emb_file, chunks_file)
    assert c.model_name == "dummy-model"
    assert c.vectors.shape == (CORPUS_SIZE, DIM)
    assert c.full_size == CORPUS_SIZE
    assert c.sample_size == CORPUS_SIZE
    assert c.sources[0] == "repo-a"
    # dict / list / None content all handled
    assert "dict content" in c.snippets[1]
    assert "list" in c.snippets[2]
    assert c.snippets[3] == ""
    # Long content truncated with ellipsis
    assert c.snippets[4].endswith("…")
    # id5 missing from chunks_data → falls back to "unknown" source
    assert c.sources[5] == "unknown"


@pytest.mark.unit
def test_subsample_for_scatter_downsamples(workspace_files):
    """Sampling for scatter always includes the top-K neighbors."""
    emb_file, chunks_file = workspace_files
    full = viz.load_corpus(emb_file, chunks_file)
    neighbor_idx = np.array([0, 2, 4])  # pretend these are top-K
    sub, new_idx = viz.subsample_for_scatter(full, 3, neighbor_idx, seed=42)
    # Subset must include all 3 neighbor positions; size >= 3
    assert len(sub.vectors) >= 3
    # Re-mapped neighbor indices point inside the sliced array
    assert all(0 <= int(i) < len(sub.vectors) for i in new_idx)


@pytest.mark.unit
def test_subsample_for_scatter_returns_full_when_no_sample(workspace_files):
    """sample_size=0 or >= corpus size → original corpus unchanged."""
    emb_file, chunks_file = workspace_files
    full = viz.load_corpus(emb_file, chunks_file)
    neighbor_idx = np.array([0, 1])
    sub, new_idx = viz.subsample_for_scatter(full, 0, neighbor_idx, seed=42)
    assert sub is full
    assert (new_idx == neighbor_idx).all()


# ---------------------------------------------------------------------------
# encode_paragraph (mocked to skip model download)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_encode_paragraph_uses_model():
    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]], dtype=np.float32)
    with patch.object(viz, "_require") as req:
        req.side_effect = lambda name, *args: {"numpy": np, "sentence_transformers": MagicMock()}.get(name, MagicMock())
        with patch("sentence_transformers.SentenceTransformer", return_value=mock_model):
            out = viz.encode_paragraph("dummy-model", "hello world")
    assert out.dtype == np.float32
    assert out.shape == (3,)


# ---------------------------------------------------------------------------
# reduce_dims
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_reduce_dims_pca(tiny_vectors, tiny_new_vec):
    coords, new_coords, info = viz.reduce_dims(tiny_vectors, tiny_new_vec, "pca", 2, 42)
    assert coords.shape == (CORPUS_SIZE, 2)
    assert new_coords.shape == (2,)
    assert "PCA" in info


@pytest.mark.unit
def test_reduce_dims_tsne(tiny_vectors, tiny_new_vec):
    coords, new_coords, info = viz.reduce_dims(tiny_vectors, tiny_new_vec, "tsne", 2, 42)
    assert coords.shape == (CORPUS_SIZE, 2)
    assert new_coords.shape == (2,)
    assert "t-SNE" in info


@pytest.mark.unit
def test_reduce_dims_umap(tiny_vectors, tiny_new_vec):
    # UMAP needs at least n_neighbors+1 points; our tiny corpus is fine
    # because UMAP clips internally. Use a slightly larger corpus.
    rng = np.random.default_rng(0)
    big = rng.standard_normal((50, DIM)).astype(np.float32)
    coords, new_coords, info = viz.reduce_dims(big, tiny_new_vec, "umap", 2, 42)
    assert coords.shape == (50, 2)
    assert new_coords.shape == (2,)
    assert "UMAP" in info


@pytest.mark.unit
def test_reduce_dims_unknown_raises(tiny_vectors, tiny_new_vec):
    with pytest.raises(ValueError, match="Unknown method"):
        viz.reduce_dims(tiny_vectors, tiny_new_vec, "bogus", 2, 42)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_local_density_normalized():
    rng = np.random.default_rng(0)
    pts = rng.standard_normal((30, 3))
    d = viz._local_density(pts, k=5)
    assert d.min() >= 0.2
    assert d.max() <= 1.0
    assert len(d) == 30


@pytest.mark.unit
def test_nearest_neighbors_returns_top_k(tiny_vectors, tiny_new_vec):
    idx, top_sims, all_sims = viz._nearest_neighbors(tiny_vectors, tiny_new_vec, 3)
    assert len(idx) == 3
    assert len(top_sims) == 3
    assert len(all_sims) == CORPUS_SIZE
    # descending order
    assert all(top_sims[i] >= top_sims[i + 1] for i in range(len(top_sims) - 1))


# ---------------------------------------------------------------------------
# figure builders
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_scatter_3d_has_both_colorings(tiny_corpus, tiny_vectors, tiny_new_vec):
    """3D scatter always builds density + per-source traces so the live toggle works."""
    coords, new_coords, _ = viz.reduce_dims(tiny_vectors, tiny_new_vec, "pca", 3, 42)
    idx, sims, _ = viz._nearest_neighbors(tiny_vectors, tiny_new_vec, 2)
    fig = viz._build_scatter_figure(
        coords, new_coords, tiny_corpus, idx, sims, "preview", "info"
    )
    assert isinstance(fig, go.Figure)
    # One density trace + one trace per source + neighbors + your-paragraph
    source_traces = [t for t in fig.data if t.name in {"repo-a", "repo-b", "repo-c"}]
    assert len(source_traces) == 3
    assert any(t.name == "density" for t in fig.data)


@pytest.mark.unit
def test_build_scatter_2d(tiny_corpus, tiny_vectors, tiny_new_vec):
    coords, new_coords, _ = viz.reduce_dims(tiny_vectors, tiny_new_vec, "pca", 2, 42)
    idx, sims, _ = viz._nearest_neighbors(tiny_vectors, tiny_new_vec, 2)
    fig = viz._build_scatter_figure(
        coords, new_coords, tiny_corpus, idx, sims, "preview", "info"
    )
    source_traces = [t for t in fig.data if t.name in {"repo-a", "repo-b", "repo-c"}]
    assert len(source_traces) == 3


@pytest.mark.unit
def test_build_scatter_handles_no_neighbors(tiny_corpus, tiny_vectors, tiny_new_vec):
    coords, new_coords, _ = viz.reduce_dims(tiny_vectors, tiny_new_vec, "pca", 3, 42)
    fig = viz._build_scatter_figure(
        coords, new_coords, tiny_corpus, np.array([], dtype=int),
        np.array([]), "preview", "info",
    )
    # Still has density + sources + paragraph
    assert isinstance(fig, go.Figure)
    assert any(t.name == "your paragraph" for t in fig.data)


@pytest.mark.unit
def test_build_local_neighborhood_empty(tiny_corpus, tiny_new_vec):
    fig = viz._build_local_neighborhood_figure(
        tiny_new_vec, tiny_corpus, np.array([], dtype=int), np.array([]), "preview"
    )
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0


@pytest.mark.unit
def test_build_local_neighborhood_with_data(tiny_corpus, tiny_vectors, tiny_new_vec):
    idx, sims, _ = viz._nearest_neighbors(tiny_vectors, tiny_new_vec, 4)
    fig = viz._build_local_neighborhood_figure(
        tiny_new_vec, tiny_corpus, idx, sims, "preview"
    )
    assert isinstance(fig, go.Figure)
    # guide-lines trace + per-source traces + paragraph
    assert any(t.name == "your paragraph" for t in fig.data)


@pytest.mark.unit
def test_build_sources_figure(tiny_corpus, tiny_vectors, tiny_new_vec):
    _, _, all_sims = viz._nearest_neighbors(tiny_vectors, tiny_new_vec, 1)
    fig = viz._build_sources_figure(tiny_corpus.sources, all_sims, top_n=2)
    assert isinstance(fig, go.Figure)
    # bar + scatter overlay
    assert len(fig.data) == 2


# ---------------------------------------------------------------------------
# _write_combined_html
# ---------------------------------------------------------------------------

def _basic_ctx(top_sim=0.6, top_source="repo-x", top_snippet="snippet"):
    """Minimal context dict for _write_combined_html tests."""
    return dict(
        paragraph_preview="preview text",
        model_name="dummy-model",
        full_size=500,
        sample_size=100,
        top_sim=top_sim,
        top_source=top_source,
        top_snippet=top_snippet,
        neighbor_count=12,
        unique_neighbor_sources=3,
        info="test info",
        verdict=viz._verdict_data(top_sim),
    )


@pytest.mark.unit
def test_write_combined_html(tmp_path):
    fig = go.Figure(data=[go.Scatter(x=[1, 2], y=[3, 4])])
    out = tmp_path / "out.html"
    viz._write_combined_html([("Title", fig, "scatter")], out, _basic_ctx())
    body = out.read_text()
    assert "<!doctype html>" in body
    # Bento-grid hero — brand + theme toggle present
    assert "OpenCrane" in body
    assert 'class="strip"' in body
    assert "theme-toggle" in body
    assert "brand-icon" in body
    assert 'class="bento"' in body
    # Verdict label appears (bento score cell)
    assert "RELATED, NOT DUPLICATE" in body
    # Stats strip cards
    assert "Neighbors" in body
    assert "Corpus sample" in body
    # How-to-read strip (three uses)
    assert "How to read this" in body
    # Glossary / per-chart helpers
    assert "Cosine similarity" in body
    assert "How to read this chart" in body
    assert "What it helps with" in body
    # Inline CSS-based tooltips
    assert 'class="tip"' in body
    assert "data-tip=" in body
    # Chart section
    assert "Title" in body


@pytest.mark.unit
def test_load_logo_b64_missing_file(monkeypatch, tmp_path):
    """When the bundled logo file is missing, _load_logo_b64 returns empty string."""
    monkeypatch.setattr(viz, "_LOGO_B64_PATH", tmp_path / "definitely-not-here.b64")
    assert viz._load_logo_b64() == ""


@pytest.mark.unit
@pytest.mark.parametrize(
    "top_sim, expected_label, expected_level",
    [
        (0.95, "LIKELY DUPLICATE", "danger"),
        (0.80, "VERY STRONGLY RELATED", "warning"),
        (0.60, "RELATED, NOT DUPLICATE", "ok"),
        (0.40, "LIKELY NEW CONTENT", "fresh"),
        (0.10, "OUT OF DISTRIBUTION", "ood"),
    ],
)
def test_verdict_data_thresholds(top_sim, expected_label, expected_level):
    v = viz._verdict_data(top_sim)
    assert v["label"] == expected_label
    assert v["level"] == expected_level
    assert "hook" in v


@pytest.mark.unit
def test_write_combined_html_truncates_long_text(tmp_path):
    """Paragraph and neighbor snippets >280 chars are clipped with ellipsis."""
    fig = go.Figure(data=[go.Scatter(x=[1], y=[1])])
    out = tmp_path / "out.html"
    ctx = _basic_ctx()
    ctx["paragraph_preview"] = "x" * 500
    ctx["top_snippet"] = "y" * 500
    viz._write_combined_html([("Title", fig, "scatter")], out, ctx)
    body = out.read_text()
    assert "&hellip;" in body


@pytest.mark.unit
def test_write_combined_html_unknown_viz_key_skips_help(tmp_path):
    """Unknown viz_key just omits the per-chart help block — still writes the page."""
    fig = go.Figure(data=[go.Scatter(x=[1, 2], y=[3, 4])])
    out = tmp_path / "out.html"
    viz._write_combined_html([("Title", fig, "unknown_viz")], out, _basic_ctx())
    body = out.read_text()
    # Glossary still present; per-chart caption + help missing for unknown viz_key
    assert "Deep-dive glossary" in body
    assert "How to read this chart" not in body


# ---------------------------------------------------------------------------
# main() end-to-end with mocked model
# ---------------------------------------------------------------------------

@pytest.fixture
def patched_encode(tiny_new_vec):
    """Replace encode_paragraph so tests don't download a real model."""
    with patch.object(viz, "encode_paragraph", return_value=tiny_new_vec) as p:
        yield p


@pytest.mark.unit
def test_main_missing_embeddings_exits(tmp_path, patched_encode):
    with pytest.raises(SystemExit) as exc:
        viz.main(text="hello", embeddings_file=tmp_path / "nope.json",
                 chunks_file=tmp_path / "chunks.json", output=tmp_path / "out.html")
    assert exc.value.code == 1


@pytest.mark.unit
def test_main_missing_chunks_exits(tmp_path, patched_encode):
    emb = tmp_path / "e.json"
    emb.write_text("{}")
    with pytest.raises(SystemExit) as exc:
        viz.main(text="hello", embeddings_file=emb,
                 chunks_file=tmp_path / "nope.json", output=tmp_path / "out.html")
    assert exc.value.code == 1


@pytest.mark.unit
def test_main_empty_paragraph_raises(tmp_path, workspace_files, patched_encode):
    emb_file, chunks_file = workspace_files
    with pytest.raises(SystemExit, match="Empty paragraph"):
        viz.main(text="   ", embeddings_file=emb_file, chunks_file=chunks_file,
                 output=tmp_path / "out.html", open_browser=False)


@pytest.mark.unit
def test_main_dim_mismatch_raises(tmp_path, workspace_files):
    emb_file, chunks_file = workspace_files
    bad_vec = np.zeros(DIM + 1, dtype=np.float32)  # wrong dimension
    with patch.object(viz, "encode_paragraph", return_value=bad_vec):
        with pytest.raises(SystemExit, match="Dimension mismatch"):
            viz.main(text="hello", embeddings_file=emb_file, chunks_file=chunks_file,
                     output=tmp_path / "out.html", open_browser=False)


@pytest.mark.unit
def test_main_all_viz_writes_combined_html(tmp_path, workspace_files, patched_encode):
    emb_file, chunks_file = workspace_files
    out = tmp_path / "out.html"
    result = viz.main(
        text="hello",
        embeddings_file=emb_file,
        chunks_file=chunks_file,
        output=out,
        method="pca",  # avoid loading UMAP
        dim=2,
        viz="all",
        sample=4,
        neighbors=2,
        open_browser=False,
    )
    assert result == out
    assert out.exists()
    body = out.read_text()
    assert "OpenCrane" in body
    assert "Local neighborhood" in body
    # Combined HTML includes the appendix-glossary, captions, and per-chart help
    assert "field glossary" in body
    assert "Cosine similarity" in body
    # Inline always-visible captions for each viz
    assert "Each small dot is one" in body
    # "What it helps with" debug-oriented boxes per chart
    assert "What it helps with" in body
    assert "chunking-quality debugging" in body
    assert "Debug chunking" in body
    # Three-use-case strip including the RAG retrieval testing case
    assert "How to read this" in body
    assert "Test RAG retrieval" in body


@pytest.mark.unit
def test_main_single_viz_writes_html(tmp_path, workspace_files, patched_encode):
    emb_file, chunks_file = workspace_files
    out = tmp_path / "out.html"
    viz.main(
        text="hello",
        embeddings_file=emb_file,
        chunks_file=chunks_file,
        output=out,
        method="pca",
        dim=3,
        viz="scatter",
        sample=0,
        neighbors=2,
        open_browser=False,
    )
    assert out.exists()


@pytest.mark.unit
def test_main_neighbors_viz_only(tmp_path, workspace_files, patched_encode):
    emb_file, chunks_file = workspace_files
    out = tmp_path / "out.html"
    viz.main(
        text="hello", embeddings_file=emb_file, chunks_file=chunks_file,
        output=out, viz="neighbors", sample=0, neighbors=3, open_browser=False,
    )
    assert out.exists()


@pytest.mark.unit
def test_main_sources_viz_only(tmp_path, workspace_files, patched_encode):
    emb_file, chunks_file = workspace_files
    out = tmp_path / "out.html"
    viz.main(
        text="hello", embeddings_file=emb_file, chunks_file=chunks_file,
        output=out, viz="sources", sample=0, neighbors=3, open_browser=False,
    )
    assert out.exists()


@pytest.mark.unit
def test_main_opens_browser(tmp_path, workspace_files, patched_encode):
    emb_file, chunks_file = workspace_files
    out = tmp_path / "out.html"
    with patch.object(viz.webbrowser, "open") as mock_open:
        viz.main(text="hello", embeddings_file=emb_file, chunks_file=chunks_file,
                 output=out, method="pca", viz="scatter", sample=0, neighbors=2,
                 open_browser=True)
    assert mock_open.called


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_cli_visualize_invokes_main(tmp_path, workspace_files, patched_encode):
    emb_file, chunks_file = workspace_files
    out = tmp_path / "out.html"
    runner = CliRunner()
    result = runner.invoke(cli_main, [
        "visualize",
        "--text", "hello",
        "--embeddings-file", str(emb_file),
        "--chunks-file", str(chunks_file),
        "--output", str(out),
        "--method", "pca",
        "--dim", "2",
        "--viz", "scatter",
        "--sample", "0",
        "--neighbors", "2",
        "--no-open",
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()


@pytest.mark.unit
def test_cli_visualize_with_file_input(tmp_path, workspace_files, patched_encode):
    emb_file, chunks_file = workspace_files
    out = tmp_path / "out.html"
    paragraph_file = tmp_path / "para.txt"
    paragraph_file.write_text("from file")
    runner = CliRunner()
    result = runner.invoke(cli_main, [
        "visualize",
        "--file", str(paragraph_file),
        "--embeddings-file", str(emb_file),
        "--chunks-file", str(chunks_file),
        "--output", str(out),
        "--method", "pca",
        "--viz", "scatter",
        "--sample", "0",
        "--neighbors", "2",
        "--no-open",
    ])
    assert result.exit_code == 0, result.output


@pytest.mark.unit
def test_cli_visualize_handles_error(tmp_path):
    """Non-SystemExit exception is caught and reported via _error."""
    runner = CliRunner()
    with patch("opencrane.visualize.main", side_effect=RuntimeError("boom")):
        result = runner.invoke(cli_main, [
            "visualize", "--text", "hello", "--no-open",
        ])
    assert result.exit_code == 1
    assert "boom" in result.output


@pytest.mark.unit
def test_cli_visualize_propagates_sysexit(tmp_path):
    """SystemExit (e.g. missing files) is re-raised cleanly."""
    runner = CliRunner()
    result = runner.invoke(cli_main, [
        "visualize",
        "--text", "hello",
        "--embeddings-file", str(tmp_path / "missing.json"),
        "--no-open",
    ])
    assert result.exit_code == 1
