"""Interactive 3D/2D visualization of where a paragraph lands in embedding space.

Given a paragraph, encode it with the same model used for the corpus, project
both the corpus sample and the new point into low dimensions, and render an
interactive Plotly HTML page with three views:

1. Global scatter (PCA / UMAP / t-SNE), with corpus + nearest neighbors + new point.
2. Local neighborhood map (PCA on paragraph + top-K only) — every point has
   real coordinates so distances among neighbors carry meaning.
3. Per-source alignment bar chart — mean cosine similarity of top-N chunks
   from each source repo, answering "which docs does this paragraph fit best?"

Optional dependencies (install via ``pip install opencrane[viz]``):
- plotly
- umap-learn  (only required if --method=umap)
- scikit-learn  (PCA, t-SNE, NearestNeighbors)
"""

from __future__ import annotations

import json
import logging
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDINGS_FILE = Path(".opencrane/embeddings.json")
DEFAULT_CHUNKS_FILE = Path(".opencrane/chunks.json")
DEFAULT_OUTPUT_FILE = Path(".opencrane/visualization.html")

VIZ_DEPS_HINT = (
    "Visualization requires extra dependencies. Install with:\n"
    "    pip install 'opencrane[viz]'"
)


def _require(module_name: str, install_hint: str = VIZ_DEPS_HINT):
    """Import a module or raise SystemExit with an install hint."""
    try:
        return __import__(module_name)
    except ImportError as e:
        logger.error("Missing dependency '%s': %s", module_name, e)
        logger.error(install_hint)
        sys.exit(1)


@dataclass
class CorpusData:
    model_name: str
    vectors: Any  # numpy array, lazily-typed because numpy is also optional
    sources: list[str]
    snippets: list[str]
    urls: list[str]
    # Bookkeeping for the UI: how many chunks are in the corpus total, and
    # how many we kept after sampling. These two numbers let the page tell
    # the user whether the top-neighbor search ran on the full corpus or
    # only a sample.
    full_size: int = 0
    sample_size: int = 0


def read_paragraph(text: str | None, file: str | None) -> str:
    """Resolve paragraph from --text, --file, or stdin."""
    if text:
        return text
    if file:
        return Path(file).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("Provide a paragraph via --text, --file, or stdin.")


def load_corpus(embeddings_file: Path, chunks_file: Path) -> CorpusData:
    """Load the full corpus — every chunk, every embedding.

    Sampling is no longer done here. Neighbor finding always runs on the full
    corpus so the top-K match is the genuine top-K, not a sample-limited
    approximation. The scatter view does its own downsampling later via
    :func:`subsample_for_scatter`.
    """
    np = _require("numpy")

    logger.info("Loading embeddings from %s", embeddings_file)
    with embeddings_file.open() as f:
        emb_data = json.load(f)
    model_name = emb_data["model"]
    records = emb_data["embeddings"]
    logger.info("Loaded %d embeddings (model=%s, dim=%d)",
                len(records), model_name, emb_data["dimensions"])

    logger.info("Loading chunks from %s", chunks_file)
    with chunks_file.open() as f:
        chunks = json.load(f)
    chunk_by_id = {c["chunk_id"]: c for c in chunks}

    vectors = np.array([r["vector"] for r in records], dtype=np.float32)
    sources, snippets, urls = [], [], []
    for r in records:
        c = chunk_by_id.get(r["chunk_id"], {})
        sources.append(c.get("source_name", "unknown"))
        raw = c.get("content")
        text = raw if isinstance(raw, str) else json.dumps(raw, default=str) if raw is not None else ""
        snippet = text[:160].replace("\n", " ")
        snippets.append(snippet + ("…" if len(text) > 160 else ""))
        urls.append((c.get("metadata") or {}).get("source_url", ""))

    n = len(records)
    return CorpusData(model_name=model_name, vectors=vectors,
                      sources=sources, snippets=snippets, urls=urls,
                      full_size=n, sample_size=n)


def subsample_for_scatter(corpus: CorpusData, sample_size: int,
                          neighbor_idx, seed: int):
    """Build a smaller CorpusData for the scatter plot.

    Always includes the top-K neighbors so their teal rings stay visible.
    Returns ``(scatter_corpus, neighbor_idx_in_scatter)``.
    """
    np = _require("numpy")
    n = corpus.full_size
    if not sample_size or sample_size >= n:
        # No sampling — use the full corpus. neighbor_idx unchanged.
        return corpus, neighbor_idx

    rng = np.random.default_rng(seed)
    base = rng.choice(n, size=sample_size, replace=False)
    keep = np.unique(np.concatenate([base, np.asarray(neighbor_idx)]))
    # Re-map full-corpus indices to positions in the sliced arrays.
    full_to_slice = {int(orig): int(pos) for pos, orig in enumerate(keep)}
    new_neighbor_idx = np.array([full_to_slice[int(i)] for i in neighbor_idx])

    sliced = CorpusData(
        model_name=corpus.model_name,
        vectors=corpus.vectors[keep],
        sources=[corpus.sources[int(i)] for i in keep],
        snippets=[corpus.snippets[int(i)] for i in keep],
        urls=[corpus.urls[int(i)] for i in keep],
        full_size=n,
        sample_size=len(keep),
    )
    logger.info("Scatter sample: %d / %d corpus points (incl. %d neighbors)",
                len(keep), n, len(neighbor_idx))
    return sliced, new_neighbor_idx


def encode_paragraph(model_name: str, paragraph: str):
    """Encode a single paragraph using the same model as the corpus."""
    np = _require("numpy")
    _require("sentence_transformers")
    from sentence_transformers import SentenceTransformer

    logger.info("Loading model %s (CPU)…", model_name)
    model = SentenceTransformer(model_name, trust_remote_code=True, device="cpu")
    logger.info("Encoding paragraph (%d chars)…", len(paragraph))
    vec = model.encode([paragraph], show_progress_bar=False)[0]
    return np.asarray(vec, dtype=np.float32)


def reduce_dims(vectors, new_vec, method: str, dim: int, seed: int):
    """Project corpus + new point into ``dim`` dimensions.

    Returns ``(coords, new_point_coords, info_string)``.
    """
    np = _require("numpy")
    _require("sklearn")

    if method == "pca":
        from sklearn.decomposition import PCA
        logger.info("Fitting PCA(%d) on %d corpus vectors…", dim, len(vectors))
        pca = PCA(n_components=dim, random_state=seed)
        coords = pca.fit_transform(vectors)
        new_coords = pca.transform(new_vec.reshape(1, -1))[0]
        pct = pca.explained_variance_ratio_.sum() * 100
        info = f"PCA keeps about {pct:.0f}% of the meaning-differences"
        return coords, new_coords, info

    if method == "umap":
        umap_module = _require("umap",
            "UMAP requires umap-learn. Install with: pip install 'opencrane[viz]'")
        logger.info("Fitting UMAP(%d) on %d corpus vectors…", dim, len(vectors))
        reducer = umap_module.UMAP(
            n_components=dim, n_neighbors=30, min_dist=0.05,
            metric="cosine", random_state=seed,
        )
        coords = reducer.fit_transform(vectors)
        new_coords = reducer.transform(new_vec.reshape(1, -1))[0]
        return coords, new_coords, "UMAP keeps similar texts close; global distances aren't preserved"

    if method == "tsne":
        from sklearn.manifold import TSNE
        logger.info("Fitting t-SNE(%d) on %d vectors (slow)…", dim, len(vectors) + 1)
        # t-SNE doesn't support out-of-sample transform — include new point in fit.
        combined = np.vstack([vectors, new_vec.reshape(1, -1)])
        perplexity = min(30, max(5, len(vectors) // 100))
        tsne = TSNE(
            n_components=dim, perplexity=perplexity, metric="cosine",
            init="pca", learning_rate="auto", random_state=seed,
        )
        all_coords = tsne.fit_transform(combined)
        return (all_coords[:-1], all_coords[-1],
                "t-SNE keeps clusters tight; distances aren't preserved")

    raise ValueError(f"Unknown method: {method}")


def _local_density(points, k: int = 20):
    """Inverse mean distance to k nearest neighbors — higher means denser.

    Output normalized to [0.2, 1.0] so even low-density points stay visible
    against a white-or-dark background.
    """
    np = _require("numpy")
    from sklearn.neighbors import NearestNeighbors
    k = min(k, len(points) - 1)
    nn = NearestNeighbors(n_neighbors=k + 1).fit(points)
    dists, _ = nn.kneighbors(points)
    mean_d = dists[:, 1:].mean(axis=1)
    density = 1.0 / (mean_d + 1e-9)
    p_lo, p_hi = np.percentile(density, [2, 98])
    normalized = np.clip((density - p_lo) / (p_hi - p_lo + 1e-9), 0, 1)
    return 0.2 + 0.8 * normalized


def _nearest_neighbors(vectors, new_vec, k: int):
    """Cosine-similarity ranking of corpus vectors against ``new_vec``."""
    np = _require("numpy")
    corpus_norm = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9)
    new_norm = new_vec / (np.linalg.norm(new_vec) + 1e-9)
    sims = corpus_norm @ new_norm
    k_eff = min(k, len(sims))
    idx = np.argpartition(-sims, k_eff - 1)[:k_eff]
    idx = idx[np.argsort(-sims[idx])]
    return idx, sims[idx], sims


def _build_scatter_figure(coords, new_coords, corpus: CorpusData,
                          neighbor_idx, neighbor_sims, paragraph_preview: str, info: str):
    _require("plotly")
    import plotly.graph_objects as go

    dim = coords.shape[1]
    hover = [
        f"<b>{src}</b><br>{snip}<br><i>{url}</i>"
        for src, snip, url in zip(corpus.sources, corpus.snippets, corpus.urls)
    ]
    xs_all = coords[:, 0].tolist()
    ys_all = coords[:, 1].tolist()
    zs_all = coords[:, 2].tolist() if dim == 3 else None

    def _scatter(x, y, z=None, **kw):
        return go.Scatter3d(x=x, y=y, z=z, **kw) if z is not None else go.Scatter(x=x, y=y, **kw)

    base_size = 7 if dim == 2 else 5
    traces = []
    # Always start in density mode; the in-chart toggle switches to per-source.
    density_initially_visible = True

    # Always build BOTH colorings so the user can toggle via Plotly's updatemenu.
    # Trace 0 = density-colored single trace. Traces 1..N = per-source traces.
    density = _local_density(coords).tolist()
    density_marker = dict(
        size=base_size, color=density, colorscale="Plasma",
        cmin=0.0, cmax=1.0, opacity=0.9,
        colorbar=dict(title="density", thickness=12, len=0.6),
    )
    kw = dict(mode="markers", marker=density_marker, text=hover,
              hoverinfo="text", name="density", visible=density_initially_visible,
              showlegend=False)
    if dim == 3:
        traces.append(_scatter(xs_all, ys_all, zs_all, **kw))
    else:
        traces.append(_scatter(xs_all, ys_all, **kw))

    unique_sources = sorted(set(corpus.sources))
    for src in unique_sources:
        mask = [s == src for s in corpus.sources]
        xs_m = [x for x, m in zip(xs_all, mask) if m]
        ys_m = [y for y, m in zip(ys_all, mask) if m]
        kw = dict(
            mode="markers",
            marker=dict(size=base_size, opacity=0.9),
            text=[h for h, m in zip(hover, mask) if m],
            hoverinfo="text", name=src,
            visible=not density_initially_visible,
            legendgroup="sources",
        )
        if dim == 3:
            zs_m = [z for z, m in zip(zs_all, mask) if m]
            traces.append(_scatter(xs_m, ys_m, zs_m, **kw))
        else:
            traces.append(_scatter(xs_m, ys_m, **kw))

    n_density_traces = 1
    n_source_traces = len(unique_sources)

    if len(neighbor_idx) > 0:
        nn_text = [
            f"#{rank+1} sim={sim:.3f}<br><b>{corpus.sources[int(i)]}</b><br>{corpus.snippets[int(i)]}"
            for rank, (i, sim) in enumerate(zip(neighbor_idx, neighbor_sims))
        ]
        nn_x = [float(coords[int(i), 0]) for i in neighbor_idx]
        nn_y = [float(coords[int(i), 1]) for i in neighbor_idx]
        kw = dict(
            mode="markers",
            marker=dict(size=10, color="#00b4a8", symbol="circle",
                        line=dict(color="black", width=1)),
            text=nn_text, hoverinfo="text", name="nearest neighbors",
        )
        if dim == 3:
            nn_z = [float(coords[int(i), 2]) for i in neighbor_idx]
            traces.append(_scatter(nn_x, nn_y, nn_z, **kw))
        else:
            traces.append(_scatter(nn_x, nn_y, **kw))

    kw = dict(
        mode="markers+text",
        marker=dict(size=16, color="#ff2a6d", symbol="diamond",
                    line=dict(color="black", width=2)),
        text=["YOUR PARAGRAPH"], textposition="top center",
        textfont=dict(color="#ff2a6d", size=13),
        hovertext=[f"<b>YOUR PARAGRAPH</b><br>{paragraph_preview}"],
        hoverinfo="text", name="your paragraph",
    )
    if dim == 3:
        traces.append(_scatter([float(new_coords[0])], [float(new_coords[1])],
                               [float(new_coords[2])], **kw))
    else:
        traces.append(_scatter([float(new_coords[0])], [float(new_coords[1])], **kw))

    fig = go.Figure(data=traces)

    # Build visibility arrays for the two coloring modes.
    # Trace order: [density, src1, src2, …, neighbors, your_paragraph]
    total = n_density_traces + n_source_traces + (1 if len(neighbor_idx) > 0 else 0) + 1
    vis_density = [True] + [False] * n_source_traces + [True] * (total - 1 - n_source_traces)
    vis_source = [False] + [True] * n_source_traces + [True] * (total - 1 - n_source_traces)

    layout = dict(
        title=f"Where your paragraph lands · {info}",
        template="plotly_white",
        margin=dict(l=0, r=0, t=80, b=0),
        legend=dict(itemsizing="constant"),
        height=700,
        updatemenus=[dict(
            type="buttons", direction="right",
            x=0.005, y=1.08, xanchor="left", yanchor="top",
            pad=dict(r=4, t=4, b=4, l=4),
            bgcolor="#f5eedd",
            bordercolor="#d6cdb6",
            font=dict(size=11, color="#1c1310", family="Inter, system-ui, sans-serif"),
            active=0,  # density view by default; user can toggle live.
            showactive=True,
            buttons=[
                dict(label="◐ density", method="update",
                     args=[{"visible": vis_density},
                           {"showlegend": False}]),
                dict(label="◑ by source", method="update",
                     args=[{"visible": vis_source},
                           {"showlegend": True}]),
            ],
        )],
    )
    if dim == 3:
        layout["scene"] = dict(xaxis_title="dim 1", yaxis_title="dim 2",
                               zaxis_title="dim 3", bgcolor="#ffffff")
        layout["showlegend"] = not density_initially_visible
    else:
        layout["xaxis_title"] = "dim 1"
        layout["yaxis_title"] = "dim 2"
        layout["plot_bgcolor"] = "#ffffff"
        layout["showlegend"] = not density_initially_visible
    fig.update_layout(**layout)
    return fig


def _build_local_neighborhood_figure(new_vec, corpus: CorpusData, neighbor_idx,
                                     neighbor_sims, paragraph_preview: str):
    """Local PCA(2) on paragraph + top-K — every point gets real coordinates."""
    np = _require("numpy")
    _require("plotly")
    from sklearn.decomposition import PCA
    import plotly.graph_objects as go

    n = len(neighbor_idx)
    if n == 0:
        return go.Figure()

    nbr_vectors = corpus.vectors[neighbor_idx]
    stacked = np.vstack([new_vec.reshape(1, -1), nbr_vectors])
    pca = PCA(n_components=2)
    coords = pca.fit_transform(stacked)
    pct = pca.explained_variance_ratio_.sum() * 100
    info = f"keeps about {pct:.0f}% of the meaning-differences (much more than the global view)"
    para_xy, nbr_xy = coords[0], coords[1:]

    palette = [
        "#636efa", "#ef553b", "#00cc96", "#ab63fa", "#ffa15a",
        "#19d3f3", "#ff6692", "#b6e880", "#ff97ff", "#fecb52",
    ]
    src_set = sorted({corpus.sources[int(i)] for i in neighbor_idx})
    source_to_color = {src: palette[i % len(palette)] for i, src in enumerate(src_set)}

    fig = go.Figure()

    # Faint guide lines from paragraph to each neighbor.
    line_x, line_y = [], []
    for xy in nbr_xy:
        line_x.extend([float(para_xy[0]), float(xy[0]), None])
        line_y.extend([float(para_xy[1]), float(xy[1]), None])
    fig.add_trace(go.Scatter(
        x=line_x, y=line_y, mode="lines",
        line=dict(color="rgba(0,0,0,0.15)", width=1),
        hoverinfo="skip", showlegend=False,
    ))

    for src in src_set:
        ranks = [rank for rank, i in enumerate(neighbor_idx) if corpus.sources[int(i)] == src]
        xs = [float(nbr_xy[r, 0]) for r in ranks]
        ys = [float(nbr_xy[r, 1]) for r in ranks]
        labels = [f"#{r+1}" for r in ranks]
        hover = [
            f"#{r+1} sim={neighbor_sims[r]:.3f}<br>"
            f"<b>{corpus.sources[int(neighbor_idx[r])]}</b><br>"
            f"{corpus.snippets[int(neighbor_idx[r])]}<br>"
            f"<i>{corpus.urls[int(neighbor_idx[r])]}</i>"
            for r in ranks
        ]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers+text",
            marker=dict(size=22, color=source_to_color[src],
                        line=dict(color="black", width=1.5)),
            text=labels, textposition="top center",
            textfont=dict(size=12, color="#222"),
            hovertext=hover, hoverinfo="text", name=src,
        ))

    fig.add_trace(go.Scatter(
        x=[float(para_xy[0])], y=[float(para_xy[1])],
        mode="markers+text",
        marker=dict(size=26, color="#ff2a6d", symbol="diamond",
                    line=dict(color="black", width=2)),
        text=["YOUR PARAGRAPH"], textposition="bottom center",
        textfont=dict(color="#ff2a6d", size=13),
        hovertext=[
            f"<b>YOUR PARAGRAPH</b><br>"
            f"position: ({para_xy[0]:.2f}, {para_xy[1]:.2f})<br>{paragraph_preview}"
        ],
        hoverinfo="text", name="your paragraph",
    ))
    fig.update_layout(
        title=f"Local neighborhood · {info}",
        template="plotly_white",
        xaxis=dict(title="PC1 (local) — main direction of variation",
                   zeroline=False),
        yaxis=dict(title="PC2 (local) — second main direction",
                   zeroline=False, scaleanchor="x", scaleratio=1),
        height=650,
        margin=dict(l=60, r=60, t=60, b=60),
        plot_bgcolor="#ffffff",
        legend=dict(title="source repo", itemsizing="constant"),
    )
    return fig


def _build_sources_figure(sources: list[str], all_sims, top_n: int = 30):
    """Per-source alignment bar chart — mean of top-N similarities per repo."""
    np = _require("numpy")
    _require("plotly")
    import plotly.graph_objects as go

    by_source: dict[str, list[float]] = {}
    for src, sim in zip(sources, all_sims):
        by_source.setdefault(src, []).append(float(sim))

    stats = []
    for src, sims in by_source.items():
        sims_sorted = sorted(sims, reverse=True)
        head = sims_sorted[: min(top_n, len(sims_sorted))]
        stats.append((src, float(np.mean(head)), float(max(sims_sorted)), len(sims_sorted)))
    stats.sort(key=lambda x: x[1], reverse=True)

    names = [s[0] for s in stats]
    mean_sim = [s[1] for s in stats]
    max_sim = [s[2] for s in stats]
    counts = [s[3] for s in stats]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=names, x=mean_sim, orientation="h",
        marker=dict(color=mean_sim, colorscale="Plasma",
                    colorbar=dict(title="mean sim", thickness=12, len=0.6)),
        name=f"mean of top-{top_n}",
        hovertemplate=f"<b>%{{y}}</b><br>mean(top-{top_n})=%{{x:.3f}}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        y=names, x=max_sim, mode="markers",
        marker=dict(symbol="line-ns", size=18, color="#00b4a8",
                    line=dict(width=3, color="#00b4a8")),
        name="max similarity",
        hovertext=[f"chunks sampled: {c}" for c in counts],
        hovertemplate="<b>%{y}</b><br>max sim=%{x:.3f}<br>%{hovertext}<extra></extra>",
    ))
    fig.update_layout(
        title=f"Per-source alignment · mean cosine sim of top-{top_n} chunks",
        template="plotly_white",
        xaxis_title="cosine similarity (0 = unrelated → 1 = duplicate)",
        yaxis=dict(autorange="reversed"),
        margin=dict(l=180, r=40, t=60, b=40),
        plot_bgcolor="#ffffff",
        legend=dict(orientation="h", y=-0.1),
    )
    return fig


# ── In-HTML help text ─────────────────────────────────────────────────────── #
# Plain-language explanations rendered inside the generated HTML so anyone can
# understand the visualization without reading external docs.

GLOSSARY_HTML = """
<details class="help">
  <summary><strong>Deep-dive glossary</strong> &mdash; click to expand if a term is unclear</summary>
  <div class="help-body">
    <p>This page shows where your paragraph "lands" relative to all the documentation
    that's already indexed. It answers three questions:
    <em>which existing docs are most similar?</em>,
    <em>which docs repo does this fit best?</em>, and
    <em>is this content novel or already well-covered?</em></p>

    <p>Below is every term you'll see on this page, with what it means, why it's there,
    what you can read from it, and how it helps your work.</p>

    <details class="term">
      <summary><strong>Embedding</strong>
        <span class="tagline">&mdash; the "meaning fingerprint" of a text</span></summary>
      <div class="term-body">
        <p><strong>What it is:</strong> Every piece of text is converted by a language
        model into a list of 768 numbers (a "vector"). Texts about similar topics produce
        similar lists. The actual numbers are arbitrary &mdash; only relative similarity
        matters.</p>
        <p><strong>Why it's here:</strong> Computers can't compare "meanings" directly,
        but they can compare lists of numbers. Embeddings are how we turn "is this text
        similar to that text?" into "are these two vectors pointing in similar directions?"</p>
        <p><strong>What you can read from it:</strong> Nothing directly &mdash; you never
        see the 768 numbers. They power every other quantity on this page.</p>
        <p><strong>How it helps:</strong> The whole search-and-similarity system that
        backs RAG / MCP is built on embeddings. If you trust the embeddings, you can
        trust the rankings.</p>
      </div>
    </details>

    <details class="term">
      <summary><strong>Cosine similarity</strong>
        <span class="tagline">&mdash; the headline number, from &minus;1 to 1</span></summary>
      <div class="term-body">
        <p><strong>What it is:</strong> A score that measures how aligned two embedding
        vectors are. <strong>1.0</strong> = identical meaning, <strong>0</strong> =
        unrelated, <strong>&minus;1</strong> = opposite. It compares <em>direction</em>,
        not magnitude.</p>
        <p><strong>Why it's here:</strong> It's the single most reliable indicator of
        "are these two pieces of text about the same thing?" You'll see it on hover for
        every dot, and in the "Top nearest neighbors" terminal output.</p>
        <p><strong>What you can read from it (rough guide for these docs):</strong></p>
        <ul>
          <li><strong>0.90&ndash;1.00</strong> &mdash; effectively duplicate; the
          neighbor chunk likely says the same thing.</li>
          <li><strong>0.75&ndash;0.90</strong> &mdash; very strongly related;
          same topic, possibly different angle.</li>
          <li><strong>0.55&ndash;0.75</strong> &mdash; related; shares concepts or
          vocabulary.</li>
          <li><strong>0.30&ndash;0.55</strong> &mdash; loosely related; same broad area
          (e.g., both are about networking).</li>
          <li><strong>below 0.30</strong> &mdash; unrelated; your paragraph is out of
          distribution for this corpus.</li>
        </ul>
        <p><strong>How it helps:</strong> If your top neighbor scores above 0.85, you
        may be duplicating existing content &mdash; check before publishing. If all
        scores are below 0.4, this paragraph doesn't really belong in this docs set.</p>
      </div>
    </details>

    <details class="term">
      <summary><strong>Chunk</strong>
        <span class="tagline">&mdash; one indexed piece of one doc</span></summary>
      <div class="term-body">
        <p><strong>What it is:</strong> A short slice of one documentation file &mdash;
        usually a paragraph, code block, or single section. The whole corpus is split
        into thousands of these by OpenCrane's chunker. Each chunk gets its own
        embedding.</p>
        <p><strong>Why it's here:</strong> Every dot on every chart represents one chunk.
        Hover shows the chunk's text snippet, source repo, and source URL.</p>
        <p><strong>What you can read from it:</strong> A neighbor's snippet tells you
        what existing doc is conceptually closest. If you see the same chunk topic
        appearing in multiple top neighbors, that topic is well-covered.</p>
        <p><strong>How it helps:</strong> When the tool says "your paragraph is similar
        to X", X is a chunk, not a whole document. Click through the source URL to read
        the surrounding context.</p>
      </div>
    </details>

    <details class="term">
      <summary><strong>Corpus &amp; sample</strong>
        <span class="tagline">&mdash; "all indexed docs" and the subset we draw</span></summary>
      <div class="term-body">
        <p><strong>What they are:</strong> The <strong>corpus</strong> is every chunk
        OpenCrane has indexed for this project. A typical corpus has tens of thousands
        of chunks. A <strong>sample</strong> is a random subset (controlled by
        <code>--sample</code>) used for the scatter chart, because drawing all of them
        would freeze the browser.</p>
        <p><strong>Why they're here:</strong> The scatter shows the sample as a backdrop.
        The "top neighbor" and "per-source alignment" rankings are computed on the
        full corpus only when the sample is large enough; otherwise on the sample.</p>
        <p><strong>What you can read from it:</strong> If <code>corpus sample: N</code>
        at the top of the page is much smaller than your full corpus, neighbor rankings
        could miss chunks that happened to be left out of the sample.</p>
        <p><strong>How it helps:</strong> Increase <code>--sample</code> when accuracy
        matters more than speed. Default 4000 is a good balance for typical corpora.</p>
      </div>
    </details>

    <details class="term">
      <summary><strong>Your paragraph</strong>
        <span class="tagline">&mdash; the <span style="color:#ff2a6d">&#9670; pink diamond</span></span></summary>
      <div class="term-body">
        <p><strong>What it is:</strong> The text you passed via <code>--text</code> or
        <code>--file</code>. OpenCrane encodes it with the <em>same model</em> as the
        corpus, so its embedding is directly comparable.</p>
        <p><strong>Why it's here:</strong> It's the anchor point. Everything else on the
        page is shown relative to it.</p>
        <p><strong>What you can read from it:</strong> Hover the diamond to see your
        full preview text plus its 2D coordinates in the local neighborhood chart.</p>
        <p><strong>How it helps:</strong> If the diamond sits inside a dense cluster,
        that part of the docs is already crowded. If it sits in empty space, you may be
        adding something novel.</p>
      </div>
    </details>

    <details class="term">
      <summary><strong>Nearest neighbors (top-K)</strong>
        <span class="tagline">&mdash; the K chunks most like your paragraph</span></summary>
      <div class="term-body">
        <p><strong>What they are:</strong> The K corpus chunks with the highest cosine
        similarity to your paragraph (default K=12, set with <code>--neighbors</code>).
        Ranking is always computed on the full 768-number embedding, <em>not</em> on
        the 2D/3D picture &mdash; even when they look far apart on screen.</p>
        <p><strong>Where they're shown:</strong> Teal-ringed dots in the global scatter;
        colored dots in the local neighborhood map; the bulleted list in your terminal.</p>
        <p><strong>What you can read from it:</strong> The list is your "see also" set.
        If they're all from one repo, your paragraph belongs there. If they spread across
        many repos, you may be writing something cross-cutting.</p>
        <p><strong>How it helps:</strong> Pick candidates for "see also" links, find
        prior art before writing, or detect that you're duplicating existing content.</p>
      </div>
    </details>

    <details class="term">
      <summary><strong>Density</strong>
        <span class="tagline">&mdash; the heatmap-style coloring in the scatter</span></summary>
      <div class="term-body">
        <p><strong>What it is:</strong> For each dot, how close are its 20 nearest
        on-screen neighbors? If they're packed tight = high density (yellow on the
        Plasma scale). If they're far apart = low density (dark purple).</p>
        <p><strong>Why it's here:</strong> Without color, 4000 dots look like one blob.
        Density coloring reveals where the docs actually cluster.</p>
        <p><strong>What you can read from it:</strong></p>
        <ul>
          <li><strong>Yellow zones</strong> = popular topics with many similar chunks
          (e.g., BGP, CRDs, deployment guides).</li>
          <li><strong>Dark zones</strong> = sparse topics with few similar chunks
          (release notes for an old patch, an obscure tool).</li>
          <li><strong>Diamond in a yellow zone</strong> = your paragraph competes with
          existing content.</li>
          <li><strong>Diamond in a dark zone</strong> = your paragraph fills a gap
          (or is out-of-distribution &mdash; check the top neighbor's similarity to
          decide which).</li>
        </ul>
        <p><strong>How it helps:</strong> Quickly spot whether your topic is already
        well-covered or under-served before you commit to writing more.</p>
        <p><strong>Caveat:</strong> Density is computed in the reduced 3D/2D space, not
        the full 768D. It's a useful approximation, not gospel.</p>
      </div>
    </details>

    <details class="term">
      <summary><strong>Mean &amp; max similarity (per-source bar chart)</strong>
        <span class="tagline">&mdash; which repo does this fit best?</span></summary>
      <div class="term-body">
        <p><strong>What they are:</strong> For each docs repo, we take the top-30
        chunks most similar to your paragraph, then compute:
        the <strong>mean</strong> of those 30 similarities (the colored bar),
        and the <strong>max</strong> of all similarities from that repo (the teal tick).</p>
        <p><strong>Why both:</strong> Mean tells you whether the repo
        <em>broadly</em> overlaps with your topic. Max tells you whether <em>any single
        chunk</em> in that repo hits hard.</p>
        <p><strong>What you can read from it:</strong></p>
        <ul>
          <li><strong>Long bar (high mean)</strong> = the repo is generally about your
          topic. Strong candidate for "where this paragraph belongs".</li>
          <li><strong>Short bar but teal tick far to the right</strong> = the repo
          isn't about your topic overall, but one specific chunk matches strongly.
          Could be a coincidence or a hidden cross-reference.</li>
          <li><strong>Both short</strong> = the repo doesn't overlap at all; skip it.</li>
        </ul>
        <p><strong>How it helps:</strong> Picks the right destination repo for new
        content, and surfaces non-obvious overlap between repos.</p>
      </div>
    </details>

    <details class="term">
      <summary><strong>Meaning-differences (and "% kept")</strong>
        <span class="tagline">&mdash; how much real information survives the flattening</span></summary>
      <div class="term-body">
        <p><strong>What it is:</strong> Each embedding has 768 numbers, all
        carrying tiny bits of "what this text is about". The full set of those
        differences between texts is the raw signal we'd want to draw. We call it
        meaning-differences. When you flatten 768 dimensions to 2 or 3 to plot,
        you lose some of those differences &mdash; some get merged, some get
        dropped.</p>
        <p><strong>Why it's shown:</strong> The percentage on a chart title
        ("PCA keeps about X% of the meaning-differences") tells you how much of
        that raw signal survived the squashing. Higher = the picture is closer
        to reality.</p>
        <p><strong>Rough thresholds:</strong></p>
        <ul>
          <li><strong>30%+</strong> &mdash; the picture is fairly trustworthy;
          most distances on screen reflect real distances.</li>
          <li><strong>15&ndash;30%</strong> &mdash; rough sketch; trust clusters
          and big patterns, not specific distances.</li>
          <li><strong>under 15%</strong> &mdash; use the picture only for
          orientation. For real comparisons, fall back to the hover
          similarities and the local close-up.</li>
        </ul>
        <p><strong>How it helps:</strong> When you see a low % on the global
        scatter (typical 10&ndash;15%), you know to trust the local-neighborhood
        chart and the similarity scores in the hover &mdash; not your eyes.</p>
      </div>
    </details>

    <details class="term">
      <summary><strong>PCA, UMAP, t-SNE</strong>
        <span class="tagline">&mdash; how 768 dimensions become 2 or 3</span></summary>
      <div class="term-body">
        <p><strong>What they are:</strong> Algorithms that take the 768-number embedding
        and squash it down to 2 or 3 numbers we can draw. Each makes different
        trade-offs.</p>
        <ul>
          <li><strong>PCA</strong> &mdash; linear, very fast, preserves the most
          variance overall but typically only ~10&ndash;15% in 3D. Use when you want
          a stable global view.</li>
          <li><strong>UMAP</strong> (default) &mdash; non-linear, preserves
          <em>local</em> neighborhoods well. Two dots close together really are similar;
          two dots far apart may or may not be far in 768D. Use for cleaner clusters.</li>
          <li><strong>t-SNE</strong> &mdash; non-linear, slowest, even better at
          revealing tight clusters. Doesn't preserve global distances at all. Use only
          when you specifically want to see groupings.</li>
        </ul>
        <p><strong>Why they're here:</strong> A 768-dimensional space can't be drawn.
        Without one of these, there's no scatter chart.</p>
        <p><strong>What you can read from them:</strong> A rough map. The structure of
        clusters and which repos sit near which is meaningful. Exact pixel distances
        are not.</p>
        <p><strong>How it helps:</strong> Switch with <code>--method</code> if one view
        seems flat or confusing. They're three different lenses on the same data.</p>
      </div>
    </details>

    <details class="term">
      <summary><strong>PC1, PC2 (local neighborhood map)</strong>
        <span class="tagline">&mdash; "main directions of variation" for the close-up</span></summary>
      <div class="term-body">
        <p><strong>What they are:</strong> The two axes of the local map. We run PCA
        on just your paragraph + its top neighbors (~13 vectors), and the axes are the
        two directions where those 13 points differ the most.</p>
        <p><strong>Why they're here:</strong> With only 13 points, PCA captures
        much more variance (typically 35&ndash;60%) than it does on thousands of
        points. So the local map is a much more faithful 2D picture than the global
        scatter.</p>
        <p><strong>What you can read from it:</strong> Distances between any two dots
        (including between two neighbors, not just from the diamond) carry real meaning.
        If two neighbors are clustered close, they're genuinely similar to each other,
        not just to you.</p>
        <p><strong>How it helps:</strong> Reveals subgroups within your top neighbors.
        Maybe 6 of them group near each other (same topic) and 6 group far away
        (related but different angle) &mdash; useful when picking what to cite.</p>
      </div>
    </details>

    <details class="term">
      <summary><strong>Source repo</strong>
        <span class="tagline">&mdash; which GitHub repository a chunk came from</span></summary>
      <div class="term-body">
        <p><strong>What it is:</strong> Every chunk is tagged with the docs repo it
        came from (e.g., <code>cgw</code>, <code>cennso-glossary</code>,
        <code>extension-cennso-upg</code>).</p>
        <p><strong>Where it's shown:</strong> Color in the global scatter when the
        <strong>by source</strong> toggle is active; colored dots in the local map;
        labels along the y-axis of the per-source bar chart.</p>
        <p><strong>What you can read from it:</strong> Click a repo in the scatter
        legend to hide its dots and see what's underneath. The per-source bar chart
        ranks all repos by relevance.</p>
        <p><strong>How it helps:</strong> Routes new content to the right home repo,
        and surfaces unexpected overlap between repos that you might want to consolidate.</p>
      </div>
    </details>

    <details class="term">
      <summary><strong>Hover</strong>
        <span class="tagline">&mdash; details on demand</span></summary>
      <div class="term-body">
        <p>Every dot in every chart has hover text with the source repo, the chunk's
        text snippet, the source URL, and (where relevant) the cosine similarity. If
        you're ever unsure what a dot represents, hover it.</p>
      </div>
    </details>

  </div>
</details>
"""

SCATTER_HELP = """
<details class="help">
  <summary><strong>How to read this chart</strong></summary>
  <div class="help-body">
    <ul>
      <li>Each small dot is one <strong>chunk</strong> from the documentation corpus.
      We're showing a random sample to keep the browser fast.</li>
      <li>The <span style="color:#ff2a6d">&#9670; pink diamond</span> is
      <strong>your paragraph</strong>.</li>
      <li>The <span style="color:#00b4a8">&#9711; teal-ringed dots</span> are your
      <strong>top neighbors</strong> &mdash; the chunks most similar to your paragraph.
      Their similarity is computed on the full 768-number embedding, <em>not</em> on
      where they happen to land in this 3D picture.</li>
      <li><strong>Density coloring</strong> (when active): yellow = crowded region with
      many similar docs (popular topic); dark purple = isolated region (niche or unique
      topic). Color reflects density in this projection only.</li>
      <li><strong>Per-source coloring</strong> (when active): each documentation repo
      gets its own color. Click a repo name in the legend to hide/show those dots.</li>
    </ul>
    <p><strong>About the % on the title (PCA only):</strong> the "keeps about X%" number
    tells you how much of the raw <strong>meaning-differences</strong> between texts
    survived the squashing from 768 dimensions to 3. PCA on a few thousand points
    typically only keeps 10&ndash;15% &mdash; meaning most of what makes texts
    different got merged or dropped during the flattening. See the local-neighborhood
    chart below for a much higher-fidelity view (typically 35&ndash;60%).</p>
    <p><strong>Caveat:</strong> reducing 768 dimensions to 3 always loses a lot of
    information. UMAP and t-SNE don't expose a % number, but they too distort.
    Trust the hover similarity numbers (computed on the full 768D) over on-screen
    distances.</p>
  </div>
</details>
"""

NEIGHBORS_HELP = """
<details class="help">
  <summary><strong>How to read this chart</strong></summary>
  <div class="help-body">
    <p>This is a <strong>fairer close-up</strong>. Instead of squashing thousands of
    points into 3D (which loses a lot of detail), we run the projection on just your
    paragraph plus its top neighbors.</p>

    <h4>What "meaning-differences" means</h4>
    <p>Two pieces of text that talk about the same topic have similar embeddings
    (similar 768-number vectors). Two pieces on totally different topics have
    very different embeddings. The full set of those differences across all 768
    dimensions is what we call <strong>meaning-differences</strong> &mdash; it's
    the raw information that makes "similar" or "different" meaningful.</p>
    <p>When we squash 768 dimensions down to 2 or 3 to draw a picture, we
    inevitably lose some of that information. The percentage on the title tells you
    <em>how much survived</em> the flattening. Higher = the picture is closer to
    the truth.</p>

    <h4>Why this close-up is more honest than the global scatter</h4>
    <p>This is the "few-points rule": <strong>the fewer points you flatten, the more
    detail you can keep.</strong></p>
    <ul>
      <li>The global scatter projects <em>thousands</em> of vectors into 3D &mdash;
      typically only about 10&ndash;15% of the meaning-differences survive.</li>
      <li>This chart projects only your paragraph + the top-K neighbors
      (about 13 points by default) into 2D &mdash; typically 35&ndash;60% of the
      meaning-differences survive.</li>
    </ul>
    <p>Intuition: with thousands of points spread across 768 dimensions, no two
    axes can do justice to all the structure. With just 13 points, two well-chosen
    axes can usually capture most of how those 13 differ from one another. That's
    why distances on this close-up are far more trustworthy than on the global view.</p>

    <h4>What's on the chart</h4>
    <ul>
      <li>The <span style="color:#ff2a6d">&#9670; pink diamond</span> is your paragraph,
      with <em>real</em> (PC1, PC2) coordinates &mdash; hover to see them.</li>
      <li>Colored dots are the top neighbors, one color per source repo. Hover to see
      the chunk's text snippet and source URL.</li>
      <li>Gray lines connect your paragraph to each neighbor &mdash; visual anchors
      for "distance from you".</li>
      <li><strong>Distances between any two neighbors carry meaning here</strong>
      (unlike in the global scatter), so two neighbors clustered close together are
      genuinely similar to each other &mdash; useful for spotting subgroups in
      your top matches.</li>
    </ul>
    <p><strong>PC1, PC2</strong> are the two directions of greatest variation among
    these 13 vectors. They don't have a fixed interpretation &mdash; they're just the
    "natural" axes for separating this small set apart.</p>
  </div>
</details>
"""

SOURCES_HELP = """
<details class="help">
  <summary><strong>How to read this chart</strong></summary>
  <div class="help-body">
    <p>For each documentation repository, we take the <strong>top 30 chunks</strong>
    most similar to your paragraph (full-dimensional cosine similarity) and average
    their similarity scores. The bars are sorted &mdash; <strong>top bar = the repo
    your paragraph fits best</strong>.</p>
    <ul>
      <li>Bar length / Plasma color = <strong>mean similarity</strong> of the
      top-30 matches. Yellow = strong fit; dark purple = weak fit.</li>
      <li><span style="color:#00b4a8">Teal tick</span> = <strong>single best
      match</strong> from that repo. If the teal tick is far to the right of the bar,
      one specific chunk hits hard even though the repo overall isn't a great match.</li>
    </ul>
    <p><strong>Use it for:</strong> deciding which repo your new content belongs to;
    spotting unexpected matches in repos you wouldn't have thought to check.</p>
  </div>
</details>
"""

VIZ_TO_HELP = {
    "scatter": SCATTER_HELP,
    "neighbors": NEIGHBORS_HELP,
    "sources": SOURCES_HELP,
}


# ── "What it helps with" boxes — chunking-quality debugging ─────────────── #
# Every chunked corpus has chunking-strategy flaws somewhere. These boxes
# explain the specific patterns to look for in each view, what they mean about
# the underlying chunking, and what to do about it.

SCATTER_DEBUG = """
<details class="help debug">
  <summary><strong>What it helps with</strong> &mdash; chunking-quality debugging</summary>
  <div class="help-body">
    <p>The global view is your <em>satellite photo</em> of the corpus. The shape
    of the cloud tells you whether your chunker is producing coherent, topically
    organized chunks &mdash; or making a mess. Click the
    <strong>by source</strong> toggle above the chart to make the patterns
    much more visible.</p>

    <h4>Patterns to look for, what they mean, what to do</h4>
    <dl>
      <dt>Isolated dots far from every cluster (dark "satellites")</dt>
      <dd><strong>Likely:</strong> a chunk got produced from content that doesn't
      fit anywhere &mdash; e.g., a stray license header, a TOC entry, a code
      snippet ripped out of context. Hover the dot; if the snippet looks like
      junk or lacks context, it is junk.<br>
      <strong>Action:</strong> tune the chunker to drop boilerplate / merge
      tiny chunks with their neighbors.
      <div class="example"><b>Example chunk:</b> a chunk containing only
      <code># License\\n\\nApache-2.0</code> or a single line like
      <code>[Table of Contents](./toc.md)</code> &mdash; semantically empty
      but the embedder still produces a vector for it.</div></dd>

      <dt>Bright yellow density hotspots (huge crowds of similar chunks)</dt>
      <dd><strong>Likely:</strong> boilerplate proliferation. The same kind of
      content (release-notes templates, "Custom Resource" definitions, generic
      install instructions) got chunked dozens of times, each chunk barely
      different from the next.<br>
      <strong>Action:</strong> deduplicate or use a longer chunk window so each
      piece carries unique signal. Boilerplate inflation poisons search by
      flooding RAG results with near-identical hits.
      <div class="example"><b>Example chunk:</b> dozens of chunks all matching
      the template <code>## Configuration parameters\\n\\nThese are all
      parameters that you can use to configure the <i>X</i> CR:</code>
      &mdash; same template per resource, embedder sees them as
      near-identical even though they belong to different products.</div></dd>

      <dt>Dots from one repo splattered across the whole map (no tight cluster)</dt>
      <dd><strong>Likely:</strong> chunks from that repo are too heterogeneous &mdash;
      the chunking boundary is wrong (too small? splitting mid-topic?) or the
      source content itself is a grab-bag.<br>
      <strong>Action:</strong> review the chunking strategy used for this repo;
      consider section-aware splitting instead of token-window splitting.</dd>

      <dt>Tight cluster mixing chunks from many repos</dt>
      <dd><strong>Likely:</strong> generic content with weak repo-specific signal.
      Could be acceptable (e.g., all docs share a Kubernetes intro) or could
      mean your chunks are too short to carry their distinguishing context.<br>
      <strong>Action:</strong> hover the cluster to see what they're all about.
      If they're truly cross-cutting (Kubernetes basics) it's fine. If they
      <em>should</em> differ but don't, your chunks are losing their context.
      <div class="example"><b>Example chunk:</b> chunks like
      <code>## Installation\\n\\nUse Helm to install this component:\\n\\n
      helm repo add ...</code> exist verbatim across many repos &mdash;
      legitimate cross-cutting boilerplate, but if you also see
      product-specific paragraphs collapsing into this cluster, the chunks
      are dropping their distinguishing context.</div></dd>

      <dt>Your paragraph landing in a dark sparse region</dt>
      <dd><strong>Likely:</strong> either (a) the topic is genuinely
      under-documented, or (b) the docs <em>do</em> cover it but the chunker
      didn't produce embeddings that capture it well.<br>
      <strong>Action:</strong> check the top neighbor similarity. High (&gt;0.7)
      = chunker is fine, you're just in a thin area. Low (&lt;0.4) = your
      paragraph is OOD <em>or</em> chunker missed the right content; grep the
      source files manually for keywords.</dd>
    </dl>
  </div>
</details>
"""

NEIGHBORS_DEBUG = """
<details class="help debug">
  <summary><strong>What it helps with</strong> &mdash; chunking-quality debugging</summary>
  <div class="help-body">
    <p>The local map is your <em>microscope</em>. Every dot is a top-K match
    for your test paragraph; together they expose whether your chunker is
    producing the right kind of chunks for similarity search to actually work.</p>

    <h4>Patterns to look for, what they mean, what to do</h4>
    <dl>
      <dt>Multiple neighbors with nearly identical snippets</dt>
      <dd><strong>Likely:</strong> the chunker is producing near-duplicate
      chunks &mdash; possibly the same section captured twice (chunks
      overlapping too much), or templated content (e.g., a CRD definition
      replicated across multiple files).<br>
      <strong>Action:</strong> reduce chunk overlap, add a dedup pass, or
      treat templated content specially.
      <div class="example"><b>Real example seen in practice:</b> auto-generated
      CRD field definitions like
      <code>{"default": "x-namespace", "description": "A Kubernetes namespace
      where X is deployed", "type": "string"}</code> can end up as multiple
      separate chunks &mdash; the embedder produces nearly the same vector
      for each, so they appear back-to-back in the top neighbors. Both should
      be a single chunk (or merged into the parent CRD definition).</div></dd>

      <dt>All top neighbors from the same source URL</dt>
      <dd><strong>Likely:</strong> one document got fragmented into many small
      chunks. The chunker is splitting more aggressively than the content
      warrants &mdash; coherent prose gets shattered.<br>
      <strong>Action:</strong> raise the chunk size or chunk at heading
      boundaries only. Sub-paragraph splitting usually destroys context for
      semantic search.
      <div class="example"><b>Example:</b> all 12 top neighbors share the
      same <code>source_url</code> (e.g., <code>.../docs/architecture/bgp.md</code>)
      and their snippets look like consecutive paragraphs of one explanation
      &mdash; you've effectively retrieved the same document 12 times instead
      of 12 different sources of information.</div></dd>

      <dt>Top neighbors come from many repos, all with high similarity</dt>
      <dd><strong>Likely:</strong> a topic that's documented in multiple
      places, and chunking is working well &mdash; each repo's coverage is
      distinct enough to show up separately.<br>
      <strong>Action:</strong> nothing &mdash; this is healthy. Use these as
      "see also" candidates in your new doc.</dd>

      <dt>Neighbors with high similarity but irrelevant snippets</dt>
      <dd><strong>Likely:</strong> the chunk that scored high contains your
      paragraph's vocabulary <em>incidentally</em> &mdash; e.g., a release-note
      that name-drops "BGP" while talking about something else entirely.
      Chunks are too long and mixing topics.<br>
      <strong>Action:</strong> shorter chunks, or chunk-at-section-boundaries
      so each chunk has a single topical focus.
      <div class="example"><b>Example chunk:</b> a release-note paragraph like
      <code>"Version 2.13.0 introduces several improvements including BGP
      support, CG-NAT rework, and bug fixes in the metrics exporter..."</code>
      &mdash; high similarity to any BGP query, but the chunk is actually
      release-cycle housekeeping, not BGP content. Splitting at bullet
      boundaries would isolate the BGP item.</div></dd>

      <dt>Two or more tight subclusters within the top-K</dt>
      <dd><strong>Likely:</strong> healthy &mdash; your chunker preserves
      topical subgroups (e.g., one cluster about "BGP config", another about
      "BGP monitoring"). Both subgroups are relevant to your paragraph but
      cover different angles.<br>
      <strong>Action:</strong> nothing &mdash; this is exactly what good
      chunking looks like. Use the subgroups to structure your new doc.</dd>

      <dt>Neighbors spread randomly, no subclusters, low similarities (~0.4)</dt>
      <dd><strong>Likely:</strong> either (a) your paragraph is OOD, or
      (b) the chunker lost the topical signal &mdash; chunks are so noisy
      that even relevant ones don't cluster cleanly.<br>
      <strong>Action:</strong> compare with a test paragraph you <em>know</em>
      is well-covered. If that one also looks bad, the chunker has a problem.
      <div class="example"><b>Sanity-check example:</b> if a paragraph like
      <code>"how do I bake a chocolate cake"</code> shows the same kind of
      scattered low-similarity results as your actual test query, it confirms
      your query is genuinely OOD. If your actual query looks like this but
      a known-covered topic also looks scattered, the chunker is the
      problem.</div></dd>
    </dl>
  </div>
</details>
"""

SOURCES_DEBUG = """
<details class="help debug">
  <summary><strong>What it helps with</strong> &mdash; chunking-quality debugging</summary>
  <div class="help-body">
    <p>The per-source bar chart is your <em>cross-repo sanity check</em>. It
    reveals whether some repos produce chunks that match <em>everything</em>
    (a chunking bug), or whether some repos are missing from results where
    they shouldn't be.</p>

    <h4>Patterns to look for, what they mean, what to do</h4>
    <dl>
      <dt>Unexpected repo at the top of the chart</dt>
      <dd><strong>Likely:</strong> chunks from that repo are too generic and
      match queries they shouldn't. Common cause: chunking strategy preserves
      navigation headers, install steps, or other boilerplate that appears in
      many repos.<br>
      <strong>Action:</strong> inspect the top-30 chunks from that repo via
      <code>opencrane search</code>. If they're boilerplate, filter them out
      at chunk time.
      <div class="example"><b>Example:</b> a <code>glossary</code> repo
      scoring high on a deeply technical query &mdash; because every
      glossary entry name-drops the technical term you're searching for,
      even when no entry is actually about it.</div></dd>

      <dt>Bar (mean) and tick (max) very close together for a repo</dt>
      <dd><strong>Likely:</strong> the repo's chunks are too homogeneous &mdash;
      probably templated content where every chunk looks the same (release
      notes, CRD schema repetitions). The mean is artificially propped up by
      the repetition.<br>
      <strong>Action:</strong> dedup or merge templated chunks. Such repos
      will dominate RAG results unfairly.
      <div class="example"><b>Example:</b> a repo whose docs are mostly
      auto-generated CRD field references &mdash; every chunk is some
      variation of <code>{namespace, description, type}</code>. The chunks
      look interchangeable to the embedder, so top-30 mean is barely below
      the max.</div></dd>

      <dt>Bar (mean) low, but teal tick (max) far to the right</dt>
      <dd><strong>Likely:</strong> one specific chunk in that repo is highly
      relevant, even though the repo overall isn't about your topic. Could be
      a genuine cross-reference (e.g., release notes mentioning BGP) or a
      chunk that captured cross-cutting context.<br>
      <strong>Action:</strong> hover the bar to find the chunk count; if it's
      small, this might be a chunk that doesn't really belong in that repo's
      bucket. Otherwise, this is a useful "see also" pointer.
      <div class="example"><b>Example:</b> a billing/OSS repo shouldn't
      score high on <code>"BGP peering"</code> overall, but one chunk in its
      install guide mentions BGP setup briefly &mdash; that single chunk
      drives the max tick while everything else stays low.</div></dd>

      <dt>Repo you expected at the top is missing or low</dt>
      <dd><strong>Likely:</strong> either (a) the docs in that repo don't
      actually cover your topic, or (b) chunking destroyed the relevant
      section &mdash; the right content exists in the source files but the
      chunks don't capture it.<br>
      <strong>Action:</strong> grep the source files for keywords. If you find
      the content, the chunker is failing on that section &mdash; check what
      chunking strategy was applied to it.</dd>

      <dt>Two or three repos with similar high mean scores</dt>
      <dd><strong>Likely:</strong> your topic legitimately spans multiple
      products / repos. Chunking is fine.<br>
      <strong>Action:</strong> consider which repo should be the primary home
      and link the others as cross-references.</dd>
    </dl>
  </div>
</details>
"""

VIZ_TO_DEBUG = {
    "scatter": SCATTER_DEBUG,
    "neighbors": NEIGHBORS_DEBUG,
    "sources": SOURCES_DEBUG,
}


VERDICT_SCALE = [
    ("danger", "LIKELY DUPLICATE", "≥ 0.90", "effectively same content"),
    ("warning", "VERY STRONGLY RELATED", "0.75 – 0.90", "covers same ground"),
    ("ok", "RELATED, NOT DUPLICATE", "0.55 – 0.75", "shares concepts"),
    ("fresh", "LIKELY NEW CONTENT", "0.30 – 0.55", "loosely covered"),
    ("ood", "OUT OF DISTRIBUTION", "< 0.30", "no related content"),
]


def _verdict_data(top_sim: float) -> dict:
    """Compute a duplicate-content verdict from the top neighbor similarity."""
    if top_sim >= 0.90:
        return dict(level="danger", label="LIKELY DUPLICATE",
                    hook=("Your paragraph is effectively the same as an existing "
                          "chunk. Review the top neighbor before publishing — "
                          "you probably want to link or merge instead of adding "
                          "new content."))
    if top_sim >= 0.75:
        return dict(level="warning", label="VERY STRONGLY RELATED",
                    hook=("An existing chunk covers very similar ground. "
                          "Consider whether your paragraph adds enough new "
                          "information to justify separate content, or link to "
                          "the existing chunk."))
    if top_sim >= 0.55:
        return dict(level="ok", label="RELATED, NOT DUPLICATE",
                    hook=("Related content exists but your paragraph likely adds "
                          "value. Use the top neighbors as \"see also\" "
                          "cross-references in your new doc."))
    if top_sim >= 0.30:
        return dict(level="fresh", label="LIKELY NEW CONTENT",
                    hook=("No close match found. Your paragraph covers ground "
                          "that's only loosely covered by the existing docs — "
                          "safe to publish as new content, but double-check the "
                          "top neighbors below first."))
    return dict(level="ood", label="OUT OF DISTRIBUTION",
                hook=("Nothing in the corpus is closely related to your "
                      "paragraph. Either this content doesn't belong in these "
                      "docs, or the topic is entirely missing — grep the source "
                      "files for key terms before writing more."))

# ── Always-visible inline captions ───────────────────────────────────────── #
# Each caption sits directly under its chart, with jargon wrapped in <abbr>
# so a brief definition pops up on hover (no clicking required).

_ABBR_CHUNK = (
    '<span class="tip" data-tip="A short slice of one doc — usually a paragraph, code block, '
    'or section. The basic unit the embeddings were computed on.">chunk</span>'
)
_ABBR_COSINE = (
    '<span class="tip" data-tip="A score from 0 to 1 measuring how aligned two text embeddings '
    'are. >0.85 = likely duplicate; 0.4-0.7 = related; below 0.3 = unrelated. '
    'Computed on the full 768-number embedding, not on this picture.">cosine '
    'similarity</span>'
)
_ABBR_DENSITY = (
    '<span class="tip" data-tip="How close are the 20 nearest dots in this projection. '
    'Yellow = a crowded neighborhood (popular topic); dark = isolated '
    '(niche or unique topic).">density</span>'
)
_ABBR_PINK_DIAMOND = (
    '<span class="tip" data-tip="Your paragraph — always shown as a pink diamond marker.">'
    '<span style="color:#ff2a6d">&#9670; pink diamond</span></span>'
)
_ABBR_TEAL_RINGS = (
    '<span class="tip" data-tip="Top-K nearest neighbors ranked by full-768D cosine similarity. '
    'They appear here even if visually far away — trust the hover similarity '
    'numbers, not the on-screen distance.">teal-ringed dots</span>'
)
_ABBR_PC = (
    '<span class="tip" data-tip="Principal Components 1 and 2 — the two directions where these '
    '~13 vectors differ the most. They\'re the natural axes for separating this '
    'small set; both carry real meaning.">PC1 &amp; PC2</span>'
)
_ABBR_MEAN = (
    '<span class="tip" data-tip="Average of the top-30 cosine similarities from this source repo. '
    'Long bar = the repo broadly overlaps with your topic.">mean</span>'
)
_ABBR_MAX = (
    '<span class="tip" data-tip="Highest single-chunk similarity from this repo. Teal tick far '
    'to the right = one specific chunk hits hard, even if the repo overall '
    'isn\'t a great match.">max</span>'
)

SCATTER_CAPTION = (
    f"Each small dot is one {_ABBR_CHUNK} from the indexed docs. "
    f"The {_ABBR_PINK_DIAMOND} is your paragraph. The {_ABBR_TEAL_RINGS} are "
    f"its top-K neighbors. Use the toggle above the chart to flip between "
    f"{_ABBR_DENSITY} coloring (heatmap of how crowded each region is) and "
    f"per-source coloring (one color per docs repo). "
    f"<em>Hover any dot for snippet + URL.</em>"
)

NEIGHBORS_CAPTION = (
    f"Re-runs the projection on <em>just</em> your paragraph plus its top "
    f"neighbors. With only ~13 points, both axes ({_ABBR_PC}) carry real "
    f"meaning, and distances between <em>any two dots</em> reflect actual "
    f"{_ABBR_COSINE} &mdash; not just distance to your paragraph. "
    f"<em>Hover the diamond to see its exact (x, y).</em>"
)

SOURCES_CAPTION = (
    f"For each docs repo: the colored bar shows the {_ABBR_MEAN} {_ABBR_COSINE} "
    f"of its top-30 chunks; the teal tick shows the {_ABBR_MAX}. "
    f"Long bar = the repo broadly matches your topic. Teal tick far right with "
    f"short bar = one strong chunk in an otherwise-unrelated repo. "
    f"<em>Hover a bar to see the chunk count sampled per repo.</em>"
)

VIZ_TO_CAPTION = {
    "scatter": SCATTER_CAPTION,
    "neighbors": NEIGHBORS_CAPTION,
    "sources": SOURCES_CAPTION,
}


# The OpenCrane brand logo (crane bird with hook), cropped to just the bird,
# resized to ~96x71 PNG and base64-encoded. Loaded from a sidecar file so the
# source stays readable; embedded inline in every generated HTML so the page
# is fully self-contained (no external image refs).
_LOGO_B64_PATH = Path(__file__).parent / "_assets" / "logo_icon.b64"


def _load_logo_b64() -> str:
    try:
        return _LOGO_B64_PATH.read_text(encoding="ascii").strip()
    except OSError:
        return ""


_LOGO_B64 = _load_logo_b64()
LOGO_IMG = (
    f'<img class="brand-icon" alt="OpenCrane" '
    f'src="data:image/png;base64,{_LOGO_B64}"/>'
) if _LOGO_B64 else (
    # Fallback: simple orange-dot placeholder if the logo file is missing.
    '<span class="brand-icon brand-icon-fallback" aria-hidden="true"></span>'
)

# Theme-toggle: sun + moon glyphs, JS swaps the data-theme attribute on <html>.
THEME_TOGGLE_HTML = (
    '<button class="theme-toggle" type="button" '
    'aria-label="Toggle light/dark theme" title="Toggle theme">'
    '<svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="4.2"/>'
    '<path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41 '
    'M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>'
    '</svg>'
    '<svg class="icon-moon" viewBox="0 0 24 24" fill="currentColor">'
    '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>'
    '</svg>'
    '</button>'
)

THEME_BOOT_JS = (
    "<script>(function(){try{"
    "var s=localStorage.getItem('oc-theme');"
    "var t=s||'light';"  # Light is the default; users opt into dark via toggle.
    "document.documentElement.setAttribute('data-theme',t);"
    "}catch(e){document.documentElement.setAttribute('data-theme','light');}})();</script>"
)

THEME_TOGGLE_JS = (
    "<script>(function(){document.addEventListener('click',function(e){"
    "var b=e.target.closest('.theme-toggle');if(!b)return;"
    "var c=document.documentElement.getAttribute('data-theme')||'light';"
    "var n=c==='dark'?'light':'dark';"
    "document.documentElement.setAttribute('data-theme',n);"
    "try{localStorage.setItem('oc-theme',n);}catch(_){}});})();</script>"
)

STYLES = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700;800;900&family=Geist+Mono:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
/* Editorial / data-journalism aesthetic.
   Hairlines, hard 90° corners, serif headlines that breathe.
   No shadows, no gradients, no rounded edges. */
:root, :root[data-theme="light"] {
  --bg: #f4eee0;          /* warm cream paper */
  --bg-elev: #ecdfc8;     /* slightly toasted */
  --bg-cell: #fbf6e8;     /* note-card */
  --line: #181410;        /* ink hairlines — sharp full-opacity */
  --line-soft: #181410;
  --line-alpha-soft: rgba(24, 20, 16, 0.16);
  --line-alpha-faint: rgba(24, 20, 16, 0.08);
  --fg: #181410;          /* warm black ink */
  --fg-soft: #4a3f33;
  --mute: #8c8478;
  --accent: #c84a06;         /* saffron ink — used sparingly */
  --accent-deep: #8a3204;
  --highlight: #1a3a5a;       /* deep navy as secondary */
  --good: #2d6a3b;
  --warn: #a67012;
  --bad: #931c2a;
  --chart-bg: #ffffff;
  --code-bg: rgba(24, 20, 16, 0.06);
}
:root[data-theme="dark"] {
  --bg: #13110d;
  --bg-elev: #1c1812;
  --bg-cell: #221d16;
  --line: #ece4d2;
  --line-soft: #ece4d2;
  --line-alpha-soft: rgba(236, 228, 210, 0.18);
  --line-alpha-faint: rgba(236, 228, 210, 0.08);
  --fg: #ece4d2;
  --fg-soft: #b8ad96;
  --mute: #76705f;
  --accent: #f4863b;
  --accent-deep: #c25a18;
  --highlight: #6fa1ce;
  --good: #7cc89a;
  --warn: #f0c270;
  --bad: #e57068;
  --chart-bg: #fbf6e8;
  --code-bg: rgba(236, 228, 210, 0.08);
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg); }
body {
  font-family: 'Geist', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
  font-weight: 400; font-size: 14.5px; line-height: 1.6;
  letter-spacing: -0.005em;
  -webkit-font-smoothing: antialiased;
  transition: background-color 0.2s ease, color 0.2s ease;
  min-height: 100vh;
}
.mono, code, .kbd { font-family: 'Geist Mono', 'SF Mono', monospace;
  font-size: 0.86em; font-weight: 400; }
code { background: var(--code-bg); padding: 1px 6px; color: var(--fg); }

::selection { background: var(--accent); color: var(--bg); }

/* Page frame — a thin double-line border like a magazine plate */
.page {
  max-width: 1240px; margin: 0 auto;
  padding: 0 clamp(20px, 5vw, 80px);
  position: relative;
}
.page::before, .page::after {
  content: ''; position: absolute; left: 0; right: 0;
  height: 1px; background: var(--line);
}


/* === TOP STRIP === */
.strip {
  padding: 16px 0; border-bottom: 1px solid var(--line);
  display: grid; grid-template-columns: auto 1fr auto; gap: 20px;
  align-items: center;
}
.strip-brand { display: flex; align-items: center; gap: 12px; }
.brand-icon { height: 32px; width: auto; flex: none; }
.brand-icon-fallback { width: 32px; height: 32px; background: var(--accent);
  display: inline-block; }
.strip-name {
  font-family: 'Geist', sans-serif; font-weight: 600;
  font-size: 15px; letter-spacing: -0.01em; color: var(--fg);
}
.strip-name .slash { color: var(--accent); margin: 0 6px; font-weight: 400; }
.strip-name .sub { color: var(--mute); font-weight: 400; }
.strip-meta {
  font-family: 'Geist Mono', monospace; font-size: 10.5px;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--mute); text-align: center;
  display: flex; gap: 18px; justify-content: center;
}
.strip-meta b { color: var(--fg); font-weight: 400;
  letter-spacing: 0.02em; text-transform: none; }
.theme-toggle {
  width: 32px; height: 32px; display: inline-flex; align-items: center;
  justify-content: center; background: transparent;
  border: 1px solid var(--line); color: var(--fg); cursor: pointer;
  padding: 0; font-family: inherit; transition: background 0.15s; }
.theme-toggle:hover { background: var(--bg-elev); }
.theme-toggle:active { background: var(--accent); color: var(--bg); }
.theme-toggle svg { width: 13px; height: 13px; display: block; }
.theme-toggle .icon-sun { display: inline; }
.theme-toggle .icon-moon { display: none; }
:root[data-theme="light"] .theme-toggle .icon-sun { display: none; }
:root[data-theme="light"] .theme-toggle .icon-moon { display: inline; }

/* === BENTO HERO ===
   A dashboard grid that puts every important number on screen 1.
   Cells share 1px lines like a printed ledger. */
.bento {
  margin: 28px 0;
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
  grid-template-rows: auto auto auto;
  gap: 0;
  border: 1px solid var(--line);
}
.cell {
  padding: 28px 30px;
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  position: relative;
  display: flex; flex-direction: column;
  min-width: 0;
}
.cell:nth-child(2n) { border-right: none; }
.cell.tag-row { padding-top: 18px; }
.cell-tag {
  font-family: 'Geist Mono', monospace;
  font-size: 9.5px; letter-spacing: 0.22em; text-transform: uppercase;
  color: var(--mute); margin-bottom: 14px;
  display: flex; align-items: baseline; gap: 10px;
}
.cell-tag .num { color: var(--accent); font-weight: 500; }
.cell-tag .meta { margin-left: auto; color: var(--fg);
  letter-spacing: 0.04em; text-transform: none; font-size: 11px; }

/* SCORE cell — the big number */
.cell-score {
  grid-column: 1 / 2; grid-row: 1 / 3;
  padding: 36px 36px 32px;
  background:
    linear-gradient(135deg,
      color-mix(in srgb, var(--verdict-color) 12%, transparent) 0%,
      transparent 60%);
  --verdict-color: var(--accent);
}
.cell-score[data-verdict="danger"] { --verdict-color: var(--bad); }
.cell-score[data-verdict="warning"] { --verdict-color: var(--accent); }
.cell-score[data-verdict="ok"] { --verdict-color: var(--accent); }
.cell-score[data-verdict="fresh"] { --verdict-color: var(--good); }
.cell-score[data-verdict="ood"] { --verdict-color: var(--mute); }
.score-num {
  font-family: 'Geist', sans-serif;
  font-weight: 200; letter-spacing: -0.06em; line-height: 0.88;
  font-size: clamp(72px, 11vw, 140px);
  font-variant-numeric: tabular-nums;
  color: var(--fg);
  margin: 8px 0 14px; white-space: nowrap;
}
.score-num .dot { color: var(--verdict-color); }
/* The metric definition — placed PROMINENTLY above the number so the
   user always knows what 0.621 (or whatever) actually measures. */
.score-label {
  font-family: 'Geist', sans-serif; font-weight: 600;
  font-size: 22px; color: var(--fg); letter-spacing: -0.015em;
  margin: 0 0 8px;
}
.score-label-scale {
  font-family: 'Geist Mono', monospace; font-weight: 400;
  font-size: 13px; color: var(--mute); margin-left: 6px;
  letter-spacing: 0.04em;
}
.score-def {
  font-size: 12.5px; color: var(--fg-soft); line-height: 1.55;
  margin: 0 0 14px; max-width: 42ch;
}
.score-def strong { color: var(--fg); font-weight: 600; }
.score-context {
  font-size: 12.5px; color: var(--fg-soft); line-height: 1.55;
  margin: -2px 0 22px; max-width: 42ch;
}
.score-context strong { color: var(--fg); font-weight: 600; }
.score-context code { background: var(--code-bg); padding: 1px 5px;
  font-family: 'Geist Mono', monospace; font-size: 0.86em; color: var(--fg); }
.score-context-arrow { color: var(--verdict-color); font-weight: 700; }
.score-divider {
  font-family: 'Geist Mono', monospace; font-size: 9.5px;
  letter-spacing: 0.22em; text-transform: uppercase;
  color: var(--mute); margin: 0 0 8px;
  display: flex; align-items: center; gap: 10px;
}
.score-divider::after {
  content: ''; flex: 1; height: 1px; background: var(--line-alpha-soft);
}
/* Collapsed "how this number is computed" — opens to reveal the 3 steps */
details.score-howto {
  margin: 0 0 18px;
  border: 1px solid var(--line-alpha-soft);
  padding: 8px 12px;
  background: color-mix(in srgb, var(--bg-elev) 60%, transparent);
}
details.score-howto > summary {
  cursor: pointer; list-style: none;
  font-family: 'Geist Mono', monospace; font-size: 10.5px;
  letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--fg-soft); font-weight: 500;
  display: flex; align-items: center; gap: 8px;
  padding: 2px 0;
}
details.score-howto > summary::-webkit-details-marker { display: none; }
details.score-howto > summary::before {
  content: '[+]'; color: var(--accent);
}
details.score-howto[open] > summary::before { content: '[−]'; }
details.score-howto > summary:hover { color: var(--accent); }
.score-howto-steps {
  margin: 12px 0 8px; padding-left: 22px;
  font-size: 12.5px; color: var(--fg-soft); line-height: 1.55;
}
.score-howto-steps li { margin: 6px 0; }
.score-howto-steps li b { color: var(--fg); font-weight: 600; }
.score-howto-steps code { background: var(--code-bg); padding: 1px 5px;
  font-family: 'Geist Mono', monospace; font-size: 0.86em; color: var(--fg); }
.score-howto-note {
  margin: 12px 0 4px; padding: 8px 12px;
  background: var(--bg-cell); border-left: 2px solid var(--accent);
  font-size: 12px; color: var(--fg-soft); line-height: 1.55;
}
.score-howto-note b { color: var(--fg); font-weight: 600; }
.score-verdict {
  display: inline-block; font-family: 'Geist Mono', monospace;
  font-size: 11px; font-weight: 500; letter-spacing: 0.14em;
  text-transform: uppercase;
  padding: 7px 12px 6px;
  background: var(--verdict-color); color: var(--bg);
  margin-bottom: 16px; align-self: flex-start;
}
.score-hook {
  font-size: 14px; line-height: 1.55; color: var(--fg-soft);
  max-width: 38ch; margin: 0;
}

/* PARAGRAPH / NEIGHBOR cells */
.cell-paragraph, .cell-neighbor {
  grid-column: 2 / 3;
}
.cell-paragraph { grid-row: 1 / 2; }
.cell-neighbor { grid-row: 2 / 3; }
.cell-text {
  font-size: 14.5px; line-height: 1.55; color: var(--fg);
  margin: 0;
  display: -webkit-box; -webkit-line-clamp: 6; -webkit-box-orient: vertical;
  overflow: hidden;
}
.cell-text::first-letter {
  font-weight: 700; font-size: 38px; line-height: 0.85;
  float: left; margin: 4px 8px 0 0; color: var(--accent);
  letter-spacing: -0.04em;
}

/* SPECTRUM cell — full width across the bento */
.cell-spectrum {
  grid-column: 1 / 3; grid-row: 3 / 4;
  border-right: none; border-bottom: none;
  padding: 24px 30px 30px;
}
.spectrum {
  position: relative; padding: 0;
}
.spectrum-bar {
  position: relative; height: 1px; background: var(--line);
  margin: 30px 0 0;
}
.spectrum-bar::before {
  content: ''; position: absolute; left: 0; right: 0; top: -3px;
  height: 7px; pointer-events: none;
  background-image:
    linear-gradient(to right,
      var(--mute) 0%, var(--mute) 30%, transparent 30%, transparent 30.5%,
      var(--good) 30.5%, var(--good) 55%, transparent 55%, transparent 55.5%,
      var(--accent) 55.5%, var(--accent) 75%, transparent 75%, transparent 75.5%,
      var(--warn) 75.5%, var(--warn) 90%, transparent 90%, transparent 90.5%,
      var(--bad) 90.5%, var(--bad) 100%);
  background-size: 100% 4px; background-repeat: no-repeat;
}
.spectrum-marker {
  position: absolute; top: -16px; width: 1px; height: 34px;
  background: var(--fg); transform: translateX(-50%); z-index: 2;
}
.spectrum-marker::after {
  content: ''; position: absolute; left: 50%; top: 0;
  width: 0; height: 0; transform: translateX(-50%) translateY(-100%);
  border-left: 6px solid transparent; border-right: 6px solid transparent;
  border-top: 8px solid var(--fg);
}
.spectrum-marker-value {
  position: absolute; top: -42px; left: 50%; transform: translateX(-50%);
  font-family: 'Geist Mono', monospace; font-weight: 500;
  font-size: 14px; color: var(--bg); white-space: nowrap;
  font-variant-numeric: tabular-nums;
  background: var(--fg); padding: 3px 8px;
}
.spectrum-ticks {
  display: flex; justify-content: space-between; margin-top: 12px;
  font-family: 'Geist Mono', monospace; font-size: 10px;
  color: var(--mute); letter-spacing: 0.04em;
}
.spectrum-zones {
  display: grid; grid-template-columns: 30fr 25fr 20fr 15fr 10fr;
  gap: 0; margin-top: 14px;
}
.spectrum-zone {
  padding: 8px 10px 10px;
  border-top: 1px solid var(--line-alpha-soft);
  border-right: 1px solid var(--line-alpha-soft);
  font-family: 'Geist Mono', monospace;
}
.spectrum-zone:last-child { border-right: none; }
.spectrum-zone.active {
  border-top-width: 2px; border-top-style: solid;
}
.spectrum-zone.danger.active { border-top-color: var(--bad); }
.spectrum-zone.warning.active { border-top-color: var(--accent); }
.spectrum-zone.ok.active { border-top-color: var(--accent); }
.spectrum-zone.fresh.active { border-top-color: var(--good); }
.spectrum-zone.ood.active { border-top-color: var(--mute); }
.spectrum-zone-label {
  font-size: 9px; letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--mute); margin-bottom: 3px;
}
.spectrum-zone.active .spectrum-zone-label {
  color: currentColor; font-weight: 500;
}
.spectrum-zone.danger.active .spectrum-zone-label { color: var(--bad); }
.spectrum-zone.warning.active .spectrum-zone-label { color: var(--accent); }
.spectrum-zone.ok.active .spectrum-zone-label { color: var(--accent); }
.spectrum-zone.fresh.active .spectrum-zone-label { color: var(--good); }
.spectrum-zone-range { font-size: 11px; color: var(--fg); }

/* STATS BAR — below bento */
.stats {
  display: grid; grid-template-columns: repeat(4, 1fr);
  border: 1px solid var(--line); border-top: none;
  margin: -28px 0 0;  /* abut to bento border */
}
.stat {
  padding: 18px 24px; border-right: 1px solid var(--line);
  position: relative;
}
.stat:last-child { border-right: none; }
.stat-label {
  font-family: 'Geist Mono', monospace; font-size: 9.5px;
  letter-spacing: 0.22em; text-transform: uppercase;
  color: var(--mute); margin-bottom: 6px;
}
.stat-value {
  font-family: 'Geist', sans-serif; font-weight: 300;
  font-size: 32px; line-height: 1; letter-spacing: -0.03em;
  color: var(--fg); font-variant-numeric: tabular-nums;
}
.stat-value-sub {
  font-family: 'Geist Mono', monospace; font-size: 11px;
  color: var(--mute); margin-left: 6px;
}
.stat-foot {
  margin-top: 6px; font-family: 'Geist Mono', monospace; font-size: 10px;
  color: var(--fg-soft); letter-spacing: 0.04em;
}
.stat-foot b { color: var(--fg); font-weight: 500; }

/* HOW-TO-USE strip */
.uses-strip {
  margin: 36px 0 0;
  padding: 18px 0; border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  display: grid; grid-template-columns: max-content 1fr 1fr 1fr;
  gap: 32px; align-items: start;
}
.uses-strip-label {
  font-family: 'Geist Mono', monospace; font-size: 10px;
  letter-spacing: 0.22em; text-transform: uppercase;
  color: var(--mute); padding-top: 2px;
}
.use-cell {
  display: grid; grid-template-columns: max-content 1fr;
  gap: 12px; align-items: baseline;
}
.use-num {
  font-family: 'Geist Mono', monospace; font-weight: 500;
  font-size: 14px; color: var(--accent); letter-spacing: 0.04em;
}
.use-cell-body { min-width: 0; }
.use-cell-title {
  font-family: 'Geist', sans-serif; font-weight: 600;
  font-size: 13px; color: var(--fg); margin: 0 0 4px;
  letter-spacing: -0.005em;
}
.use-cell-text {
  font-size: 12.5px; line-height: 1.5; color: var(--fg-soft);
}
.use-cell-text code, .use-cell-text .inline-badge { font-size: 0.86em; }

/* FIGURE SECTIONS */
.fig {
  padding: 56px 0 32px;
  border-bottom: 1px solid var(--line);
}
.fig-head-block {
  display: grid; grid-template-columns: minmax(0, 2fr) minmax(220px, 1fr);
  gap: 48px; margin-bottom: 22px; align-items: end;
}
.fig h3 {
  font-family: 'Geist', sans-serif; font-weight: 300;
  font-size: clamp(28px, 3.6vw, 44px);
  line-height: 1; letter-spacing: -0.035em;
  color: var(--fg); margin: 8px 0 0;
}
.fig-meta {
  font-family: 'Geist Mono', monospace;
  font-size: 10.5px; letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--accent); font-weight: 500;
}
.caption {
  font-family: 'Geist', sans-serif; font-weight: 400;
  font-size: 13.5px; line-height: 1.6; color: var(--fg-soft);
  border-top: 1px solid var(--line);
  padding-top: 14px;
}
.caption em { color: var(--fg); font-style: italic; }
.caption code { background: var(--code-bg); padding: 1px 6px; font-size: 0.86em;
  font-style: normal; font-family: 'Geist Mono', monospace; }
.viz {
  background: var(--chart-bg); border: 1px solid var(--line);
  padding: 0; margin: 24px 0;
}

/* DETAILS — help / debug */
details.help {
  border: 1px solid var(--line); border-left-width: 3px;
  border-left-color: var(--accent);
  background: transparent;
  padding: 14px 20px; margin: 14px 0;
  font-size: 14px;
}
details.help.debug { border-left-color: var(--highlight); }
details.help summary {
  cursor: pointer; color: var(--fg);
  font-family: 'Geist Mono', monospace;
  font-size: 11px; font-weight: 500;
  letter-spacing: 0.16em; text-transform: uppercase;
  padding: 2px 0;
  list-style: none;
  display: flex; align-items: center; gap: 10px;
}
details.help summary::-webkit-details-marker { display: none; }
details.help summary::before {
  content: '[+]'; font-family: 'Geist Mono', monospace;
  font-size: 11px; color: var(--accent);
}
details.help[open] summary::before { content: '[−]'; }
details.help.debug summary::before { color: var(--highlight); }
.help-body {
  margin-top: 18px;
  font-family: 'Geist', sans-serif; font-size: 13.5px;
  color: var(--fg-soft); line-height: 1.65;
  max-width: 70ch;
}
.help-body p { margin: 10px 0; }
.help-body h4 { color: var(--fg);
  font-family: 'Geist Mono', monospace; font-weight: 500;
  font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase;
  margin: 22px 0 10px; padding-bottom: 6px;
  border-bottom: 1px solid var(--line-alpha-soft); }
.help-body code { background: var(--code-bg); padding: 1px 6px;
  font-family: 'Geist Mono', monospace; font-size: 0.86em;
  color: var(--fg); }
.help-body ul, .help-body ol { padding-left: 22px; margin: 10px 0; }
.help-body li { margin: 8px 0; }
.help-body dl { display: block; margin: 12px 0; }
.help-body dt { font-weight: 600; color: var(--fg);
  font-family: 'Geist', sans-serif;
  font-size: 14px; margin-top: 18px; letter-spacing: -0.005em; }
.help-body dd { margin: 6px 0 0; color: var(--fg-soft); padding-left: 0; }

.example {
  font-family: 'Geist', sans-serif;
  border-left: 2px solid var(--highlight);
  padding: 10px 18px; margin: 14px 0 14px 12px;
  font-size: 13px; color: var(--fg-soft);
  line-height: 1.6;
}
.example b { color: var(--highlight); font-weight: 500;
  font-family: 'Geist Mono', monospace;
  font-size: 0.8em; letter-spacing: 0.12em; text-transform: uppercase;
  font-style: normal; display: inline-block; margin-right: 6px; }
.example code { background: var(--code-bg);
  font-family: 'Geist Mono', monospace; font-style: normal;
  padding: 1px 5px; font-size: 0.86em; color: var(--fg); }

/* APPENDIX — Glossary at the end */
.appendix {
  margin-top: 56px; padding-top: 40px;
  border-top: 2px solid var(--line);
}
.appendix-head {
  display: grid; grid-template-columns: max-content 1fr;
  gap: 24px; align-items: baseline; margin-bottom: 28px;
}
.appendix-num {
  font-family: 'Geist Mono', monospace; font-size: 11px;
  letter-spacing: 0.22em; text-transform: uppercase;
  color: var(--accent); font-weight: 500;
}
.appendix-title {
  font-family: 'Geist', sans-serif; font-weight: 300;
  font-size: 36px; letter-spacing: -0.03em;
  color: var(--fg); margin: 0;
}
.appendix-intro {
  max-width: 60ch; color: var(--fg-soft); font-size: 14px;
  line-height: 1.6; margin: 0 0 24px;
}
details.help.glossary {
  border: none; padding: 0; margin: 0;
  background: transparent;
}
details.help.glossary > summary { display: none; }
details.help.glossary[open] > summary { display: none; }
details.help.glossary > .help-body { display: block !important;
  margin: 0; max-width: none; }
/* Force the glossary to be always-expanded in appendix */
details.term {
  border: none; border-bottom: 1px solid var(--line-alpha-soft);
  background: transparent;
  padding: 16px 0; margin: 0;
}
details.term:last-child { border-bottom: none; }
details.term summary { cursor: pointer; color: var(--fg);
  font-family: 'Geist', sans-serif; font-weight: 500;
  font-size: 16px; padding: 4px 0; list-style: none;
  display: flex; align-items: baseline; gap: 12px;
  letter-spacing: -0.01em;
}
details.term summary::-webkit-details-marker { display: none; }
details.term summary::before {
  content: '§'; color: var(--accent); font-style: normal;
  font-family: 'Geist', sans-serif; font-size: 18px; font-weight: 400;
}
details.term .tagline { color: var(--mute); font-weight: normal;
  font-size: 0.85em; margin-left: 0.4em; font-style: normal;
  font-family: 'Geist Mono', monospace; letter-spacing: 0.04em; }
.term-body { color: var(--fg-soft); padding: 10px 0 6px 1.8em;
  line-height: 1.65; font-size: 13.5px;
  font-family: 'Geist', sans-serif; max-width: 72ch; }
.term-body p { margin: 8px 0; }
.term-body strong { color: var(--fg); font-weight: 500; }
.term-body code { background: var(--code-bg); padding: 1px 5px;
  font-family: 'Geist Mono', monospace; font-size: 0.86em; color: var(--fg); }
.term-body ul { padding-left: 22px; margin: 10px 0; }
.term-body li { margin: 6px 0; }

/* CSS tooltip */
.tip { position: relative;
  text-decoration: underline; text-decoration-style: dotted;
  text-decoration-color: var(--accent);
  text-underline-offset: 3px;
  cursor: help; }
.tip:hover { color: var(--accent); }
.tip:hover::after {
  content: attr(data-tip); position: absolute;
  bottom: calc(100% + 10px); left: 0;
  transform: translateX(-22%);
  background: var(--fg); color: var(--bg);
  padding: 12px 16px;
  font-family: 'Geist', sans-serif;
  font-size: 13px; font-weight: 400; line-height: 1.5;
  white-space: normal; width: 320px; z-index: 1000;
  pointer-events: none;
}
.tip:hover::before {
  content: ''; position: absolute; bottom: calc(100% + 4px); left: 22%;
  border: 6px solid transparent; border-top-color: var(--fg);
  z-index: 1000; pointer-events: none;
}

.inline-badge {
  padding: 1px 8px; font-family: 'Geist Mono', monospace;
  font-size: 0.78em; font-weight: 500; letter-spacing: 0.1em;
  background: var(--fg); color: var(--bg);
  text-transform: uppercase;
}

.colophon {
  margin: 56px 0 32px; padding-top: 24px;
  border-top: 1px solid var(--line);
  font-family: 'Geist Mono', monospace;
  font-size: 10px; letter-spacing: 0.18em; text-transform: uppercase;
  color: var(--mute); display: flex; justify-content: space-between;
  gap: 24px; flex-wrap: wrap;
}
.colophon b { color: var(--fg); font-weight: 500; }
.colophon a { color: var(--accent); text-decoration: none; }

@media (max-width: 900px) {
  body { font-size: 15px; }
  .strip { grid-template-columns: 1fr; gap: 12px; text-align: center; }
  .strip-meta { justify-content: center; flex-wrap: wrap; }
  .bento { grid-template-columns: 1fr; }
  .cell { border-right: none; }
  .cell-score { grid-column: 1; grid-row: auto; }
  .cell-paragraph, .cell-neighbor, .cell-spectrum {
    grid-column: 1; grid-row: auto; border-right: none; }
  .stats { grid-template-columns: 1fr 1fr; }
  .stat { border-bottom: 1px solid var(--line); }
  .uses-strip { grid-template-columns: 1fr; gap: 20px; }
  .fig-head-block { grid-template-columns: 1fr; gap: 16px; }
  .spectrum-zones { grid-template-columns: 1fr 1fr; }
}
</style>"""


def _write_combined_html(figs, out_path: Path, ctx: dict):
    """Render the full self-documenting HTML page.

    ``ctx`` carries everything the header layout needs: paragraph preview,
    model name, corpus stats, verdict info, etc. ``figs`` entries are
    ``(title, fig, viz_key)`` tuples.
    """
    import plotly.io as pio

    verdict = ctx["verdict"]
    # Big sim score gets a colored decimal point — split & inject.
    sim_str = f"{ctx['top_sim']:.3f}".replace(
        ".", '<span class="dot">.</span>'
    )

    # Jargon tooltips for the use-cases banner.
    tip_boilerplate = (
        '<span class="tip" data-tip="A flood of nearly-identical chunks '
        'flooding search results — usually because templated content '
        '(release-notes templates, CRD schema repetitions, navigation '
        'headers) was chunked dozens of times with barely any difference '
        'between chunks. Drowns out real signal in RAG.">'
        'boilerplate inflation</span>'
    )
    tip_oversplit = (
        '<span class="tip" data-tip="The chunker is cutting documents into '
        'pieces that are too small or too granular — coherent prose gets '
        'shattered into fragments, each one missing enough context to be '
        'useful for semantic search.">'
        'over-aggressive splitting</span>'
    )

    # Pre-render figure sections so the main parts-list stays readable.
    fig_sections = []
    for i, (title, fig, viz_key) in enumerate(figs):
        fig_num = i + 2  # fig 01 is the spectrum (inside the bento)
        caption = VIZ_TO_CAPTION.get(viz_key, "")
        help_html = VIZ_TO_HELP.get(viz_key, "")
        debug_html = VIZ_TO_DEBUG.get(viz_key, "")
        fig_sections.append(
            f'<section class="fig">'
            f'<div class="fig-head-block">'
            f'<div>'
            f'<div class="fig-meta">Fig. {fig_num:02d} &mdash; {viz_key}</div>'
            f'<h3>{title}</h3>'
            f'</div>'
            f'<div class="caption">{caption}</div>'
            f'</div>'
            f'<div class="viz">{pio.to_html(fig, include_plotlyjs=False, full_html=False)}</div>'
            f'{help_html}{debug_html}'
            f'</section>'
        )

    import datetime
    today = datetime.date.today().strftime("%Y-%m-%d")
    truncated = ctx["paragraph_preview"][:280]
    if len(ctx["paragraph_preview"]) > 280:
        truncated += "&hellip;"
    neighbor_snippet = ctx["top_snippet"][:280]
    if len(ctx["top_snippet"]) > 280:
        neighbor_snippet += "&hellip;"

    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>OpenCrane &middot; embedding placement</title>",
        THEME_BOOT_JS,
        # Pin Plotly to a version compatible with plotly-python 6.x output.
        "<script src='https://cdn.plot.ly/plotly-3.0.1.min.js'></script>",
        STYLES,
        "</head><body><div class='page'>",

        # ── TOP STRIP ─────────────────────────────────────────────
        '<header class="strip">',
        f'<div class="strip-brand">{LOGO_IMG}'
        f'<div class="strip-name">OpenCrane<span class="slash">/</span>'
        f'<span class="sub">visualize</span></div></div>',
        f'<div class="strip-meta">'
        f'<span>v <b>0.18</b></span>'
        f'<span>{today}</span>'
        f'<span><b>{ctx["model_name"].split("/")[-1]}</b></span>'
        f'</div>',
        f'<div>{THEME_TOGGLE_HTML}</div>',
        '</header>',
        THEME_TOGGLE_JS,

        # ── BENTO HERO ────────────────────────────────────────────
        '<section class="bento">',
        # SCORE — metric definition + big number + verdict (spans 2 rows)
        f'<div class="cell cell-score" data-verdict="{verdict["level"]}">',
        '<div class="cell-tag"><span class="num">01</span>'
        '<span>the metric</span></div>',
        '<div class="score-label">Cosine similarity '
        '<span class="score-label-scale">(0 &ndash; 1)</span></div>',
        '<div class="score-def">A number from 0 to 1 measuring how aligned '
        'two pieces of text are in meaning. <strong>0 = unrelated, '
        '1 = identical.</strong></div>',
        f'<div class="score-num">{sim_str}</div>',
        f'<div class="score-context">'
        f'<span class="score-context-arrow">&darr;</span> '
        f'between <strong>your paragraph</strong> and its single closest '
        f'match in <code>{ctx["top_source"]}</code> '
        f'(out of <strong>{ctx["full_size"]:,}</strong> chunks indexed).'
        f'</div>',
        # Collapsed "how this is computed" so users can dig into the math
        '<details class="score-howto">',
        '<summary>How this number is computed</summary>',
        '<ol class="score-howto-steps">',
        f'<li><b>Encode</b> &mdash; your paragraph is turned into a '
        f'<b>768-number vector</b> by the same model that built the corpus '
        f'(<code>{ctx["model_name"].split("/")[-1]}</code>, locally on CPU).</li>',
        f'<li><b>Score every chunk</b> &mdash; cosine similarity is computed '
        f'between your vector and <em>each of the {ctx["full_size"]:,} corpus '
        f'chunks</em>. One numpy matrix multiplication, milliseconds.</li>',
        f'<li><b>Pick the top</b> &mdash; sort the scores; the highest is '
        f'<b>{ctx["top_sim"]:.3f}</b> (with <code>{ctx["top_source"]}</code>). '
        f'The top {ctx["neighbor_count"]} highest are your &laquo;neighbors&raquo; '
        f'shown in every chart below.</li>',
        '</ol>',
        '<p class="score-howto-note">Runs entirely in-process &mdash; '
        'no Milvus, no remote service, no caching. '
        f'The scatter below renders only <b>{ctx["sample_size"]:,}</b> of '
        f'the {ctx["full_size"]:,} chunks (uniform random sample for browser '
        f'performance and UMAP / t-SNE speed; the top-{ctx["neighbor_count"]} '
        f'neighbors are always force-included so their teal rings stay '
        f'visible). Pass <code>--sample {ctx["full_size"] + 1}</code> (or any '
        f'number above the corpus size) to render the full corpus.</p>',
        '</details>',
        '<div class="score-divider">verdict</div>',
        f'<span class="score-verdict">{verdict["label"]}</span>',
        f'<p class="score-hook">{verdict["hook"]}</p>',
        '</div>',
        # PARAGRAPH cell
        '<div class="cell cell-paragraph">',
        '<div class="cell-tag"><span class="num">02</span>'
        '<span>your paragraph</span><span class="meta">input</span></div>',
        f'<p class="cell-text">{truncated}</p>',
        '</div>',
        # NEIGHBOR cell
        '<div class="cell cell-neighbor">',
        '<div class="cell-tag"><span class="num">03</span>'
        f'<span>top neighbor</span><span class="meta">{ctx["top_source"]}'
        f' &middot; sim {ctx["top_sim"]:.3f}</span></div>',
        f'<p class="cell-text">{neighbor_snippet}</p>',
        '</div>',
        # SPECTRUM cell — full bento width
        '<div class="cell cell-spectrum">',
        '<div class="cell-tag"><span class="num">Fig. 01</span>'
        '<span>similarity spectrum</span></div>',
        '<div class="spectrum">',
        '<div class="spectrum-bar">',
        f'<div class="spectrum-marker" style="left: {min(100, max(0, ctx["top_sim"] * 100)):.1f}%">'
        f'<span class="spectrum-marker-value">{ctx["top_sim"]:.3f}</span>'
        '</div>',
        '</div>',
        '<div class="spectrum-ticks">',
        '<span>0.00</span><span>0.30</span><span>0.55</span>'
        '<span>0.75</span><span>0.90</span><span>1.00</span>',
        '</div>',
        '<div class="spectrum-zones">',
        *[(f'<div class="spectrum-zone {lvl}'
           f'{" active" if lvl == verdict["level"] else ""}">'
           f'<div class="spectrum-zone-label">{lbl.lower()}</div>'
           f'<div class="spectrum-zone-range">{rng}</div>'
           f'</div>')
          for lvl, lbl, rng, _ in VERDICT_SCALE],
        '</div>',  # /spectrum-zones
        '</div>',  # /spectrum
        '</div>',  # /cell-spectrum
        '</section>',  # /bento

        # ── STATS STRIP ───────────────────────────────────────────
        '<div class="stats">',
        '<div class="stat"><div class="stat-label">Verdict</div>'
        f'<div class="stat-value" style="font-size:18px;line-height:1.3">{verdict["label"]}</div>'
        '</div>',
        '<div class="stat"><div class="stat-label">Neighbors</div>'
        f'<div class="stat-value">{ctx["neighbor_count"]}</div>'
        f'<div class="stat-foot">across <b>{ctx["unique_neighbor_sources"]}</b> repo(s)</div>'
        '</div>',
        '<div class="stat"><div class="stat-label">Corpus sample</div>'
        f'<div class="stat-value">{ctx["sample_size"]:,}<span class="stat-value-sub">chunks</span></div>'
        f'<div class="stat-foot">projected from <b>768D</b> embeddings</div>'
        '</div>',
        '<div class="stat"><div class="stat-label">Top repo match</div>'
        f'<div class="stat-value" style="font-size:18px;line-height:1.3">{ctx["top_source"]}</div>'
        f'<div class="stat-foot">sim <b>{ctx["top_sim"]:.3f}</b></div>'
        '</div>',
        '</div>',

        # ── HOW-TO-USE STRIP ──────────────────────────────────────
        '<div class="uses-strip">',
        '<div class="uses-strip-label">How to read this</div>',
        '<div class="use-cell">',
        '<div class="use-num">01</div>',
        '<div class="use-cell-body">',
        '<div class="use-cell-title">Place new content</div>',
        '<div class="use-cell-text">Paste a draft; verdict above tells you '
        'if you\'re duplicating existing chunks.</div>',
        '</div></div>',
        '<div class="use-cell">',
        '<div class="use-num">02</div>',
        '<div class="use-cell-body">',
        '<div class="use-cell-title">Test RAG retrieval</div>',
        '<div class="use-cell-text">Paste a <em>user query</em>; '
        '<span class="inline-badge">OOD</span> verdict = clear docs gap.</div>',
        '</div></div>',
        '<div class="use-cell">',
        '<div class="use-num">03</div>',
        '<div class="use-cell-body">',
        '<div class="use-cell-title">Debug chunking</div>',
        f'<div class="use-cell-text">Each figure has a <b>What it helps with</b> '
        f'box: spot {tip_boilerplate}, {tip_oversplit}, duplicates.</div>',
        '</div></div>',
        '</div>',

        # ── FIGURE SECTIONS ───────────────────────────────────────
        *fig_sections,

        # ── APPENDIX — GLOSSARY ───────────────────────────────────
        '<section class="appendix">',
        '<div class="appendix-head">',
        '<div class="appendix-num">Appendix &middot; A</div>',
        '<h2 class="appendix-title">A field glossary.</h2>',
        '</div>',
        '<p class="appendix-intro">Every term that appears on this page, '
        'with what it means, why it\'s shown, what you can read from it, '
        'and how it helps your work.</p>',
        GLOSSARY_HTML.replace(chr(10), " "),
        '</section>',

        # ── COLOPHON ──────────────────────────────────────────────
        '<footer class="colophon">',
        f'<div>Generated by <b>OpenCrane</b> &middot; '
        f'<a href="https://github.com/derberg/OpenCrane">github.com/derberg/OpenCrane</a></div>',
        f'<div>{ctx["sample_size"]:,} embeddings &middot; '
        f'{ctx["unique_neighbor_sources"]} repos surveyed</div>',
        '</footer>',
        "</div></body></html>",
    ]
    out_path.write_text("\n".join(parts), encoding="utf-8")


def main(
    text: str | None = None,
    file: str | None = None,
    embeddings_file: Path | None = None,
    chunks_file: Path | None = None,
    output: Path | None = None,
    method: str = "umap",
    dim: int = 3,
    viz: str = "all",
    sample: int = 4000,
    neighbors: int = 12,
    seed: int = 42,
    open_browser: bool = True,
):
    """Generate an interactive embedding-placement HTML.

    See module docstring for the three visualization views and dependency
    requirements.
    """
    embeddings_file = embeddings_file or DEFAULT_EMBEDDINGS_FILE
    chunks_file = chunks_file or DEFAULT_CHUNKS_FILE
    output = output or DEFAULT_OUTPUT_FILE

    if not embeddings_file.exists():
        logger.error("Embeddings file not found: %s", embeddings_file)
        logger.error("Run 'opencrane embed' first to generate embeddings.")
        sys.exit(1)
    if not chunks_file.exists():
        logger.error("Chunks file not found: %s", chunks_file)
        logger.error("Run 'opencrane chunk' first to generate chunks.")
        sys.exit(1)

    paragraph = read_paragraph(text, file).strip()
    if not paragraph:
        raise SystemExit("Empty paragraph.")

    # Always load the FULL corpus — neighbor finding must search every chunk,
    # not a random sample, or "top neighbor" lies.
    corpus = load_corpus(embeddings_file, chunks_file)
    new_vec = encode_paragraph(corpus.model_name, paragraph)
    if new_vec.shape[0] != corpus.vectors.shape[1]:
        raise SystemExit(
            f"Dimension mismatch: model returned {new_vec.shape[0]}, "
            f"corpus is {corpus.vectors.shape[1]}"
        )

    # Top-K + per-chunk similarities on the FULL corpus.
    neighbor_idx, neighbor_sims, all_sims = _nearest_neighbors(corpus.vectors, new_vec, neighbors)
    logger.info("Top neighbor similarity: %.3f (%s)",
                float(neighbor_sims[0]), corpus.sources[int(neighbor_idx[0])])

    # Smaller subset for the scatter only — to keep the browser responsive and
    # to keep UMAP/t-SNE fast. Always includes the top-K neighbors so they
    # remain visible as teal rings on the chart.
    scatter_corpus, neighbor_idx_in_scatter = subsample_for_scatter(
        corpus, sample, neighbor_idx, seed
    )

    paragraph_preview = (paragraph[:240].replace("\n", " ")
                         + ("…" if len(paragraph) > 240 else ""))

    figs = []
    info = ""
    if viz in ("scatter", "all"):
        coords, new_coords, info = reduce_dims(scatter_corpus.vectors, new_vec,
                                               method, dim, seed)
        figs.append((
            f"Global scatter ({method.upper()}, {dim}D)",
            _build_scatter_figure(coords, new_coords, scatter_corpus,
                                  neighbor_idx_in_scatter, neighbor_sims,
                                  paragraph_preview, info),
            "scatter",
        ))
    if viz in ("neighbors", "all"):
        figs.append((
            "Local neighborhood map (paragraph + top-K only)",
            _build_local_neighborhood_figure(new_vec, corpus, neighbor_idx,
                                             neighbor_sims, paragraph_preview),
            "neighbors",
        ))
    if viz in ("sources", "all"):
        figs.append((
            "Per-source alignment",
            _build_sources_figure(corpus.sources, all_sims),
            "sources",
        ))

    output.parent.mkdir(parents=True, exist_ok=True)
    top_sim = float(neighbor_sims[0])
    top_source = corpus.sources[int(neighbor_idx[0])]
    top_snippet = corpus.snippets[int(neighbor_idx[0])]

    unique_neighbor_sources = len({corpus.sources[int(i)] for i in neighbor_idx})

    ctx = dict(
        paragraph_preview=paragraph_preview,
        model_name=corpus.model_name,
        full_size=corpus.full_size,            # whole indexed corpus
        sample_size=scatter_corpus.sample_size, # scatter subset only
        top_sim=top_sim,
        top_source=top_source,
        top_snippet=top_snippet,
        neighbor_count=len(neighbor_idx),
        unique_neighbor_sources=unique_neighbor_sources,
        info=info,
        verdict=_verdict_data(top_sim),
    )

    _write_combined_html(figs, output, ctx)
    logger.info("Wrote %s", output)

    print("\nTop nearest neighbors (cosine similarity, full embedding dim):")
    for rank, (i, sim) in enumerate(zip(neighbor_idx, neighbor_sims), 1):
        print(f"  {rank:2d}. sim={float(sim):.3f}  [{corpus.sources[int(i)]}]  "
              f"{corpus.snippets[int(i)]}")

    if open_browser:
        webbrowser.open(output.resolve().as_uri())

    return output
