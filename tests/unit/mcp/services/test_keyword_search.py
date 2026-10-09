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


# --- BM25 tokenizer selection (BM25_TOKENIZER) ---

from opencrane.mcp.services.keyword_search import (  # noqa: E402
    _identifier_tokenize,
    _resolve_tokenizer,
    _simple_tokenize,
)


def test_simple_tokenizer_splits_identifiers():
    """The default tokenizer is unchanged: identifiers are split into fragments."""
    assert _simple_tokenize("See clause 5.4.1 for GTP-U.") == ["see", "clause", "5", "4", "1", "for", "gtp", "u"]


@pytest.mark.parametrize("text, expected", [
    # Clause numbers keep their identity and strip trailing sentence punctuation
    ("as specified in clause 5.4.1.", ["as", "specified", "in", "clause", "5.4.1", "5", "4", "1"]),
    # Spec references
    ("3GPP TS 29.244 v16.5.0", ["3gpp", "ts", "29.244", "29", "244", "v16.5.0", "v16", "5", "0"]),
    # Hyphenated protocol names and compounds, trailing comma stripped
    ("GTP-U, Sx-based", ["gtp-u", "gtp", "u", "sx-based", "sx", "based"]),
    # Underscored identifiers
    ("call get_yaml_definition()", ["call", "get_yaml_definition", "get", "yaml", "definition"]),
    # Alphanumeric identifiers without joiners stay single tokens
    ("N4 v1alpha1 PFCP", ["n4", "v1alpha1", "pfcp"]),
    # Parts are de-duplicated per compound occurrence
    ("5.5.5", ["5.5.5", "5"]),
    # Dangling joiners are separators, not part of a token
    ("GTP- -U _x_ a..b", ["gtp", "u", "x", "a", "b"]),
    ("", []),
])
def test_identifier_tokenizer(text, expected):
    assert _identifier_tokenize(text) == expected


def test_resolve_tokenizer_default_is_simple(monkeypatch):
    monkeypatch.delenv("BM25_TOKENIZER", raising=False)
    assert _resolve_tokenizer() is _simple_tokenize


def test_resolve_tokenizer_from_env(monkeypatch):
    monkeypatch.setenv("BM25_TOKENIZER", " Identifier ")
    assert _resolve_tokenizer() is _identifier_tokenize
    assert _resolve_tokenizer("simple") is _simple_tokenize


def test_resolve_tokenizer_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown BM25_TOKENIZER 'stemmed'"):
        _resolve_tokenizer("stemmed")


_SPEC_CHUNKS = [
    {"chunk_id": "clause", "content": "5.4.1 General. The SMF shall send the PFCP Session Establishment Request over N4.",
     "source_file": "ts_29244.md", "chunk_type": "prose", "metadata": {}},
    {"chunk_id": "scattered", "content": "Step 5 of 4 retries, then 1 more attempt per clause 4.5.1.",
     "source_file": "ts_23502.md", "chunk_type": "prose", "metadata": {}},
    {"chunk_id": "gtpu", "content": "The UPF encapsulates user plane packets in GTP-U towards the gNB.",
     "source_file": "ts_29281.md", "chunk_type": "prose", "metadata": {}},
    {"chunk_id": "gtpc", "content": "GTP control plane messages are defined for GTPv2 on S5 and S8.",
     "source_file": "ts_29274.md", "chunk_type": "prose", "metadata": {}},
    # Fillers keep the corpus large enough for BM25 IDF to stay positive
    {"chunk_id": "amf", "content": "The AMF handles registration and mobility management.",
     "source_file": "ts_23501.md", "chunk_type": "prose", "metadata": {}},
    {"chunk_id": "nrf", "content": "The NRF supports network function discovery.",
     "source_file": "ts_29510.md", "chunk_type": "prose", "metadata": {}},
]


def test_identifier_tokenizer_ranks_exact_clause_number_first(monkeypatch):
    monkeypatch.setenv("BM25_TOKENIZER", "identifier")
    results = KeywordSearchService(chunks=_SPEC_CHUNKS).search("5.4.1", limit=2)
    assert results[0]["chunk_id"] == "clause"
    assert results[0]["distance"] > results[1]["distance"]


def test_simple_tokenizer_cannot_tell_clause_numbers_apart(monkeypatch):
    """Baseline for the test above: with the default tokenizer 5.4.1 and 4.5.1 look the same."""
    monkeypatch.delenv("BM25_TOKENIZER", raising=False)
    results = KeywordSearchService(chunks=_SPEC_CHUNKS).search("5.4.1", limit=4)
    scores = {r["chunk_id"]: r["distance"] for r in results}
    assert scores["scattered"] >= scores["clause"]


def test_identifier_tokenizer_part_query_still_matches_compound(monkeypatch):
    monkeypatch.setenv("BM25_TOKENIZER", "identifier")
    svc = KeywordSearchService(chunks=_SPEC_CHUNKS)
    # A bare "gtp" query matches both the GTP-U and the GTP chunk
    ids = {r["chunk_id"] for r in svc.search("gtp", limit=4) if r["distance"] > 0}
    assert {"gtpu", "gtpc"} <= ids
    # The exact compound ranks the GTP-U chunk first
    assert svc.search("GTP-U", limit=1)[0]["chunk_id"] == "gtpu"
