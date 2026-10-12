# Vector search and the MCP server

OpenCrane includes a vector search system based on Milvus Lite, with a Model Context Protocol (MCP) server for semantic search over documentation. The vector database is embedded, so the server runs as one process or one Docker container and needs no external services.

## Search capabilities

The following table lists the search modes and filters that the MCP server supports:

| Capability | Description |
|---|---|
| Semantic search | Vector similarity with Nomic Embed v1.5 embeddings |
| Keyword search | Best Matching 25 (BM25) ranking, without a dependency on the vector database |
| Hybrid search | Weighted combination of the semantic and keyword scores |
| Filters | Restrict results by chunk type, source name, and metadata content |

## Start the MCP server

You can start the MCP server in one of the following ways:

- Locally, without Docker
- In Docker
- From a prebuilt Docker image

### Run locally without Docker

By default, `opencrane serve` uses the standard input/output (stdio) transport. To build the full pipeline and start the server, run the following commands:

```bash
# Build the full pipeline
opencrane build

# Start the MCP server. It prints setup instructions for Claude Code, Cursor, and Windsurf.
opencrane serve
```

> [!CAUTION]
> By default, the HTTP transport has no authentication and listens on all network interfaces. Anyone who can reach port 8000 can search every source. To restrict access, see [Authentication and authorization](auth.md).

To serve over HTTP on port 8000 instead, run `opencrane serve --transport http`.

To test the tools interactively in a web user interface (UI), run the following command:

```bash
opencrane inspect
```

### Run in Docker

In Docker, the server uses the HTTP transport on port 8000. Run `opencrane init` once to generate `.opencrane/Dockerfile` and `.opencrane/docker-compose.yml`.

> [!CAUTION]
> By default, the HTTP transport has no authentication and listens on all network interfaces. Anyone who can reach port 8000 can search every source. To restrict access, see [Authentication and authorization](auth.md).

Start the server from the project root:

```bash
docker-compose -f .opencrane/docker-compose.yml up --build
```

The MCP server is then available at `http://localhost:8000/mcp`.

If you use Podman, generate the files with the `--podman` flag and start the server with `podman-compose`:

```bash
opencrane init --podman
podman-compose -f .opencrane/docker-compose.yml up --build
```

### Run a prebuilt Docker image

> [!CAUTION]
> By default, the HTTP transport has no authentication and listens on all network interfaces. Anyone who can reach port 8000 can search every source. To restrict access, see [Authentication and authorization](auth.md).

To start a prebuilt image, run the following command:

```bash
docker run -p 8000:8000 {REGISTRY}/{IMAGE_NAME}:latest
```

## Share the server as a `uvx` package

To package the built MCP server for distribution through `uvx`, run the following command:

```bash
opencrane pack --name {PACKAGE_NAME}
```

The package includes the Milvus database and the chunk index, so the people you share it with do not need to rebuild anything. For example, after you publish the package to a GitHub repository, they add the server to Claude Code with the following command:

```bash
claude mcp add {SERVER_NAME} -- uvx --from "git+https://github.com/{OWNER}/{PACKAGE_NAME}" {PACKAGE_NAME}
```

For other ways to share the package and for the `opencrane pack` options, see [Package the server with `opencrane pack`](../README.md#package-the-server-with-opencrane-pack).

## MCP tools

The MCP server provides the following tools. An MCP client calls them to search and read the documentation.

### `search_docs`

The `search_docs` tool searches the indexed documentation. OpenCrane builds the tool description and the list of available chunk types from the indexed content and the configured sources.

The following table lists the parameters of `search_docs`:

| Parameter | Type | Required | Description | Default value |
|---|---|---|---|---|
| `query` | string | Yes | The search query. | none |
| `limit` | integer | No | The maximum number of results, from 1 to 50. | `5` |
| `search_mode` | string | No | The search mode: `semantic`, `keyword`, or `hybrid`. | `hybrid` |
| `alpha` | number | No | The weight of the semantic score in hybrid mode, from 0 to 1. | `0.6` |
| `chunk_types` | array | No | Filters by content type. Possible values are `prose`, `code_snippet`, `crd_definition`, `openapi_spec`, `json_schema`, `yaml_content`, `list_item`, and `table_row`. The tool schema lists only the types present in the index. | none |
| `metadata_contains` | array | No | Filters by metadata content. Each value is a text string that the chunk metadata must contain. A chunk must match all values (AND logic). | none |
| `source_names` | array | No | Restricts results to one or more configured sources (OR logic). The values must be keys of the `sources:` block in the `.opencrane/config.yaml` file, for example `MicrosoftDocs/microsoft-style-guide`. The tool schema advertises this parameter only when sources are configured, and its enum lists the exact valid values. With authentication, the caller's permissions can narrow the results further. See [Authentication and authorization](auth.md). | none |

The following examples call `search_docs` with the default settings and with a custom hybrid weighting:

```python
# Search with the default settings
search_docs(query="kubernetes deployment", limit=5)

# Hybrid search with custom weighting
search_docs(
    query="configuration options",
    search_mode="hybrid",
    alpha=0.7,  # 70% semantic, 30% keyword
    chunk_types=["prose"]
)
```

The following example combines several filters:

```python
search_docs(
    query="authentication methods",
    search_mode="hybrid",
    chunk_types=["prose", "code_snippet"],
    source_names=["MicrosoftDocs/microsoft-style-guide"],
    limit=10
)
```

### `get_yaml_definition`

The `get_yaml_definition` tool returns the complete YAML definition of a CustomResourceDefinition (CRD), OpenAPI, or JSON Schema chunk. Breadcrumb comments show where the chunk is in the YAML document. The tool is available only when the index contains CRD, OpenAPI, or JSON Schema chunks.

The following table lists the parameter of `get_yaml_definition`:

| Parameter | Type | Required | Description | Default value |
|---|---|---|---|---|
| `chunk_id` | string | Yes | The chunk ID from the search results. | none |

Call `get_yaml_definition` when you need one of the following:

- Full YAML context with location breadcrumbs
- Complete content of a chunk that the search results show truncated
- Neighbor chunks at the same level of the YAML document
- Documentation URL of a YAML chunk

The following example calls the tool:

```python
get_yaml_definition(chunk_id="{CHUNK_ID}")
```

### `get_metadata_schema`

The `get_metadata_schema` tool returns documentation of all metadata fields available in chunks. The tool is available only when the index contains CRD, OpenAPI, JSON Schema, `list_item`, or `table_row` chunks.

The following table lists the parameter of `get_metadata_schema`:

| Parameter | Type | Required | Description | Default value |
|---|---|---|---|---|
| `chunk_type` | string | No | Returns only the section for this chunk type, for example `list_item`. | none, which returns the full schema |

The returned documentation covers the following:

- Universal metadata fields (`source_url`, `original_format`, `schema_type`)
- Hierarchical navigation metadata (`breadcrumb_path`, `logical_parent`, `neighbor_chunks`)
- Type-specific metadata for CRD, OpenAPI, JSON Schema, `list_item`, and `table_row` chunks
- Programmatic usage examples
- MCP server integration patterns

Use `get_metadata_schema` for the following tasks:

- Learn what each metadata field means
- Navigate hierarchical structures
- Expand the context of a result with neighbor chunks
- Rebuild YAML from chunks with breadcrumb paths

The following example calls the tool for the full schema and for one chunk type:

```python
get_metadata_schema()
get_metadata_schema(chunk_type="list_item")
```

### `get_list_members`

The `get_list_members` tool returns all items of a Markdown list by its `list_id`. The tool is available only when the index contains `list_item` chunks.

The following table lists the parameter of `get_list_members`:

| Parameter | Type | Required | Description | Default value |
|---|---|---|---|---|
| `list_id` | string | Yes | The `list_id` from the metadata of a `list_item` chunk. | none |

Call `get_list_members` when a search returns one or more `list_item` chunks and you need the whole list. The tool returns the items in list order.

The following example calls the tool:

```python
get_list_members(list_id="{LIST_ID}")
```

### `get_table_members`

The `get_table_members` tool returns all rows of a Markdown table by its `table_id`, ordered by `row_index`. The tool is available only when the index contains `table_row` chunks.

The following table lists the parameter of `get_table_members`:

| Parameter | Type | Required | Description | Default value |
|---|---|---|---|---|
| `table_id` | string | Yes | The `table_id` from the metadata of a `table_row` chunk. | none |

Call `get_table_members` when a search returns one or more `table_row` chunks and you need the whole table. The tool returns the rows in table order.

The following example calls the tool:

```python
get_table_members(table_id="{TABLE_ID}")
```

### `health`

The `health` tool checks whether the MCP server can serve queries. The tool takes no parameters. It returns the same report as the `GET /health` endpoint of the HTTP transport. The report has an overall `status` of `healthy`, `degraded`, or `unhealthy`, and the following checks:

- Embeddings service
- Milvus vector database
- Collection statistics, such as the row count
- A test search for one result, with a timeout
- Free memory
- Load state of the keyword (BM25) search index

For the statuses and an example response, see [Health endpoint](../README.md#health-endpoint).

The following example calls the tool:

```python
health()
```
