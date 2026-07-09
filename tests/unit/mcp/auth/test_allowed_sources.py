"""Unit tests for the generic per-request allowed-sources override.

Covers:
- ``set_allowed_sources`` / ``current_allowed_sources`` contextvar helpers.
- ``reset_auth_runtime`` clears the override back to ``None``.
- Search-time precedence: a middleware-set allowed set overrides the access
  policy, intersects narrow-only with the client-supplied ``source_names``, and
  short-circuits to zero results when empty.
"""

import pytest
from unittest.mock import patch

from opencrane.mcp import server as mcp_server
from opencrane.mcp.auth import reset_auth_runtime
from opencrane.mcp.auth.runtime import current_allowed_sources, set_allowed_sources


class RecordingMilvus:
    """Fake Milvus service that records the ``source_names`` it receives."""

    def __init__(self, results=None):
        self.calls = []
        self._results = results if results is not None else []

    def search(self, vector, limit=5, chunk_types=None, source_names=None, metadata_contains=None):
        self.calls.append(source_names)
        return self._results


class DummyEmbeddings:
    class DummyModel:
        def encode(self, queries, batch_size=None, show_progress_bar=False):
            return [[0.1] * 4 for _ in queries]

    model = DummyModel()


class TestAllowedSourcesRuntime:
    def test_default_is_none(self):
        reset_auth_runtime()
        assert current_allowed_sources() is None

    def test_set_stores_tuple(self):
        reset_auth_runtime()
        set_allowed_sources(["a", "b"])
        assert current_allowed_sources() == ("a", "b")

    def test_reset_clears_to_none(self):
        set_allowed_sources(["a"])
        reset_auth_runtime()
        assert current_allowed_sources() is None


def _wire_backend(monkeypatch):
    recording = RecordingMilvus()
    monkeypatch.setattr(mcp_server, "get_milvus_service", lambda: recording)
    monkeypatch.setattr(mcp_server, "get_embeddings_service", lambda: DummyEmbeddings())
    monkeypatch.setattr(mcp_server, "_build_chunk_source_map", lambda: {})
    monkeypatch.setattr(mcp_server, "_build_chunk_index", lambda: {})
    return recording


@pytest.mark.anyio
async def test_allowed_sources_override_no_client_filter(monkeypatch):
    """Middleware-set allowed sources are used when the client supplies no filter."""
    reset_auth_runtime()
    recording = _wire_backend(monkeypatch)
    set_allowed_sources(["cgw", "npp"])

    with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=None):
        await mcp_server._search_documentation_impl({
            "query": "test",
            "search_mode": "semantic",
            "limit": 1,
        })

    assert recording.calls == [["cgw", "npp"]]


@pytest.mark.anyio
async def test_allowed_sources_override_intersects_client_filter(monkeypatch):
    """Client-supplied source_names are narrowed to the allowed set (never expanded)."""
    reset_auth_runtime()
    recording = _wire_backend(monkeypatch)
    set_allowed_sources(["cgw", "npp"])

    with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=None):
        await mcp_server._search_documentation_impl({
            "query": "test",
            "search_mode": "semantic",
            "limit": 1,
            "source_names": ["npp", "other"],
        })

    # "other" is outside the allowed set → dropped; only the intersection remains.
    assert recording.calls == [["npp"]]


@pytest.mark.anyio
async def test_allowed_sources_empty_short_circuits(monkeypatch):
    """An empty allowed set short-circuits to zero results; backend is never called."""
    reset_auth_runtime()
    recording = _wire_backend(monkeypatch)
    set_allowed_sources([])

    with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=None):
        res = await mcp_server._search_documentation_impl({
            "query": "test",
            "search_mode": "semantic",
            "limit": 1,
        })

    assert len(res) == 1
    assert res[0].text == "No results found."
    assert recording.calls == []


@pytest.mark.anyio
async def test_allowed_sources_empty_with_client_filter_short_circuits(monkeypatch):
    """Empty allowed set short-circuits even when the client requests sources."""
    reset_auth_runtime()
    recording = _wire_backend(monkeypatch)
    set_allowed_sources([])

    with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=None):
        res = await mcp_server._search_documentation_impl({
            "query": "test",
            "search_mode": "semantic",
            "limit": 1,
            "source_names": ["cgw"],
        })

    assert res[0].text == "No results found."
    assert recording.calls == []
