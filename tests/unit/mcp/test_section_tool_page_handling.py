"""get_section and search_docs follow-ups: shared page URLs and the truncation tip."""

import json
from unittest.mock import Mock, patch

import pytest

from opencrane.mcp import server as s
from tests.unit.mcp.test_section_tool import FakeMilvus, _rows


@pytest.mark.anyio
async def test_clause_on_two_pages_with_one_url_asks_for_source(monkeypatch):
    # A synthesized llms.txt index gives every page of a source the same URL.
    url = "https://docs.example.com"
    rows = _rows({("docs", url): [
        ("a1", "# Install guide\n\nIntro."),
        ("a5", "## 1 Introduction\n\nInstall intro."),
        ("b1", "# Upgrade guide\n\nIntro."),
        ("b5", "## 1 Introduction\n\nUpgrade intro."),
    ]})
    fake = FakeMilvus(rows)
    monkeypatch.setattr(s, "get_milvus_service", lambda: fake)
    text = (await s.get_section({"clause_id": "1"}))[0].text
    assert text.startswith("Clause '1' appears in 2 documents; pass source to pick one:")
    text = (await s.get_section({"clause_id": "1", "source": "upgrade"}))[0].text
    assert "Upgrade intro." in text and "Install intro." not in text


@pytest.mark.anyio
async def test_truncated_prose_result_points_to_get_section():
    milvus = Mock()
    embeddings = Mock()
    embeddings.model.encode.return_value = [[0.1] * 768]
    milvus.search.return_value = [{
        "chunk_id": "p1",
        "content": "x" * 1500,
        "chunk_type": "prose",
        "metadata_json": json.dumps({"position": 1}),
        "distance": 0.5,
    }]
    with patch.object(s, "get_milvus_service", return_value=milvus), \
            patch.object(s, "get_embeddings_service", return_value=embeddings):
        result = await s._search_documentation_impl({"query": "q", "limit": 1, "search_mode": "semantic"})
    text = result[0].text
    assert "get_section(chunk_id='p1')" in text
    assert "get_yaml_definition" not in text
