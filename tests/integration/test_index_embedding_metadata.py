"""Milvus Lite persists the embedding settings that `opencrane index` records."""

from opencrane.mcp.services.milvus_client import MilvusService


def test_embedding_metadata_round_trips_through_milvus_lite(tmp_path, monkeypatch):
    monkeypatch.setenv("MILVUS_DB_PATH", str(tmp_path / "milvus.db"))
    recorded = {
        "model": "intfloat/e5-base-v2",
        "document_prompt": "passage: ",
        "query_prompt": 'Instruct: find "docs"\nQuery: {query}',
        "dim": 8,
    }
    writer = MilvusService(collection_name="meta_round_trip")
    writer.create_collection(dim=8, embedding_metadata=recorded)
    writer.client.close()

    reader = MilvusService(collection_name="meta_round_trip")
    assert reader.embedding_metadata() == recorded
    assert reader.vector_dim() == 8
    reader.client.close()
