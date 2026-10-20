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

#### Embedding settings in the image

The image build reads the embedding model from `.opencrane/embeddings.json`, which records the model and the prompts that `opencrane embed` used. The model download and the index use that model, and the index records the model and the prompts. The server then embeds queries with the recorded settings. See [Embedding settings in the index](embeddings.md#embedding-settings-in-the-index). The build fails when `embeddings.json` is missing and you do not set the model.

The build reads the following build arguments. The compose file passes each one only when your shell sets the environment variable of the same name.

| Build argument | Description |
|---|---|
| `EMBEDDING_MODEL` | Must match the model in `embeddings.json`, or the build fails. An empty value counts as not set. |
| `EMBEDDING_QUERY_PROMPT` | Must match the query prompt in `embeddings.json`, or the build fails. When unset, the server uses the query prompt that the index records. An empty value means no prompt. |
| `EMBEDDING_TRUST_REMOTE_CODE` | `true` or `false`. When unset, it is `true` only for `nomic-ai/*` models. The download and the server use the same value. |
| `EMBEDDING_DTYPE`, `EMBEDDING_DEVICE` | Default precision and device of the embedding model in the container. Only the server uses them, so you can set them when you start the container instead. See [Model loading settings](embeddings.md#model-loading-settings). |
| `RERANKER_MODEL` | Optional reranker model that the build downloads into the image. |
| `RERANKER_TRUST_REMOTE_CODE` | The same as `EMBEDDING_TRUST_REMOTE_CODE`, for the reranker model. |

The build writes these settings to `/app/image.env`, and the entrypoint loads them before it starts the server. A variable that you set when you start the container, for example with `docker run -e`, overrides the value from the build.

To load the embedding model in `bfloat16`, set `EMBEDDING_DTYPE` when you start the container. Run the following command:

```bash
docker run -e EMBEDDING_DTYPE=bfloat16 -p 8000:8000 {REGISTRY}/{IMAGE_NAME}:latest
```

With compose, set `EMBEDDING_DTYPE` or `EMBEDDING_DEVICE` in your shell before `docker compose up --build`. The compose file passes them as build arguments, which set the default value in the image.

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

List items of one list, and table rows of one table, appear as one result. A grouped result shows the same `Source` and `Source Name` fields as other results, followed by the location, the list or table ID, and the matched items.

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

The `get_list_members` tool returns all items of a Markdown list in list order. Call it when a search returns `list_item` chunks and you need the whole list. The output starts with the `Source` and `Source Name` of the list, like a search result. The tool is available only when the index contains `list_item` chunks.

The following table lists the parameter of `get_list_members`:

| Parameter | Type | Required | Description | Default value |
|---|---|---|---|---|
| **list_id** | string | Yes | The `list_id` from the metadata of a `list_item` chunk. | none |

The following example calls the tool:

```python
get_list_members(list_id="{LIST_ID}")
```

### `get_table_members`

The `get_table_members` tool returns all rows of a Markdown table, ordered by `row_index`. Call it when a search returns `table_row` chunks and you need the whole table. The output starts with the `Source` and `Source Name` of the table, like a search result. The tool is available only when the index contains `table_row` chunks.

The following table lists the parameter of `get_table_members`:

| Parameter | Type | Required | Description | Default value |
|---|---|---|---|---|
| **table_id** | string | Yes | The `table_id` from the metadata of a `table_row` chunk. | none |

The following example calls the tool:

```python
get_table_members(table_id="{TABLE_ID}")
```

### `get_section`

The `get_section` tool returns a whole section, for example when a search result is cut off. The section text includes the lists and tables of the section, in the order of the page. The tool is available only when the prose chunks have [navigation metadata](../opencrane/mcp/metadata-schema.md#prose-navigation-metadata).

The following table lists the parameters of `get_section`. Pass **chunk_id** or **clause_id**:

| Parameter | Type | Required | Description | Default value |
|---|---|---|---|---|
| **chunk_id** | string | No | The chunk ID of a search result. For a `list_item` or `table_row` result, the tool returns the section that the list or table sits in. It overrides **clause_id**. | none |
| **clause_id** | string | No | The clause number from the section heading, for example `5.4.1.2a` or `Annex C`. | none |
| **source** | string | No | Limits a **clause_id** lookup to pages whose source name, page URL, or page title contains this text. The match ignores case. | none |
| **include_subsections** | boolean | No | Returns the full text of the sub-sections, with their lists and tables, instead of a list of the direct sub-sections. The tool shows up to 50 chunks of sub-sections, and each list item and table row counts as one chunk. | `false` |
| **neighbors** | integer | No | The number of sections on the same page, from `0` to `5`, to add before and after the section. | `0` |

The following example opens a clause:

```python
get_section(clause_id="5.4.1.2a", source="{SOURCE_NAME}")
```

The tool shows a list as its items and a table as its rows, each under a header with its heading path. The following example shows a list in a section:

```text
To upgrade the gateway, follow these steps:

List (3 of 3 items, style=ordered)
Location: Gateway operations > Upgrade the gateway
[1] 1. Back up the gateway configuration.
[2] 2. Install the gateway Helm chart in version 1.7.0.
[3] 3. Check that every gateway pod reports `Ready`.
```

The tool shows up to 50 items of a list and 50 rows of a table. For a longer list or table, the last line names the call that returns all of it, for example `get_table_members(table_id="{TABLE_ID}")`.

The chunker records where each list and table sits on the page, in the `parent_chunk_id` and `doc_order` fields. A heading followed only by a list has no prose chunk of its own, so its list belongs to the enclosing section. With **include_subsections**, the tool shows that list with the sub-sections, where it sits on the page. An index made before OpenCrane recorded these fields returns sections without their lists and tables. To add the fields, run `opencrane chunk`, `opencrane embed`, and `opencrane index` again.

### `health`

The `health` tool takes no parameters. It returns the same JSON report as the `GET /health` endpoint of the HTTP transport. For the details and an example response, see [Health endpoint](../README.md#health-endpoint).
