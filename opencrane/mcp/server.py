"""MCP Server for semantic search over documentation."""

import asyncio
import importlib.resources
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

_YAML_CHUNK_TYPES = {"crd_definition", "openapi_spec", "json_schema"}

# Human-readable labels for chunk types
_CHUNK_TYPE_LABELS = {
    "prose": "prose (markdown documentation text)",
    "code_snippet": "code_snippet (fenced code blocks)",
    "yaml_content": "yaml_content (generic YAML blocks)",
    "crd_definition": "crd_definition (Kubernetes CRD YAML properties)",
    "openapi_spec": "openapi_spec (OpenAPI specification endpoints/schemas)",
    "json_schema": "json_schema (JSON Schema definitions)",
    "list_item": "list_item (individual markdown list items)",
    "table": "table (markdown table overview)",
    "table_row": "table_row (individual markdown table rows)",
}


def _has_list_item_chunks() -> bool:
    return "list_item" in _get_indexed_chunk_types()


def _has_table_row_chunks() -> bool:
    return "table_row" in _get_indexed_chunk_types()


def _get_table_members(table_id: str) -> list[dict]:
    """Return the overview chunk then all rows for a table_id, rows by row_index."""
    chunk_index = _build_chunk_index()
    overview = []
    rows = []
    for chunk in chunk_index.values():
        metadata = chunk.get("metadata", {}) or {}
        if metadata.get("table_id") != table_id:
            continue
        if chunk.get("chunk_type") == "table":
            overview.append(chunk)
        elif chunk.get("chunk_type") == "table_row":
            rows.append(chunk)
    rows.sort(key=lambda c: c.get("metadata", {}).get("row_index", 0))
    return overview + rows


def _get_list_members(list_id: str) -> list[dict]:
    """Return all indexed chunks belonging to a given list_id, ordered by position."""
    chunk_index = _build_chunk_index()
    members = []
    for chunk in chunk_index.values():
        if chunk.get("chunk_type") != "list_item":
            continue
        metadata = chunk.get("metadata", {}) or {}
        if metadata.get("list_id") == list_id:
            members.append(chunk)
    members.sort(key=lambda c: c.get("metadata", {}).get("position", 0))
    return members


def _group_list_item_results(results: list[dict]) -> list[dict]:
    """Collapse consecutive result slots that share a list_id into a grouped slot.

    When two or more list_item hits share the same list_id, combine them into a
    single result dict tagged with ``_grouped=True`` and containing a
    ``_grouped_items`` list preserving per-item score, position, and content.
    The grouped slot inherits the max score of its members. Non list_item
    results pass through untouched.
    """
    # Build groups keyed by list_id (None for non-list_item hits)
    groups: dict = {}
    order: list = []
    for r in results:
        if r.get("chunk_type") != "list_item":
            order.append(("single", id(r)))
            groups[("single", id(r))] = [r]
            continue
        metadata_json = r.get("metadata_json", "{}")
        try:
            metadata = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
        except (json.JSONDecodeError, TypeError, ValueError):  # pragma: no cover - defensive
            metadata = {}  # pragma: no cover
        list_id = metadata.get("list_id")
        if not list_id:  # pragma: no cover - validated list_item chunks always carry list_id
            order.append(("single", id(r)))
            groups[("single", id(r))] = [r]
            continue
        key = ("list", list_id)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)

    merged: list[dict] = []
    for key in order:
        members = groups[key]
        if key[0] == "single" or len(members) == 1:
            merged.append(members[0])
            continue
        # Grouped slot — sort members by position, inherit the max score
        def _pos(rec):
            try:
                return json.loads(rec.get("metadata_json") or "{}").get("position", 0)
            except Exception:  # pragma: no cover
                return 0
        members_sorted = sorted(members, key=_pos)
        max_score = max(float(m.get("distance", 0.0)) for m in members_sorted)
        head = dict(members_sorted[0])
        head["distance"] = max_score
        head["_grouped"] = True
        head["_grouped_items"] = members_sorted
        merged.append(head)
    return merged


def _format_grouped_list_item(result: dict, chunk_index: dict) -> str:
    """Format a grouped list_item result slot showing all matched members inline."""
    members = result["_grouped_items"]
    try:
        head_meta = json.loads(members[0].get("metadata_json") or "{}")
    except Exception:  # pragma: no cover
        head_meta = {}
    breadcrumb = head_meta.get("breadcrumb_path", "")
    list_id = head_meta.get("list_id", "")
    total = head_meta.get("total_siblings", len(members))
    list_style = head_meta.get("list_style", "")

    lines = [
        f"Matched List ({len(members)} of {total} items):",
    ]
    if breadcrumb:
        lines.append(f"Location: {breadcrumb}")
    lines.append(f"List ID: {list_id}  style={list_style}")
    lines.append("Matched items:")
    for m in members:
        try:
            mm = json.loads(m.get("metadata_json") or "{}")
        except Exception:  # pragma: no cover
            mm = {}
        pos = mm.get("position")
        content = m.get("content", "")
        # Drop breadcrumb header prefix when displaying inline for readability
        stripped = content
        if breadcrumb and stripped.startswith(f"# {breadcrumb}\n"):
            stripped = stripped[len(breadcrumb) + 3:].lstrip("\n")
        lines.append(f"  [{pos}] {stripped}")

    unmatched_previews = head_meta.get("sibling_previews") or []
    matched_positions = {
        json.loads(m.get("metadata_json") or "{}").get("position")
        for m in members
    }
    unmatched = []
    if unmatched_previews:
        # sibling_previews excludes self; map via sibling_ids to detect matched ones.
        sibling_ids = head_meta.get("sibling_ids") or []
        member_ids = {m.get("chunk_id") for m in members}
        for sid, preview in zip(sibling_ids, unmatched_previews):
            if sid not in member_ids:
                unmatched.append(preview)
        if unmatched:
            lines.append("Other items in list (not matched):")
            for p in unmatched:
                lines.append(f"  - {p}")

    lines.append(f"💡 Tip: Use get_list_members(list_id='{list_id}') for the full list.")
    return "\n".join(lines) + "\n"


def _get_indexed_chunk_types() -> set[str]:
    """Return the set of chunk_type values present in the indexed data."""
    chunk_index = _build_chunk_index()
    return {c.get("chunk_type") for c in chunk_index.values() if c.get("chunk_type")}


def _has_yaml_chunks() -> bool:
    """Check whether indexed chunks contain any YAML-based types (CRD, OpenAPI, JSON Schema)."""
    return bool(_get_indexed_chunk_types() & _YAML_CHUNK_TYPES)


def _get_source_topics() -> list[str]:
    """Derive topic names from the source mapping file.

    Returns human-readable topic names extracted from the mapping path keys
    (e.g., ``MicrosoftDocs/microsoft-style-guide`` → ``microsoft-style-guide``).
    """
    sources = _get_source_keys()
    return [
        Path(key).name.replace("-", " ").replace("_", " ")
        for key in sources
    ]


def _get_source_keys() -> list[str]:
    """Return the raw source path keys (e.g., ``MicrosoftDocs/microsoft-style-guide``).

    These are the values stored in chunks' ``source_name`` field and accepted
    by the ``source_names`` filter on ``search_docs``.
    """
    mapping_file = Path(os.environ.get("MAPPING_FILE", ".opencrane/config.yaml"))
    if not mapping_file.exists():
        return []
    try:
        import yaml as _yaml
        data = _yaml.safe_load(mapping_file.read_text(encoding="utf-8")) or {}
        sources = data.get("sources", {})
        return sorted(sources.keys())
    except Exception:
        return []


def _build_search_tool() -> Tool:
    """Build the search_docs tool with description and schema derived from indexed data."""
    chunk_types = sorted(_get_indexed_chunk_types())
    topics = _get_source_topics()
    source_keys = _get_source_keys()

    # Build description
    if topics:
        topics_str = ", ".join(topics)
        description = f"Search indexed documentation. Topics: {topics_str}."
    else:
        description = "Search indexed documentation."

    # Build chunk_types filter — only include types that actually exist
    chunk_types_property: dict = {
        "type": "array",
        "items": {"type": "string", "enum": chunk_types} if chunk_types else {"type": "string"},
        "description": "Filter by content types. Available: "
            + ", ".join(_CHUNK_TYPE_LABELS.get(ct, ct) for ct in chunk_types)
            + "." if chunk_types else "Filter by content types.",
    }

    properties: dict = {
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
        "chunk_types": chunk_types_property,
        "metadata_contains": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Filter results whose metadata JSON contains all provided substrings (AND logic). Example: ['SMC', 'v1alpha1'] finds chunks with both strings in metadata."
                + (" Use get_metadata_schema tool for details on available metadata fields." if _has_yaml_chunks() else "")
        },
    }

    if source_keys:
        properties["source_names"] = {
            "type": "array",
            "items": {"type": "string", "enum": source_keys},
            "description": "Restrict results to one or more configured sources (OR logic). Available: "
                + ", ".join(source_keys) + ".",
        }

    return Tool(
        name="search_docs",
        description=description,
        inputSchema={
            "type": "object",
            "properties": {
                **properties,
                "search_mode": {
                    "type": "string",
                    "enum": ["semantic", "keyword", "hybrid"],
                    "description": "Search mode. 'hybrid' (default) combines vector similarity with keyword matching — best for most queries. Switch to 'keyword' when you have an exact identifier, field name, config key, or API path (e.g., 'spec.replicas', 'RetryPolicy', '/api/v1/users'). Switch to 'semantic' for conceptual questions where there's no specific term to match on (e.g., 'how does authentication work', 'what handles retry logic').",
                    "default": "hybrid"
                },
                "alpha": {
                    "type": "number",
                    "description": "Blend weight for hybrid mode (0-1). Controls the semantic vs keyword balance. Default 0.6 works well for most queries. Set alpha=0.2 when you have a specific term but want some fuzzy matching. Set alpha=0.9 for conceptual queries that happen to include a known term. Set alpha=1.0 for pure semantic within hybrid mode. Only used when search_mode is 'hybrid'.",
                    "minimum": 0,
                    "maximum": 1
                }
            },
            "required": ["query"]
        }
    )


app = Server("opencrane")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    tools = [
        _build_search_tool(),
        Tool(
            name="health",
            description="Check the health of the documentation search service",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
    ]

    if _has_list_item_chunks():
        tools.append(Tool(
            name="get_list_members",
            description="Fetch every chunk that belongs to the same markdown list, ordered by position. Use when a search returned one or more list_item chunks sharing a list_id and you need the full list for reconstructing a procedure, enumeration, or step-by-step instruction.",
            inputSchema={
                "type": "object",
                "properties": {
                    "list_id": {
                        "type": "string",
                        "description": "The list_id from a list_item chunk's metadata (see sibling grouping in search_docs output)."
                    }
                },
                "required": ["list_id"],
            },
        ))

    if _has_table_row_chunks():
        tools.append(Tool(
            name="get_table_members",
            description="Fetch a full markdown table: its overview chunk and every row chunk sharing a table_id, ordered by row_index. Use when a search returned one or more table_row chunks and you need the whole table.",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_id": {
                        "type": "string",
                        "description": "The table_id from a table_row chunk's metadata."
                    }
                },
                "required": ["table_id"],
            },
        ))

    if _has_yaml_chunks():
        tools.append(Tool(
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
        ))

    if _has_yaml_chunks() or _has_list_item_chunks() or _has_table_row_chunks():
        tools.append(Tool(
            name="get_metadata_schema",
            description="Retrieve comprehensive documentation of all metadata fields available in chunks. Use this when you need to understand what metadata fields mean (breadcrumb_path, logical_parent, neighbor_chunks, list_id, sibling_ids, table_id, row_index, etc.) and how to use them programmatically for navigation, context expansion, and re-hydration. Pass chunk_type to get only the section for a specific type (e.g., 'list_item' returns the list_item metadata fields plus the universal fields; 'table_row' returns the table_row metadata fields).",
            inputSchema={
                "type": "object",
                "properties": {
                    "chunk_type": {
                        "type": "string",
                        "description": "Optional: filter the schema to a specific chunk type (e.g., 'list_item', 'crd_definition', 'openapi_spec', 'json_schema'). When omitted, the full schema is returned."
                    }
                },
                "required": []
            }
        ))

    return tools

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    # Log tool call with parameters
    args_summary = json.dumps(arguments, ensure_ascii=False)
    if len(args_summary) > 200:
        args_summary = args_summary[:200] + "..."
    logger.info(f"🔧 Tool call: {name} | Args: {args_summary}")

    _TOOL_HANDLERS = {
        "search_docs": search_docs,
        "health": health_check,
        "get_yaml_definition": get_yaml_definition,
        "get_metadata_schema": get_metadata_schema,
        "get_list_members": get_list_members,
        "get_table_members": get_table_members,
    }

    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        logger.warning(f"Unknown tool requested: {name}")
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)

async def search_docs(arguments: dict) -> list[TextContent]:
    """
    Search indexed documentation.
    Delegates to the shared search implementation.
    """
    logger.info(f"🔍 Search: {arguments.get('query', '')[:100]}")

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
    source_names = arguments.get("source_names")
    metadata_contains = arguments.get("metadata_contains")
    search_mode = arguments.get("search_mode", "hybrid")
    alpha = max(0.0, min(1.0, float(arguments.get("alpha", get_config().hybrid_alpha))))

    logger.info(
        f"   📖 search: query=\"{query}\" mode={search_mode} limit={limit} "
        f"types={chunk_types} sources={source_names} metadata={metadata_contains}"
    )

    try:
        def _format(results: list[dict]) -> list[TextContent]:
            if not results:
                logger.info("   📖 search: 0 results found")
                return [TextContent(type="text", text="No results found.")]

            # Collapse list_item hits that share a list_id into one slot each.
            results = _group_list_item_results(results)
            logger.info(f"   📖 search: {len(results)} results found (after list grouping)")

            source_map = _build_chunk_source_map()
            chunk_index = _build_chunk_index()
            formatted: list[TextContent] = []
            for i, result in enumerate(results, 1):
                if result.get("_grouped"):
                    grouped_body = _format_grouped_list_item(result, chunk_index)
                    formatted.append(TextContent(type="text", text=f"Result {i}:\n{grouped_body}"))
                    continue
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

                source_name = result.get("source_name") or ""

                result_text = f"Result {i}:\n"
                result_text += f"Source: {source_url}\n"
                if source_name:
                    result_text += f"Source Name: {source_name}\n"
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
                if chunk_type == "table_row":
                    table_id = (metadata or {}).get("table_id")
                    if table_id:
                        result_text += f"\n💡 Tip: Use get_table_members(table_id='{table_id}') for the full table.\n"
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
                source_names=source_names,
                metadata_contains=metadata_contains,
            )

        def _keyword_results() -> list[dict]:
            keyword_service = get_keyword_service()
            return keyword_service.search(
                query,
                limit=limit,
                chunk_types=chunk_types,
                source_names=source_names,
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

_CHUNK_TYPE_SECTION_HEADINGS = {
    "list_item": "List Item Metadata",
    "table": "Table Metadata",
    "table_row": "Table Row Metadata",
    "crd_definition": "CRD-Specific Metadata",
    "openapi_spec": "OpenAPI-Specific Metadata",
    "json_schema": "JSON Schema-Specific Metadata",
    "prose": "Universal Metadata",
    "code_snippet": "Universal Metadata",
    "yaml_content": "Universal Metadata",
}


def _extract_schema_section(full_schema: str, heading_prefix: str) -> str | None:
    """Return the ``## {heading_prefix}…`` section up to the next top-level heading.

    The schema uses ``## Section Name`` for each chunk-type section, so we can
    slice between headings of that level.
    """
    marker = f"\n## {heading_prefix}"
    idx = full_schema.find(marker)
    if idx == -1:
        return None
    # Find the next '\n## ' after our section start
    rest_start = idx + 1
    next_idx = full_schema.find("\n## ", rest_start + 1)
    if next_idx == -1:
        return full_schema[idx:].rstrip() + "\n"
    return full_schema[idx:next_idx].rstrip() + "\n"


async def get_metadata_schema(arguments: dict) -> list[TextContent]:
    """Return comprehensive metadata schema documentation.

    When called with no arguments, returns the full schema. When called with
    ``chunk_type="list_item"`` (or any supported type), returns just the
    Universal Metadata section plus the chunk-type-specific section.
    """
    chunk_type = arguments.get("chunk_type") if arguments else None
    logger.info(f"   get_metadata_schema: chunk_type={chunk_type!r}")

    try:
        schema_content = (
            importlib.resources.files("opencrane.mcp")
            .joinpath("metadata-schema.md")
            .read_text(encoding="utf-8")
        )

        if not chunk_type:
            return [TextContent(type="text", text=schema_content)]

        heading = _CHUNK_TYPE_SECTION_HEADINGS.get(chunk_type)
        if heading is None:
            return [TextContent(
                type="text",
                text=f"Unknown chunk_type '{chunk_type}'. Omit chunk_type to retrieve the full schema.",
            )]

        universal = _extract_schema_section(schema_content, "Universal Metadata") or ""
        specific = _extract_schema_section(schema_content, heading) or ""
        body = universal + "\n" + specific if specific else universal
        logger.info(f"   get_metadata_schema: returned {len(body)} chars (filtered to {chunk_type})")
        return [TextContent(type="text", text=body)]

    except Exception as e:
        logger.error(f"Failed to retrieve metadata schema: {e}")
        return [TextContent(type="text", text=f"Failed to retrieve metadata schema: {str(e)}")]


async def get_list_members(arguments: dict) -> list[TextContent]:
    """Return every chunk belonging to the given list_id, ordered by position."""
    list_id = arguments.get("list_id")
    logger.info(f"   📋 get_list_members: list_id={list_id!r}")
    if not list_id:
        return [TextContent(type="text", text="Error: list_id must be a non-empty string.")]

    members = _get_list_members(list_id)
    if not members:
        return [TextContent(type="text", text=f"No list found for list_id={list_id!r}.")]

    first_meta = members[0].get("metadata", {}) or {}
    breadcrumb = first_meta.get("breadcrumb_path", "")
    style = first_meta.get("list_style", "")
    total = first_meta.get("total_siblings", len(members))

    lines = [f"List ({len(members)} of {total} items, style={style})"]
    if breadcrumb:
        lines.append(f"Location: {breadcrumb}")
    lines.append("")
    for m in members:
        mm = m.get("metadata", {}) or {}
        pos = mm.get("position")
        depth = mm.get("depth", 0)
        indent = "  " * depth
        content = m.get("content", "")
        # Strip breadcrumb header for readable inline display
        if breadcrumb and content.startswith(f"# {breadcrumb}\n"):
            content = content[len(breadcrumb) + 3:].lstrip("\n")
        lines.append(f"{indent}[{pos}] {content}")

    return [TextContent(type="text", text="\n".join(lines) + "\n")]


async def get_table_members(arguments: dict) -> list[TextContent]:
    """Return the overview chunk and all rows for the given table_id."""
    table_id = arguments.get("table_id")
    logger.info(f"   📊 get_table_members: table_id={table_id!r}")
    if not table_id:
        return [TextContent(type="text", text="Error: table_id must be a non-empty string.")]
    members = _get_table_members(table_id)
    if not members:
        return [TextContent(type="text", text=f"No table found for table_id={table_id!r}.")]
    lines = []
    for m in members:
        lines.append(m.get("content", ""))
        lines.append("")
    return [TextContent(type="text", text="\n".join(lines).strip() + "\n")]


async def main():
    """Main entry point for the MCP server."""

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":  # pragma: no cover
    import asyncio
    asyncio.run(main())