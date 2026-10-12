"""MilvusService support for prose navigation: clause/parent columns and lookups."""

from unittest.mock import Mock, patch

from opencrane.mcp.services.milvus_client import MilvusService
from opencrane.shared.models.vector_chunk import VectorChunk


def _service():
    patcher = patch("opencrane.mcp.services.milvus_client.MilvusClient")
    client_class = patcher.start()
    client = Mock()
    client_class.return_value = client
    service = MilvusService()
    patcher.stop()
    return service, client


def test_insert_lifts_clause_and_parent_columns():
    service, client = _service()
    service.insert_chunks([
        VectorChunk(
            chunk_id="p1", embedding=[0.1] * 768, content="## 5.4 Title\n\nBody",
            source_file="f.md", chunk_type="prose", metadata_json="{}", token_count=3,
            clause_id="5.4", parent_chunk_id="p0",
        ),
        VectorChunk(
            chunk_id="p2", embedding=[0.1] * 768, content="text", source_file="f.md",
            chunk_type="prose", metadata_json="{}", token_count=1,
        ),
    ])
    rows = client.insert.call_args[1]["data"]
    assert (rows[0]["clause_id"], rows[0]["parent_chunk_id"]) == ("5.4", "p0")
    # Absent values become empty strings, like list_id/table_id.
    assert (rows[1]["clause_id"], rows[1]["parent_chunk_id"]) == ("", "")


def test_query_by_values_builds_in_filter_with_chunk_type():
    service, client = _service()
    client.query.return_value = [{"chunk_id": "a"}]
    rows = service.query_by_values("parent_chunk_id", ["b", "a", "a"], chunk_type="prose")
    assert rows == [{"chunk_id": "a"}]
    assert client.query.call_args[1]["filter"] == (
        'parent_chunk_id in ["a", "b"] and chunk_type == "prose"'
    )


def test_query_by_values_keeps_clause_dots_and_spaces_but_strips_quotes():
    service, client = _service()
    client.query.return_value = []
    service.query_by_values("clause_id", ['Annex C', '5.4" || chunk_type != "x'])
    assert client.query.call_args[1]["filter"] == 'clause_id in ["5.4  chunk_type  x", "Annex C"]'


def test_query_by_values_ids_use_strict_charset():
    service, client = _service()
    client.query.return_value = []
    service.query_by_values("parent_chunk_id", ["a.b c"])
    assert client.query.call_args[1]["filter"] == 'parent_chunk_id in ["abc"]'


def test_query_by_values_empty_after_sanitizing_skips_query():
    service, client = _service()
    assert service.query_by_values("clause_id", ['""', ""]) == []
    client.query.assert_not_called()


def test_query_by_values_warns_on_cap_and_survives_errors():
    service, client = _service()
    client.query.return_value = [{"chunk_id": "a"}, {"chunk_id": "b"}]
    assert len(service.query_by_values("clause_id", ["5"], limit=2)) == 2
    client.query.side_effect = Exception("boom")
    assert service.query_by_values("clause_id", ["5"]) == []


def test_has_prose_navigation():
    service, client = _service()
    client.query.return_value = [{"metadata_json": '{"position": 1}'}]
    assert service.has_prose_navigation() is True
    assert client.query.call_args[1]["filter"] == 'chunk_type == "prose"'
    assert client.query.call_args[1]["limit"] == 1

    client.query.return_value = [{"metadata_json": '{"source_url": "u"}'}]
    assert service.has_prose_navigation() is False

    client.query.return_value = []
    assert service.has_prose_navigation() is False

    client.query.side_effect = Exception("no collection")
    assert service.has_prose_navigation() is False


def test_query_by_prefix_builds_like_filter():
    service, client = _service()
    client.query.return_value = [{"chunk_id": "a"}]
    assert service.query_by_prefix("clause_id", "5.4.", chunk_type="prose") == [{"chunk_id": "a"}]
    assert client.query.call_args[1]["filter"] == 'clause_id like "5.4.%" and chunk_type == "prose"'
    # A wildcard or quote in the prefix is stripped, so it stays a literal prefix.
    service.query_by_prefix("clause_id", '5%" or "')
    assert client.query.call_args[1]["filter"] == 'clause_id like "5 or %"'
    client.query.reset_mock()
    assert service.query_by_prefix("clause_id", '%"') == []
    client.query.assert_not_called()
