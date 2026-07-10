"""Unit tests for Layer-2 authorization enforcement at search time.

Tests cover:
- AllowAll (no scope_sources): source_names passed through unchanged.
- ScopeSourcesPolicy constrains source_names to permitted sources.
- Empty allowlist short-circuits to "No results found." and backend is never called.
- current_scopes() returns () when get_access_token returns None.
- Missing / unparseable MAPPING_FILE treated as empty config (AllowAll).
"""

import pytest
from unittest.mock import patch

from opencrane.mcp import server as mcp_server
from opencrane.mcp.auth import reset_auth_runtime


# ---------------------------------------------------------------------------
# Recording fake Milvus service
# ---------------------------------------------------------------------------

class RecordingMilvus:
    """Fake Milvus service that records calls to .search()."""

    def __init__(self, results=None):
        self.calls = []  # list of source_names values received
        self._results = results if results is not None else []

    def search(self, vector, limit=5, chunk_types=None, source_names=None, metadata_contains=None):
        self.calls.append(source_names)
        return self._results


class DummyEmbeddings:
    """Fake embeddings service returning a small fixed vector."""

    class DummyModel:
        def encode(self, queries, batch_size=None, show_progress_bar=False):
            return [[0.1] * 4 for _ in queries]

    model = DummyModel()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_allow_all_passes_source_names_unchanged(tmp_path, monkeypatch):
    """AllowAll policy: source_names = None is passed through to the backend unchanged."""
    config_yaml = tmp_path / "config.yaml"
    _write_config(config_yaml, "sources:\n  cgw:\n    url: https://github.com/org/cgw\n")

    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))
    reset_auth_runtime()

    recording = RecordingMilvus()
    monkeypatch.setattr(mcp_server, "get_milvus_service", lambda: recording)
    monkeypatch.setattr(mcp_server, "get_embeddings_service", lambda: DummyEmbeddings())

    # No token → empty scopes
    with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=None):
        res = await mcp_server._search_documentation_impl({
            "query": "test",
            "search_mode": "semantic",
            "limit": 1,
        })

    assert recording.calls, "backend must have been called"
    # AllowAll returns requested (None) unchanged
    assert recording.calls[0] is None


@pytest.mark.anyio
async def test_scope_sources_constrains_source_names(tmp_path, monkeypatch):
    """ScopeSourcesPolicy maps caller scopes to a restricted set of sources."""
    config_yaml = tmp_path / "config.yaml"
    _write_config(config_yaml, (
        "sources:\n"
        "  cgw:\n"
        "    url: https://github.com/org/cgw\n"
        "  other:\n"
        "    url: https://github.com/org/other\n"
        "auth:\n"
        "  scope_sources:\n"
        "    docs:tp:\n"
        "      - cgw\n"
    ))

    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))
    reset_auth_runtime()

    recording = RecordingMilvus()
    monkeypatch.setattr(mcp_server, "get_milvus_service", lambda: recording)
    monkeypatch.setattr(mcp_server, "get_embeddings_service", lambda: DummyEmbeddings())

    from mcp.server.auth.middleware.auth_context import AccessToken
    fake_token = AccessToken(token="t", client_id="c", scopes=["docs:tp"], expires_at=None)

    with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=fake_token):
        await mcp_server._search_documentation_impl({
            "query": "test",
            "search_mode": "semantic",
            "limit": 1,
        })

    assert recording.calls, "backend must have been called"
    # ScopeSourcesPolicy for scopes=("docs:tp",) with no requested → returns sorted(allowed)
    assert recording.calls[0] == ["cgw"]


@pytest.mark.anyio
async def test_empty_allowlist_short_circuits_no_backend_call(tmp_path, monkeypatch):
    """SECURITY: empty allowlist must not reach the backend — proves no source leak."""
    config_yaml = tmp_path / "config.yaml"
    _write_config(config_yaml, (
        "sources:\n"
        "  cgw:\n"
        "    url: https://github.com/org/cgw\n"
        "auth:\n"
        "  scope_sources:\n"
        "    docs:tp:\n"
        "      - cgw\n"
    ))

    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))
    reset_auth_runtime()

    recording = RecordingMilvus()
    monkeypatch.setattr(mcp_server, "get_milvus_service", lambda: recording)
    monkeypatch.setattr(mcp_server, "get_embeddings_service", lambda: DummyEmbeddings())

    # Caller has a scope that maps to nothing (not in scope_sources) and no default_sources
    from mcp.server.auth.middleware.auth_context import AccessToken
    fake_token = AccessToken(token="t", client_id="c", scopes=["docs:no-match"], expires_at=None)

    with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=fake_token):
        res = await mcp_server._search_documentation_impl({
            "query": "test",
            "search_mode": "semantic",
            "limit": 1,
        })

    # Short-circuit must return "No results found."
    assert len(res) == 1
    assert res[0].text == "No results found."
    # SECURITY: backend must never have been called
    assert recording.calls == [], "backend must NOT be called when allowlist is empty"


@pytest.mark.anyio
async def test_current_scopes_no_token_returns_empty_tuple(monkeypatch):
    """current_scopes() returns () when get_access_token returns None (stdio / no-auth)."""
    from opencrane.mcp.auth.runtime import current_scopes

    with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=None):
        scopes = current_scopes()

    assert scopes == ()


@pytest.mark.anyio
async def test_current_scopes_with_token_returns_tuple(monkeypatch):
    """current_scopes() converts token.scopes list to a tuple."""
    from opencrane.mcp.auth.runtime import current_scopes
    from mcp.server.auth.middleware.auth_context import AccessToken

    fake_token = AccessToken(token="t", client_id="c", scopes=["a", "b"], expires_at=None)

    with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=fake_token):
        scopes = current_scopes()

    assert scopes == ("a", "b")


@pytest.mark.anyio
async def test_missing_mapping_file_treated_as_allow_all(tmp_path, monkeypatch):
    """Missing MAPPING_FILE → AllowAll (empty config), no restriction on source_names."""
    monkeypatch.setenv("MAPPING_FILE", str(tmp_path / "nonexistent.yaml"))
    reset_auth_runtime()

    recording = RecordingMilvus()
    monkeypatch.setattr(mcp_server, "get_milvus_service", lambda: recording)
    monkeypatch.setattr(mcp_server, "get_embeddings_service", lambda: DummyEmbeddings())

    with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=None):
        await mcp_server._search_documentation_impl({
            "query": "test",
            "search_mode": "semantic",
            "limit": 1,
        })

    assert recording.calls, "backend must have been called (AllowAll)"
    assert recording.calls[0] is None


@pytest.mark.anyio
async def test_get_access_policy_is_cached(tmp_path, monkeypatch):
    """get_access_policy() returns the same object on repeated calls (cached)."""
    config_yaml = tmp_path / "config.yaml"
    _write_config(config_yaml, "sources:\n  cgw:\n    url: https://github.com/org/cgw\n")

    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))
    reset_auth_runtime()

    from opencrane.mcp.auth.runtime import get_access_policy

    policy1 = get_access_policy()
    policy2 = get_access_policy()
    assert policy1 is policy2


@pytest.mark.anyio
async def test_reset_auth_runtime_clears_cache(tmp_path, monkeypatch):
    """reset_auth_runtime() causes get_access_policy() to rebuild the cache."""
    config_yaml = tmp_path / "config.yaml"
    _write_config(config_yaml, "sources:\n  cgw:\n    url: https://github.com/org/cgw\n")

    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))
    reset_auth_runtime()

    from opencrane.mcp.auth.runtime import get_access_policy

    policy1 = get_access_policy()
    reset_auth_runtime()
    policy2 = get_access_policy()
    assert policy1 is not policy2


@pytest.mark.anyio
async def test_unparseable_mapping_file_treated_as_allow_all(tmp_path, monkeypatch):
    """Unparseable MAPPING_FILE → logs warning, falls back to AllowAll."""
    config_yaml = tmp_path / "config.yaml"
    # Write invalid YAML that will raise on parse
    config_yaml.write_bytes(b"\x00\x01\x02invalid yaml \xff")

    monkeypatch.setenv("MAPPING_FILE", str(config_yaml))
    reset_auth_runtime()

    recording = RecordingMilvus()
    monkeypatch.setattr(mcp_server, "get_milvus_service", lambda: recording)
    monkeypatch.setattr(mcp_server, "get_embeddings_service", lambda: DummyEmbeddings())

    with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=None):
        await mcp_server._search_documentation_impl({
            "query": "test",
            "search_mode": "semantic",
            "limit": 1,
        })

    assert recording.calls, "backend must have been called (AllowAll fallback)"
    assert recording.calls[0] is None
