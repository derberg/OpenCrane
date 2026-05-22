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


def read_paragraph(text: str | None, file: str | None) -> str:
    """Resolve paragraph from --text, --file, or stdin."""
    if text:
        return text
    if file:
        return Path(file).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("Provide a paragraph via --text, --file, or stdin.")


def load_corpus(embeddings_file: Path, chunks_file: Path, sample_size: int, seed: int) -> CorpusData:
    """Load corpus embeddings + chunks, optionally downsampling."""
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

    if sample_size and sample_size < len(records):
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(records), size=sample_size, replace=False)
        records = [records[i] for i in idx]
        logger.info("Downsampled corpus to %d points", len(records))

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

    return CorpusData(model_name=model_name, vectors=vectors,
                      sources=sources, snippets=snippets, urls=urls)


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
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;1,9..144,400;1,9..144,500&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
/* Default theme is LIGHT — users opt into dark via toggle. */
:root, :root[data-theme="light"] {
  --bg: #fdfaf3;
  --bg-elev: #fff7e8;
  --bg-cell: #fffdf6;
  --line: #ead9b8;
  --line-soft: #f0e3c8;
  --fg: #1c1310;
  --fg-soft: #5a4d3e;
  --mute: #9a8870;
  --accent: #ef6c1a;          /* OpenCrane hook orange */
  --accent-soft: #f29547;
  --accent-deep: #b94d0a;
  --highlight: #c12c3a;        /* crane crest red */
  --good: #297a4a;
  --warn: #b08217;
  --bad: #a02a2a;
  --grid: rgba(40, 20, 10, 0.025);
  --glow-1: rgba(239, 108, 26, 0.08);
  --glow-2: rgba(193, 44, 58, 0.05);
  --chart-bg: #ffffff;
  --code-bg: #f3e7c6;
  --shadow: 0 6px 22px rgba(120, 80, 30, 0.10);
  --shadow-soft: 0 2px 10px rgba(120, 80, 30, 0.06);
}
:root[data-theme="dark"] {
  --bg: #0f0d10;
  --bg-elev: #1a1620;
  --bg-cell: #1e1a26;
  --line: #322a3a;
  --line-soft: #251f2c;
  --fg: #f4ecdc;
  --fg-soft: #b0a692;
  --mute: #6a5f72;
  --accent: #f58220;
  --accent-soft: #f9a85a;
  --accent-deep: #d36100;
  --highlight: #e63946;
  --good: #6bd49a;
  --warn: #f4b94e;
  --bad: #e85a5a;
  --grid: rgba(255,255,255,0.02);
  --glow-1: rgba(245, 130, 32, 0.08);
  --glow-2: rgba(230, 57, 70, 0.05);
  --chart-bg: #ffffff;
  --code-bg: #2a2230;
  --shadow: 0 6px 22px rgba(0,0,0,0.40);
  --shadow-soft: 0 2px 10px rgba(0,0,0,0.25);
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
  font-weight: 400; font-size: 14px; line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  transition: background-color 0.2s ease, color 0.2s ease;
}
code, .mono { font-family: 'DM Mono', ui-monospace, monospace; font-size: 0.92em; }
body {
  background-image:
    radial-gradient(circle at 12% -10%, var(--glow-1), transparent 50%),
    radial-gradient(circle at 100% 5%, var(--glow-2), transparent 55%),
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px);
  background-size: auto, auto, 32px 32px, 32px 32px;
  background-attachment: fixed;
  min-height: 100vh; padding-bottom: 6em;
}

/* === TOPBAR === */
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 2em; padding: 1.1em 2.4em;
  border-bottom: 1px solid var(--line-soft);
  background: linear-gradient(to bottom, color-mix(in srgb, var(--bg) 60%, transparent), transparent);
}
.brand { display: flex; align-items: center; gap: 0.85em;
  font-size: 11px; letter-spacing: 0.2em; text-transform: uppercase;
  color: var(--fg-soft); }
.brand-icon { height: 36px; width: auto; flex: none;
  filter: drop-shadow(0 1px 0 rgba(0,0,0,0.04)); }
.brand-icon-fallback { width: 36px; height: 36px; background: var(--accent);
  border-radius: 50%; display: inline-block; }
.brand strong { color: var(--fg); font-weight: 500; letter-spacing: 0.18em; }
.brand .sep { color: var(--mute); margin: 0 0.3em; }
.topbar-right { display: flex; align-items: center; gap: 1.4em; }
.topbar-meta { font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--mute); text-align: right; line-height: 1.7; }
.topbar-meta b { color: var(--fg-soft); font-weight: 400; text-transform: none;
  letter-spacing: 0.02em; }
.theme-toggle {
  width: 36px; height: 36px; display: inline-flex; align-items: center;
  justify-content: center; background: var(--bg-elev);
  border: 1px solid var(--line); color: var(--fg-soft); cursor: pointer;
  padding: 0; font-family: inherit;
  transition: background 0.18s, color 0.18s, border-color 0.18s, transform 0.18s;
  border-radius: 4px;
}
.theme-toggle:hover { background: var(--bg-cell); color: var(--fg);
  border-color: var(--accent); }
.theme-toggle:active { transform: scale(0.94); }
.theme-toggle svg { width: 14px; height: 14px; display: block; }
.theme-toggle .icon-sun { display: inline; }
.theme-toggle .icon-moon { display: none; }
:root[data-theme="light"] .theme-toggle .icon-sun { display: none; }
:root[data-theme="light"] .theme-toggle .icon-moon { display: inline; }

/* === HERO === */
.hero { padding: 4em 2.4em 3em; border-bottom: 1px solid var(--line-soft);
  position: relative; display: grid;
  grid-template-columns: minmax(280px, 0.9fr) minmax(320px, 1.1fr);
  gap: 3.5em; align-items: start; }
.hero-left { position: relative; }
.hero-eyebrow { font-size: 11px; letter-spacing: 0.28em; text-transform: uppercase;
  color: var(--mute); margin-bottom: 1.2em; font-weight: 500;
  display: flex; align-items: center; gap: 0.7em; }
.hero-eyebrow::before { content: ''; width: 20px; height: 1px;
  background: var(--accent); }

/* Big sim score — the typographic centerpiece. */
.hero-sim {
  font-family: 'Fraunces', 'Times New Roman', serif;
  font-weight: 500; font-variation-settings: 'opsz' 144;
  font-size: clamp(96px, 16vw, 180px);
  line-height: 0.85; letter-spacing: -0.06em;
  color: var(--fg); margin: 0 0 0.1em;
  font-variant-numeric: tabular-nums;
  text-shadow: 0 1px 0 color-mix(in srgb, var(--accent) 25%, transparent);
}
.hero-sim .dot { color: var(--accent); }
.hero[data-verdict="danger"] .hero-sim { color: var(--bad); }
.hero[data-verdict="warning"] .hero-sim { color: var(--warn); }
.hero[data-verdict="ok"] .hero-sim { color: var(--accent); }
.hero[data-verdict="fresh"] .hero-sim { color: var(--good); }
.hero[data-verdict="ood"] .hero-sim { color: var(--mute); }

.hero-sim-label { font-size: 11px; letter-spacing: 0.16em;
  text-transform: uppercase; color: var(--fg-soft); margin-bottom: 1.6em;
  display: flex; align-items: center; gap: 0.6em; }
.hero-sim-label code { background: none; padding: 0; color: var(--accent);
  font-weight: 500; }

.verdict-label {
  font-family: 'Fraunces', serif; font-style: italic; font-weight: 400;
  font-variation-settings: 'opsz' 144;
  font-size: clamp(32px, 4.5vw, 48px);
  line-height: 1.05; letter-spacing: -0.02em;
  color: var(--fg); margin: 0 0 0.6em;
}
.hero[data-verdict="danger"] .verdict-label { color: var(--bad); }
.hero[data-verdict="warning"] .verdict-label { color: var(--warn); }
.hero[data-verdict="ok"] .verdict-label { color: var(--accent-deep); }
.hero[data-verdict="fresh"] .verdict-label { color: var(--good); }
.hero[data-verdict="ood"] .verdict-label { color: var(--mute); }

.hero-hook { font-size: 15px; color: var(--fg-soft); max-width: 50ch;
  margin: 0 0 1.6em; line-height: 1.6; }

/* Spectrum bar — replaces EvalForge-style verdict list. */
.spectrum { position: relative; margin-top: 2em;
  padding: 1.2em 0 1.8em; }
.spectrum-title { font-size: 10px; letter-spacing: 0.24em;
  text-transform: uppercase; color: var(--mute); margin-bottom: 1.4em; }
.spectrum-bar {
  position: relative; height: 8px; border-radius: 4px;
  background: linear-gradient(to right,
    var(--mute) 0%, var(--mute) 30%,
    var(--good) 30%, var(--good) 55%,
    var(--accent) 55%, var(--accent) 75%,
    var(--warn) 75%, var(--warn) 90%,
    var(--bad) 90%, var(--bad) 100%);
  box-shadow: inset 0 1px 2px rgba(0,0,0,0.15);
}
.spectrum-marker {
  position: absolute; top: -10px; width: 2px; height: 28px;
  background: var(--fg);
  box-shadow: 0 0 0 3px var(--bg);
  transform: translateX(-50%);
  transition: left 0.6s cubic-bezier(0.2,0.8,0.2,1);
}
.spectrum-marker::after {
  content: ''; position: absolute; left: 50%; top: -4px;
  width: 12px; height: 12px; border-radius: 50%;
  background: var(--fg); transform: translateX(-50%);
  box-shadow: 0 0 0 3px var(--bg), 0 0 12px color-mix(in srgb, var(--fg) 40%, transparent);
}
.spectrum-ticks { display: flex; justify-content: space-between;
  margin-top: 8px; font-family: 'DM Mono', monospace; font-size: 10px;
  color: var(--mute); }
.spectrum-legend { display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 0.6em; margin-top: 1.4em; font-size: 11px; }
.spectrum-legend-item { padding: 0.6em 0.7em;
  border: 1px solid var(--line-soft);
  background: var(--bg-elev); border-radius: 4px; transition: all 0.2s; }
.spectrum-legend-item.active {
  border-color: currentColor;
  background: color-mix(in srgb, currentColor 12%, var(--bg-elev));
}
.spectrum-legend-item.danger { color: var(--bad); }
.spectrum-legend-item.warning { color: var(--warn); }
.spectrum-legend-item.ok { color: var(--accent); }
.spectrum-legend-item.fresh { color: var(--good); }
.spectrum-legend-item.ood { color: var(--mute); }
.spectrum-legend-label { font-weight: 600; letter-spacing: 0.04em;
  font-size: 10px; text-transform: uppercase; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.spectrum-legend-range { color: var(--mute); font-size: 10px;
  font-family: 'DM Mono', monospace; margin-top: 2px; }

/* Right-side cards: paragraph + top neighbor */
.hero-right { display: flex; flex-direction: column; gap: 1em; }
.hero-card {
  position: relative; padding: 1.4em 1.6em 1.4em 2em;
  background: var(--bg-elev); border-radius: 6px;
  border: 1px solid var(--line-soft);
  box-shadow: var(--shadow-soft);
}
.hero-card::before {
  content: ''; position: absolute; left: 0; top: 1em; bottom: 1em;
  width: 3px; background: var(--accent); border-radius: 0 2px 2px 0;
}
.hero-card.neighbor::before { background: var(--highlight); }
.hero-card-label { font-size: 10px; letter-spacing: 0.18em;
  text-transform: uppercase; color: var(--accent-deep); font-weight: 600;
  margin-bottom: 0.7em; display: flex; align-items: center;
  justify-content: space-between; gap: 0.6em; }
.hero-card.neighbor .hero-card-label { color: var(--highlight); }
.hero-card-meta { font-family: 'DM Mono', monospace;
  font-size: 11px; color: var(--mute); font-weight: 400;
  letter-spacing: 0; text-transform: none; }
.hero-card-text { font-size: 14px; color: var(--fg); line-height: 1.55;
  font-style: italic; }
.hero-card.neighbor .hero-card-text { font-style: normal; }

/* === METRICS === */
.metrics { display: grid; grid-template-columns: repeat(3, 1fr);
  border-bottom: 1px solid var(--line-soft); }
.metric { padding: 2em 2.4em; border-right: 1px solid var(--line-soft);
  position: relative; overflow: hidden; }
.metric:last-child { border-right: none; }
.metric-label { font-size: 10px; letter-spacing: 0.28em;
  text-transform: uppercase; color: var(--mute); margin-bottom: 0.8em; }
.metric-value { font-size: 44px; font-weight: 300; line-height: 1;
  letter-spacing: -0.04em; color: var(--fg); font-variant-numeric: tabular-nums; }
.metric-value-sub { font-size: 22px; color: var(--mute); font-weight: 300;
  letter-spacing: -0.02em; }
.metric-detail { margin-top: 0.6em; font-size: 11px; color: var(--fg-soft);
  letter-spacing: 0.04em; }
.metric-detail b { color: var(--fg); font-weight: 400; }

/* === SECTION TITLE === */
.section-title { font-size: 11px; letter-spacing: 0.32em;
  text-transform: uppercase; color: var(--mute);
  margin: 3.5em 2.4em 1.4em; display: flex; align-items: center; gap: 1em; }
.section-title::before { content: ''; width: 24px; height: 1px;
  background: var(--accent); }
.section-title::after { content: ''; flex: 1; height: 1px; background: var(--line); }

/* === CHART SECTION === */
.chart-section { padding: 0 2.4em; margin-bottom: 3em; }
.chart-section h3 {
  font-family: 'Fraunces', serif; font-style: italic; font-weight: 400;
  font-size: 32px; margin: 0 0 0.4em; color: var(--fg);
  letter-spacing: -0.01em; line-height: 1.1;
}
.caption {
  background: var(--bg-elev); border-left: 2px solid var(--accent);
  padding: 1em 1.4em; margin: 0.4em 0 1em;
  font-size: 13px; line-height: 1.55; color: var(--fg-soft);
}
.caption code { background: var(--code-bg); padding: 1px 6px;
  border-radius: 3px; font-size: 0.88em; color: var(--fg); }
.viz {
  background: var(--chart-bg); border: 1px solid var(--line);
  border-radius: 4px; padding: 8px; margin-bottom: 0.8em;
  box-shadow: var(--shadow);
}

/* === HELP/DEBUG DETAILS === */
details.help {
  background: var(--bg-elev); border: 1px solid var(--line);
  border-radius: 4px; padding: 12px 18px; margin: 8px 0;
  font-size: 13px;
}
details.help.debug { border-left: 3px solid var(--highlight); }
details.help summary {
  cursor: pointer; color: var(--fg); font-size: 12px;
  letter-spacing: 0.04em; padding: 4px 0;
  list-style: none;
}
details.help summary::-webkit-details-marker { display: none; }
details.help summary::before {
  content: '+'; display: inline-block; width: 1.2em; color: var(--accent);
  font-weight: 700;
}
details.help[open] summary::before { content: '−'; }
details.help summary:hover { color: var(--accent); }
details.help.debug summary::before { color: var(--highlight); }
details.help.debug summary:hover { color: var(--highlight); }
.help-body { margin-top: 12px; color: var(--fg-soft); line-height: 1.6; }
.help-body p { margin: 8px 0; }
.help-body h4 { color: var(--fg); font-weight: 500; font-size: 12px;
  letter-spacing: 0.08em; text-transform: uppercase; margin: 16px 0 8px; }
.help-body code { background: var(--code-bg); padding: 1px 6px;
  border-radius: 3px; font-size: 0.88em; color: var(--fg); }
.help-body ul, .help-body ol { padding-left: 22px; margin: 8px 0; }
.help-body li { margin: 6px 0; }
.help-body dl { display: block; }
.help-body dt { font-weight: 500; color: var(--fg);
  font-size: 12.5px; margin-top: 14px; }
.help-body dd { margin: 6px 0 0; color: var(--fg-soft); padding-left: 0; }

/* Example box */
.example {
  background: color-mix(in srgb, var(--highlight) 10%, var(--bg-cell));
  border-left: 2px solid var(--highlight);
  padding: 10px 14px; margin: 10px 0; font-size: 12px;
  color: var(--fg-soft); border-radius: 0 4px 4px 0;
}
.example b { color: var(--highlight); font-weight: 500; }
.example code { background: var(--code-bg); padding: 1px 5px;
  border-radius: 3px; font-size: 0.88em; color: var(--fg); }

/* Glossary block */
details.help.glossary { margin: 2em 2.4em; }
details.term {
  background: var(--bg-cell); border: 1px solid var(--line-soft);
  border-radius: 4px; padding: 10px 16px; margin: 8px 0;
}
details.term summary { cursor: pointer; color: var(--fg); font-size: 13px;
  padding: 4px 0; list-style: none; }
details.term summary::-webkit-details-marker { display: none; }
details.term summary::before {
  content: '›'; display: inline-block; width: 1.2em; color: var(--accent);
  transition: transform 0.2s;
}
details.term[open] summary::before { transform: rotate(90deg); }
details.term summary:hover { color: var(--accent); }
details.term .tagline { color: var(--mute); font-weight: normal;
  font-size: 0.9em; margin-left: 0.5em; }
.term-body { color: var(--fg-soft); padding: 6px 0 4px 1.2em;
  line-height: 1.6; }
.term-body p { margin: 6px 0; }
.term-body strong { color: var(--fg); }
.term-body code { background: var(--code-bg); padding: 1px 5px;
  border-radius: 3px; font-size: 0.88em; color: var(--fg); }
.term-body ul { padding-left: 20px; margin: 6px 0; }

/* CSS tooltip */
.tip { position: relative; text-decoration: underline dotted var(--mute);
  cursor: help; }
.tip:hover { color: var(--accent); }
.tip:hover::after {
  content: attr(data-tip); position: absolute;
  bottom: calc(100% + 8px); left: 0;
  transform: translateX(-25%);
  background: var(--bg-elev); color: var(--fg);
  border: 1px solid var(--accent);
  padding: 10px 14px; border-radius: 4px;
  font-size: 12px; font-weight: normal; line-height: 1.5;
  white-space: normal; width: 320px; z-index: 1000;
  box-shadow: var(--shadow); pointer-events: none;
}
.tip:hover::before {
  content: ''; position: absolute; bottom: calc(100% + 2px); left: 25%;
  border: 6px solid transparent; border-top-color: var(--accent);
  z-index: 1000; pointer-events: none;
}

/* Use-cases banner */
.use-cases { padding: 2em 2.4em; border-bottom: 1px solid var(--line-soft);
  background: var(--bg-elev); }
.use-cases-title { font-size: 11px; letter-spacing: 0.32em;
  text-transform: uppercase; color: var(--mute); margin-bottom: 1.4em; }
.use-cases-grid { display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 1.6em; }
.use-case { padding: 0; }
.use-case-num { font-family: 'Fraunces', serif; font-style: italic;
  font-size: 32px; color: var(--accent); line-height: 1; margin-bottom: 0.4em; }
.use-case-title { font-weight: 500; color: var(--fg); font-size: 13px;
  letter-spacing: 0.04em; margin-bottom: 0.5em; }
.use-case-text { color: var(--fg-soft); line-height: 1.55; font-size: 12px; }
.use-case-text code { background: var(--code-bg); padding: 1px 5px;
  border-radius: 3px; font-size: 0.88em; color: var(--fg); }

.inline-badge { padding: 1px 8px; border-radius: 10px;
  font-size: 0.78rem; font-weight: 700; letter-spacing: 0.4px;
  white-space: nowrap; background: var(--bg-cell); color: var(--mute);
  border: 1px solid var(--line); }

@media (max-width: 900px) {
  .topbar, .hero, .metrics, .use-cases { padding-left: 1.4em; padding-right: 1.4em; }
  .hero { grid-template-columns: 1fr; gap: 2em; }
  .metrics { grid-template-columns: 1fr; }
  .use-cases-grid { grid-template-columns: 1fr; }
  .spectrum-legend { grid-template-columns: repeat(2, 1fr); }
  .chart-section { padding: 0 1.4em; }
  .section-title { margin-left: 1.4em; margin-right: 1.4em; }
  details.help.glossary { margin: 2em 1.4em; }
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

    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>OpenCrane · embedding placement</title>",
        THEME_BOOT_JS,
        # Pin Plotly to a version compatible with plotly-python 6.x output.
        "<script src='https://cdn.plot.ly/plotly-3.0.1.min.js'></script>",
        STYLES,
        "</head><body>",
        # Topbar
        '<div class="topbar">',
        '<div class="brand">',
        LOGO_IMG,
        '<span><strong>OpenCrane</strong><span class="sep">//</span>embedding placement</span>',
        '</div>',
        '<div class="topbar-right">',
        '<div class="topbar-meta">',
        f'<div>model <b>{ctx["model_name"]}</b></div>',
        f'<div>corpus sample <b>{ctx["sample_size"]}</b>'
        f'{" · " + ctx["info"] if ctx.get("info") else ""}</div>',
        '</div>',
        THEME_TOGGLE_HTML,
        '</div>',
        '</div>',
        THEME_TOGGLE_JS,
        # Hero — two-column: sim score + verdict on left, content cards on right.
        f'<div class="hero" data-verdict="{verdict["level"]}">',
        '<div class="hero-left">',
        '<div class="hero-eyebrow">duplicate-content check</div>',
        # Big sim number with period in accent color.
        f'<div class="hero-sim">{sim_str}</div>',
        '<div class="hero-sim-label">cos similarity · top match in '
        f'<code>{ctx["top_source"]}</code></div>',
        f'<div class="verdict-label">{verdict["label"]}</div>',
        f'<p class="hero-hook">{verdict["hook"]}</p>',
        # Spectrum bar.
        '<div class="spectrum">',
        '<div class="spectrum-title">where you land on the similarity spectrum</div>',
        '<div class="spectrum-bar">',
        f'<div class="spectrum-marker" style="left: {min(100, max(0, ctx["top_sim"] * 100)):.1f}%"></div>',
        '</div>',
        '<div class="spectrum-ticks">',
        '<span>0.00</span><span>0.30</span><span>0.55</span>'
        '<span>0.75</span><span>0.90</span><span>1.00</span>',
        '</div>',
        '<div class="spectrum-legend">',
        *[(f'<div class="spectrum-legend-item {lvl}'
           f'{" active" if lvl == verdict["level"] else ""}">'
           f'<div class="spectrum-legend-label">{lbl}</div>'
           f'<div class="spectrum-legend-range">{rng}</div>'
           f'</div>')
          for lvl, lbl, rng, _ in VERDICT_SCALE],
        '</div>',  # /spectrum-legend
        '</div>',  # /spectrum
        '</div>',  # /hero-left
        # Right side: paragraph + top neighbor side-by-side comparison.
        '<div class="hero-right">',
        '<div class="hero-card">',
        '<div class="hero-card-label">your paragraph'
        '<span class="hero-card-meta">input</span></div>',
        f'<div class="hero-card-text">{ctx["paragraph_preview"]}</div>',
        '</div>',
        '<div class="hero-card neighbor">',
        '<div class="hero-card-label">top neighbor'
        f'<span class="hero-card-meta">{ctx["top_source"]} · '
        f'sim {ctx["top_sim"]:.3f}</span></div>',
        f'<div class="hero-card-text">{ctx["top_snippet"]}</div>',
        '</div>',
        '</div>',  # /hero-right
        '</div>',  # /hero
        # Metrics
        '<div class="metrics">',
        '<div class="metric">',
        '<div class="metric-label">Top neighbor</div>',
        f'<div class="metric-value">{ctx["top_sim"]:.3f}<span class="metric-value-sub"> sim</span></div>',
        f'<div class="metric-detail">repo <b>{ctx["top_source"]}</b></div>',
        '</div>',
        '<div class="metric">',
        '<div class="metric-label">Neighbors checked</div>',
        f'<div class="metric-value">{ctx["neighbor_count"]}</div>',
        f'<div class="metric-detail">spread across <b>{ctx["unique_neighbor_sources"]}</b> repo(s)</div>',
        '</div>',
        '<div class="metric">',
        '<div class="metric-label">Corpus sample</div>',
        f'<div class="metric-value">{ctx["sample_size"]:,}</div>',
        f'<div class="metric-detail">chunks projected</div>',
        '</div>',
        '</div>',
        # Three ways
        '<div class="use-cases">',
        '<div class="use-cases-title">three ways to use this page</div>',
        '<div class="use-cases-grid">',
        '<div class="use-case">',
        '<div class="use-case-num">01</div>',
        '<div class="use-case-title">Place new content</div>',
        '<div class="use-case-text">Paste a draft to see which repos cover '
        'the topic, what to cross-reference, and whether you\'d be duplicating '
        'existing chunks (verdict above is your answer).</div>',
        '</div>',
        '<div class="use-case">',
        '<div class="use-case-num">02</div>',
        '<div class="use-case-title">Test RAG retrieval</div>',
        '<div class="use-case-text">Paste a <em>user query</em> instead of a '
        'draft and check whether the doc that <em>should</em> answer it shows '
        f'up in the top neighbors. An '
        f'<span class="inline-badge">OUT OF DISTRIBUTION</span> verdict on a '
        'real question = clear docs gap.</div>',
        '</div>',
        '<div class="use-case">',
        '<div class="use-case-num">03</div>',
        '<div class="use-case-title">Debug chunking pipeline</div>',
        f'<div class="use-case-text">Spot duplicate chunks, {tip_boilerplate}, '
        f'{tip_oversplit}, and other chunking-quality problems. Each chart '
        'has its own <b>What it helps with</b> box.</div>',
        '</div>',
        '</div></div>',
        # Glossary
        '<div class="section-title">deep-dive glossary</div>',
        f'<div style="margin: 0 2.4em">{GLOSSARY_HTML.replace(chr(10), " ")}</div>',
    ]

    # Chart sections
    for title, fig, viz_key in figs:
        parts.append('<div class="section-title">visualization</div>')
        parts.append('<div class="chart-section">')
        parts.append(f'<h3>{title}</h3>')
        caption = VIZ_TO_CAPTION.get(viz_key)
        if caption:
            parts.append(f'<div class="caption">{caption}</div>')
        parts.append('<div class="viz">')
        parts.append(pio.to_html(fig, include_plotlyjs=False, full_html=False))
        parts.append('</div>')
        parts.append(VIZ_TO_HELP.get(viz_key, ""))
        parts.append(VIZ_TO_DEBUG.get(viz_key, ""))
        parts.append('</div>')

    parts.append("</body></html>")
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

    corpus = load_corpus(embeddings_file, chunks_file, sample, seed)
    new_vec = encode_paragraph(corpus.model_name, paragraph)
    if new_vec.shape[0] != corpus.vectors.shape[1]:
        raise SystemExit(
            f"Dimension mismatch: model returned {new_vec.shape[0]}, "
            f"corpus is {corpus.vectors.shape[1]}"
        )

    neighbor_idx, neighbor_sims, all_sims = _nearest_neighbors(corpus.vectors, new_vec, neighbors)
    logger.info("Top neighbor similarity: %.3f (%s)",
                float(neighbor_sims[0]), corpus.sources[int(neighbor_idx[0])])

    paragraph_preview = (paragraph[:240].replace("\n", " ")
                         + ("…" if len(paragraph) > 240 else ""))

    figs = []
    info = ""
    if viz in ("scatter", "all"):
        coords, new_coords, info = reduce_dims(corpus.vectors, new_vec, method, dim, seed)
        figs.append((
            f"Global scatter ({method.upper()}, {dim}D)",
            _build_scatter_figure(coords, new_coords, corpus,
                                  neighbor_idx, neighbor_sims, paragraph_preview, info),
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
        sample_size=len(corpus.vectors),
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
