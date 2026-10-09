"""End-to-end test for prose navigation and the get_section tool.

Chunks a 3GPP-style llms-full.txt (numbered clauses, an annex, a code block
splitting a section), indexes it into a throwaway Milvus Lite DB, and reads
sections back through the MCP tool, exercising the real clause_id /
parent_chunk_id scalar columns and their ``in [...]`` filters.
"""

import json

import pytest

pytestmark = pytest.mark.integration

from opencrane.mcp import server as mcp_server
from opencrane.mcp.services.milvus_client import MilvusService
from opencrane.rag import chunker
from opencrane.shared.models.vector_chunk import EmbeddingRecord, VectorChunk

LLMS_FULL = """# TS 23.501 System architecture

Intro text for the spec.

## 5 Functional description

General text of clause 5.

### 5.1 General

Text of 5.1.

### 5.2 Network access control

Text of 5.2 before code.

```bash
echo hi
```

Continuation of 5.2 after the code block.

#### 5.2.1 Inner clause

Inner text 5.2.1.

## 6 Heading-only clause

### 6.1 First

Text of 6.1.

### 6.2 Second

Text of 6.2.

## Annex C (informative): Extras

Annex text.

### C.4 Sub annex

Sub annex text.
"""

LLMS_INDEX = "# Docs\n\n## spec\n\n- [TS 23.501 System architecture](https://example.com/23501.md)\n"


@pytest.fixture
def section_index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MILVUS_DB_PATH", str(tmp_path / "milvus.db"))
    llm = tmp_path / "llm"
    llm.mkdir()
    (llm / "llms-full.txt").write_text(LLMS_FULL)
    (llm / "llms.txt").write_text(LLMS_INDEX)
    chunks_path = tmp_path / "chunks.json"
    chunker.main(llmstxt_dir=llm, chunks_file=chunks_path)
    chunks = json.loads(chunks_path.read_text())

    milvus = MilvusService()
    milvus.create_collection()
    vector_chunks = []
    for i, data in enumerate(chunks):
        chunk = type("Chunk", (), data)()
        record = EmbeddingRecord(chunk_index=i, chunk_id=data["chunk_id"], vector=[0.1] * 768)
        vector_chunks.append(VectorChunk.from_chunk_and_embedding(chunk, record))
    milvus.insert_chunks(vector_chunks)
    milvus.client.flush(milvus.collection_name)
    milvus.load_collection()
    return chunks


@pytest.mark.anyio
async def test_get_section_is_advertised(section_index):
    names = {t.name for t in await mcp_server.list_tools()}
    assert "get_section" in names
    assert "get_metadata_schema" in names


@pytest.mark.anyio
async def test_get_section_by_clause_with_subsections_and_neighbours(section_index):
    result = await mcp_server.call_tool("get_section", {"clause_id": "5", "neighbors": 1})
    text = result[0].text
    assert text.startswith("Section: TS 23.501 System architecture > 5 Functional description\n")
    assert "Sub-sections (2):" in text
    assert "5.2 Network access control (chunk_id=" in text
    assert "=== Previous section ===" in text and "Intro text for the spec." in text
    assert "=== Next section ===" in text and "Text of 5.1." in text


@pytest.mark.anyio
async def test_get_section_joins_continuation_and_slices_inner_clause(section_index):
    text = (await mcp_server.call_tool("get_section", {"clause_id": "5.2"}))[0].text
    assert "Text of 5.2 before code." in text
    assert "Continuation of 5.2 after the code block." in text
    assert "(continued in " in text

    text = (await mcp_server.call_tool("get_section", {"clause_id": "5.2.1"}))[0].text
    assert "Clause: 5.2.1" in text
    assert "Inner text 5.2.1." in text
    assert "Text of 5.2 before code." not in text


@pytest.mark.anyio
async def test_get_section_annex_and_recursive_subsections(section_index):
    text = (await mcp_server.call_tool(
        "get_section", {"clause_id": "Annex C", "include_subsections": True, "source": "23.501"},
    ))[0].text
    assert "Annex text." in text
    assert "Sub annex text." in text

    by_clause = {c["metadata"].get("clause_id"): c for c in section_index if c["chunk_type"] == "prose"}
    text = (await mcp_server.call_tool(
        "get_section", {"chunk_id": by_clause["C.4"]["chunk_id"]},
    ))[0].text
    assert f"Parent Chunk ID: {by_clause['Annex C']['chunk_id']}" in text


@pytest.mark.anyio
async def test_heading_only_clause_is_in_ancestry_and_lists_subsections(section_index):
    by_clause = {c["metadata"].get("clause_id"): c for c in section_index if c["chunk_type"] == "prose"}
    assert "6" not in by_clause  # dropped by the chunker: no text of its own
    assert by_clause["6.1"]["metadata"]["heading_path"] == (
        "TS 23.501 System architecture > 6 Heading-only clause > 6.1 First"
    )
    text = (await mcp_server.call_tool("get_section", {"clause_id": "6"}))[0].text
    assert text.startswith("Section: TS 23.501 System architecture > 6 Heading-only clause\nClause: 6\n")
    assert f"  - 6.1 First (chunk_id={by_clause['6.1']['chunk_id']})" in text
    assert f"  - 6.2 Second (chunk_id={by_clause['6.2']['chunk_id']})" in text
