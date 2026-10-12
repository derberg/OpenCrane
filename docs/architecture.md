# OpenCrane architecture

OpenCrane is a command-line tool that builds and runs an AI-powered documentation search pipeline. The pipeline does the following:

- Reads documentation from GitHub repositories, local directories, and existing `llms-full.txt` files
- Splits the documentation into typed semantic chunks
- Generates vector embeddings for the chunks
- Stores the embeddings in a vector database
- Serves the indexed chunks through a Model Context Protocol (MCP) server that AI assistants can query

## The typical role of OpenCrane

OpenCrane usually runs as the documentation search service for AI coding assistants. Claude Code, Cursor, and other MCP clients query it for the following content:

- Component specifications
- CustomResourceDefinition (CRD) references
- Operational guides

When an engineer asks the assistant about a documented component, the assistant calls the OpenCrane `search_docs` tool. The tool returns the relevant documentation chunks, and the assistant uses them as context.

OpenCrane is open source (Apache 2.0). It runs as a containerized service, or locally over standard input and output (stdio). It needs no specific platform or infrastructure.

## Pipeline steps

Each pipeline step has its own command-line interface (CLI) subcommand. You can run each step on its own, or run the steps from `fetch` to `index` in sequence with `opencrane build`.

The following diagram shows each step, the command that runs it, and the output it writes:

```text
GitHub repositories
      ↓  add / fetch
.opencrane/sources/
      ↓  llms
.opencrane/llmstxt/  (llms-full.txt bundles + companion llms.txt index)
      ↓  chunk
.opencrane/chunks.json
      ↓  embed
.opencrane/embeddings.json
      ↓  index
.opencrane/milvus.db  (or Milvus Server)
      ↓  serve
MCP server (stdio or HTTP)
```

### Add sources

The `opencrane add` command registers documentation sources in the [source mapping file](source-mapping.md), `.opencrane/config.yaml`. Each source is either a GitHub repository or an existing `llms-full.txt` file. The `opencrane init` command creates a new project and offers the same interactive source addition.

### Fetch

The `opencrane fetch` command downloads the documentation of the registered GitHub repositories into `.opencrane/sources/`. It finds repositories in one of the following ways:

- Auto-discovery: OpenCrane finds the repositories of a GitHub organization that carry the discovery topic. The topic is `documentation` by default, and the `DOCS_TOPIC` environment variable changes it.
- Manual: OpenCrane uses the repositories you listed in the source mapping file.

The fetch never downloads sources marked `local: true`. OpenCrane reads those sources from the project directory. For the details, see [Fetch documentation sources](fetching.md).

> [!CAUTION]
> When auto-discovery no longer returns a repository, `opencrane fetch` removes the entry of that repository from the source mapping file. It also deletes the source directory and the generated `llmstxt/` output of that repository. This happens, for example, when the repository loses the discovery topic. To keep the source, set `manual: true` on its entry before you run the fetch.

### Generate `llms-full.txt` bundles

The `opencrane llms` command combines the Markdown files of each source into `llms-full.txt` bundles under `.opencrane/llmstxt/`. It writes one bundle for each source, and a combined `llms-full.txt` with all sources. Next to the combined bundle, it writes a companion `llms.txt` index that maps the title of each page to its URL. The bundles carry no URLs.

When the source mapping file lists no sources, the command combines the `llms-full.txt` bundles that already exist under `.opencrane/llmstxt/`. [Fence type](../README.md#write-a-custom-fence-type) handlers replace structured content in fenced code blocks, such as OpenAPI specs and CRDs. For the bundle format, see [Generate llms-full.txt bundles](llms-generation.md).

### Chunk

The `opencrane chunk` command splits the combined `llms-full.txt` bundle into typed semantic chunks and writes them to `.opencrane/chunks.json`. The command gives each chunk the `source_url` of its page from the companion `llms.txt` index. It matches pages to index entries by position within each source, and checks each match against the page title. For the details, see [Document boundaries and page URLs](chunking.md#document-boundaries-and-page-urls).

Chunking strategies run in the following order, and the first strategy that matches a fragment handles it:

1. YAML: sends structured YAML specs, such as CRDs and OpenAPI specs, to [tree walkers](../README.md#write-a-custom-yaml-tree-walker), which create one chunk for each field or element. Other YAML becomes a `yaml_content` chunk.
2. Code: handles fenced code blocks and detects the language.
3. Table: creates one `table_row` chunk for each data row.
4. List: creates one `list_item` chunk for each list item, nested items included.
5. Prose: handles all other content. By default, it splits at headings down to `###` and keeps each section whole.

For the chunk types and fields, see the [chunking guide](chunking.md). For the metadata fields, see [Chunk metadata schema](metadata-schema.md).

### Embed

The `opencrane embed` command generates a vector embedding for each chunk and writes the results to `.opencrane/embeddings.json`. It uses the `sentence-transformers` library with the `nomic-ai/nomic-embed-text-v1.5` model by default. To change the model, see [Choose an embedding model](embeddings.md#choose-an-embedding-model).

### Index

The `opencrane index` command loads `.opencrane/embeddings.json` into a Milvus vector database. It creates a collection with the following indexes:

- A vector index on the embeddings, with cosine similarity as the distance metric
- `INVERTED` scalar indexes on the ID columns that the lookup tools query

With the scalar indexes, the member and section lookup tools find chunks without a scan of the whole collection. OpenCrane uses `INVERTED` because Milvus Lite accepts `AUTOINDEX` only on vector fields.

> [!CAUTION]
> In the following cases, `opencrane index` deletes the existing collection and builds it again:
>
> - An older OpenCrane version built the collection, and the collection lacks a scalar ID column that the current version needs.
> - The vector size of the embeddings differs from the vector size of the populated collection.
> - `DROP_EXISTING` is `true`.
>
> Searches fail until the rebuild finishes. Before you run the command, check that `MILVUS_COLLECTION` names the collection to replace.

Milvus runs in one of the following deployment modes:

- Milvus Lite: an embedded, file-based database at `.opencrane/milvus.db`. It is the default and needs no separate service. To store the file somewhere else, set `MILVUS_DB_PATH`.
- Milvus Server: a separate Milvus instance. To connect to it, set `MILVUS_DB_PATH` to an empty value, and set `MILVUS_HOST` and `MILVUS_PORT`.

### Serve

The `opencrane serve` command starts the MCP server on top of the indexed data. The server supports the following transport modes:

- stdio: for local MCP clients such as Claude Code or Cursor
- HTTP: for containerized or remote deployments, and used by the `Dockerfile` and `docker-compose.yml` that `opencrane init` creates

## MCP tools

The server always lists `search_docs` and `health`. It lists the other tools only when the index holds the chunk types they work with. The following table lists each tool and the condition for it:

| Tool | Condition | Description |
|---|---|---|
| `search_docs` | Always present | Searches all indexed chunks. See [Search modes](#search-modes). |
| `get_yaml_definition` | CRD, OpenAPI, or JSON Schema chunks indexed | Returns a complete YAML document by chunk ID, with breadcrumb comments that show its location. |
| `get_metadata_schema` | At least one other conditional tool present | Returns the reference documentation for the chunk metadata fields. |
| `get_list_members` | List item chunks indexed | Returns all items of a list by list ID. |
| `get_table_members` | Table row chunks indexed | Returns all rows of a table by table ID. |
| `get_section` | Prose chunks with navigation metadata indexed | Returns a whole prose section by chunk ID or clause number. |
| `health` | Always present | Reports whether the server can serve queries, with Milvus and collection checks. |

The server reads the indexed chunk types from Milvus on the first request for the tool list. It keeps that answer until the process stops, so restart the server after you run `opencrane index`.

For the tool parameters, see [MCP tools](vector-search.md#mcp-tools). To add your own tools, see [Add custom MCP tools](../README.md#add-custom-mcp-tools).

### Search modes

The **search_mode** parameter of `search_docs` selects one of the following modes:

- `semantic`
- `keyword`
- `hybrid`

The default is `hybrid`, which combines vector similarity with Best Matching 25 (BM25) keyword scoring as follows:

```text
final_score = alpha × vector_score + (1 − alpha) × bm25_score
```

The default **alpha** is `0.6`, which means 60% semantic and 40% keyword. To override it for a single query, pass the **alpha** parameter. To set a different default, use the `HYBRID_ALPHA` environment variable.

By default, each arm of hybrid search returns **limit** results before the fusion. A chunk that both arms rank slightly below **limit** then can't reach the fused list. To fetch more candidates from each arm, set the `HYBRID_CANDIDATE_POOL` environment variable, for example to `50`.

The `HYBRID_FUSION` environment variable selects how hybrid search merges the two arms:

- `minmax`: the default. It normalizes the scores of each arm to the range 0 to 1 and applies the previous formula.
- `rrf`: Reciprocal Rank Fusion (RRF), which blends the ranks of a chunk instead of its scores:

  ```text
  final_score = 2 × alpha / (k + vector_rank) + 2 × (1 − alpha) / (k + bm25_rank)
  ```

  An **alpha** of `0.5` gives classic RRF. The `HYBRID_RRF_K` environment variable sets `k`, and the default is `60`. RRF scores are at most `2 / (k + 1)`, so they order the results but don't measure confidence.

A change to any `HYBRID_*` variable needs a server restart but no re-indexing.

The BM25 index uses the `simple` tokenizer by default. This tokenizer lowercases text and splits it on every non-alphanumeric character, so `5.4.1` and `4.5.1` produce the same tokens. To keep dotted, hyphenated, and underscored identifiers as one token, set the `BM25_TOKENIZER` environment variable to `identifier`. This tokenizer also emits the parts of each identifier, so a query for `gtp` still matches `GTP-U`. A change of tokenizer needs a server restart but no re-indexing.

An optional reranker reorders the results of every search mode. The reranker scores each candidate against the query, and can move up a chunk that search ranks too low. Reranking is off by default and needs no re-indexing.

To turn on the built-in reranker, set the `RERANKER_MODEL` environment variable to a sentence-transformers cross-encoder model, for example `cross-encoder/ms-marco-MiniLM-L-6-v2`. To use your own reranker, see [Custom reranker](#custom-reranker). The Docker image from `opencrane init` runs offline, so set `RERANKER_MODEL` before you build the image. The build then downloads the model into the image.

The server reranks the first `RERANK_DEPTH` candidates, `50` by default, and returns the top **limit** results. A value below **limit** counts as **limit**, and OpenCrane caps the value at `16384`. The built-in reranker runs on the CPU, so a higher `RERANK_DEPTH` makes each search slower. With the built-in reranker, the `Score` line of each result shows the reranker score.

If the reranker fails, the server logs the `Reranker failed, returning unreranked results` warning and returns the results in search order. The health check skips the reranker.

## Internal components

This section describes the main packages in the `opencrane/` source tree.

### Command-line interface

The CLI is in `opencrane/cli.py`. Every subcommand loads the project configuration class from the first of the following sources that is set:

1. The `--config` flag, as `module:Class` or as the path of a Python file
2. The `OPENCRANE_CONFIG` environment variable
3. The file that the `extensions` key in `.opencrane/config.yaml` names, relative to `.opencrane/`
4. The base `OpenCraneConfig` class

From a Python file, the CLI loads the class named `Config`. The `config.yaml` that `opencrane init` creates contains the `extensions` key as a comment.

### Retrieval-augmented generation pipeline

The `opencrane/rag/` package implements the retrieval-augmented generation (RAG) pipeline steps. The following table lists its key modules:

| Module | Responsibility |
|---|---|
| `opencrane/rag/fetch_docs.py` | Fetches GitHub repositories, discovers sources, and removes stale sources. |
| `opencrane/rag/generate_llms_txt.py` | Generates the `llms-full.txt` bundles and the companion `llms.txt` index, runs fence type handlers, and rewrites links. |
| `opencrane/rag/services/llms_index.py` | Parses and renders the `llms.txt` index. |
| `opencrane/rag/chunker.py` | Runs the `chunk` step: loads the bundle, assigns page URLs and source names, adds navigation metadata, and writes `chunks.json`. |
| `opencrane/rag/services/file_processor.py` | Runs the chunking strategies in order. |
| `opencrane/rag/services/chunking_strategies/` | Holds the YAML tree walkers. |
| `opencrane/rag/generate_embeddings.py` | Generates the embeddings in batches. |
| `opencrane/rag/services/source_mapping.py` | Reads and updates the source mapping file. |

### MCP server

The MCP server is in `opencrane/mcp/`. The stdio server loads its backing services on first use, which keeps startup fast. The HTTP server loads them at startup.

The vector database serves `search_docs` in `semantic` mode and the lookup tools. Keyword and hybrid search also use a BM25 index, which the server builds in memory from `chunks.json` on the first keyword or hybrid query. The server rebuilds the BM25 index only when the modification time or size of `chunks.json` changes. The server needs `chunks.json` for keyword and hybrid search.

The following table lists the backing services in `opencrane/mcp/services/`:

| Service | Responsibility |
|---|---|
| `milvus_client.py` | Manages the connection to Milvus, and runs vector searches and scalar lookups. |
| `embeddings.py` | Loads the embedding model and generates embeddings. The `embed` step uses it too. |
| `keyword_search.py` | Builds and queries the BM25 index. |
| `reranker.py` | Runs the optional reranker. |

### Configuration

`OpenCraneConfig` in `opencrane/config.py` is the base class for project configuration. Its attributes and methods are the [extension points](#extension-points). `Config` in `opencrane/shared/config.py` is a different class. It holds the runtime settings that come from environment variables.

## Extension points

You extend OpenCrane with a subclass of `OpenCraneConfig` named `Config` in `.opencrane/extensions.py`. To load the file, set `extensions: extensions.py` in `.opencrane/config.yaml`. The following table lists where each extension point is described:

| Extension point | Reference |
|---|---|
| `fence_types` | [Write a custom fence type](../README.md#write-a-custom-fence-type) |
| `chunking_strategies` | [Add a processing strategy](chunking.md#add-a-processing-strategy) |
| `yaml_tree_walkers` | [Write a custom YAML tree walker](../README.md#write-a-custom-yaml-tree-walker) |
| `section_anchor_for`, `section_clause_for` | [Extension points](../README.md#extension-points) |
| `extra_tools` | [Add custom MCP tools](../README.md#add-custom-mcp-tools) |
| `middleware`, `token_verifier`, `auth_provider` | [Authentication and authorization](auth.md) |
| `reranker` | [Custom reranker](#custom-reranker) |

### Custom reranker

A custom reranker replaces the built-in reranker, for example to call a hosted rerank API or a large language model. Set the `reranker` attribute of your `Config` class to a function or to an object with a `rerank` method. The reranker takes the query and a list of candidates. Each candidate is a dictionary with the following keys:

- `chunk_id`: the chunk ID
- `content`: the chunk text, which is a JSON string for YAML chunks
- `source_file`: the source file path
- `source_name`: the documentation source
- `chunk_type`: the chunk type
- `metadata_json`: the chunk metadata as JSON
- `distance`: the search score, where a higher value is better

Return the candidates best first. You can drop candidates, or set `distance` to your own score. The following example moves candidates that contain the query text to the top:

```python
def my_reranker(query: str, candidates: list[dict]) -> list[dict]:
    return sorted(candidates, key=lambda c: query.lower() in c["content"].lower(), reverse=True)


class Config(OpenCraneConfig):
    reranker = my_reranker
```

## External dependencies

The following table lists the libraries and services that OpenCrane depends on:

| Dependency | Purpose |
|---|---|
| Milvus | Vector database for embedding storage and similarity search |
| sentence-transformers | Embedding model (`nomic-ai/nomic-embed-text-v1.5` by default) and the built-in reranker |
| rank-bm25 | BM25 scoring for keyword search |
| PyGithub | GitHub API client for repository discovery and file download |
| Docling | Document conversion for chunker input other than `.txt` files. The `chunk` step reads `llms-full.txt`, so it does not use Docling. |
| tiktoken | Token counting with the `cl100k_base` encoding |
| Pydantic | Data model validation |
| Click | CLI framework |
| MCP SDK | Model Context Protocol server implementation |
