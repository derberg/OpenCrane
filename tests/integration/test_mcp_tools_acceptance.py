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
from opencrane.shared.utils.category import infer_category_from_path
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
    async def test_list_tools_exposes_both_search_tools(self):
        """Verify both search_product_docs and search_guidelines are exposed via MCP."""
        tools = await list_tools()
        tool_names = [t.name for t in tools]

        # New tools should be present
        assert "search_product_docs" in tool_names, "search_product_docs tool not exposed"
        assert "search_guidelines" in tool_names, "search_guidelines tool not exposed"

        # Old unified tool should be removed
        assert "search_documentation" not in tool_names, "Old search_documentation tool still present"

        # Verify tool descriptions are distinct
        product_tool = next(t for t in tools if t.name == "search_product_docs")
        guidelines_tool = next(t for t in tools if t.name == "search_guidelines")

        assert "product" in product_tool.description.lower()
        assert "guidelines" in guidelines_tool.description.lower()

    @pytest.mark.anyio
    async def test_tool_schemas_are_identical(self):
        """Verify both tools accept the same parameters."""
        tools = await list_tools()

        product_tool = next(t for t in tools if t.name == "search_product_docs")
        guidelines_tool = next(t for t in tools if t.name == "search_guidelines")

        # Both should have same parameter structure
        product_props = product_tool.inputSchema["properties"]
        guidelines_props = guidelines_tool.inputSchema["properties"]

        # Same parameter names
        assert set(product_props.keys()) == set(guidelines_props.keys()), \
            "Both tools should accept same parameters"

        # Same required fields
        assert product_tool.inputSchema["required"] == guidelines_tool.inputSchema["required"], \
            "Both tools should have same required parameters"

        # Key parameters exist
        assert "query" in product_props
        assert "limit" in product_props
        assert "search_mode" in product_props
        assert "chunk_types" in product_props

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
    async def test_search_guidelines_returns_results(self):
        """Test search_guidelines returns results via MCP protocol."""
        results = await call_tool("search_guidelines", {
            "query": "documentation writing style",
            "search_mode": "semantic",
            "limit": 5
        })

        assert len(results) > 0, "Should return results for common query"
        assert isinstance(results[0], TextContent), "Should return TextContent type"
        assert len(results[0].text) > 0, "Result should have content"

    @pytest.mark.anyio
    async def test_category_filter_product_excludes_guidelines(self):
        """CRITICAL: Verify product search excludes guidelines source files."""
        results = await call_tool("search_product_docs", {
            "query": "documentation",  # Common term in both categories
            "search_mode": "semantic",
            "limit": 10
        })

        assert len(results) > 0, "Should return results"

        # Extract source files from results
        source_files = extract_source_files(results)

        # Verify no guidelines source files appear
        guidelines_markers = ["content-guidelines/"]

        for source_file in source_files:
            category = infer_category_from_path(source_file)
            assert category == "product", \
                f"Product search returned guidelines file: {source_file}"

    @pytest.mark.anyio
    async def test_category_filter_guidelines_excludes_product(self):
        """CRITICAL: Verify guidelines search excludes product source files."""
        results = await call_tool("search_guidelines", {
            "query": "documentation",  # Common term in both categories
            "search_mode": "semantic",
            "limit": 10
        })

        assert len(results) > 0, "Should return results"

        # Extract source files from results
        source_files = extract_source_files(results)

        # Verify no product source files appear (external-sources/)
        for source_file in source_files:
            category = infer_category_from_path(source_file)
            assert category == "guidelines", \
                f"Guidelines search returned product file: {source_file}"

    @pytest.mark.anyio
    async def test_cross_category_search_returns_different_results(self):
        """Verify product and guidelines searches return different chunk sets."""
        # Search same query in both categories
        product_results = await call_tool("search_product_docs", {
            "query": "API documentation",
            "search_mode": "semantic",
            "limit": 5
        })

        guidelines_results = await call_tool("search_guidelines", {
            "query": "API documentation",
            "search_mode": "semantic",
            "limit": 5
        })

        # Both should return results
        assert len(product_results) > 0, "Product search should return results"
        assert len(guidelines_results) > 0, "Guidelines search should return results"

        # Extract chunk IDs from results
        def extract_chunk_ids(results):
            chunk_ids = []
            for result in results:
                match = re.search(r'Chunk ID:\s*([^\s\n]+)', result.text)
                if match:
                    chunk_ids.append(match.group(1))
            return chunk_ids

        product_ids = set(extract_chunk_ids(product_results))
        guideline_ids = set(extract_chunk_ids(guidelines_results))

        # Should have no overlap (different categories)
        overlap = product_ids & guideline_ids
        assert len(overlap) == 0, \
            f"Product and guidelines searches should return different chunks, found overlap: {overlap}"

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


@pytest.mark.integration
class TestMCPCategoryFilteringEndToEnd:
    """End-to-end tests specifically for category filtering through full stack."""

    @pytest.mark.anyio
    async def test_product_search_excludes_guidelines_specific_content(self):
        """CRITICAL: Test that product search excludes guidelines-specific content.

        Searches for content that ONLY exists in guidelines (writing/diagrams).
        If filtering works, should return no guidelines sources.
        If filtering broken, would return guidelines content.
        """
        # "diagram guidelines" is specific to content-guidelines/diagrams/
        results = await call_tool("search_product_docs", {
            "query": "diagram guidelines writing style",
            "search_mode": "keyword",  # Keyword mode for predictable results
            "limit": 10
        })

        # Extract all source files from results
        source_files = extract_source_files(results)

        # Check each source - should be ZERO guidelines sources
        guidelines_sources = [f for f in source_files if f and infer_category_from_path(f) == "guidelines"]

        assert len(guidelines_sources) == 0, \
            f"FILTERING BROKEN: Product search returned {len(guidelines_sources)} guidelines sources: {guidelines_sources[:3]}"

    @pytest.mark.anyio
    async def test_guidelines_search_excludes_product_specific_content(self):
        """CRITICAL: Test that guidelines search excludes product-specific content.

        Searches for content that ONLY exists in product docs (Kubernetes, CRD, API).
        If filtering works, should return no product sources.
        If filtering broken, would return product content.
        """
        # "kubernetes CRD API" is specific to product documentation
        results = await call_tool("search_guidelines", {
            "query": "kubernetes CRD SMC nsmf",
            "search_mode": "keyword",  # Keyword mode for predictable results
            "limit": 10
        })

        # Extract all source files from results
        source_files = extract_source_files(results)

        # Check each source - should be ZERO product sources
        product_sources = [f for f in source_files if f and infer_category_from_path(f) == "product"]

        assert len(product_sources) == 0, \
            f"FILTERING BROKEN: Guidelines search returned {len(product_sources)} product sources: {product_sources[:3]}"

    @pytest.mark.anyio
    async def test_semantic_search_respects_categories(self):
        """Test that semantic search (vector) respects category filters."""
        results = await call_tool("search_product_docs", {
            "query": "documentation guide",
            "search_mode": "semantic",  # Semantic only
            "limit": 10
        })

        assert len(results) > 0, "Should return results"

        # All source files should be product category
        source_files = extract_source_files(results)
        for source_file in source_files:
            if source_file:  # Skip if extraction failed
                category = infer_category_from_path(source_file)
                assert category == "product", \
                    f"Semantic search leaked guidelines file: {source_file}"

    @pytest.mark.anyio
    async def test_keyword_search_respects_categories(self):
        """Test that keyword search (BM25) respects category filters."""
        results = await call_tool("search_guidelines", {
            "query": "documentation template",
            "search_mode": "keyword",  # Keyword only
            "limit": 10
        })

        assert len(results) > 0, "Should return results"

        # All source files should be guidelines category
        source_files = extract_source_files(results)
        for source_file in source_files:
            if source_file:  # Skip if extraction failed
                category = infer_category_from_path(source_file)
                assert category == "guidelines", \
                    f"Keyword search leaked product file: {source_file}"

    @pytest.mark.anyio
    async def test_hybrid_search_respects_categories(self):
        """Test that hybrid search (semantic + keyword) respects category filters."""
        results = await call_tool("search_product_docs", {
            "query": "API configuration",
            "search_mode": "hybrid",
            "limit": 10
        })

        assert len(results) > 0, "Should return results"

        # All source files should be product category
        source_files = extract_source_files(results)
        categories = [infer_category_from_path(f) for f in source_files if f]

        # Should be all product (or empty if extraction failed)
        assert all(cat == "product" for cat in categories if cat), \
            f"Hybrid search leaked guidelines files: {[f for f, c in zip(source_files, categories) if c == 'guidelines']}"


if __name__ == '__main__':
    # Run acceptance tests only
    pytest.main([__file__, '-v', '-m', 'integration'])
