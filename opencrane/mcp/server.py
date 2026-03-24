"""MCP Server for semantic search over documentation."""

import asyncio
import json
import logging
import os
import re
import yaml
from pathlib import Path
from typing import List
from mcp import Tool
from mcp.server import Server
from mcp.types import TextContent, PromptMessage
from mcp.server.stdio import stdio_server
from opencrane.mcp.services.embeddings import EmbeddingService
from opencrane.mcp.services.milvus_client import MilvusService
from opencrane.mcp.services.keyword_search import KeywordSearchService
from opencrane.shared.config import get_config
from opencrane.shared.models.vector_chunk import generate_chunk_id

import sys

# Configure logging to stderr (stdout is reserved for MCP stdio transport)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# Lazy initialization of services
_embeddings_service = None
_milvus_service = None
_keyword_service = None
_chunk_source_map: dict[str, str] | None = None
_chunk_index: dict[str, dict] | None = None

def _extract_source_url(text: str) -> str | None:
    """Extract the first http(s) URL from the chunk content, if present."""
    match = re.search(r"https?://\S+", text)
    return match.group(0) if match else None


def _rehydrate_to_yaml(content: dict | str, metadata: dict, chunk_type: str = "") -> str:
    """Convert JSON chunk content to YAML with breadcrumb comments.

    Args:
        content: The chunk content (dict for YAML chunks, str for others)
        metadata: Chunk metadata containing breadcrumb_path, source_url, etc.
        chunk_type: The type of chunk (crd_definition, openapi_spec, json_schema, etc.)

    Returns:
        YAML string with breadcrumb comments if chunk is YAML-based,
        original content string otherwise.
    """
    # Only re-hydrate YAML-based chunk types
    if chunk_type not in ("crd_definition", "openapi_spec", "json_schema"):
        return content if isinstance(content, str) else str(content)

    # Build breadcrumb comment header
    breadcrumb_lines = []

    if metadata.get("breadcrumb_path"):
        breadcrumb_lines.append(f"# Location: {metadata['breadcrumb_path']}")

    if metadata.get("source_url"):
        breadcrumb_lines.append(f"# Documentation: {metadata['source_url']}")

    if metadata.get("logical_parent"):
        breadcrumb_lines.append(f"# Parent: {metadata['logical_parent']}")

    # Add type-specific context
    if metadata.get("crd_kind"):
        breadcrumb_lines.append(f"# CRD Kind: {metadata['crd_kind']}")
    if metadata.get("crd_version"):
        breadcrumb_lines.append(f"# CRD Version: {metadata['crd_version']}")
    if metadata.get("openapi_version"):
        breadcrumb_lines.append(f"# OpenAPI Version: {metadata['openapi_version']}")
    if metadata.get("endpoint_path"):
        breadcrumb_lines.append(f"# Endpoint: {metadata['endpoint_path']}")
    if metadata.get("http_method"):
        breadcrumb_lines.append(f"# Method: {metadata['http_method'].upper()}")
    if metadata.get("schema_version"):
        breadcrumb_lines.append(f"# JSON Schema Version: {metadata['schema_version']}")
    if metadata.get("schema_title"):
        breadcrumb_lines.append(f"# Schema Title: {metadata['schema_title']}")
    if metadata.get("property_path"):
        breadcrumb_lines.append(f"# Property Path: {metadata['property_path']}")
    
    breadcrumb = "\n".join(breadcrumb_lines)
    
    # Convert content to YAML
    if isinstance(content, dict):
        yaml_content = yaml.dump(content, default_flow_style=False, sort_keys=False)
    else:
        # If content is already a string, assume it's YAML
        yaml_content = content
    
    # Combine breadcrumb and YAML
    if breadcrumb:
        return f"{breadcrumb}\n\n{yaml_content}"
    return yaml_content




def _build_chunk_source_map() -> dict[str, str]:
    """Precompute chunk_id -> source_url map from rag-chunks.json with heuristics.

    This map lets us attach better source URLs even when chunks were built from
    the flattened llms-full.txt file.
    """
    global _chunk_source_map
    if _chunk_source_map is not None:
        return _chunk_source_map

    chunks_path = Path(os.environ.get("AI_DOCS_CHUNKS_FILE", ".opencrane/chunks.json"))
    try:
        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Failed to load {chunks_path}: {exc}")
        _chunk_source_map = {}
        return _chunk_source_map

    mapping: dict[str, str] = {}
    for chunk in chunks:
        # Use chunk_id from chunk data instead of regenerating
        chunk_id = chunk.get("chunk_id")
        if not chunk_id:
            # Fallback to generation only if missing (shouldn't happen)
            try:
                chunk_id = generate_chunk_id(
                    chunk.get("source_file", ""),
                    chunk.get("chunk_type", ""),
                    chunk.get("line_start"),
                    chunk.get("content", ""),
                )
            except Exception:
                continue

        # All chunks are guaranteed to have a source_url in metadata
        metadata = chunk.get("metadata", {})
        url = metadata.get("source_url") if isinstance(metadata, dict) else None

        if not url:
            url = _extract_source_url(chunk.get("content", ""))
        if not url:
            url = _extract_source_url(json.dumps(metadata) if isinstance(metadata, dict) else str(metadata))

        if url:
            mapping[chunk_id] = url

    logger.info(f"Built chunk source map with {len(mapping)} entries")
    _chunk_source_map = mapping
    return _chunk_source_map

def _build_chunk_index() -> dict[str, dict]:
    """Precompute chunk_id -> chunk dict from rag-chunks.json for O(1) lookups."""
    global _chunk_index
    if _chunk_index is not None:
        return _chunk_index

    chunks_path = Path(os.environ.get("AI_DOCS_CHUNKS_FILE", ".opencrane/chunks.json"))
    try:
        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Failed to load {chunks_path} for chunk index: {exc}")
        _chunk_index = {}
        return _chunk_index

    _chunk_index = {c.get("chunk_id"): c for c in chunks if c.get("chunk_id")}
    logger.info(f"Built chunk index with {len(_chunk_index)} entries")
    return _chunk_index

def get_embeddings_service():
    global _embeddings_service
    if _embeddings_service is None:
        _embeddings_service = EmbeddingService()
    return _embeddings_service

def get_milvus_service():
    global _milvus_service
    if _milvus_service is None:
        _milvus_service = MilvusService()
    return _milvus_service

def get_keyword_service():
    global _keyword_service
    if _keyword_service is None:
        _keyword_service = KeywordSearchService()
    return _keyword_service

app = Server("opencrane")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="search_product_docs",
            description="Search product documentation: extensions, APIs, CRDs, deployment guides, and operational documentation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 50
                    },
                    "chunk_types": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["prose", "code_snippet", "crd_definition", "openapi_spec", "json_schema"]},
                        "description": "Filter by content types: 'prose' (markdown documentation text), 'code_snippet' (fenced code blocks), 'crd_definition' (Kubernetes CRD YAML properties), 'openapi_spec' (OpenAPI specification endpoints/schemas), 'json_schema' (JSON Schema definitions). Example: ['crd_definition', 'json_schema'] to search only schema definitions."
                    },
                    "metadata_contains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter results whose metadata JSON contains all provided substrings (AND logic). Example: ['SMC', 'v1alpha1'] finds chunks with both strings in metadata. Use get_metadata_schema tool for details on available metadata fields."
                    },
                    "search_mode": {
                        "type": "string",
                        "enum": ["semantic", "keyword", "hybrid"],
                        "description": "Search mode. Use 'hybrid' (default) for general queries — it combines vector similarity with keyword matching. Use 'keyword' when searching for exact identifiers, CRD field names, or API paths. Use 'semantic' when searching by concept or natural-language question with no specific term in mind.",
                        "default": "hybrid"
                    },
                    "alpha": {
                        "type": "number",
                        "description": "Weight for semantic score in hybrid mode (0-1). Higher values favor semantic similarity, lower values favor keyword matching. If omitted, defaults to the server's configured value (HYBRID_ALPHA env var, 0.6 by default).",
                        "minimum": 0,
                        "maximum": 1
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="health",
            description="Check the health of the documentation search service",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_yaml_definition",
            description="Retrieve complete YAML definition for CRD, OpenAPI, or JSON Schema chunks with breadcrumb comments. Use this when: 1) You need full YAML context with location breadcrumbs (e.g., 'spec.replicas is at spec.versions[0].schema.properties.spec.replicas in SMC CRD'), 2) Search results show truncated content and suggest using this tool, 3) You want to see neighbor chunks at the same tree level, 4) You need the documentation URL for a YAML chunk. Returns YAML with comment headers showing: location in tree, parent path, schema type/version information, and up to 5 sibling chunks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chunk_id": {
                        "type": "string",
                        "description": "The chunk ID from search results (look for 'Chunk ID:' field)"
                    }
                },
                "required": ["chunk_id"]
            }
        ),
        Tool(
            name="get_metadata_schema",
            description="Retrieve comprehensive documentation of all metadata fields available in chunks. Use this when you need to understand what metadata fields mean (breadcrumb_path, logical_parent, neighbor_chunks, etc.) and how to use them programmatically for navigation, context expansion, and re-hydration. Returns detailed schema documentation with field definitions, examples, and usage patterns.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    # Log tool call with parameters
    args_summary = json.dumps(arguments, ensure_ascii=False)
    if len(args_summary) > 200:
        args_summary = args_summary[:200] + "..."
    logger.info(f"🔧 Tool call: {name} | Args: {args_summary}")

    _TOOL_HANDLERS = {
        "search_product_docs": search_product_docs,
        "health": health_check,
        "get_yaml_definition": get_yaml_definition,
        "get_metadata_schema": get_metadata_schema,
    }

    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        logger.warning(f"Unknown tool requested: {name}")
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)

async def search_product_docs(arguments: dict) -> list[TextContent]:
    """
    Search product documentation.
    Delegates to the shared search implementation.
    """
    logger.info(f"🔍 Product docs search: {arguments.get('query', '')[:100]}")

    return await _search_documentation_impl(arguments)


async def _search_documentation_impl(arguments: dict) -> list[TextContent]:
    """
    Internal implementation of search logic.
    This contains all the existing search_documentation code.
    """
    query = arguments.get("query", "")
    if not query or not query.strip():
        return [TextContent(type="text", text="Error: query must be a non-empty string.")]
    limit = arguments.get("limit", 5)
    chunk_types = arguments.get("chunk_types")
    metadata_contains = arguments.get("metadata_contains")
    search_mode = arguments.get("search_mode", "hybrid")
    alpha = max(0.0, min(1.0, float(arguments.get("alpha", get_config().hybrid_alpha))))

    logger.info(
        f"   📖 search: query=\"{query}\" mode={search_mode} limit={limit} "
        f"types={chunk_types} metadata={metadata_contains}"
    )

    try:
        def _format(results: list[dict]) -> list[TextContent]:
            if not results:
                logger.info("   📖 search: 0 results found")
                return [TextContent(type="text", text="No results found.")]
            logger.info(f"   📖 search: {len(results)} results found")

            source_map = _build_chunk_source_map()
            chunk_index = _build_chunk_index()
            formatted: list[TextContent] = []
            for i, result in enumerate(results, 1):
                content = result.get("content", "")
                source_file = result.get("source_file", "")
                chunk_type = result.get("chunk_type", "")
                chunk_id = result.get("chunk_id")
                metadata_json = result.get("metadata_json", "{}")
                score = result.get("distance", 0)

                # Get token_count from chunk index
                token_count = None
                if chunk_id and chunk_index:
                    chunk_data = chunk_index.get(chunk_id)
                    if chunk_data:
                        token_count = chunk_data.get("token_count")

                # Parse metadata JSON
                try:
                    metadata = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
                except (json.JSONDecodeError, TypeError, ValueError):
                    metadata = {}

                # Re-hydrate YAML chunks with breadcrumb comments
                display_content = _rehydrate_to_yaml(content, metadata, chunk_type)

                # Extract source URL
                source_url = metadata.get("source_url")
                if not source_url:
                    source_url = _extract_source_url(str(content))
                if not source_url and chunk_id and source_map:
                    source_url = source_map.get(chunk_id)
                if not source_url:
                    source_url = source_file

                result_text = f"Result {i}:\n"
                result_text += f"Source: {source_url}\n"
                result_text += f"Type: {chunk_type}\n"
                result_text += f"Chunk ID: {chunk_id}\n"
                if token_count is not None:
                    result_text += f"Token Count: {token_count}\n"

                # Add metadata section only for non-YAML chunks (YAML chunks already have breadcrumbs in content)
                if metadata and chunk_type not in ("crd_definition", "openapi_spec", "json_schema"):
                    result_text += f"Metadata:\n"
                    if metadata.get("breadcrumb_path"):
                        result_text += f"  Location: {metadata['breadcrumb_path']}\n"
                    if metadata.get("logical_parent"):
                        result_text += f"  Parent: {metadata['logical_parent']}\n"
                    neighbor_count = len(metadata.get("neighbor_chunks", []))
                    if neighbor_count:
                        result_text += f"  Siblings: {neighbor_count} chunks at same level\n"

                result_text += f"Content:\n{display_content[:1000]}\n"
                if len(display_content) > 1000:
                    result_text += f"...(truncated - {len(display_content)} total chars)\n"
                    result_text += f"💡 Tip: Use get_yaml_definition tool with chunk_id='{chunk_id}' to retrieve the complete definition with breadcrumb comments.\n"
                elif chunk_type in ("crd_definition", "openapi_spec", "json_schema"):
                    result_text += f"💡 Tip: Use get_yaml_definition(chunk_id='{chunk_id}') to see this with breadcrumb comments showing its location in the YAML tree and neighbor chunks.\n"
                result_text += f"Score: {score}\n\n"

                formatted.append(TextContent(type="text", text=result_text))
            return formatted

        def _semantic_results() -> list[dict]:
            embeddings_service = get_embeddings_service()
            query_embedding = embeddings_service.model.encode([query], batch_size=8, show_progress_bar=False)
            if hasattr(query_embedding, 'tolist'):
                query_embedding = query_embedding.tolist()
            query_vec = query_embedding[0]

            milvus_service = get_milvus_service()
            return milvus_service.search(
                query_vec,
                limit=limit,
                chunk_types=chunk_types,
                metadata_contains=metadata_contains,
            )

        def _keyword_results() -> list[dict]:
            keyword_service = get_keyword_service()
            return keyword_service.search(
                query,
                limit=limit,
                chunk_types=chunk_types,
                metadata_contains=metadata_contains,
            )

        if search_mode == "semantic":
            results = _semantic_results()
            if results is None:
                results = []
            return _format(results)
        elif search_mode == "keyword":
            results = _keyword_results()
            if results is None:
                results = []
            return _format(results)
        elif search_mode == "hybrid":
            loop = asyncio.get_event_loop()
            sem, key = await asyncio.gather(
                loop.run_in_executor(None, _semantic_results),
                loop.run_in_executor(None, _keyword_results),
            )
            
            # Handle None results
            if sem is None:
                sem = []
            if key is None:
                key = []

            # Normalize scores and merge by chunk_id
            def _normalize(rs: list[dict]) -> dict[str, float]:
                if not rs:
                    return {}
                scores = [float(r.get("distance", 0.0)) for r in rs]
                min_s, max_s = min(scores), max(scores)
                spread = max_s - min_s
                if spread == 0:
                    return {r.get("chunk_id"): 1.0 for r in rs}
                return {r.get("chunk_id"): (float(r.get("distance", 0.0)) - min_s) / spread for r in rs}

            sem_norm = _normalize(sem)
            key_norm = _normalize(key)
            ids = set(sem_norm.keys()) | set(key_norm.keys())

            # For assembling final objects, index originals by id
            def _by_id(rs: list[dict]) -> dict[str, dict]:
                if not rs:
                    return {}
                return {r.get("chunk_id"): r for r in rs if r.get("chunk_id")}

            sem_map = _by_id(sem)
            key_map = _by_id(key)

            combined: List[dict] = []
            for cid in ids:
                s = sem_norm.get(cid, 0.0)
                k = key_norm.get(cid, 0.0)
                score = alpha * s + (1 - alpha) * k
                # Prefer semantic record, else keyword
                rec = sem_map.get(cid) or key_map.get(cid)
                if not rec:
                    continue
                out = dict(rec)
                out["distance"] = score
                combined.append(out)

            combined.sort(key=lambda r: r.get("distance", 0), reverse=True)
            return _format(combined[:limit])
        else:
            return [TextContent(type="text", text=f"Invalid search_mode: {search_mode}")]


    except Exception as e:
        logger.error(f"Search failed: {e}")
        return [TextContent(type="text", text=f"Search failed: {str(e)}")]

async def health_check(arguments: dict) -> list[TextContent]:
    """Check service health."""
    logger.info("   💓 health: checking service status")
    try:
        # Check if services are initialized
        embeddings_service = get_embeddings_service()
        milvus_service = get_milvus_service()
        health_status = {
            "embeddings_service": "healthy" if embeddings_service.model else "unhealthy",
            "milvus_service": "healthy" if milvus_service.client else "unhealthy"
        }

        # Try to get collection stats
        try:
            stats = milvus_service.get_collection_stats()
            health_status["collection_stats"] = stats
        except Exception as e:
            health_status["collection_stats"] = f"error: {str(e)}"

        health_text = "Health Check Results:\n"
        for component, status in health_status.items():
            health_text += f"- {component}: {status}\n"

        return [TextContent(type="text", text=health_text)]

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return [TextContent(type="text", text=f"Health check failed: {str(e)}")]

async def get_yaml_definition(arguments: dict) -> list[TextContent]:
    """Fetch a chunk by ID and re-hydrate to YAML with breadcrumb comments.

    Enables agents to retrieve specific YAML chunks and navigate between related chunks
    using neighbor references from metadata.
    """
    chunk_id = arguments["chunk_id"]
    logger.info(f"   📄 get_yaml_definition: chunk_id=\"{chunk_id}\"")

    try:
        chunk_index = _build_chunk_index()
        chunk = chunk_index.get(chunk_id)

        if not chunk:
            logger.info(f"   📄 get_yaml_definition: chunk not found")
            return [TextContent(type="text", text=f"Chunk not found: {chunk_id}")]

        # Extract data
        content = chunk.get("content", "")
        chunk_type = chunk.get("chunk_type", "")
        metadata = chunk.get("metadata", {})

        # Re-hydrate to YAML with breadcrumb
        yaml_output = _rehydrate_to_yaml(content, metadata, chunk_type)

        # Add neighbor information if available
        neighbor_chunks = metadata.get("neighbor_chunks", [])
        if neighbor_chunks:
            yaml_output += f"\n\n# Neighbor Chunks (siblings at same level):\n"
            for neighbor_id in neighbor_chunks[:5]:  # Limit to 5 neighbors
                yaml_output += f"#   - {neighbor_id}\n"
            if len(neighbor_chunks) > 5:
                yaml_output += f"#   ... and {len(neighbor_chunks) - 5} more\n"

        logger.info(f"   📄 get_yaml_definition: found chunk type={chunk_type}")

        result_text = f"Chunk ID: {chunk_id}\n"
        result_text += f"Type: {chunk_type}\n"
        result_text += f"Definition:\n\n{yaml_output}\n"

        return [TextContent(type="text", text=result_text)]

    except Exception as e:
        logger.error(f"Failed to fetch chunk {chunk_id}: {e}")
        return [TextContent(type="text", text=f"Failed to fetch chunk: {str(e)}")]

async def get_metadata_schema(arguments: dict) -> list[TextContent]:
    """Return comprehensive metadata schema documentation.

    Provides detailed information about all metadata fields, their purpose,
    format, and usage patterns for programmatic navigation and context expansion.

    Note: Requires docs/metadata-schema.md to be present in the working directory.
    This file is copied into the Docker image via Dockerfile.
    """
    logger.info("   get_metadata_schema: retrieving schema documentation")

    try:
        # Read the metadata schema documentation.
        # Check METADATA_SCHEMA_PATH env var first (used by opencrane pack),
        # then .opencrane/ (new convention), then docs/ (legacy).
        env_path = os.environ.get("METADATA_SCHEMA_PATH")
        if env_path:
            docs_path = Path(env_path)
        else:
            docs_path = Path(".opencrane/metadata-schema.md")
            if not docs_path.exists():
                docs_path = Path("docs/metadata-schema.md")
        if not docs_path.exists():
            logger.warning("   get_metadata_schema: schema file not found")
            return [TextContent(
                type="text",
                text="Metadata schema documentation file not found. Place it at .opencrane/metadata-schema.md."
            )]

        schema_content = docs_path.read_text(encoding="utf-8")
        logger.info(f"   get_metadata_schema: returned {len(schema_content)} chars")

        return [TextContent(type="text", text=schema_content)]

    except Exception as e:
        logger.error(f"Failed to retrieve metadata schema: {e}")
        return [TextContent(type="text", text=f"Failed to retrieve metadata schema: {str(e)}")]

async def main():
    """Main entry point for the MCP server."""

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())