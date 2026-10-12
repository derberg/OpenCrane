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
- Custom Resource Definition (CRD) references
- Operational guides

When an engineer asks the assistant a question about a documented component, the assistant calls the OpenCrane `search_docs` tool. The tool returns the relevant documentation chunks, and the assistant uses them as context.

OpenCrane is open source (Apache 2.0). It runs as a containerized service, or locally over standard input and output (stdio), and it needs no specific platform or infrastructure.

## Pipeline steps

OpenCrane organizes work into steps, and each step has its own command-line interface (CLI) subcommand. You can run each step on its own, or run the steps from `fetch` to `index` in sequence with `opencrane build`.

The following diagram shows each step, the command that runs it, and the output it writes:

```text
GitHub repositories
      ↓  add / fetch
.opencrane/sources/
      ↓  llms
.opencrane/llmstxt/  (hierarchical llms-full.txt bundles + companion llms.txt index)
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

The `opencrane add` command registers documentation sources in the [source mapping file](source-mapping.md), `.opencrane/config.yaml`. Each source is either a GitHub repository or an existing `llms-full.txt` file. You can also run `opencrane init` to create a new project and add sources interactively in one step.

### Fetch

The `opencrane fetch` command downloads the documentation files of registered GitHub repositories into `.opencrane/sources/`. It supports the following discovery modes:

- Auto-discovery: OpenCrane finds all repositories in a GitHub organization that carry the discovery topic. The topic is `documentation` by default, and the `DOCS_TOPIC` environment variable changes it.
- Manual: OpenCrane uses the list of repositories you defined in the source mapping file.

The command fetches repositories concurrently. OpenCrane never fetches sources marked `local: true`, and reads them from the local file system as they are.

A stale source is an auto-discovered repository (`manual: false`) that auto-discovery no longer returns. The fetch removes stale sources automatically. For the causes, see [How the fetch removes stale sources](fetching.md#how-the-fetch-removes-stale-sources).

> [!CAUTION]
> When auto-discovery no longer returns a repository (it lost the discovery topic, its topics could not be read, or the token cannot see it), `opencrane fetch` removes its entry from the source mapping file. It also deletes its source directory and its generated `llmstxt/` output. To keep the source, set `manual: true` on its entry before you run the fetch.

### Generate `llms-full.txt` bundles

The `opencrane llms` command combines the fetched Markdown files into `llms-full.txt` bundles under `.opencrane/llmstxt/`. It writes the following bundles:

- A top-level bundle that combines all sources
- One bundle for each path in the source mapping file

When the source mapping file lists no sources, the command only combines the `llms-full.txt` bundles that already exist under `.opencrane/llmstxt/`. With `--sources-dir`, it instead writes a bundle for each directory under the directory you pass, and for each directory one level below that.

For each bundle, the command does the following:

- Processes Markdown files recursively.
- Produces clean content, with no URLs added to headings.
- Adds separators: a `<!-- opencrane:page -->` marker between files within a source, and `======` between sources.
- Adds a `# {title}` heading at the start of each page, unless the page already starts with exactly that heading. OpenCrane takes the title from the front matter `title`. If that is missing, it uses the first heading, and then the file name. An existing H1 with different text stays under the new heading, so the page then has two H1 headings.
- Replaces relative links to Markdown files and anchors with their link text.
- Runs [fence type](#custom-fence-types) handlers for structured content embedded as fenced code blocks, such as OpenAPI specs and Kubernetes CRDs.
- Writes a companion `llms.txt` index next to the combined `llms-full.txt`.

The page separator is an HTML comment, so the chunker does not treat Markdown thematic breaks (`---`) in the content as page boundaries.

The companion `llms.txt` index has the following parts:

- A `# {project}` H1
- One `## {source}` section for each source
- A `- [title](page_url)` link for each page

The sections and links follow the page order of the bundle.

The `chunk` step uses the companion `llms.txt` index to find the page `source_url` of each chunk. For an external `llmstxt` source, `opencrane fetch` can download a companion `llms.txt`. The `llms` command copies its page URLs into the index it writes. When no companion exists, the `llms` command builds an index from the `docs_url` of the source.

### Chunk

The `opencrane chunk` command splits the combined `.opencrane/llmstxt/llms-full.txt` bundle into typed semantic chunks and writes them to `.opencrane/chunks.json`. It reads the companion `llms.txt` index next to the bundle and gives each chunk the `source_url` of its own page. To do this, it matches the pages in the bundle to the index entries by position within each source. It then checks each match against the H1 title of the page. When no companion index is present, the command reads page URL markers inside the bundle instead. A bundle that an older OpenCrane version built is an example of this case.

Chunking strategies run in priority order. The first strategy that matches a document fragment handles it. The following table lists the strategies in that order:

| Order | Strategy | Behavior |
|---|---|---|
| 1 | YAML | Handles YAML content. Passes structured specs (CRDs, OpenAPI, JSON Schema) to [tree walkers](#custom-yaml-tree-walkers), which split a spec into one chunk for each field or element. Falls back to a generic `yaml_content` chunk for unrecognized YAML. |
| 2 | Code | Handles fenced code blocks. Detects the language, and runs tree walkers for structured YAML specs inside code fences. |
| 3 | Table | Handles Markdown tables. Produces one `table_row` chunk for each data row, written as natural-language `Column: value.` lines. Links each row to the rest of the table through `table_id` and `sibling_ids`. Passes text outside the table to the list and prose strategies. |
| 4 | List | Handles Markdown lists. Produces one chunk for each top-level list item, and attaches sibling previews and breadcrumb paths. |
| 5 | Prose | Handles every fragment the other strategies do not match. Splits at heading boundaries (`#`, `##`, `###`) and keeps each section whole. It does not split a section by token count. |

Each chunk carries type-specific metadata fields and a `chunk_type` field. The `chunk_type` field takes one of the following values:

- `prose`
- `code_snippet`
- `crd_definition`
- `openapi_spec`
- `json_schema`
- `yaml_content`
- `list_item`
- `table_row`

For the full field reference, see [Chunk metadata schema](metadata-schema.md).

### Embed

The `opencrane embed` command generates a vector embedding for each chunk in `.opencrane/chunks.json` and writes the results to `.opencrane/embeddings.json`. It uses the `sentence-transformers` library with `nomic-ai/nomic-embed-text-v1.5` as the default model. To change the model, set the `EMBEDDING_MODEL` environment variable. The Milvus collection stores 768-dimension vectors, so the model must produce vectors of that size. The command processes chunks in batches to limit memory use.

### Index

The `opencrane index` command loads `.opencrane/embeddings.json` into a Milvus vector database. It creates a collection with the following indexes:

- A vector index on the embeddings, with cosine similarity as the distance metric
- `INVERTED` scalar indexes on the `list_id` and `table_id` columns

With the scalar indexes, the `get_list_members` and `get_table_members` MCP tools run an indexed lookup instead of scanning all chunks in memory. OpenCrane uses `INVERTED` rather than `AUTOINDEX` because Milvus Lite accepts `AUTOINDEX` only on vector fields.

> [!NOTE]
> OpenCrane stores `list_id` and `table_id` in their own columns. If an older OpenCrane version built the collection without these columns, the next `index` run drops the collection and rebuilds it. This happens once after the upgrade, and the logs report it.

Milvus runs in one of the following deployment modes:

- Milvus Lite: an embedded, file-based database stored at `.opencrane/milvus.db`. It needs no separate service, and it is the default mode. To store the file somewhere else, set `MILVUS_DB_PATH`.
- Milvus Server: a separate Milvus instance. To connect to it, set `MILVUS_DB_PATH` to an empty value, and set `MILVUS_HOST` and `MILVUS_PORT`.

### Serve

The `opencrane serve` command starts the MCP server on top of the indexed data. The server supports the following transport modes:

- stdio: for local MCP clients such as Claude Code or Cursor.
- HTTP: for containerized or remote deployments. The `Dockerfile` and `docker-compose.yml` that `opencrane init` creates use this mode.

## MCP tools

The tools the server exposes depend on the content of the index. `search_docs` and `health` are always present. The other tools appear only when the index contains the chunk types they work with, as the following table shows:

| Tool | Condition | Description |
|---|---|---|
| `search_docs` | Always present | Searches all indexed chunks in semantic, keyword, or hybrid mode. |
| `get_yaml_definition` | YAML chunks indexed | Returns a complete YAML document by chunk ID, with breadcrumb comments that show its location. |
| `get_metadata_schema` | YAML, list, or table row chunks indexed | Returns the reference documentation for all chunk metadata fields. |
| `get_list_members` | List chunks indexed | Returns all items in a list by list ID. |
| `get_table_members` | Table row chunks indexed | Returns all rows of a table by table ID. |
| `health` | Always present | Reports the service status, the Milvus connection state, and collection statistics. |

### Search modes

`search_docs` supports the following search modes, which you select with the **search_mode** parameter:

- `semantic`
- `keyword`
- `hybrid`

The default is `hybrid`, which combines vector similarity with Best Matching 25 (BM25) keyword scoring as follows:

```text
final_score = alpha × vector_score + (1 − alpha) × bm25_score
```

The default **alpha** is `0.6`, which means 60% semantic and 40% keyword. To override it for a single query, pass the **alpha** parameter. To set a different default, use the `HYBRID_ALPHA` environment variable.

To narrow the results, pass the following `search_docs` parameters:

- **chunk_types**: limits the results to the given chunk types
- **source_names**: limits the results to the given documentation sources
- **metadata_contains**: limits the results to chunks whose metadata contains all the given strings

## Internal components

This section describes the main packages in the `opencrane/` source tree and what each one does.

### Command-line interface

The CLI is in `opencrane/cli.py`. All subcommands resolve their configuration in the following order:

1. Explicit `--config` flag
2. `OPENCRANE_CONFIG` environment variable
3. The file that the `extensions` key in `.opencrane/config.yaml` names, relative to `.opencrane/`
4. Base `OpenCraneConfig` defaults

When `.opencrane/config.yaml` has an `extensions` key, for example `extensions: extensions.py`, the CLI loads the `OpenCraneConfig` subclass named `Config` from that file. The `config.yaml` that `opencrane init` creates contains this key as a comment. This subclass is the primary extension mechanism. Without modifying the OpenCrane core, a subclass of `OpenCraneConfig` can override the following:

- Fence types
- Chunking strategies
- YAML tree walkers

### Retrieval-augmented generation pipeline

The `opencrane/rag/` package implements all retrieval-augmented generation (RAG) pipeline steps. The following table lists its key modules:

| Module | Responsibility |
|---|---|
| `opencrane/rag/fetch_docs.py` | Fetches GitHub repositories, discovers sources, and cleans up stale sources. |
| `opencrane/rag/generate_llms_txt.py` | Generates `llms-full.txt` bundles, writes the companion `llms.txt` index, dispatches fence types, and rewrites links. |
| `opencrane/rag/services/llms_index.py` | Parses and renders the `llms.txt` index (`LlmsIndex`, `render_llms_txt`) that the `chunk` step uses to match content to page URLs. |
| `opencrane/rag/chunker.py` | Runs the `chunk` step: loads bundles, resolves source names, and writes `chunks.json`. |
| `opencrane/rag/services/file_processor.py` | Runs the chunking strategies in order, and the first match handles the fragment. |
| `opencrane/rag/generate_embeddings.py` | Generates embeddings in batches. |
| `opencrane/rag/services/source_mapping.py` | Reads the source mapping file and resolves source URLs to source names. |

Tree walkers are in `opencrane/rag/services/chunking_strategies/` and split structured YAML documents into chunks. The following table lists them:

| Tree walker | Behavior |
|---|---|
| `k8s_crd_tree_walker.py` | Chunks Kubernetes CRDs. Produces one chunk for each `spec.properties` field, and recursively splits nested properties that exceed 800 tokens. |
| `openapi_tree_walker.py` | Chunks OpenAPI 3.x specs. Produces one chunk for `info`, one for each server, one for each operation (path and method), and one for each item under `components`. `security` and `tags` get a chunk each. A schema over 800 tokens splits into chunks for its properties. |
| `json_schema_tree_walker.py` | Chunks JSON Schema documents. Produces one chunk for each property, and splits a property that exceeds 800 tokens into chunks for its nested properties. |

### MCP server

The MCP server is in `opencrane/mcp/`. With the stdio transport, the server starts its backing services on the first tool call, so startup is fast. With the HTTP transport, the server starts its backing services at server startup.

The following tools read from the vector database and do not keep an in-memory copy of the chunks:

- `get_yaml_definition` fetches a single chunk by its primary key.
- `get_list_members` and `get_table_members` query the indexed `list_id` and `table_id` columns for the members of a list or table. The query reads only chunks of the matching `chunk_type`.
- In `semantic` mode, `search_docs` reads `token_count` and the `source_url` of each chunk directly from the query result.

Keyword and hybrid search are the exception. They use a BM25 index that OpenCrane builds from `chunks.json` and holds in memory.

On the first request for the tool list, the server queries Milvus for the `chunk_type` values that the collection contains. It caches the answer for the life of the process. The query reads only the `chunk_type` field through `query_iterator`, not the chunk content. The tool list then matches the content that was indexed when the server first listed its tools. Restart the server after you run `opencrane index`.

The following table lists the backing services:

| Service | Responsibility |
|---|---|
| `opencrane/mcp/services/milvus_client.py` | Manages the connection to Milvus and runs the vector searches. |
| `opencrane/mcp/services/keyword_search.py` | Builds the BM25 index from `chunks.json` when the first keyword or hybrid query arrives. The server needs `chunks.json` for keyword and hybrid search. |

### Configuration

The configuration is in `opencrane/config.py` and `opencrane/shared/config.py`. `OpenCraneConfig` is the base class for all project-level configuration. The following table lists the attributes that act as its pipeline extension points:

| Attribute | Description |
|---|---|
| `fence_types` | A dictionary of fence type handlers. The defaults include OpenAPI, AsyncAPI, CRD, and JSON Schema. |
| `chunking_strategies` | An ordered list of chunking strategy instances. OpenCrane evaluates them in order, and the first match handles the fragment. |
| `yaml_tree_walkers` | A list of tree walker classes. OpenCrane evaluates them in the order listed. |

`Config` in `opencrane/shared/config.py` is the runtime configuration that comes from the environment. It reads all settings from environment variables when the process starts. This runtime `Config` is a different class from the `Config` subclass in `.opencrane/extensions.py`.

## Extension points

You extend OpenCrane with a subclass of `OpenCraneConfig` named `Config` in `.opencrane/extensions.py`. To load the file, set `extensions: extensions.py` in `.opencrane/config.yaml`. This section covers the extension points of the pipeline. For the authentication hooks, see [Authentication and authorization](auth.md).

### Custom fence types

A fence type handles structured content embedded as fenced code blocks during the `llms` step. To add a fence type, add an entry to `fence_types` with a `CodeFenceConfig` that names the fence and provides a handler function:

```python
class Config(OpenCraneConfig):
    fence_types = {
        **OpenCraneConfig.fence_types,
        "terraform": CodeFenceConfig(fence_type="terraform", handler=my_handler),
    }
```

The handler has the following signature:

```python
def my_handler(
    content: str,
    file_path: Path,
    project_dir: Path,
    project_name: str,
) -> str: ...
```

The handler receives the text inside the fence. OpenCrane replaces the whole fenced block, fences included, with the string that the handler returns.

### Custom chunking strategies

To add a chunking strategy, insert it into the `chunking_strategies` list at the priority position you want. The first strategy that matches a fragment handles it, so place more specific strategies before more general ones. The following example places a custom strategy immediately after the YAML strategy:

```python
class Config(OpenCraneConfig):
    chunking_strategies = [
        YamlChunkingStrategy(),
        MyCustomStrategy(),   # runs before Code, Table, List, and Prose
        CodeChunkingStrategy(),
        TableChunkingStrategy(),
        ListChunkingStrategy(),
        ProseChunkingStrategy(),
    ]
```

### Custom YAML tree walkers

A tree walker splits one kind of structured YAML document into chunks. To add a tree walker, append it to `yaml_tree_walkers`. Each walker must implement the following methods:

- `can_handle(cls, doc: dict) -> bool`: returns `True` if this walker handles the given YAML document
- `walk(self) -> list[Chunk]`: returns typed `Chunk` objects for the document

The following example shows a tree walker for YAML documents that contain a `terraform` key:

```python
class TerraformTreeWalker(YamlTreeWalker):
    @classmethod
    def can_handle(cls, doc: dict) -> bool:
        return "terraform" in doc

    def walk(self) -> list[Chunk]:
        ...
```

## Data model

The `Chunk` model in `opencrane/shared/models/chunk.py` is the core data structure of the pipeline. The following table lists its fields:

| Field | Type | Description |
|---|---|---|
| `chunk_id` | `str` | Deterministic 64-character hexadecimal ID, hashed from the chunk content, source file, chunk type, and metadata. Stable across pipeline runs. |
| `content` | `str` or `dict` or `list` | A string for prose and code, and a dictionary or list for YAML. |
| `source_file` | `str` | Relative path from the project root. |
| `source_name` | `str` or `None` | Resolved from the `source_url` metadata field. `None` if no source mapping entry matches. |
| `chunk_type` | `str` | One of the chunk type values listed in the [Chunk](#chunk) section. |
| `metadata` | `dict` | Type-specific metadata fields. |
| `token_count` | `int` | Token count using the `cl100k_base` encoding. |
| `line_start` | `int` or `None` | Reserved for line-level source tracking. Currently always `None`. |

`VectorChunk` extends `Chunk` with an `embedding` field, which is a list of floats. Only the `embed` and `index` steps use it.

## External dependencies

The following table lists the libraries and services that OpenCrane depends on:

| Dependency | Purpose |
|---|---|
| Milvus | Vector database for embedding storage and similarity search |
| sentence-transformers | Embedding model (`nomic-ai/nomic-embed-text-v1.5` by default) |
| rank-bm25 | BM25 scoring for keyword search |
| PyGithub | GitHub API client for repository discovery and file download |
| Docling | Document parsing for PDF, DOCX, and other non-Markdown formats |
| tiktoken | Token counting using the `cl100k_base` encoding |
| Pydantic | Data model validation |
| Click | CLI framework |
| MCP SDK | Model Context Protocol server implementation |
