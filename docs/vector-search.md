# Vector search and the MCP server

OpenCrane serves the indexed documentation through a Model Context Protocol (MCP) server. The server uses Milvus Lite, an embedded vector database, so it runs as one process or one container and needs no external services.

## Search capabilities

The following table lists the search modes and filters of the MCP server:

| Capability | Description |
|---|---|
| Semantic search | Cosine similarity between the query and the chunk embeddings. The server embeds the query with the model and query prompt that the index records. See [Embedding settings in the index](embeddings.md#embedding-settings-in-the-index). |
| Keyword search | Best Matching 25 (BM25) ranking over the chunks file. To keep identifiers such as `5.4.1` or `GTP-U` as one token, set `BM25_TOKENIZER` to `identifier`. |
| Hybrid search | The default mode. It merges the semantic and keyword results, weighted by **alpha**. `HYBRID_FUSION` selects a merge of normalized scores (`minmax`, the default) or of ranks (`rrf`). |
| Reranking | Optional. A cross-encoder model from `RERANKER_MODEL`, or your own reranker, reorders the results of every mode. `RERANKER_TRUST_REMOTE_CODE` allows a cross-encoder that ships its own code. See [Search modes](architecture.md#search-modes). |
| Filters | Chunk type, source name, and metadata content |

For the scoring formulas and the tuning variables, see [Search modes](architecture.md#search-modes).

## Start the MCP server

You can start the MCP server in one of the following ways:

- Locally, without a container
- In Docker or Podman, from the files that `opencrane init` generates
- From a prebuilt image

### Run locally without a container

By default, `opencrane serve` uses the standard input/output (stdio) transport. The following commands build the pipeline and start the server:

```bash
opencrane build

# Prints the setup instructions for common MCP clients, then starts the server
opencrane serve
```

> [!CAUTION]
> The HTTP transport has no authentication by default and listens on all network interfaces. Anyone who can reach the port can search every source. To accept connections from this machine only, set `MCP_HTTP_HOST=127.0.0.1`. To restrict access, see [Authentication and authorization](auth.md).

To serve over HTTP on port 8000 instead, run `opencrane serve --transport http`. To use another port, set `MCP_HTTP_PORT`.

To call the tools from the MCP Inspector web interface, run the following command:

```bash
opencrane inspect
```

### Run in Docker or Podman

In a container, the server uses the HTTP transport on port 8000. `opencrane init` generates `.opencrane/Dockerfile` and `.opencrane/docker-compose.yml`. The image build indexes the chunks and embeddings from `.opencrane/`, so run `opencrane build` first.

> [!CAUTION]
> The HTTP transport has no authentication by default. Anyone who can reach port 8000 can search every source. To accept connections from this machine only, change the port mapping in `.opencrane/docker-compose.yml` to `127.0.0.1:8000:8000`. To restrict access, see [Authentication and authorization](auth.md).

To build the image and start the server, run the following command from the project root:

```bash
docker-compose -f .opencrane/docker-compose.yml up --build
```

The MCP endpoint is `http://localhost:8000/mcp`.

To use Podman, run the same files with `podman-compose`:

```bash
podman-compose -f .opencrane/docker-compose.yml up --build
```

### Run a prebuilt image

> [!CAUTION]
> The HTTP transport has no authentication by default. Anyone who can reach port 8000 can search every source. To accept connections from this machine only, publish the port as `-p 127.0.0.1:8000:8000`. To restrict access, see [Authentication and authorization](auth.md).

To start an image built from `.opencrane/Dockerfile` and pushed to a registry, run the following command:

```bash
docker run -p 8000:8000 {REGISTRY}/{IMAGE_NAME}:latest
```

## Share the server as a `uvx` package

To package the built server with its Milvus database and chunks file, run the following command:

```bash
opencrane pack --name {PACKAGE_NAME}
```

The people you share the package with run it through `uvx` and do not rebuild anything. For the options and the commands that add the package to an MCP client, see [Package the server with `opencrane pack`](../README.md#package-the-server-with-opencrane-pack).

## MCP tools

The server always provides `search_docs` and `health`. It provides each other tool only when the index contains the chunks that the tool reads. Every tool that returns chunks applies the source policy of the endpoint. For an ID from a source that the caller cannot read, the tool returns the same answer as for an ID that does not exist. See [Authentication and authorization](auth.md). The following sections describe the tools.

### `search_docs`

The `search_docs` tool searches the indexed documentation. Its description names the topics of the configured sources. The **chunk_types** and **source_names** parameters accept only the values that exist in the index and the configuration.

The server also checks these two parameters, because a client can ignore the tool schema. Each must be a list of strings. A **chunk_types** value can contain only letters, digits, `_`, and `-`. A **source_names** value cannot be empty or contain a double quote, a backslash, or a control character. If a value breaks these rules, `search_docs` returns an error and does not search. Authorization still removes a valid source name that the caller cannot read, so that source returns no results.

The following table lists the parameters of `search_docs`:

| Parameter | Type | Required | Description | Default value |
|---|---|---|---|---|
| **query** | string | Yes | The search query. | none |
| **limit** | integer | No | The maximum number of results, from `1` to `50`. | `5` |
| **search_mode** | string | No | `semantic`, `keyword`, or `hybrid`. | `hybrid` |
| **alpha** | number | No | The weight of the semantic results in hybrid mode, from `0` to `1`. The keyword results get `1 - alpha`. With `HYBRID_FUSION=rrf`, it weights ranks instead of scores. | The value of `HYBRID_ALPHA`, by default `0.6` |
| **chunk_types** | array of strings | No | The content types to return, for example `prose` or `code_snippet`. The tool schema lists only the types in the index, custom chunk types included. See [Chunk types](chunking.md#chunk-types). | none |
| **metadata_contains** | array of strings | No | Strings that the chunk metadata must all contain. | none |
| **source_names** | array of strings | No | The sources to search, as keys of the `sources:` block in `.opencrane/config.yaml`, for example `MicrosoftDocs/microsoft-style-guide`. A chunk matches if it comes from any of them. The tool schema has this parameter only when sources are configured. Authorization can narrow the results further. See [Authentication and authorization](auth.md). | none |

The following example runs a hybrid search with a higher semantic weight, limited to two content types and one source:

```python
search_docs(
    query="authentication methods",
    search_mode="hybrid",
    alpha=0.7,
    chunk_types=["prose", "code_snippet"],
    source_names=["MicrosoftDocs/microsoft-style-guide"],
    limit=10,
)
```

Each result contains the following fields:

- `Source`: the page URL
- `Source Name`: the configured source
- `Type`: the chunk type
- `Chunk ID`: the ID that the other tools take
- `Token Count`: the size of the chunk
- `Metadata`: the location and the section anchor of the chunk. CRD, OpenAPI, and JSON Schema results have no `Metadata` block. A chunk from a custom tree walker also shows its parent path and its number of siblings, when the walker records them.
- `Content`: the chunk text, cut at 1,000 characters, with a tip that names the tool that returns the full text
- `Score`: the score that orders the results. Its scale depends on the search mode and the reranker.

List items of one list, and table rows of one table, appear as one result.

### `get_yaml_definition`

The `get_yaml_definition` tool returns a CustomResourceDefinition (CRD), OpenAPI, or JSON Schema chunk as YAML. The tool is available only when the index contains CRD, OpenAPI, or JSON Schema chunks. Comment lines in the output show the following:

- Location of the chunk in the YAML tree, and its parent path
- Documentation URL
- Schema kind and version, or the API endpoint
- Up to five sibling chunk IDs

The following table lists the parameter of `get_yaml_definition`:

| Parameter | Type | Required | Description | Default value |
|---|---|---|---|---|
| **chunk_id** | string | Yes | The chunk ID from the search results. | none |

The following example calls the tool:

```python
get_yaml_definition(chunk_id="{CHUNK_ID}")
```

### `get_metadata_schema`

The `get_metadata_schema` tool returns [Chunk metadata schema](../opencrane/mcp/metadata-schema.md), the reference of the chunk metadata fields. The tool is available only when at least one other conditional tool is available. See [MCP tools](architecture.md#mcp-tools).

The following table lists the parameter of `get_metadata_schema`:

| Parameter | Type | Required | Description | Default value |
|---|---|---|---|---|
| **chunk_type** | string | No | Returns only the universal fields and the fields of this chunk type, for example `list_item`. For a custom chunk type, returns the universal fields. | none, which returns the full reference |

The following example calls the tool for the full reference and for one chunk type:

```python
get_metadata_schema()
get_metadata_schema(chunk_type="list_item")
```

### `get_list_members`

The `get_list_members` tool returns all items of a Markdown list in list order. Call it when a search returns `list_item` chunks and you need the whole list. The tool is available only when the index contains `list_item` chunks.

The following table lists the parameter of `get_list_members`:

| Parameter | Type | Required | Description | Default value |
|---|---|---|---|---|
| **list_id** | string | Yes | The `list_id` from the metadata of a `list_item` chunk. | none |

The following example calls the tool:

```python
get_list_members(list_id="{LIST_ID}")
```

### `get_table_members`

The `get_table_members` tool returns all rows of a Markdown table, ordered by `row_index`. Call it when a search returns `table_row` chunks and you need the whole table. The tool is available only when the index contains `table_row` chunks.

The following table lists the parameter of `get_table_members`:

| Parameter | Type | Required | Description | Default value |
|---|---|---|---|---|
| **table_id** | string | Yes | The `table_id` from the metadata of a `table_row` chunk. | none |

The following example calls the tool:

```python
get_table_members(table_id="{TABLE_ID}")
```

### `get_section`

The `get_section` tool returns a whole prose section, for example when a search result is cut off. The tool is available only when the prose chunks have [navigation metadata](../opencrane/mcp/metadata-schema.md#prose-navigation-metadata).

The following table lists the parameters of `get_section`. Pass **chunk_id** or **clause_id**:

| Parameter | Type | Required | Description | Default value |
|---|---|---|---|---|
| **chunk_id** | string | No | The chunk ID of a prose search result. It overrides **clause_id**. | none |
| **clause_id** | string | No | The clause number from the section heading, for example `5.4.1.2a` or `Annex C`. | none |
| **source** | string | No | Limits a **clause_id** lookup to pages whose source name, page URL, or page title contains this text. The match ignores case. | none |
| **include_subsections** | boolean | No | Returns the full text of up to 50 sub-section chunks instead of a list of the direct sub-sections. | `false` |
| **neighbors** | integer | No | The number of sections on the same page, from `0` to `5`, to add before and after the section. | `0` |

The following example opens a clause:

```python
get_section(clause_id="5.4.1.2a", source="{SOURCE_NAME}")
```

### `health`

The `health` tool takes no parameters. It returns the same JSON report as the `GET /health` endpoint of the HTTP transport. For the details and an example response, see [Health endpoint](../README.md#health-endpoint).
