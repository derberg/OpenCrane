import json
import pytest

from opencrane.mcp.services.keyword_search import KeywordSearchService


def test_keyword_search_basic_ranking():
    chunks = [
        {"chunk_id": "a", "content": "Kubernetes CRD policy configuration", "source_file": "a.md", "chunk_type": "prose", "metadata": {}},
        {"chunk_id": "b", "content": "OpenAPI pet store schema and endpoints", "source_file": "b.md", "chunk_type": "code_snippet", "metadata": {"openapi_version": "3.0.0"}},
        {"chunk_id": "c", "content": "Miscellaneous notes", "source_file": "c.md", "chunk_type": "prose", "metadata": {}},
    ]
    svc = KeywordSearchService(chunks=chunks)
    results = svc.search("pet openapi", limit=2)
    assert len(results) == 2
    assert results[0]["chunk_id"] == "b"
    assert "distance" in results[0]


def test_keyword_search_with_filters():
    chunks = [
        {"chunk_id": "a", "content": "alpha", "source_file": "foo.md", "chunk_type": "prose", "metadata": {"k": "v"}},
        {"chunk_id": "b", "content": "alpha beta", "source_file": "bar.md", "chunk_type": "code_snippet", "metadata": {"k": "v", "x": "y"}},
        {"chunk_id": "c", "content": "beta", "source_file": "bar.md", "chunk_type": "prose", "metadata": {"x": "z"}},
    ]
    svc = KeywordSearchService(chunks=chunks)

    # Filter by chunk_types
    res1 = svc.search("alpha", limit=5, chunk_types=["code_snippet"])  # only 'b'
    assert [r["chunk_id"] for r in res1] == ["b"]

    # Filter by source_files
    res2 = svc.search("alpha", limit=5, source_files=["foo.md"])  # only 'a'
    assert [r["chunk_id"] for r in res2] == ["a"]

    # Filter by metadata_contains (substring in metadata JSON)
    res3 = svc.search("beta", limit=5, metadata_contains=["\"x\": \"y\""])  # matches 'b' only
    assert [r["chunk_id"] for r in res3] == ["b"]


def test_keyword_search_filters_by_source_name():
    chunks = [
        {"chunk_id": "a", "content": "alpha", "source_file": "x.md", "chunk_type": "prose", "metadata": {}, "source_name": "Org/repo-a"},
        {"chunk_id": "b", "content": "alpha", "source_file": "y.md", "chunk_type": "prose", "metadata": {}, "source_name": "Org/repo-b"},
        {"chunk_id": "c", "content": "alpha", "source_file": "z.md", "chunk_type": "prose", "metadata": {}},
    ]
    svc = KeywordSearchService(chunks=chunks)
    res = svc.search("alpha", limit=5, source_names=["Org/repo-a"])
    assert [r["chunk_id"] for r in res] == ["a"]
    assert res[0]["source_name"] == "Org/repo-a"


def test_keyword_search_no_results():
    """Test search with query that matches no chunks."""
    chunks = [
        {"chunk_id": "a", "content": "kubernetes orchestration", "source_file": "a.md", "chunk_type": "prose", "metadata": {}},
    ]
    svc = KeywordSearchService(chunks=chunks)
    # Search for words not in the corpus
    results = svc.search("elasticsearch nosql database", limit=5, chunk_types=["code_snippet"])
    assert len(results) == 0  # No code_snippet type matches


def test_keyword_search_with_dict_content():
    """Test search handles dict content (YAML chunks) correctly."""
    chunks = [
        {
            "chunk_id": "yaml1",
            "content": {"spec": {"replicas": 3, "name": "test-deployment"}},
            "source_file": "crd.yaml",
            "chunk_type": "crd_definition",
            "metadata": {"crd_kind": "SMC"}
        },
        {
            "chunk_id": "text1",
            "content": "deployment replicas configuration",
            "source_file": "docs.md",
            "chunk_type": "prose",
            "metadata": {}
        }
    ]
    svc = KeywordSearchService(chunks=chunks)

    # Search should work with both dict and string content
    results = svc.search("replicas", limit=5)
    assert len(results) == 2
    
    # Both chunks should be searchable
    chunk_ids = {r["chunk_id"] for r in results}
    assert "yaml1" in chunk_ids
    assert "text1" in chunk_ids


def test_keyword_search_with_list_content():
    """Test search handles list content correctly."""
    chunks = [
        {
            "chunk_id": "list1",
            "content": ["item1", "item2", "deployment"],
            "source_file": "data.json",
            "chunk_type": "code_snippet",
            "metadata": {}
        },
        {
            "chunk_id": "text1",
            "content": "deployment configuration",
            "source_file": "docs.md",
            "chunk_type": "prose",
            "metadata": {}
        }
    ]
    svc = KeywordSearchService(chunks=chunks)

    # Search should work with both list and string content
    results = svc.search("deployment", limit=5)
    assert len(results) == 2
    
    # Both chunks should be searchable
    chunk_ids = {r["chunk_id"] for r in results}
    assert "list1" in chunk_ids
    assert "text1" in chunk_ids


def test_keyword_search_with_mixed_content_types():
    """Test search handles all content types (str, dict, list, int)."""
    chunks = [
        {"chunk_id": "a", "content": "string content", "source_file": "a.md", "chunk_type": "prose", "metadata": {}},
        {"chunk_id": "b", "content": {"key": "dict content"}, "source_file": "b.yaml", "chunk_type": "crd_definition", "metadata": {}},
        {"chunk_id": "c", "content": ["list", "content"], "source_file": "c.json", "chunk_type": "code_snippet", "metadata": {}},
        {"chunk_id": "d", "content": 12345, "source_file": "d.txt", "chunk_type": "prose", "metadata": {}},
    ]
    svc = KeywordSearchService(chunks=chunks)
    
    # Search for "content" - should match string, dict, and list
    results = svc.search("content", limit=5)
    assert len(results) >= 3  # at least string, dict, list should match
