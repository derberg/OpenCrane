"""Custom chunk types: a project strategy can emit its own ``chunk_type``.

Covers the whole path: the chunk model, chunking with a custom strategy,
serialization to chunks.json, conversion for indexing, search filtering and
tool advertising in the MCP server (Milvus mocked), and get_metadata_schema.
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from opencrane.config import OpenCraneConfig
from opencrane.mcp import server as mcp_server
from opencrane.mcp.server import _build_search_tool, _search_documentation_impl, get_metadata_schema
from opencrane.mcp.services.keyword_search import KeywordSearchService
from opencrane.rag.chunker import main as chunker_main
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.rag.services.chunk_serializer import ChunkSerializer
from opencrane.shared.models.chunk import (
    BUILTIN_CHUNK_TYPES,
    CHUNK_TYPE_MAX_LENGTH,
    Chunk,
    is_valid_chunk_type,
)
from opencrane.shared.models.vector_chunk import EmbeddingRecord, VectorChunk

pytestmark = pytest.mark.unit


class NoteStrategy(ProcessingStrategy):
    """Emits a ``my_type`` chunk for every text node that holds a ``NOTE:`` line."""

    def can_process(self, node) -> bool:
        return "NOTE:" in getattr(node, "text", "")

    def process(self, node, source_file: Path):
        return [Chunk(
            content=node.text,
            source_file=str(source_file),
            chunk_type="my_type",
            metadata={"severity": "high", "tags": ["a", "b"]},
            token_count=3,
        )]


class NoteConfig(OpenCraneConfig):
    chunking_strategies = [NoteStrategy(), *OpenCraneConfig.chunking_strategies]


def _chunk(chunk_type, content="body", metadata=None):
    return Chunk(content=content, source_file="d.md", chunk_type=chunk_type,
                 metadata=metadata or {}, token_count=1)


class TestChunkTypeValidation:

    @pytest.mark.parametrize("value", ["my_type", "asyncapi-spec", "X1", "a" * CHUNK_TYPE_MAX_LENGTH])
    def test_custom_identifier_accepted(self, value):
        assert _chunk(value).chunk_type == value

    @pytest.mark.parametrize("value", ["", "my type", 'x"y', "x||y", "ünïcode", "a" * (CHUNK_TYPE_MAX_LENGTH + 1)])
    def test_invalid_type_rejected(self, value):
        with pytest.raises(ValidationError, match="chunk_type must be"):
            _chunk(value)

    def test_non_string_type_rejected(self):
        with pytest.raises(ValidationError):
            _chunk(5)

    def test_is_valid_chunk_type_rejects_non_string(self):
        assert is_valid_chunk_type(None) is False

    def test_custom_type_metadata_is_permissive(self):
        chunk = _chunk("my_type", content={"k": "v"}, metadata={"anything": {"nested": 1}})
        assert chunk.metadata == {"anything": {"nested": 1}}

    def test_custom_type_content_must_not_be_empty(self):
        with pytest.raises(ValidationError, match="must not be empty"):
            _chunk("my_type", content="   ")

    def test_builtin_validation_unchanged(self):
        with pytest.raises(ValidationError, match="prose chunks must use supported metadata keys only"):
            _chunk("prose", metadata={"severity": "high"})
        with pytest.raises(ValidationError, match="code_snippet chunks must have language"):
            _chunk("code_snippet")
        with pytest.raises(ValidationError, match="table_row chunks must have"):
            _chunk("table_row")

    def test_every_builtin_type_has_a_schema_section(self):
        assert set(mcp_server._CHUNK_TYPE_SECTION_HEADINGS) == BUILTIN_CHUNK_TYPES


@pytest.mark.anyio
async def test_custom_type_round_trips_through_chunking_and_search(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    llms_dir = tmp_path / "llmstxt"
    llms_dir.mkdir()
    (llms_dir / "llms-full.txt").write_text(
        "# Page\nIntro paragraph with enough real text here.\n\n"
        "## Operations\nNOTE: rotate the signing keys every quarter.\n"
    )
    out = tmp_path / "chunks.json"

    chunker_main(config=NoteConfig(), llmstxt_dir=llms_dir, chunks_file=out)

    # Serialization: the custom chunk survives chunks.json and reloads.
    raw = [c for c in json.loads(out.read_text()) if c["chunk_type"] == "my_type"]
    assert len(raw) == 1
    reloaded = [c for c in ChunkSerializer.deserialize_chunks(out) if c.chunk_type == "my_type"]
    assert len(reloaded) == 1
    note = reloaded[0]
    assert note.metadata["severity"] == "high"

    # Indexing: the chunk converts to a vector record with its type intact.
    record = EmbeddingRecord(chunk_index=0, chunk_id=note.chunk_id or "n1", vector=[0.1] * 768)
    vector = VectorChunk.from_chunk_and_embedding(note, record)
    assert vector.chunk_type == "my_type"

    # BM25: the chunk_types filter matches the custom type.
    bm25 = KeywordSearchService(chunks=[
        {**note.model_dump(), "chunk_id": "n1"},
        {"chunk_id": "p1", "content": "rotate keys in prose", "source_file": "d.md",
         "chunk_type": "prose", "metadata": {}},
    ])
    assert [r["chunk_id"] for r in bm25.search("rotate keys", limit=5, chunk_types=["my_type"])] == ["n1"]

    # Vector search through the MCP server, Milvus mocked.
    embeddings = Mock()
    embeddings.model.encode.return_value = [[0.1] * 768]
    milvus = Mock()
    milvus.search.return_value = [{
        "chunk_id": vector.chunk_id,
        "content": vector.content,
        "source_file": vector.source_file,
        "chunk_type": vector.chunk_type,
        "metadata_json": vector.metadata_json,
        "distance": 0.9,
    }]
    with patch.object(mcp_server, "get_embeddings_service", return_value=embeddings), \
         patch.object(mcp_server, "get_milvus_service", return_value=milvus):
        results = await _search_documentation_impl({"query": "rotate keys", "limit": 3,
            "chunk_types": ["my_type"], "search_mode": "semantic"})

    assert milvus.search.call_args.kwargs["chunk_types"] == ["my_type"]
    assert "Type: my_type" in results[0].text
    assert "rotate the signing keys" in results[0].text


def test_search_tool_advertises_custom_types():
    with patch.object(mcp_server, "_get_indexed_chunk_types", return_value={"prose", "my_type"}), \
         patch.object(mcp_server, "_get_source_keys", return_value=[]), \
         patch.object(mcp_server, "_get_source_topics", return_value=[]):
        tool = _build_search_tool()
    prop = tool.inputSchema["properties"]["chunk_types"]
    assert prop["items"]["enum"] == ["my_type", "prose"]
    assert "my_type" in prop["description"]


@pytest.mark.anyio
async def test_get_metadata_schema_custom_type_returns_universal_section():
    result = await get_metadata_schema({"chunk_type": "my_type"})
    text = result[0].text
    assert "Universal Metadata" in text
    assert "`my_type` is a custom chunk type" in text
    assert "crd_kind" not in text


# A chunk_types value that closes the quoted literal and widens the filter.
# Unvalidated, it turns ``source_name == "public"`` into an OR that matches
# every source, which bypasses source authorization.
_INJECTION = 'prose") || (chunk_type != "'


@patch("opencrane.mcp.services.milvus_client.MilvusClient")
def test_milvus_search_rejects_unsafe_chunk_types(mock_client_class):
    from opencrane.mcp.services.milvus_client import MilvusService

    service = MilvusService()
    # An unsafe value is dropped. With no safe value left, the search matches
    # nothing instead of losing the clause.
    assert service.search([0.1] * 768, limit=3, chunk_types=[_INJECTION], source_names=["public"]) == []
    mock_client_class.return_value.search.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("chunk_types", [[_INJECTION], "prose", ["prose", 5]])
async def test_search_rejects_unsafe_chunk_types_before_backends(chunk_types):
    milvus = Mock()
    keyword = Mock()
    with patch.object(mcp_server, "get_milvus_service", return_value=milvus), \
         patch.object(mcp_server, "get_keyword_service", return_value=keyword):
        results = await _search_documentation_impl(
            {"query": "q", "chunk_types": chunk_types, "source_names": ["public"]})

    assert results[0].text.startswith("Error: invalid chunk_types")
    milvus.search.assert_not_called()
    keyword.search.assert_not_called()


def test_custom_type_with_non_string_id_metadata_indexes():
    chunk = _chunk("my_type", metadata={"table_id": 5, "list_id": "L1"})
    record = EmbeddingRecord(chunk_index=0, chunk_id="c1", vector=[0.1])
    vector = VectorChunk.from_chunk_and_embedding(chunk, record)
    assert vector.table_id is None
    assert vector.list_id == "L1"
    assert json.loads(vector.metadata_json)["table_id"] == 5
