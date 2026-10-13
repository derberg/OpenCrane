"""Unit tests: search filter values cannot inject Milvus filter logic.

Milvus Lite has no ``filter_params`` templating, so filter values are
interpolated into a double-quoted literal. A value that closes the literal could
OR in its own clause and lift the ``source_names`` restriction the source policy
relies on. These tests cover both layers of the fix: ``search_docs`` rejects
malformed filter arguments, and ``MilvusService`` never interpolates a value
that can close the literal.
"""

from unittest.mock import Mock, patch

import pytest

from opencrane.mcp import server as mcp_server
from opencrane.mcp.auth import reset_auth_runtime
from opencrane.mcp.auth.runtime import set_allowed_sources
from opencrane.mcp.services.milvus_client import MilvusService


TYPE_INJECTION = 'prose") || (chunk_type != "'
NAME_INJECTION = 'source-a") || (source_name != "'
FILE_INJECTION = 'x" || source_file != "y") || (source_file != "'


# ---------------------------------------------------------------------------
# MilvusService filter building
# ---------------------------------------------------------------------------

@pytest.fixture
def milvus():
    with patch("opencrane.mcp.services.milvus_client.MilvusClient") as client_class:
        client = Mock()
        client.search.return_value = [[]]
        client.query.return_value = []
        client_class.return_value = client
        service = MilvusService()
        service.vector_dim = lambda: None
        yield service, client


def _filter(client):
    return client.search.call_args[1]["filter"]


@pytest.mark.parametrize("kwargs, expected", [
    ({"chunk_types": ["prose", TYPE_INJECTION], "source_names": ["source-a"]},
     '(chunk_type == "prose") && (source_name == "source-a")'),
    ({"source_files": ["a.md", FILE_INJECTION], "source_names": ["source-a"]},
     '(source_file == "a.md") && (source_name == "source-a")'),
    ({"source_names": ["source-a", NAME_INJECTION]},
     '(source_name == "source-a")'),
    ({"chunk_types": ["prose\\"], "source_names": ["source-a", "bad\nname"]},
     None),
])
def test_unsafe_values_are_dropped_from_filter(milvus, kwargs, expected):
    """A value with a quote, backslash or control character never reaches the filter."""
    service, client = milvus
    service.search([0.1] * 4, limit=5, **kwargs)
    if expected is None:
        # Every chunk_types value was unsafe: no search runs at all.
        client.search.assert_not_called()
    else:
        assert _filter(client) == expected


@pytest.mark.parametrize("field", ["chunk_types", "source_files", "source_names"])
def test_all_unsafe_values_match_nothing_instead_of_widening(milvus, field):
    """If every value is unsafe the search returns nothing, it never drops the clause."""
    service, client = milvus
    injection = {"chunk_types": TYPE_INJECTION, "source_files": FILE_INJECTION,
                 "source_names": NAME_INJECTION}[field]
    assert service.search([0.1] * 4, limit=5, **{field: [injection]}) == []
    client.search.assert_not_called()


def test_safe_values_still_build_the_filter(milvus):
    """Ordinary values keep the existing filter shape."""
    service, client = milvus
    service.search([0.1] * 4, limit=5, chunk_types=["prose", "list_item"],
                   source_files=["docs/a b.md"], source_names=["Org/repo-a"])
    assert _filter(client) == (
        '(chunk_type == "prose" || chunk_type == "list_item") && '
        '(source_file == "docs/a b.md") && (source_name == "Org/repo-a")'
    )


def test_lookup_chunk_type_is_sanitized(milvus):
    """query_by_field and the query_by_values/prefix path strip the chunk_type too."""
    service, client = milvus
    service.query_by_field("list_id", "L1", chunk_type='list_item" || chunk_type != "')
    assert client.query.call_args[1]["filter"] == 'list_id == "L1" and chunk_type == "list_itemchunk_type"'
    service.query_by_prefix("clause_id", "5.4", chunk_type='prose" || "1')
    assert client.query.call_args[1]["filter"] == 'clause_id like "5.4%" and chunk_type == "prose1"'


@pytest.mark.parametrize("call", [
    lambda s: s.query_by_field('list_id == "x" || list_id', "L1"),
    lambda s: s.query_by_values("clause_id) || (1", ["5.4"]),
    lambda s: s.query_by_prefix("clause_id ", "5.4"),
    lambda s: s.query_by_field(None, "L1"),
])
def test_lookup_field_name_must_be_plain(milvus, call):
    """A field name that is not a plain identifier is refused before any query."""
    service, client = milvus
    with pytest.raises(ValueError, match="Invalid filter field name"):
        call(service)
    client.query.assert_not_called()


# ---------------------------------------------------------------------------
# search_docs argument validation
# ---------------------------------------------------------------------------

class RecordingMilvus:
    def __init__(self):
        self.calls = []

    def search(self, vector, limit=5, chunk_types=None, source_names=None, metadata_contains=None):
        self.calls.append({"chunk_types": chunk_types, "source_names": source_names})
        return []


class DummyEmbeddings:
    class DummyModel:
        def encode(self, queries, batch_size=None, show_progress_bar=False):
            return [[0.1] * 4 for _ in queries]

    model = DummyModel()


@pytest.fixture
def backend(monkeypatch, tmp_path):
    monkeypatch.setenv("MAPPING_FILE", str(tmp_path / "missing-config.yaml"))
    reset_auth_runtime()
    recording = RecordingMilvus()
    monkeypatch.setattr(mcp_server, "get_milvus_service", lambda: recording)
    monkeypatch.setattr(mcp_server, "get_embeddings_service", lambda: DummyEmbeddings())
    yield recording
    reset_auth_runtime()


async def _search(**extra):
    with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=None):
        return await mcp_server._search_documentation_impl(
            {"query": "test", "search_mode": "semantic", "limit": 1, **extra}
        )


@pytest.mark.anyio
@pytest.mark.parametrize("chunk_types", [
    [TYPE_INJECTION],
    ["prose", "has space"],
    ["prose", 3],
    "prose",
])
async def test_search_docs_rejects_invalid_chunk_types(backend, chunk_types):
    """Malformed chunk_types return an error and no search runs."""
    set_allowed_sources(("source-a",))
    res = await _search(chunk_types=chunk_types)
    assert len(res) == 1
    assert res[0].text.startswith("Error: invalid chunk_types")
    assert backend.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("source_names", [
    [NAME_INJECTION],
    ["source-a", "back\\slash"],
    ["source-a", ""],
    ["source-a", None],
    "source-a",
])
async def test_search_docs_rejects_invalid_source_names(backend, source_names):
    """Malformed source_names return an error and no search runs."""
    res = await _search(source_names=source_names)
    assert len(res) == 1
    assert res[0].text.startswith("Error: invalid source_names")
    assert backend.calls == []


@pytest.mark.anyio
async def test_search_docs_accepts_valid_filters(backend):
    """Well-formed values pass through; a disallowed source is still only dropped."""
    set_allowed_sources(("source-a",))
    await _search(chunk_types=["prose", "list_item", "crd-definition"],
                  source_names=["source-a", "Org/source-b"])
    assert backend.calls == [{"chunk_types": ["prose", "list_item", "crd-definition"],
                              "source_names": ["source-a"]}]
