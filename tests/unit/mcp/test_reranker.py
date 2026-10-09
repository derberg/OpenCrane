"""Tests for the optional search reranker stage."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from opencrane.config import OpenCraneConfig
from opencrane.mcp import server as mcp_server
from opencrane.mcp.services.reranker import (
    CrossEncoderReranker,
    apply_reranker,
    candidate_text,
)


def _cand(cid: str, content="text", distance: float = 0.5) -> dict:
    return {
        "chunk_id": cid,
        "content": content,
        "source_file": f"{cid}.md",
        "chunk_type": "prose",
        "metadata_json": "{}",
        "distance": distance,
    }


@pytest.fixture
def reranker_state(monkeypatch):
    """Isolate the module-level reranker cache; tests set it via this helper."""
    monkeypatch.setattr(mcp_server, "_reranker", None)
    monkeypatch.setattr(mcp_server, "_reranker_resolved", False)

    def _set(reranker, depth=50):
        monkeypatch.setattr(mcp_server, "_reranker", reranker)
        monkeypatch.setattr(mcp_server, "_reranker_resolved", True)
        monkeypatch.setenv("RERANK_DEPTH", str(depth))

    return _set


# --- candidate_text -------------------------------------------------------


def test_candidate_text_string_and_structured_content():
    assert candidate_text({"content": "plain"}) == "plain"
    assert candidate_text({}) == ""
    assert "kind: Thing" in candidate_text({"content": {"kind": "Thing"}})
    assert "- a" in candidate_text({"content": ["a"]})


# --- CrossEncoderReranker -------------------------------------------------


def test_cross_encoder_empty_candidates_does_not_load_model():
    with patch("sentence_transformers.CrossEncoder") as ce:
        assert CrossEncoderReranker("m").rerank("q", []) == []
    ce.assert_not_called()


def test_cross_encoder_scores_sorts_and_loads_lazily_once():
    model = MagicMock()
    model.predict.side_effect = [[0.1, 0.9, 0.5], [0.3]]
    with patch("sentence_transformers.CrossEncoder", return_value=model) as ce:
        rr = CrossEncoderReranker("cross/model", batch_size=4)
        ce.assert_not_called()  # lazy
        cands = [_cand("a", "alpha"), _cand("b", {"k": "v"}), _cand("c", "gamma")]
        out = rr.rerank("question", cands)
        rr.rerank("question", [_cand("d")])

    ce.assert_called_once_with("cross/model", device="cpu", trust_remote_code=True)
    assert [r["chunk_id"] for r in out] == ["b", "c", "a"]
    assert [r["distance"] for r in out] == [0.9, 0.5, 0.1]
    # Input dicts are not mutated.
    assert cands[0]["distance"] == 0.5
    pairs = model.predict.call_args_list[0].args[0]
    assert pairs[0] == ("question", "alpha")
    assert pairs[1] == ("question", "k: v\n")
    assert model.predict.call_args_list[0].kwargs == {"batch_size": 4, "show_progress_bar": False}


# --- apply_reranker -------------------------------------------------------


def test_apply_reranker_object_and_callable_truncate_to_limit():
    cands = [_cand("a"), _cand("b"), _cand("c")]

    class Rev:
        def rerank(self, query, candidates):
            return list(reversed(candidates))

    assert [r["chunk_id"] for r in apply_reranker(Rev(), "q", cands, 2)] == ["c", "b"]
    fn = lambda q, cs: cs[1:]  # noqa: E731 — callable that also drops a candidate
    assert [r["chunk_id"] for r in apply_reranker(fn, "q", cands, 5)] == ["b", "c"]


@pytest.mark.parametrize(
    "reranker",
    [
        lambda q, cs: (_ for _ in ()).throw(RuntimeError("model gone")),
        lambda q, cs: tuple(cs),  # wrong return type
    ],
)
def test_apply_reranker_failure_falls_back_with_warning(reranker, caplog):
    cands = [_cand("a"), _cand("b"), _cand("c")]
    with caplog.at_level(logging.WARNING, logger="opencrane.mcp.services.reranker"):
        out = apply_reranker(reranker, "q", cands, 2)
    assert [r["chunk_id"] for r in out] == ["a", "b"]
    assert "Reranker failed" in caplog.text


# --- get_reranker ---------------------------------------------------------


def test_get_reranker_default_off(reranker_state, monkeypatch):
    monkeypatch.delenv("RERANKER_MODEL", raising=False)
    with patch("opencrane.cli.load_config", return_value=OpenCraneConfig()) as lc:
        assert mcp_server.get_reranker() is None
        assert mcp_server.get_reranker() is None
    lc.assert_called_once_with(None)  # resolved once, then cached


def test_get_reranker_project_hook_wins_over_env(reranker_state, monkeypatch):
    monkeypatch.setenv("RERANKER_MODEL", "cross/model")
    hook = lambda q, cs: cs  # noqa: E731

    class Cfg(OpenCraneConfig):
        reranker = hook

    with patch("opencrane.cli.load_config", return_value=Cfg()):
        assert mcp_server.get_reranker() is hook


def test_get_reranker_unwraps_staticmethod(reranker_state):
    def hook(q, cs):
        return cs

    class Cfg(OpenCraneConfig):
        reranker = staticmethod(hook)

    with patch("opencrane.cli.load_config", return_value=Cfg()):
        assert mcp_server.get_reranker() is hook


def test_get_reranker_env_selects_cross_encoder(reranker_state, monkeypatch):
    monkeypatch.setenv("RERANKER_MODEL", "cross/model")
    with patch("opencrane.cli.load_config", return_value=OpenCraneConfig()):
        rr = mcp_server.get_reranker()
    assert isinstance(rr, CrossEncoderReranker)
    assert rr.model_name == "cross/model"
    assert rr.model is None  # not loaded until first search


def test_get_reranker_config_load_failure_falls_back_to_env(reranker_state, monkeypatch, caplog):
    monkeypatch.setenv("RERANKER_MODEL", "cross/model")
    with patch("opencrane.cli.load_config", side_effect=RuntimeError("bad extensions")), \
            caplog.at_level(logging.WARNING, logger="opencrane.mcp.server"):
        rr = mcp_server.get_reranker()
    assert isinstance(rr, CrossEncoderReranker)
    assert "Failed to load project reranker" in caplog.text


# --- search_docs integration ---------------------------------------------


class _Embeddings:
    class model:  # noqa: N801 — mimics EmbeddingService.model
        @staticmethod
        def encode(queries, batch_size=None, show_progress_bar=False):
            return [[0.1] * 4 for _ in queries]


def _backends(monkeypatch, sem: list[dict], key: list[dict]):
    calls = {}

    class Milvus:
        def search(self, vec, limit=5, **kw):
            calls["semantic"] = limit
            return [dict(r) for r in sem[:limit]]

    class Keyword:
        def search(self, query, limit=5, **kw):
            calls["keyword"] = limit
            return [dict(r) for r in key[:limit]]

    monkeypatch.setattr(mcp_server, "get_embeddings_service", lambda: _Embeddings())
    monkeypatch.setattr(mcp_server, "get_milvus_service", lambda: Milvus())
    monkeypatch.setattr(mcp_server, "get_keyword_service", lambda: Keyword())
    return calls


def _ids(res) -> list[str]:
    return [line.split(": ", 1)[1] for t in res for line in t.text.splitlines() if line.startswith("Chunk ID:")]


class _Reverser:
    def __init__(self):
        self.seen = None

    def rerank(self, query, candidates):
        self.seen = (query, [c["chunk_id"] for c in candidates])
        out = []
        for i, c in enumerate(reversed(candidates)):
            c = dict(c)
            c["distance"] = 100 - i
            out.append(c)
        return out


POOL = [_cand(f"c{i}", f"content {i}", distance=1.0 - i / 10) for i in range(6)]


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["semantic", "keyword"])
async def test_single_mode_reranks_depth_candidates(mode, monkeypatch, reranker_state):
    rr = _Reverser()
    reranker_state(rr, depth=4)
    calls = _backends(monkeypatch, POOL, POOL)

    res = await mcp_server._search_documentation_impl({"query": "q", "search_mode": mode, "limit": 2})

    assert calls == {mode: 4}
    assert rr.seen == ("q", ["c0", "c1", "c2", "c3"])
    assert _ids(res) == ["c3", "c2"]
    assert "Score: 100" in res[0].text


@pytest.mark.anyio
async def test_hybrid_reranks_after_fusion(monkeypatch, reranker_state):
    rr = _Reverser()
    reranker_state(rr, depth=3)
    calls = _backends(monkeypatch, POOL, POOL)

    res = await mcp_server._search_documentation_impl({"query": "q", "search_mode": "hybrid", "limit": 1})

    assert calls == {"semantic": 3, "keyword": 3}
    assert rr.seen == ("q", ["c0", "c1", "c2"])  # fused order, cut to depth
    assert _ids(res) == ["c2"]


@pytest.mark.anyio
async def test_depth_never_below_limit(monkeypatch, reranker_state):
    rr = _Reverser()
    reranker_state(rr, depth=1)
    calls = _backends(monkeypatch, POOL, POOL)

    res = await mcp_server._search_documentation_impl({"query": "q", "search_mode": "semantic", "limit": 3})

    assert calls == {"semantic": 3}
    assert _ids(res) == ["c2", "c1", "c0"]


@pytest.mark.anyio
async def test_no_reranker_keeps_todays_behaviour(monkeypatch, reranker_state):
    reranker_state(None)
    calls = _backends(monkeypatch, POOL, POOL)

    res = await mcp_server._search_documentation_impl({"query": "q", "search_mode": "hybrid", "limit": 2})

    assert calls == {"semantic": 2, "keyword": 2}
    assert _ids(res) == ["c0", "c1"]


@pytest.mark.anyio
async def test_failing_reranker_returns_unreranked_results(monkeypatch, reranker_state, caplog):
    def boom(query, candidates):
        raise RuntimeError("cuda on fire")

    reranker_state(boom, depth=4)
    _backends(monkeypatch, POOL, POOL)

    with caplog.at_level(logging.WARNING, logger="opencrane.mcp.services.reranker"):
        res = await mcp_server._search_documentation_impl({"query": "q", "search_mode": "keyword", "limit": 2})

    assert _ids(res) == ["c0", "c1"]
    assert "cuda on fire" in caplog.text


@pytest.mark.anyio
async def test_reranker_not_called_without_candidates(monkeypatch, reranker_state):
    rr = MagicMock()
    reranker_state(rr)
    _backends(monkeypatch, [], [])

    res = await mcp_server._search_documentation_impl({"query": "q", "search_mode": "semantic", "limit": 2})

    assert res[0].text == "No results found."
    rr.rerank.assert_not_called()
