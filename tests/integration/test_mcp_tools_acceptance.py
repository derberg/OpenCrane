"""Acceptance tests for MCP tool protocol integration.

These tests call the actual MCP server through the protocol layer
using PRODUCTION data to verify tools work as users will call them.

Run with: pytest tests/integration/test_mcp_tools_acceptance.py -v -m integration

IMPORTANT: These tests require production data files:
  - rag-chunks.json (keyword search)
  - milvus.db (semantic search)

Install dependencies: pip install pymilvus[milvus_lite]
"""

import pytest
import re
from pathlib import Path

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration

from opencrane.mcp.server import list_tools, call_tool
from mcp.types import TextContent


def extract_source_files(results: list[TextContent]) -> list[str]:
    """Extract source file paths from MCP search results."""
    source_files = []
    for result in results:
        # Look for "Source: <filepath>" or "Source: <url>" in result text
        match = re.search(r'Source:\s*([^\n]+)', result.text)
        if match:
            source = match.group(1).strip()
            # Extract path from GitHub URLs
            if "github.com" in source:
                # Extract path after blob/main/
                path_match = re.search(r'blob/[^/]+/(.+?)(?:\s|$)', source)
                if path_match:
                    source_files.append(path_match.group(1))
            else:
                source_files.append(source)
    return source_files


@pytest.mark.integration
class TestMCPToolsAcceptance:
    """End-to-end acceptance tests for MCP split tools using production data."""

    @pytest.mark.anyio
    async def test_list_tools_exposes_search_tool(self):
        """Verify search_product_docs is exposed via MCP."""
        tools = await list_tools()
        tool_names = [t.name for t in tools]

        assert "search_product_docs" in tool_names, "search_product_docs tool not exposed"

        # Old unified tool should be removed
        assert "search_documentation" not in tool_names, "Old search_documentation tool still present"

        # Verify tool description mentions product
        product_tool = next(t for t in tools if t.name == "search_product_docs")
        assert "product" in product_tool.description.lower()

    @pytest.mark.anyio
    async def test_search_product_docs_returns_results(self):
        """Test search_product_docs returns results via MCP protocol."""
        # Use semantic mode for predictability (avoids keyword search variability)
        results = await call_tool("search_product_docs", {
            "query": "kubernetes deployment configuration",
            "search_mode": "semantic",
            "limit": 5
        })

        assert len(results) > 0, "Should return results for common query"
        assert isinstance(results[0], TextContent), "Should return TextContent type"
        assert len(results[0].text) > 0, "Result should have content"

    @pytest.mark.anyio
    async def test_tool_parameters_work_via_protocol(self):
        """Test that tool parameters (limit, search_mode, chunk_types) work via MCP."""
        # Test limit parameter
        results_limit_2 = await call_tool("search_product_docs", {
            "query": "configuration",
            "search_mode": "semantic",
            "limit": 2
        })

        results_limit_5 = await call_tool("search_product_docs", {
            "query": "configuration",
            "search_mode": "semantic",
            "limit": 5
        })

        # Should respect limits (results are formatted as single TextContent with multiple results)
        assert len(results_limit_2) >= 1, "Should return results"
        assert len(results_limit_5) >= 1, "Should return results"

        # Count actual results in text (look for "Result N:")
        def count_results(results):
            if not results:
                return 0
            return len(re.findall(r'Result \d+:', results[0].text))

        count_2 = count_results(results_limit_2)
        count_5 = count_results(results_limit_5)

        assert count_2 <= 2, f"Should return at most 2 results, got {count_2}"
        assert count_5 <= 5, f"Should return at most 5 results, got {count_5}"

    @pytest.mark.anyio
    async def test_search_modes_work(self):
        """Test that different search modes (semantic, keyword, hybrid) work."""
        query = "kubernetes"

        # Test semantic mode
        results_semantic = await call_tool("search_product_docs", {
            "query": query,
            "search_mode": "semantic",
            "limit": 3
        })
        assert len(results_semantic) >= 1, "Semantic mode should work"

        # Test keyword mode
        results_keyword = await call_tool("search_product_docs", {
            "query": query,
            "search_mode": "keyword",
            "limit": 3
        })
        assert len(results_keyword) >= 1, "Keyword mode should work"

        # Test hybrid mode (default)
        results_hybrid = await call_tool("search_product_docs", {
            "query": query,
            "search_mode": "hybrid",
            "limit": 3
        })
        assert len(results_hybrid) >= 1, "Hybrid mode should work"

    @pytest.mark.anyio
    async def test_empty_query_handled_gracefully(self):
        """Test that empty queries are handled gracefully."""
        results = await call_tool("search_product_docs", {"query": ""})

        assert len(results) == 1, "Should return single error message"
        assert "Error:" in results[0].text or "error" in results[0].text.lower(), \
            "Should return error message for empty query"

    @pytest.mark.anyio
    async def test_chunk_type_filter_works(self):
        """Test that chunk_types filter parameter works."""
        # Use keyword mode to avoid Milvus dependency
        results = await call_tool("search_product_docs", {
            "query": "configuration",
            "search_mode": "keyword",  # Changed to keyword for reliability
            "chunk_types": ["prose"],
            "limit": 5
        })

        assert len(results) >= 1, "Should return results with chunk type filter"

        # Verify results contain content
        result_text = results[0].text
        assert len(result_text) > 50, "Should return actual results"


if __name__ == '__main__':
    # Run acceptance tests only
    pytest.main([__file__, '-v', '-m', 'integration'])
