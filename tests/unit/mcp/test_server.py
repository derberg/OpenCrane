"""Unit tests for MCP server."""

import json
import pytest
from unittest.mock import Mock, patch, AsyncMock, mock_open
from opencrane.mcp.server import (
    search_docs, _search_documentation_impl, _build_search_tool,
    health_check, list_tools, call_tool,
    get_embeddings_service, get_milvus_service, get_keyword_service,
    get_yaml_definition, get_metadata_schema, _rehydrate_to_yaml, _has_yaml_chunks,
    _get_indexed_chunk_types, _get_source_topics, main
)
from mcp.types import TextContent


class TestMCPServer:
    """Test cases for MCP server functions."""

    @patch('opencrane.mcp.server._get_source_topics', return_value=["my project"])
    @patch('opencrane.mcp.server._get_indexed_chunk_types', return_value={"prose", "crd_definition"})
    @patch('opencrane.mcp.server._has_yaml_chunks', return_value=True)
    @pytest.mark.anyio
    async def test_list_tools_with_yaml_chunks(self, mock_has_yaml, mock_types, mock_topics):
        """Test list_tools includes YAML tools when YAML chunks exist."""
        tools = await list_tools()

        assert len(tools) == 4
        assert tools[0].name == "search_docs"
        assert tools[1].name == "health"
        assert tools[2].name == "get_yaml_definition"
        assert tools[3].name == "get_metadata_schema"

        # Verify dynamic description includes topics
        assert "my project" in tools[0].description

        # Verify chunk_types enum only includes indexed types
        enum = tools[0].inputSchema["properties"]["chunk_types"]["items"]["enum"]
        assert "crd_definition" in enum
        assert "prose" in enum
        assert "openapi_spec" not in enum

    @patch('opencrane.mcp.server._get_source_topics', return_value=[])
    @patch('opencrane.mcp.server._get_indexed_chunk_types', return_value={"prose"})
    @patch('opencrane.mcp.server._has_yaml_chunks', return_value=False)
    @pytest.mark.anyio
    async def test_list_tools_without_yaml_chunks(self, mock_has_yaml, mock_types, mock_topics):
        """Test list_tools excludes YAML tools when no YAML chunks exist."""
        tools = await list_tools()

        assert len(tools) == 2
        assert tools[0].name == "search_docs"
        assert tools[1].name == "health"

        # No topics — generic description
        assert "Topics:" not in tools[0].description

    @patch('opencrane.mcp.server._get_source_keys', return_value=["Org/repo-a", "Org/repo-b"])
    @patch('opencrane.mcp.server._get_source_topics', return_value=["repo a", "repo b"])
    @patch('opencrane.mcp.server._get_indexed_chunk_types', return_value={"prose"})
    @patch('opencrane.mcp.server._has_yaml_chunks', return_value=False)
    def test_search_tool_advertises_source_names_filter(self, *_mocks):
        """search_docs tool exposes a source_names filter when sources are configured."""
        tool = _build_search_tool()
        props = tool.inputSchema["properties"]
        assert "source_names" in props
        assert props["source_names"]["items"]["enum"] == ["Org/repo-a", "Org/repo-b"]

    @patch('opencrane.mcp.server._get_source_keys', return_value=[])
    @patch('opencrane.mcp.server._get_source_topics', return_value=[])
    @patch('opencrane.mcp.server._get_indexed_chunk_types', return_value={"prose"})
    @patch('opencrane.mcp.server._has_yaml_chunks', return_value=False)
    def test_search_tool_omits_source_names_when_no_sources(self, *_mocks):
        tool = _build_search_tool()
        assert "source_names" not in tool.inputSchema["properties"]

    @patch('opencrane.mcp.server.EmbeddingService')
    def test_get_embeddings_service_lazy_init(self, mock_embedding_service):
        """Test lazy initialization of embeddings service."""
        # Reset global state
        import opencrane.mcp.server as server_module
        server_module._embeddings_service = None

        mock_instance = Mock()
        mock_embedding_service.return_value = mock_instance

        service = get_embeddings_service()

        assert service == mock_instance
        mock_embedding_service.assert_called_once()

        # Second call should return cached instance
        service2 = get_embeddings_service()
        assert service2 == mock_instance
        assert mock_embedding_service.call_count == 1  # Not called again

    @patch('opencrane.mcp.server.MilvusService')
    def test_get_milvus_service_lazy_init(self, mock_milvus_service):
        """Test lazy initialization of Milvus service."""
        # Reset global state
        import opencrane.mcp.server as server_module
        server_module._milvus_service = None

        mock_instance = Mock()
        mock_milvus_service.return_value = mock_instance

        service = get_milvus_service()

        assert service == mock_instance
        mock_milvus_service.assert_called_once()

        # Second call should return cached instance
        service2 = get_milvus_service()
        assert service2 == mock_instance
        assert mock_milvus_service.call_count == 1  # Not called again

    @patch('opencrane.mcp.server.KeywordSearchService')
    def test_get_keyword_service_init(self, mock_keyword_service):
        """Test initialization of keyword search service."""
        mock_instance = Mock()
        mock_keyword_service.return_value = mock_instance

        service = get_keyword_service()

        assert service == mock_instance
        mock_keyword_service.assert_called_once()

    @patch('opencrane.mcp.server.search_docs')
    @pytest.mark.anyio
    async def test_call_tool_search_docs(self, mock_search):
        """Test call_tool for search_docs."""
        mock_search.return_value = [TextContent(type="text", text="result")]

        result = await call_tool("search_docs", {"query": "test"})

        mock_search.assert_called_once_with({"query": "test"})
        assert result == [TextContent(type="text", text="result")]

    @patch('opencrane.mcp.server.health_check')
    @pytest.mark.anyio
    async def test_call_tool_health(self, mock_health):
        """Test call_tool for health."""
        mock_health.return_value = [TextContent(type="text", text="healthy")]

        result = await call_tool("health", {})

        mock_health.assert_called_once_with({})
        assert result == [TextContent(type="text", text="healthy")]

    @patch('opencrane.mcp.server.search_docs')
    @pytest.mark.anyio
    async def test_call_tool_long_args_summary(self, mock_search):
        """Test call_tool truncates long argument summaries."""
        mock_search.return_value = [TextContent(type="text", text="result")]
        long_args = {"query": "x" * 300}

        result = await call_tool("search_docs", long_args)

        mock_search.assert_called_once_with(long_args)
        assert result == [TextContent(type="text", text="result")]

    @pytest.mark.anyio
    async def test_call_tool_unknown(self):
        """Test call_tool for unknown tool."""
        with pytest.raises(ValueError, match="Unknown tool"):
            await call_tool("unknown", {})

    @patch('opencrane.mcp.server.get_yaml_definition')
    @pytest.mark.anyio
    async def test_call_tool_get_yaml_definition(self, mock_get_yaml):
        """Test call_tool for get_yaml_definition."""
        mock_get_yaml.return_value = [TextContent(type="text", text="yaml content")]

        result = await call_tool("get_yaml_definition", {"chunk_id": "test-id"})

        mock_get_yaml.assert_called_once_with({"chunk_id": "test-id"})
        assert result == [TextContent(type="text", text="yaml content")]

    @patch('opencrane.mcp.server._search_documentation_impl')
    @pytest.mark.anyio
    async def test_search_docs_wrapper(self, mock_impl):
        """Test search_docs wrapper delegates to impl."""
        mock_impl.return_value = [TextContent(type="text", text="result")]

        result = await search_docs({"query": "test"})

        # Verify it called the impl with the original arguments
        mock_impl.assert_called_once_with({"query": "test"})
        assert result == [TextContent(type="text", text="result")]

    @patch('opencrane.mcp.server.get_embeddings_service')
    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_search_documentation_success(self, mock_milvus_get, mock_embeddings_get):
        """Test successful search documentation."""
        # Mock services
        mock_embeddings = Mock()
        mock_model = Mock()
        mock_model.encode.return_value = [[0.1] * 768]
        mock_embeddings.model = mock_model
        mock_embeddings_get.return_value = mock_embeddings

        mock_milvus = Mock()
        mock_milvus.search.return_value = [
            {
                "content": "test content",
                "source_file": "file.md",
                "chunk_type": "prose",
                "metadata_json": '{"key": "value"}',
                "distance": 0.5
            }
        ]

        mock_milvus_get.return_value = mock_milvus

        arguments = {"query": "test query", "limit": 5, "search_mode": "semantic"}

        results = await _search_documentation_impl(arguments)

        assert len(results) == 1
        assert "Result 1:" in results[0].text
        assert "test content" in results[0].text
        assert "file.md" in results[0].text

        mock_model.encode.assert_called_once_with(["test query"], batch_size=8, show_progress_bar=False)
        mock_milvus.search.assert_called_once_with([0.1] * 768, limit=5, chunk_types=None, source_names=None, metadata_contains=None)

    @patch('opencrane.mcp.server.get_embeddings_service')
    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_search_result_includes_source_name(self, mock_milvus_get, mock_embeddings_get):
        """When a hit carries source_name, it's surfaced in the formatted output."""
        mock_embeddings = Mock()
        mock_model = Mock()
        mock_model.encode.return_value = [[0.1] * 768]
        mock_embeddings.model = mock_model
        mock_embeddings_get.return_value = mock_embeddings

        mock_milvus = Mock()
        mock_milvus.search.return_value = [
            {
                "content": "test",
                "source_file": "file.md",
                "source_name": "Org/repo-a",
                "chunk_type": "prose",
                "metadata_json": "{}",
                "distance": 0.5,
            }
        ]
        mock_milvus_get.return_value = mock_milvus

        results = await _search_documentation_impl({
            "query": "q", "limit": 1, "search_mode": "semantic",
        })
        assert "Source Name: Org/repo-a" in results[0].text

    @patch('opencrane.mcp.server.get_embeddings_service')
    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_search_result_includes_section_anchor(self, mock_milvus_get, mock_embeddings_get):
        """A chunk's section_anchor is surfaced with a hint to build the section link."""
        mock_embeddings = Mock()
        mock_model = Mock()
        mock_model.encode.return_value = [[0.1] * 768]
        mock_embeddings.model = mock_model
        mock_embeddings_get.return_value = mock_embeddings

        mock_milvus = Mock()
        mock_milvus.search.return_value = [
            {
                "content": "test",
                "source_file": "file.md",
                "chunk_type": "prose",
                "metadata_json": '{"source_url": "https://x/about", "section_anchor": "who-we-serve"}',
                "distance": 0.5,
            }
        ]
        mock_milvus_get.return_value = mock_milvus

        results = await _search_documentation_impl({
            "query": "q", "limit": 1, "search_mode": "semantic",
        })
        assert "Section Anchor: who-we-serve" in results[0].text
        assert "Source#who-we-serve" in results[0].text

    @patch('opencrane.mcp.server.get_embeddings_service')
    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_search_documentation_with_filters(self, mock_milvus_get, mock_embeddings_get):
        """Test search with chunk type filters."""
        mock_embeddings = Mock()
        mock_model = Mock()
        mock_model.encode.return_value = [[0.1] * 768]
        mock_embeddings.model = mock_model
        mock_embeddings_get.return_value = mock_embeddings

        mock_milvus = Mock()
        mock_milvus.search.return_value = []
        mock_milvus_get.return_value = mock_milvus

        arguments = {"query": "test", "limit": 3, "chunk_types": ["prose", "code"], "search_mode": "semantic"}

        results = await _search_documentation_impl(arguments)

        assert len(results) == 1
        assert "No results found." in results[0].text

        mock_milvus.search.assert_called_once_with([0.1] * 768, limit=3, chunk_types=["prose", "code"], source_names=None, metadata_contains=None)

    @patch('opencrane.mcp.server.get_embeddings_service')
    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_search_documentation_failure(self, mock_milvus_get, mock_embeddings_get):
        """Test search failure handling."""
        mock_embeddings = Mock()
        mock_model = Mock()
        mock_model.encode.side_effect = Exception("Encoding failed")
        mock_embeddings.model = mock_model
        mock_embeddings_get.return_value = mock_embeddings

        mock_milvus_get.return_value = Mock()

        arguments = {"query": "test"}

        results = await _search_documentation_impl(arguments)

        assert len(results) == 1
        assert "Search failed:" in results[0].text

    @patch('opencrane.mcp.server.get_milvus_service')
    @patch('opencrane.mcp.server.get_embeddings_service')
    @pytest.mark.anyio
    async def test_health_check_success(self, mock_embeddings_get, mock_milvus_get):
        """Test successful health check."""
        mock_embeddings = Mock()
        mock_embeddings.model = Mock()
        mock_embeddings_get.return_value = mock_embeddings

        mock_milvus = Mock()
        mock_milvus.client = Mock()
        mock_milvus.get_collection_stats.return_value = {"row_count": 100}
        mock_milvus_get.return_value = mock_milvus

        arguments = {}

        results = await health_check(arguments)

        assert len(results) == 1
        health_text = results[0].text
        assert "embeddings_service: healthy" in health_text
        assert "milvus_service: healthy" in health_text
        assert "collection_stats" in health_text

    @patch('opencrane.mcp.server.get_milvus_service')
    @patch('opencrane.mcp.server.get_embeddings_service')
    @pytest.mark.anyio
    async def test_health_check_failure(self, mock_embeddings_get, mock_milvus_get):
        """Test health check with failures."""
        mock_embeddings = Mock()
        mock_embeddings.model = None
        mock_embeddings_get.return_value = mock_embeddings

        mock_milvus = Mock()
        mock_milvus.client = None
        mock_milvus.get_collection_stats.side_effect = Exception("Stats error")
        mock_milvus_get.return_value = mock_milvus

        arguments = {}

        results = await health_check(arguments)

        assert len(results) == 1
        health_text = results[0].text
        assert "embeddings_service: unhealthy" in health_text
        assert "milvus_service: unhealthy" in health_text
        assert "error: Stats error" in health_text

    @patch('opencrane.mcp.server.app')
    @pytest.mark.anyio
    async def test_main(self, mock_app):
        """Test main function execution."""
        from unittest.mock import AsyncMock, Mock

        # Create a mock context manager for stdio_server
        mock_read_stream = Mock()
        mock_write_stream = Mock()
        mock_cm = Mock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_read_stream, mock_write_stream))
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch('opencrane.mcp.server.stdio_server', return_value=mock_cm):
            mock_app.run = AsyncMock()
            mock_app.create_initialization_options.return_value = {}

            await main()

            mock_app.run.assert_called_once_with(
                mock_read_stream,
                mock_write_stream,
                {}
            )

    @patch('opencrane.mcp.server.get_embeddings_service')
    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_search_with_numpy_array_conversion(self, mock_milvus_get, mock_embeddings_get):
        """Test search when model returns numpy array."""
        import numpy as np

        mock_embeddings = Mock()
        mock_model = Mock()
        # Return numpy array
        mock_model.encode.return_value = np.array([[0.1] * 768])
        mock_embeddings.model = mock_model
        mock_embeddings_get.return_value = mock_embeddings

        mock_milvus = Mock()
        mock_milvus.search.return_value = [
            {
                "content": "test",
                "source_file": "file.md",
                "chunk_type": "prose",
                "chunk_id": "test_id",
                "metadata_json": '{}',
                "distance": 0.5
            }
        ]
        mock_milvus_get.return_value = mock_milvus

        arguments = {"query": "test", "limit": 5, "search_mode": "semantic"}
        results = await _search_documentation_impl(arguments)

        assert len(results) == 1
        mock_model.encode.assert_called_once()

    @patch('opencrane.mcp.server.get_embeddings_service')
    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_search_falls_back_to_source_file(self, mock_milvus_get, mock_embeddings_get):
        """When no URL is in metadata or content, source falls back to source_file."""
        mock_embeddings = Mock()
        mock_model = Mock()
        mock_model.encode.return_value = [[0.1] * 768]
        mock_embeddings.model = mock_model
        mock_embeddings_get.return_value = mock_embeddings

        mock_milvus = Mock()
        mock_milvus.search.return_value = [
            {
                "content": "test content without URL",
                "source_file": "llmstxt/product-docs/llms-full.txt",
                "chunk_type": "prose",
                "chunk_id": "test_id_123",
                "metadata_json": '{}',
                "distance": 0.5
            }
        ]
        mock_milvus_get.return_value = mock_milvus

        arguments = {"query": "test", "limit": 5, "search_mode": "semantic"}
        results = await _search_documentation_impl(arguments)

        assert len(results) == 1
        assert "Source: llmstxt/product-docs/llms-full.txt" in results[0].text

    @patch('opencrane.mcp.server.get_embeddings_service')
    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_health_check_exception(self, mock_milvus_get, mock_embeddings_get):
        """Test health check handles exceptions."""
        mock_embeddings_get.side_effect = Exception("Service unavailable")
        
        arguments = {}
        results = await health_check(arguments)
        
        assert len(results) == 1
        assert "Health check failed" in results[0].text
        assert "Service unavailable" in results[0].text

    def test_rehydrate_to_yaml_with_dict_content(self):
        """Test YAML re-hydration with dict content and full metadata."""
        content = {"spec": {"replicas": 3}}
        metadata = {
            "original_format": "yaml",
            "breadcrumb_path": "spec.versions[0].schema.properties.spec",
            "source_url": "https://github.com/my-org/smc/docs/config.md",
            "logical_parent": "spec.versions[0].schema.properties",
            "crd_kind": "SMC",
            "crd_version": "v1"
        }

        result = _rehydrate_to_yaml(content, metadata, "crd_definition")

        # Check breadcrumb comments
        assert "# Location: spec.versions[0].schema.properties.spec" in result
        assert "# Documentation: https://github.com/my-org/smc/docs/config.md" in result
        assert "# Parent: spec.versions[0].schema.properties" in result
        assert "# CRD Kind: SMC" in result
        assert "# CRD Version: v1" in result
        # Check YAML content
        assert "spec:" in result
        assert "replicas: 3" in result

    def test_rehydrate_to_yaml_with_openapi_metadata(self):
        """Test YAML re-hydration with OpenAPI-specific metadata."""
        content = {"get": {"summary": "Get user"}}
        metadata = {
            "original_format": "yaml",
            "breadcrumb_path": "paths./users.get",
            "openapi_version": "3.0.0",
            "endpoint_path": "/users",
            "http_method": "get"
        }

        result = _rehydrate_to_yaml(content, metadata, "openapi_spec")

        assert "# Location: paths./users.get" in result
        assert "# OpenAPI Version: 3.0.0" in result
        assert "# Endpoint: /users" in result
        assert "# Method: GET" in result
        assert "get:" in result
        assert "summary: Get user" in result

    def test_rehydrate_to_yaml_non_yaml_content(self):
        """Test that non-YAML content is returned as-is."""
        content = "This is prose text"
        metadata = {"original_format": "text"}

        result = _rehydrate_to_yaml(content, metadata, "prose")

        assert result == content

    def test_rehydrate_to_yaml_minimal_metadata(self):
        """Test YAML re-hydration with minimal metadata."""
        content = {"key": "value"}
        metadata = {"original_format": "yaml"}

        result = _rehydrate_to_yaml(content, metadata, "crd_definition")

        # Should just have YAML content, no breadcrumb
        assert "key: value" in result
        assert "#" not in result

    def test_rehydrate_to_yaml_string_content(self):
        """Test YAML re-hydration with string content (already YAML)."""
        content = "already_yaml: true\nkey: value"
        metadata = {
            "original_format": "yaml",
            "breadcrumb_path": "test.path"
        }

        result = _rehydrate_to_yaml(content, metadata, "crd_definition")

        # Should have breadcrumb plus original string
        assert "# Location: test.path" in result
        assert "already_yaml: true" in result
        assert "key: value" in result

    def test_rehydrate_to_yaml_json_schema(self):
        """Test YAML re-hydration with JSON Schema chunk."""
        content = {
            "type": "string",
            "description": "User email address",
            "format": "email"
        }
        metadata = {
            "original_format": "yaml",
            "schema_type": "json_schema",
            "breadcrumb_path": "properties.email",
            "logical_parent": "properties",
            "schema_version": "https://json-schema.org/draft/2020-12/schema",
            "schema_title": "User Schema",
            "property_path": "email",
            "source_url": "https://example.com/schema.json"
        }

        result = _rehydrate_to_yaml(content, metadata, "json_schema")

        # Should have JSON Schema-specific breadcrumbs
        assert "# Location: properties.email" in result
        assert "# Documentation: https://example.com/schema.json" in result
        assert "# Parent: properties" in result
        assert "# JSON Schema Version: https://json-schema.org/draft/2020-12/schema" in result
        assert "# Schema Title: User Schema" in result
        assert "# Property Path: email" in result
        # Should have YAML content
        assert "type: string" in result
        assert "format: email" in result

    @pytest.mark.anyio
    async def test_search_documentation_metadata_parse_error(self):
        """Test search when metadata JSON parsing fails."""
        from opencrane.mcp.server import _search_documentation_impl

        # Setup mock services
        mock_milvus = Mock()
        mock_embeddings = Mock()
        mock_embeddings.model.encode.return_value = [[0.1] * 768]

        with patch('opencrane.mcp.server.get_milvus_service', return_value=mock_milvus), \
             patch('opencrane.mcp.server.get_embeddings_service', return_value=mock_embeddings):

            # Return result with metadata_json that will fail to parse
            mock_milvus.search.return_value = [
                {
                    "chunk_id": "test-123",
                    "content": "test content",
                    "chunk_type": "prose",
                    "metadata_json": '{"invalid"',  # Invalid JSON
                    "distance": 0.5
                }
            ]

            result = await _search_documentation_impl({
                "query": "test",
                "limit": 1,
                "search_mode": "semantic",
            })

            # Should handle the error gracefully
            assert len(result) > 0
            assert "test content" in result[0].text

    @pytest.mark.anyio
    async def test_search_documentation_long_content_truncation(self):
        """Test that long content is truncated in search results."""
        from opencrane.mcp.server import _search_documentation_impl

        # Setup mock services
        mock_milvus = Mock()
        mock_embeddings = Mock()
        mock_embeddings.model.encode.return_value = [[0.1] * 768]

        # Create content > 1000 chars
        long_content = "x" * 1500

        with patch('opencrane.mcp.server.get_milvus_service', return_value=mock_milvus), \
             patch('opencrane.mcp.server.get_embeddings_service', return_value=mock_embeddings):

            mock_milvus.search.return_value = [
                {
                    "chunk_id": "test-123",
                    "content": long_content,
                    "chunk_type": "prose",
                    "metadata": "{}",
                    "distance": 0.5
                }
            ]

            result = await _search_documentation_impl({
                "query": "test",
                "limit": 1,
                "search_mode": "semantic",
            })

            # Should have truncation message
            assert len(result) > 0
            assert "...(truncated" in result[0].text
            assert "1500 total chars" in result[0].text
            assert "get_yaml_definition" in result[0].text
            assert "chunk_id='test-123'" in result[0].text

    @pytest.mark.anyio
    async def test_search_documentation_yaml_chunk_hint(self):
        """Test that YAML chunks show hint to use get_yaml_definition."""
        from opencrane.mcp.server import _search_documentation_impl

        # Setup mock services
        mock_milvus = Mock()
        mock_embeddings = Mock()
        mock_embeddings.model.encode.return_value = [[0.1] * 768]

        with patch('opencrane.mcp.server.get_milvus_service', return_value=mock_milvus), \
             patch('opencrane.mcp.server.get_embeddings_service', return_value=mock_embeddings):

            # Return CRD chunk with short content (not truncated)
            mock_milvus.search.return_value = [
                {
                    "chunk_id": "crd-456",
                    "content": {"replicas": 3},
                    "chunk_type": "crd_definition",
                    "metadata_json": '{"original_format": "yaml"}',
                    "distance": 0.8
                }
            ]

            result = await _search_documentation_impl({
                "query": "test crd",
                "limit": 1,
                "search_mode": "semantic",
            })

            # Should have hint to use get_yaml_definition
            assert len(result) > 0
            assert "get_yaml_definition" in result[0].text
            assert "chunk_id='crd-456'" in result[0].text
            assert "breadcrumb comments" in result[0].text

    @pytest.mark.anyio
    async def test_search_documentation_empty_query(self):
        """Test search_documentation returns error for empty query."""
        result = await _search_documentation_impl({"query": ""})
        assert len(result) == 1
        assert "Error: query must be a non-empty string." in result[0].text

    @pytest.mark.anyio
    async def test_search_documentation_whitespace_query(self):
        """Test search_documentation returns error for whitespace-only query."""
        result = await _search_documentation_impl({"query": "   "})
        assert len(result) == 1
        assert "Error: query must be a non-empty string." in result[0].text

    @pytest.mark.anyio
    async def test_search_documentation_exposes_token_count(self):
        """Test that search results include token_count carried on the search result."""
        from opencrane.mcp.server import _search_documentation_impl

        # Setup mock services
        mock_milvus = Mock()
        mock_embeddings = Mock()
        mock_embeddings.model.encode.return_value = [[0.1] * 768]

        with patch('opencrane.mcp.server.get_milvus_service', return_value=mock_milvus), \
             patch('opencrane.mcp.server.get_embeddings_service', return_value=mock_embeddings):

            mock_milvus.search.return_value = [
                {
                    "chunk_id": "chunk-123",
                    "content": "test content",
                    "chunk_type": "prose",
                    "metadata_json": '{}',
                    "token_count": 2073,
                    "distance": 0.9
                }
            ]

            result = await _search_documentation_impl({
                "query": "test",
                "limit": 1,
                "search_mode": "semantic",
            })

            # Should include token count in output
            assert len(result) > 0
            assert "Token Count: 2073" in result[0].text
            assert "Chunk ID: chunk-123" in result[0].text

    @staticmethod
    def _milvus_with_chunk(chunk):
        """Return a get_milvus_service patch target whose get_chunk yields ``chunk``."""
        svc = Mock()
        svc.get_chunk.return_value = chunk
        return svc

    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_get_yaml_definition_with_many_neighbors(self, mock_get_milvus):
        """Test get_yaml_definition with > 5 neighbor chunks."""
        # Milvus stores YAML content and metadata as JSON strings.
        chunk_row = {
            "chunk_id": "test-123",
            "content": json.dumps({"spec": {"replicas": 3}}),
            "chunk_type": "crd_definition",
            "metadata_json": json.dumps({
                "original_format": "yaml",
                "neighbor_chunks": ["n1", "n2", "n3", "n4", "n5", "n6", "n7", "n8"],
            }),
        }
        mock_get_milvus.return_value = self._milvus_with_chunk(chunk_row)

        result = await get_yaml_definition({"chunk_id": "test-123"})

        assert len(result) == 1
        # Should show "and X more" message
        assert "and 3 more" in result[0].text
        # Should show first 5 neighbors
        assert "n1" in result[0].text
        assert "n5" in result[0].text

    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_get_yaml_definition_success(self, mock_get_milvus):
        """Test successful chunk retrieval and YAML re-hydration from Milvus."""
        chunk_row = {
            "chunk_id": "test-123",
            "content": json.dumps({"spec": {"replicas": 3}}),
            "chunk_type": "crd_definition",
            "metadata_json": json.dumps({
                "original_format": "yaml",
                "breadcrumb_path": "spec.properties.spec",
                "source_url": "https://github.com/test/doc.md",
                "neighbor_chunks": ["chunk-456", "chunk-789"],
            }),
        }
        mock_get_milvus.return_value = self._milvus_with_chunk(chunk_row)

        result = await get_yaml_definition({"chunk_id": "test-123"})

        assert len(result) == 1
        assert "Chunk ID: test-123" in result[0].text
        assert "Type: crd_definition" in result[0].text
        assert "# Location: spec.properties.spec" in result[0].text
        assert "# Documentation: https://github.com/test/doc.md" in result[0].text
        assert "spec:" in result[0].text
        assert "replicas: 3" in result[0].text
        assert "# Neighbor Chunks" in result[0].text
        assert "chunk-456" in result[0].text

    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_get_yaml_definition_malformed_content_and_metadata(self, mock_get_milvus):
        """Invalid metadata JSON and un-parseable YAML content degrade gracefully."""
        chunk_row = {
            "chunk_id": "test-123",
            "content": "not: [valid json",  # str, YAML type, but not JSON -> stays as-is
            "chunk_type": "crd_definition",
            "metadata_json": '{"invalid"',  # unparseable -> metadata treated as {}
        }
        mock_get_milvus.return_value = self._milvus_with_chunk(chunk_row)

        result = await get_yaml_definition({"chunk_id": "test-123"})

        assert len(result) == 1
        assert "Chunk ID: test-123" in result[0].text
        assert "not: [valid json" in result[0].text

    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_get_yaml_definition_non_yaml_chunk(self, mock_get_milvus):
        """A non-YAML chunk returns its content untouched (no JSON re-parse)."""
        chunk_row = {
            "chunk_id": "p-1",
            "content": "just some prose",
            "chunk_type": "prose",
            # no metadata_json key -> metadata falls back to {}
        }
        mock_get_milvus.return_value = self._milvus_with_chunk(chunk_row)

        result = await get_yaml_definition({"chunk_id": "p-1"})

        assert len(result) == 1
        assert "just some prose" in result[0].text

    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_get_yaml_definition_chunk_not_found(self, mock_get_milvus):
        """Test get_yaml_definition with non-existent chunk ID."""
        mock_get_milvus.return_value = self._milvus_with_chunk(None)

        result = await get_yaml_definition({"chunk_id": "nonexistent"})

        assert len(result) == 1
        assert "Chunk not found" in result[0].text

    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_get_yaml_definition_service_error(self, mock_get_milvus):
        """Test get_yaml_definition when the Milvus lookup raises."""
        svc = Mock()
        svc.get_chunk.side_effect = Exception("connection lost")
        mock_get_milvus.return_value = svc

        result = await get_yaml_definition({"chunk_id": "test-123"})

        assert len(result) == 1
        assert "Failed to fetch chunk" in result[0].text

    @patch('opencrane.mcp.server.get_milvus_service')
    @patch('opencrane.mcp.server._rehydrate_to_yaml')
    @pytest.mark.anyio
    async def test_get_yaml_definition_processing_error(self, mock_rehydrate, mock_get_milvus):
        """Test get_yaml_definition with error during YAML re-hydration."""
        chunk_row = {
            "chunk_id": "test-123",
            "content": json.dumps({"spec": {"replicas": 3}}),
            "chunk_type": "crd_definition",
            "metadata_json": json.dumps({"original_format": "yaml"}),
        }
        mock_get_milvus.return_value = self._milvus_with_chunk(chunk_row)
        mock_rehydrate.side_effect = Exception("YAML conversion failed")

        result = await get_yaml_definition({"chunk_id": "test-123"})

        assert len(result) == 1
        assert "Failed to fetch chunk" in result[0].text
        assert "YAML conversion failed" in result[0].text

    @pytest.mark.anyio
    async def test_get_metadata_schema_success(self):
        """Test get_metadata_schema returns schema from bundled package file."""
        from opencrane.mcp.server import get_metadata_schema

        result = await get_metadata_schema({})

        assert len(result) == 1
        assert "Chunk Metadata Schema" in result[0].text
        assert "breadcrumb_path" in result[0].text
        assert "logical_parent" in result[0].text
        assert "neighbor_chunks" in result[0].text

    @patch('importlib.resources.files')
    @pytest.mark.anyio
    async def test_get_metadata_schema_read_error(self, mock_files):
        """Test get_metadata_schema with package resource read error."""
        from opencrane.mcp.server import get_metadata_schema

        mock_files.side_effect = Exception("Resource not found")

        result = await get_metadata_schema({})

        assert len(result) == 1
        assert "Failed to retrieve metadata schema" in result[0].text


def _write_collection_meta(tmp_path, chunk_types):
    (tmp_path / ".opencrane").mkdir(exist_ok=True)
    (tmp_path / ".opencrane" / "collection_meta.json").write_text(
        json.dumps({"chunk_types": chunk_types}), encoding="utf-8"
    )


def test_has_yaml_chunks_true(tmp_path, monkeypatch):
    """Test _has_yaml_chunks returns True when the sidecar lists a YAML type."""
    import opencrane.mcp.server as server_module

    monkeypatch.chdir(tmp_path)
    server_module._chunk_types_cache = None
    _write_collection_meta(tmp_path, ["prose", "crd_definition"])

    assert server_module._has_yaml_chunks() is True


def test_has_yaml_chunks_false(tmp_path, monkeypatch):
    """Test _has_yaml_chunks returns False when the sidecar lists no YAML type."""
    import opencrane.mcp.server as server_module

    monkeypatch.chdir(tmp_path)
    server_module._chunk_types_cache = None
    _write_collection_meta(tmp_path, ["prose", "code_snippet"])

    assert server_module._has_yaml_chunks() is False


def test_has_yaml_chunks_empty_index(tmp_path, monkeypatch):
    """Test _has_yaml_chunks returns False when the sidecar is empty."""
    import opencrane.mcp.server as server_module

    monkeypatch.chdir(tmp_path)
    server_module._chunk_types_cache = None
    _write_collection_meta(tmp_path, [])

    assert server_module._has_yaml_chunks() is False


def test_get_indexed_chunk_types_caches(tmp_path, monkeypatch):
    """The chunk-type set is read from the sidecar once and cached."""
    import opencrane.mcp.server as server_module

    monkeypatch.chdir(tmp_path)
    server_module._chunk_types_cache = None
    _write_collection_meta(tmp_path, ["prose", "list_item"])

    first = server_module._get_indexed_chunk_types()
    assert first == {"prose", "list_item"}

    # Remove the sidecar; a cached call must not re-read it.
    (tmp_path / ".opencrane" / "collection_meta.json").unlink()
    assert server_module._get_indexed_chunk_types() is first


@pytest.mark.anyio
@patch('opencrane.mcp.server.get_embeddings_service')
@patch('opencrane.mcp.server.get_milvus_service')
async def test_search_documentation_metadata_display_prose(mock_milvus_get, mock_embeddings_get, monkeypatch):
    """Test that metadata is displayed for prose chunks but not for YAML chunks."""
    import opencrane.mcp.server as server_module

    # Mock services
    mock_embeddings = Mock()
    mock_model = Mock()
    mock_model.encode.return_value = [[0.1] * 768]
    mock_embeddings.model = mock_model
    mock_embeddings_get.return_value = mock_embeddings

    mock_milvus = Mock()
    mock_milvus.search.return_value = [
        {
            "chunk_id": "test-prose-id",
            "content": "prose content",
            "source_file": "file.md",
            "chunk_type": "prose",
            "metadata_json": json.dumps({
                "breadcrumb_path": "section/subsection",
                "logical_parent": "parent.section",
                "neighbor_chunks": ["chunk1", "chunk2"]
            }),
            "distance": 0.5
        },
        {
            "chunk_id": "test-crd-id",
            "content": {"apiVersion": "v1", "kind": "Test"},
            "source_file": "crd.yaml",
            "chunk_type": "crd_definition",
            "metadata_json": json.dumps({
                "breadcrumb_path": "spec.replicas",
                "crd_kind": "TestCRD",
                "crd_version": "v1alpha1"
            }),
            "distance": 0.4
        }
    ]

    mock_milvus_get.return_value = mock_milvus

    results = await server_module._search_documentation_impl({"query": "test", "search_mode": "semantic"})

    assert len(results) == 2

    # Prose chunk should have Metadata section
    assert "Metadata:" in results[0].text
    assert "Location: section/subsection" in results[0].text
    assert "Parent: parent.section" in results[0].text
    assert "Siblings: 2 chunks" in results[0].text

    # CRD chunk should NOT have duplicate Metadata section (already in breadcrumb comments)
    # Count occurrences of "CRD Kind" - should only appear once (in breadcrumb)
    crd_kind_count = results[1].text.count("CRD Kind")
    assert crd_kind_count == 1  # Only in breadcrumb, not in separate Metadata section
