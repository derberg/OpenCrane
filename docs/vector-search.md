# Vector Search and MCP Server

OpenCrane includes a Milvus Lite-based vector search system with MCP (Model Context Protocol) server for semantic search over documentation. The entire system runs in a single Docker container with an embedded vector database - no complex infrastructure required.

## Search Capabilities

- **Semantic Search**: Vector similarity using Nomic Embed v1.5 embeddings
- **Keyword Search**: BM25 ranking without vector database dependency
- **Hybrid Search**: Weighted combination of semantic + keyword scores
- **Advanced Filtering**: By chunk type, source file, and metadata content

## Getting Started

### Option 1: Locally without Docker (stdio)

```bash
# Build the full pipeline
opencrane build

# Start MCP server — prints instructions for adding to Claude Code, Cursor, Windsurf, etc.
opencrane serve
```

To interactively test tools via a web UI (no Docker needed):

```bash
opencrane inspect
```

### Option 2: Docker (HTTP, port 8000)

Run `opencrane init` once to generate the `Dockerfile` and `docker-compose.yml`, then:

```bash
docker-compose up --build
# MCP server available at http://localhost:8000/http
```

For Podman users:

```bash
opencrane init --podman
podman-compose up --build
```

### Option 3: Package for distribution via `uvx`

```bash
# Package the built MCP server
opencrane pack --name my-docs-mcp

# Share a one-liner with teammates
claude mcp add my-docs -- uvx --from "git+https://github.com/you/my-docs-mcp" my-docs-mcp
```

Recipients don't need to rebuild anything — the package includes the Milvus database and chunk index. See `opencrane pack --help` for options.

### Option 4: Using a Pre-built Docker Image

```bash
docker run -p 8000:8000 your-registry/your-project-mcp:latest
```

## Example Search Queries

```python
# Search product documentation
search_product_docs(query="kubernetes deployment", limit=5)

# Search guidelines
search_guidelines(query="documentation style", search_mode="semantic")

# Hybrid search with custom weighting
search_product_docs(
    query="configuration options",
    search_mode="hybrid",
    alpha=0.7,  # 70% semantic, 30% keyword
    chunk_types=["prose"]
)

# Cross-category search: Call both tools
product_results = search_product_docs(query="API documentation examples")
guideline_results = search_guidelines(query="API documentation best practices")
```

## Available MCP Tools

The MCP server provides the following tools for interacting with documentation:

### 1. `search_product_docs`

Search product documentation: APIs, deployment guides, configuration references, and operational documentation.

**Parameters:**
- `query` (string, required): The search query
- `limit` (integer, optional): Maximum number of results (1-50, default: 5)
- `search_mode` (string, optional): Search mode - "semantic", "keyword", or "hybrid" (default: "hybrid")
- `alpha` (number, optional): Weight for semantic score in hybrid mode (0-1, default: 0.6)
- `chunk_types` (array, optional): Filter by content type - "prose", "code_snippet", "crd_definition", "openapi_spec", "json_schema"
- `metadata_contains` (array, optional): Filter by metadata content (AND logic)

**Example:**
```python
search_product_docs(
    query="authentication methods",
    search_mode="hybrid",
    chunk_types=["prose", "code_snippet"],
    limit=10
)
```

### 2. `search_guidelines`

Search content guidelines: writing style, documentation templates, diagram conventions, and content strategy.

**Parameters:**
- `query` (string, required): The search query
- `limit` (integer, optional): Maximum number of results (1-50, default: 5)
- `search_mode` (string, optional): Search mode - "semantic", "keyword", or "hybrid" (default: "hybrid")
- `alpha` (number, optional): Weight for semantic score in hybrid mode (0-1, default: 0.6)
- `chunk_types` (array, optional): Filter by content type - "prose", "code_snippet", "crd_definition", "openapi_spec", "json_schema"
- `metadata_contains` (array, optional): Filter by metadata content (AND logic)

**Example:**
```python
search_guidelines(
    query="documentation templates",
    search_mode="semantic",
    limit=5
)
```

### 3. `get_yaml_definition`

Retrieve complete YAML definition for CRD, OpenAPI, or JSON Schema chunks with breadcrumb comments showing location in tree.

**Parameters:**
- `chunk_id` (string, required): The chunk ID from search results

**Use cases:**
- Need full YAML context with location breadcrumbs
- Search results show truncated content
- Want to see neighbor chunks at same tree level
- Need the documentation URL for a YAML chunk

**Example:**
```python
get_yaml_definition(chunk_id="abc123...")
```

### 4. `get_metadata_schema`

Retrieve comprehensive documentation of all metadata fields available in chunks. Use this to understand what metadata fields mean and how to use them programmatically.

**Parameters:** None

**Returns:** Complete metadata schema documentation including:
- Universal metadata fields (`source_url`, `original_format`, `schema_type`)
- Hierarchical navigation metadata (`breadcrumb_path`, `logical_parent`, `neighbor_chunks`)
- Type-specific metadata (CRD, OpenAPI, JSON Schema)
- Programmatic usage examples
- MCP server integration patterns

**Use cases:**
- Understanding metadata field meanings
- Learning how to navigate hierarchical structures
- Implementing context expansion with neighbor chunks
- Re-hydrating YAML from chunks using breadcrumb paths

**Example:**
```python
get_metadata_schema()
```

### 5. `health`

Check the health status of the MCP server and its services.

**Parameters:** None

**Returns:** Health status of:
- Embeddings service
- Milvus vector database
- Collection statistics

**Example:**
```python
health()
```
