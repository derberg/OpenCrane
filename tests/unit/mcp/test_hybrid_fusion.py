"""Hybrid search candidate pool and fusion method (min-max blend vs RRF)."""
import re

import pytest
from unittest.mock import patch

from opencrane.mcp import server as mcp_server
from opencrane.shared.config import Config


def _hit(cid: str, distance: float) -> dict:
    return {
        "chunk_id": cid,
        "content": f"content {cid}",
        "source_file": f"{cid}.md",
        "chunk_type": "prose",
        "metadata_json": "{}",
        "distance": distance,
    }


class _Embeddings:
    class model:  # noqa: N801 - mimics the service attribute
        @staticmethod
        def encode(queries, batch_size=None, show_progress_bar=False):
            return [[0.5] * 4 for _ in queries]


class _Arm:
    """Fake search backend returning the top ``limit`` of a fixed ranked list."""

    def __init__(self, hits: list[dict]):
        self.hits = hits
        self.limits: list[int] = []

    def search(self, _query, limit=5, chunk_types=None, source_names=None, metadata_contains=None):
        self.limits.append(limit)
        return self.hits[:limit]


def _ids(res) -> list[str]:
    return [re.search(r"Chunk ID: (\S+)", r.text).group(1) for r in res]


def _scores(res) -> list[float]:
    return [float(re.search(r"Score: (\S+)", r.text).group(1)) for r in res]


async def _run(monkeypatch, sem_hits, key_hits, env: dict, **args):
    for name in ("HYBRID_CANDIDATE_POOL", "HYBRID_FUSION", "HYBRID_RRF_K", "HYBRID_ALPHA"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    sem, key = _Arm(sem_hits), _Arm(key_hits)
    with patch.object(mcp_server, "get_embeddings_service", return_value=_Embeddings()), \
         patch.object(mcp_server, "get_milvus_service", return_value=sem), \
         patch.object(mcp_server, "get_keyword_service", return_value=key):
        res = await mcp_server._search_documentation_impl(
            {"query": "q", "search_mode": "hybrid", **args}
        )
    return res, sem, key


# Both arms rank "shared" 3rd; each arm's top two are unique to that arm.
SEM = [_hit("s1", 0.9), _hit("s2", 0.8), _hit("shared", 0.7), _hit("s4", 0.1)]
KEY = [_hit("k1", 9.0), _hit("k2", 8.0), _hit("shared", 7.0), _hit("k4", 1.0)]


class TestConfigKnobs:
    def test_defaults(self, monkeypatch):
        for name in ("HYBRID_CANDIDATE_POOL", "HYBRID_FUSION", "HYBRID_RRF_K"):
            monkeypatch.delenv(name, raising=False)
        cfg = Config()
        assert cfg.hybrid_candidate_pool == 0
        assert cfg.hybrid_fusion == "minmax"
        assert cfg.hybrid_rrf_k == 60

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("HYBRID_CANDIDATE_POOL", "50")
        monkeypatch.setenv("HYBRID_FUSION", " RRF ")
        monkeypatch.setenv("HYBRID_RRF_K", "10")
        cfg = Config()
        assert cfg.hybrid_candidate_pool == 50
        assert cfg.hybrid_fusion == "rrf"
        assert cfg.hybrid_rrf_k == 10


class TestCandidatePool:
    @pytest.mark.anyio
    async def test_default_pool_equals_limit(self, monkeypatch):
        """Unset pool keeps today's behaviour: each arm fetches exactly `limit`."""
        res, sem, key = await _run(monkeypatch, SEM, KEY, {}, limit=2)
        assert sem.limits == [2] and key.limits == [2]
        assert len(res) == 2
        assert "shared" not in _ids(res)

    @pytest.mark.anyio
    async def test_pool_smaller_than_limit_uses_limit(self, monkeypatch):
        _, sem, key = await _run(monkeypatch, SEM, KEY, {"HYBRID_CANDIDATE_POOL": "1"}, limit=3)
        assert sem.limits == [3] and key.limits == [3]

    @pytest.mark.anyio
    async def test_wider_pool_fetches_more_and_still_cuts_to_limit(self, monkeypatch):
        res, sem, key = await _run(
            monkeypatch, SEM, KEY,
            {"HYBRID_CANDIDATE_POOL": "4", "HYBRID_FUSION": "rrf"}, limit=1, alpha=0.5,
        )
        assert sem.limits == [4] and key.limits == [4]
        # Rank 3 in both arms beats rank 1 in only one arm under RRF.
        assert _ids(res) == ["shared"]

    @pytest.mark.anyio
    async def test_pool_not_applied_outside_hybrid(self, monkeypatch):
        monkeypatch.setenv("HYBRID_CANDIDATE_POOL", "50")
        sem = _Arm(SEM)
        with patch.object(mcp_server, "get_embeddings_service", return_value=_Embeddings()), \
             patch.object(mcp_server, "get_milvus_service", return_value=sem):
            await mcp_server._search_documentation_impl(
                {"query": "q", "search_mode": "semantic", "limit": 2}
            )
        assert sem.limits == [2]


class TestFusion:
    @pytest.mark.anyio
    async def test_rrf_scores_classic_at_alpha_half(self, monkeypatch):
        res, _, _ = await _run(
            monkeypatch, SEM, KEY,
            {"HYBRID_CANDIDATE_POOL": "4", "HYBRID_FUSION": "rrf", "HYBRID_RRF_K": "60"},
            limit=3, alpha=0.5,
        )
        assert _ids(res)[0] == "shared"
        assert _scores(res)[0] == pytest.approx(2 / 63)
        assert _scores(res)[1] == pytest.approx(1 / 61)

    @pytest.mark.anyio
    async def test_rrf_alpha_weights_arms(self, monkeypatch):
        env = {"HYBRID_FUSION": "rrf", "HYBRID_RRF_K": "1"}
        res, _, _ = await _run(monkeypatch, SEM, KEY, env, limit=1, alpha=1.0)
        assert _ids(res) == ["s1"]
        assert _scores(res) == [pytest.approx(2 * 1 / 2)]
        res, _, _ = await _run(monkeypatch, SEM, KEY, env, limit=1, alpha=0.0)
        assert _ids(res) == ["k1"]

    @pytest.mark.anyio
    async def test_rrf_ranks_by_score_not_input_order_and_keeps_best_duplicate(self, monkeypatch):
        sem = [_hit("low", 0.1), _hit("high", 0.9), _hit("high", 0.05)]
        res, _, _ = await _run(
            monkeypatch, sem, [], {"HYBRID_FUSION": "rrf", "HYBRID_RRF_K": "0"},
            limit=2, alpha=1.0,
        )
        assert _ids(res) == ["high", "low"]
        assert _scores(res) == [pytest.approx(2.0), pytest.approx(1.0)]

    @pytest.mark.anyio
    async def test_minmax_default_unchanged(self, monkeypatch):
        res, _, _ = await _run(monkeypatch, SEM, KEY, {"HYBRID_CANDIDATE_POOL": "4"}, limit=1, alpha=0.6)
        # shared: 0.6 * (0.6 / 0.8) + 0.4 * (6 / 8) = 0.75 beats s1 (1.0 * 0.6).
        assert _ids(res) == ["shared"]
        assert _scores(res) == [pytest.approx(0.75)]

    @pytest.mark.anyio
    async def test_unknown_fusion_falls_back_to_minmax(self, monkeypatch, caplog):
        res, _, _ = await _run(monkeypatch, SEM, KEY, {"HYBRID_FUSION": "bogus"}, limit=1, alpha=0.6)
        assert _ids(res) == ["s1"]
        assert "Unknown HYBRID_FUSION 'bogus'" in caplog.text


class TestFusionRobustness:
    @pytest.mark.anyio
    async def test_rrf_ignores_keyword_hits_with_zero_score(self, monkeypatch):
        """Keyword padding that matches no query term must not earn RRF rank credit."""
        sem = [_hit("s1", 0.9), _hit("s2", 0.8), _hit("s3", 0.7)]
        key = [_hit("k1", 5.0), _hit("pad", 0.0), _hit("s3", 0.0)]
        res, _, _ = await _run(
            monkeypatch, sem, key,
            {"HYBRID_CANDIDATE_POOL": "3", "HYBRID_FUSION": "rrf"}, limit=5, alpha=0.5,
        )
        assert "pad" not in _ids(res)
        # s3 keeps only its semantic rank; the score-0 keyword hit adds nothing.
        assert dict(zip(_ids(res), _scores(res)))["s3"] == pytest.approx(1 / 63)

    @pytest.mark.anyio
    async def test_minmax_without_keyword_match_keeps_semantic_order(self, monkeypatch):
        """When no chunk matches a query term, min-max must not boost the padding to 1.0."""
        sem = [_hit("s1", 0.9), _hit("s2", 0.5)]
        key = [_hit("s2", 0.0), _hit("pad", 0.0)]
        res, _, _ = await _run(monkeypatch, sem, key, {}, limit=3, alpha=0.6)
        assert _ids(res) == ["s1", "s2"]

    @pytest.mark.anyio
    async def test_negative_rrf_k_is_clamped(self, monkeypatch):
        res, _, _ = await _run(
            monkeypatch, SEM, [], {"HYBRID_FUSION": "rrf", "HYBRID_RRF_K": "-1"}, limit=2, alpha=1.0,
        )
        assert _ids(res) == ["s1", "s2"]
        assert _scores(res) == [pytest.approx(2.0), pytest.approx(1.0)]

    @pytest.mark.anyio
    async def test_pool_capped_at_milvus_topk_limit(self, monkeypatch):
        _, sem, key = await _run(monkeypatch, SEM, KEY, {"HYBRID_CANDIDATE_POOL": "100000"}, limit=2)
        assert sem.limits == [mcp_server.MAX_HYBRID_CANDIDATE_POOL]
        assert key.limits == [mcp_server.MAX_HYBRID_CANDIDATE_POOL]

    @pytest.mark.anyio
    @pytest.mark.parametrize("sem_id, key_id", [("z", "a"), ("a", "z")])
    async def test_ties_break_by_chunk_id(self, monkeypatch, sem_id, key_id):
        """Equal RRF scores order by chunk_id, whichever arm each chunk came from."""
        res, _, _ = await _run(
            monkeypatch, [_hit(sem_id, 0.9)], [_hit(key_id, 5.0)],
            {"HYBRID_FUSION": "rrf"}, limit=2, alpha=0.5,
        )
        assert _ids(res) == ["a", "z"]
        assert _scores(res)[0] == pytest.approx(_scores(res)[1])


class TestAlphaSchema:
    def _alpha(self, monkeypatch, env: dict) -> dict:
        for name in ("HYBRID_FUSION", "HYBRID_RRF_K", "HYBRID_ALPHA"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        with patch.object(mcp_server, "_get_source_keys", return_value=[]), \
             patch.object(mcp_server, "_get_source_topics", return_value=[]), \
             patch.object(mcp_server, "_get_indexed_chunk_types", return_value={"prose"}), \
             patch.object(mcp_server, "_has_yaml_chunks", return_value=False):
            return mcp_server._build_search_tool().inputSchema["properties"]["alpha"]

    def test_minmax_schema_advertises_configured_default(self, monkeypatch):
        alpha = self._alpha(monkeypatch, {"HYBRID_ALPHA": "0.7"})
        assert alpha["default"] == 0.7
        assert "Default 0.7 " in alpha["description"]
        assert "rank fusion" not in alpha["description"]

    def test_rrf_schema_explains_rank_fusion_and_score_scale(self, monkeypatch):
        alpha = self._alpha(monkeypatch, {"HYBRID_FUSION": "rrf", "HYBRID_RRF_K": "60"})
        assert alpha["default"] == 0.6
        assert "reciprocal rank fusion" in alpha["description"]
        assert "at most 0.033" in alpha["description"]
        assert "a low score does not mean a weak match" in alpha["description"]
