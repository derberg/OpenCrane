"""Concurrent searches must not run the shared models in parallel.

Some models cache state between forward passes (nomic-bert caches its rotary
position tensors), so overlapping calls corrupt that state. These fakes record
how many calls are inside the model at once.
"""

import asyncio
import threading
import time

import pytest

from opencrane.mcp import server as mcp_server
from opencrane.mcp.services.reranker import CrossEncoderReranker


class _OverlapDetector:
    """Counts the calls that are inside the model at the same time."""

    def __init__(self):
        self._guard = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = 0

    def enter(self):
        with self._guard:
            self.active += 1
            self.calls += 1
            self.max_active = max(self.max_active, self.active)
        # Long enough for another thread to enter if nothing serializes the calls
        time.sleep(0.02)
        with self._guard:
            self.active -= 1


def _hit(cid: str) -> dict:
    return {
        "chunk_id": cid,
        "content": f"content {cid}",
        "source_file": f"{cid}.md",
        "chunk_type": "prose",
        "metadata_json": "{}",
        "distance": 0.5,
    }


@pytest.fixture
def detector(monkeypatch):
    detector = _OverlapDetector()

    class Model:
        def encode(self, texts, batch_size=None, show_progress_bar=False):
            detector.enter()
            return [[0.1] * 4 for _ in texts]

    class Embeddings:
        model = Model()
        model_name = "fake"

    class Backend:
        def search(self, *_args, limit=5, **_kwargs):
            return [_hit("a"), _hit("b")][:limit]

    monkeypatch.setattr(mcp_server, "get_embeddings_service", lambda: Embeddings())
    monkeypatch.setattr(mcp_server, "get_milvus_service", lambda: Backend())
    monkeypatch.setattr(mcp_server, "get_keyword_service", lambda: Backend())
    monkeypatch.setattr(mcp_server, "_reranker", None)
    monkeypatch.setattr(mcp_server, "_reranker_resolved", True)
    return detector


def test_concurrent_searches_and_health_probe_never_overlap_in_encode(detector):
    workers = 12
    barrier = threading.Barrier(workers + 1)
    results: list = []
    errors: list = []

    def search(mode: str, query: str):
        barrier.wait()
        try:
            results.append(asyncio.run(mcp_server._search_documentation_impl({"query": query, "search_mode": mode})))
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    def probe():
        barrier.wait()
        results.append(asyncio.run(mcp_server._query_probe()))

    threads = [
        threading.Thread(target=search, args=("semantic" if i % 2 else "hybrid", "word " * (i + 1)))
        for i in range(workers)
    ]
    threads.append(threading.Thread(target=probe))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert detector.calls == workers + 1
    assert detector.max_active == 1
    probe_result = next(r for r in results if isinstance(r, dict))
    assert probe_result["status"] in ("healthy", "degraded")
    for res in (r for r in results if isinstance(r, list)):
        assert not res[0].text.startswith("Search failed")


def test_concurrent_cross_encoder_reranks_never_overlap_in_predict():
    detector = _OverlapDetector()

    class Model:
        def predict(self, pairs, batch_size=None, show_progress_bar=False):
            detector.enter()
            return [0.5] * len(pairs)

    rr = CrossEncoderReranker("m")
    rr.model = Model()
    workers = 8
    barrier = threading.Barrier(workers)

    def worker():
        barrier.wait()
        rr.rerank("q", [_hit("a"), _hit("b")])

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert detector.calls == workers
    assert detector.max_active == 1
