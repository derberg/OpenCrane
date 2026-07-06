# OpenCrane architecture

OpenCrane is a command-line tool that builds and runs an AI-powered documentation search pipeline. It ingests Markdown documentation from GitHub repositories, processes it into typed semantic chunks, generates vector embeddings, stores them in a vector database, and exposes a Model Context Protocol (MCP) server that AI assistants can query.

## Typical role

OpenCrane is typically deployed as the documentation search service that AI coding assistants (Claude Code, Cursor, and other MCP clients) query for component specifications, Custom Resource Definition (CRD) references, and operational guides. When an engineer asks the assistant a question about a documented component, the assistant calls OpenCrane's `search_docs` tool to retrieve the relevant documentation chunks and return them as context.

The tool is open-source (Apache 2.0) and platform-agnostic. It can run as a containerized service or locally via stdio, and has no dependency on any specific platform or infrastructure.

## Pipeline overview

OpenCrane organizes work into six stages. You can run each stage independently via its CLI subcommand, or run all stages in sequence with `opencrane build`.

```
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
MCP server — stdio or HTTP
```

### Add sources

The `opencrane add` command registers documentation sources in `.opencrane/config.yaml`. Each source is either a GitHub repository or a pre-existing `llms-full.txt` file. You can also run `opencrane init` to scaffold a new project and add sources interactively in one step.

### Fetch

The `opencrane fetch` command clones registered GitHub repositories into `.opencrane/sources/`. It supports two discovery modes:

- **Auto-discovery:** Finds all repositories in a GitHub organization that carry the `documentation` topic.
- **Manual:** Uses the list of repositories you defined in `.opencrane/config.yaml`.

The command fetches repositories concurrently. It auto-removes stale sources (repositories that lost the `documentation` topic) unless you mark the source `manual: true` in the configuration. Sources marked `local: true` are never fetched — OpenCrane uses them as-is from the local file system.

### Generate `llms-full.txt` bundles

The `opencrane llms` command flattens the cloned Markdown files into a hierarchy of `llms-full.txt` bundles under `.opencrane/llmstxt/`: a top-level combined bundle, plus per-source, per-project, and per-subproject bundles. For each bundle it:

- Processes Markdown files recursively.
- Emits **clean** content — no URLs are injected into headings.
- Adds separators (a `<!-- opencrane:page -->` sentinel between files within a source, `======` between sources) and normalizes each page to lead with a single `# {title}` H1 (title precedence: frontmatter `title` → first heading → filename). The page separator is a collision-proof HTML comment so markdown thematic breaks (`---`) in content are not mistaken for page boundaries.
- Rewrites relative links to work in the flattened output.
- Invokes fence type handlers for structured content such as OpenAPI specs and Kubernetes CRDs embedded as fenced code blocks.
- Writes a companion `llms.txt` index next to each `llms-full.txt`: a `# {project}` H1 with one `## {source}` section per source and a `- [title](page_url)` link per page, in the same order as the bundle. This index is how the `chunk` step recovers each chunk's specific page `source_url`. For external `llmstxt` sources, a fetched companion `llms.txt` (real per-page URLs) is merged, or an index is synthesized from the source's `docs_url` when no companion exists.

### Chunk

The `opencrane chunk` command splits each `llms-full.txt` bundle into typed semantic chunks and writes them to `.opencrane/chunks.json`. It reads the companion `llms.txt` index alongside the bundle and assigns each chunk its specific page `source_url` by joining the clean content to the index positionally per source, validated by the page's H1 title (falling back to the legacy inline-marker path when no companion index is present). Chunking strategies run in priority order — the first strategy that matches a document fragment handles it:

1. **YAML strategy:** Handles YAML content. Delegates structured specs (CRDs, OpenAPI, JSON Schema) to tree walkers. Falls back to a generic `yaml_content` chunk for unrecognized YAML.
2. **Code strategy:** Handles fenced code blocks. Detects the language and, for structured YAML specs embedded in code fences, invokes tree walkers.
3. **Table strategy:** Handles Markdown tables. Produces one `table_row` chunk per data row, rendered as natural-language `Column: value.` lines and self-linked via `table_id` and `sibling_ids`. Delegates non-table regions to the list and prose strategies.
4. **List strategy:** Handles Markdown lists. Produces one chunk per top-level list item and attaches sibling previews and breadcrumb paths.
5. **Prose strategy:** The fallback. Splits at heading boundaries (`#`, `##`, `###`). Preserves complete sections — does not split within a section by token count.

Each chunk carries a `chunk_type` field (`prose`, `code_snippet`, `crd_definition`, `openapi_spec`, `json_schema`, `yaml_content`, `list_item`, or `table_row`) and type-specific metadata fields. See [Chunk metadata schema](metadata-schema.md) for the full field reference.

### Embed

The `opencrane embed` command generates a vector embedding for each chunk in `.opencrane/chunks.json` and writes the results to `.opencrane/embeddings.json`. It uses the `sentence-transformers` library with `nomic-ai/nomic-embed-text-v1.5` as the default model. You can change the model via the `EMBEDDING_MODEL` environment variable. The command processes chunks in batches to manage memory.

### Index

The `opencrane index` command loads `.opencrane/embeddings.json` into a Milvus vector database. It creates a collection with an Hierarchical Navigable Small World (HNSW) index on the embedding vectors and uses cosine similarity as the distance metric.

Two deployment modes are available:

- **Milvus Lite:** An embedded, file-based database stored at `.opencrane/milvus.db`. No separate service is needed. Set `MILVUS_DB_PATH` to use this mode.
- **Milvus Server:** A separate Milvus instance. Set `MILVUS_HOST` and `MILVUS_PORT` to connect.

### Serve

The `opencrane serve` command starts the MCP server backed by the indexed data. Two transport modes are available:

- **stdio:** For local MCP clients such as Claude Code or Cursor.
- **HTTP:** For containerized or remote deployments. The `Dockerfile` and `docker-compose.yml` generated by `opencrane init` use this mode.

## MCP tools

The server exposes up to six tools. The set of tools adapts to the content of the index — `get_yaml_definition`, `get_metadata_schema`, `get_list_members`, and `get_table_members` appear only when the index contains the relevant chunk types.

| Tool | Condition | Description |
|---|---|---|
| `search_docs` | Always present | Hybrid semantic and keyword search across all indexed chunks |
| `get_yaml_definition` | YAML chunks indexed | Retrieve a complete YAML document by chunk ID, with breadcrumb comments showing its location |
| `get_metadata_schema` | YAML chunks indexed | Reference documentation for all chunk metadata fields |
| `get_list_members` | List chunks indexed | Retrieve all items in a list by list ID |
| `get_table_members` | Table row chunks indexed | Retrieve all rows of a table by table ID |
| `health` | Always present | Service status, Milvus connection state, and collection stats |

### Search modes

`search_docs` supports three search modes via the **search_mode** parameter: `semantic`, `keyword`, and `hybrid`. The default is `hybrid`, which blends vector similarity with BM25 keyword scoring:

```
final_score = alpha × vector_score + (1 − alpha) × bm25_score
```

The default **alpha** is `0.6` (60% semantic, 40% keyword). You can override it per query via the **alpha** parameter, or set a default with the `HYBRID_ALPHA` environment variable.

Additional `search_docs` parameters let you filter results by **chunk_types**, **source_names**, and **metadata_contains**, which is useful when you want to restrict a search to a specific documentation source or chunk type.

## Internal components

### CLI (`opencrane/cli.py`)

All subcommands share the same configuration resolution order:

1. Explicit `--config` flag.
2. `OPENCRANE_CONFIG` environment variable.
3. Auto-discovery from `.opencrane/extensions.py` in the working directory.
4. Base `OpenCraneConfig` defaults.

The CLI auto-discovers a custom `OpenCraneConfig` subclass from `.opencrane/extensions.py:Config`. This is the primary extension mechanism — subclassing `OpenCraneConfig` lets you override fence types, chunking strategies, and YAML tree walkers without modifying OpenCrane's core.

### RAG pipeline (`opencrane/rag/`)

This package contains the implementation of all pipeline stages. The key modules are:

- **`opencrane/rag/fetch_docs.py`** — GitHub repository fetching, source discovery, and stale-source cleanup.
- **`opencrane/rag/generate_llms_txt.py`** — `llms-full.txt` bundle generation, companion `llms.txt` index emission, fence type dispatch, and link rewriting.
- **`opencrane/rag/services/llms_index.py`** — parses and renders the `llms.txt` index (`LlmsIndex`, `render_llms_txt`) used to join clean content to per-page URLs.
- **`opencrane/rag/chunker.py`** — Top-level chunking orchestration. Loads bundles, resolves source names, and writes `chunks.json`.
- **`opencrane/rag/services/file_processor.py`** — Strategy-pattern chunking. Evaluates strategies in order; the first match handles the fragment.
- **`opencrane/rag/generate_embeddings.py`** — Batch embedding generation.
- **`opencrane/rag/services/source_mapping.py`** — Reads `.opencrane/config.yaml` and resolves source URLs to source names.

Tree walkers live in `opencrane/rag/services/chunking_strategies/` and handle structured YAML documents:

- **`k8s_crd_tree_walker.py`** — Kubernetes CRD chunking. Produces one chunk per `spec.properties` field and recursively splits nested properties that exceed 800 tokens.
- **`openapi_tree_walker.py`** — OpenAPI 3.x spec chunking. Produces element-level chunks (info, servers, paths, components) and per-method operation chunks.
- **`json_schema_tree_walker.py`** — JSON Schema chunking. Produces property-based chunks with recursive nesting for complex schemas.

### MCP server (`opencrane/mcp/`)

The server initializes its backing services lazily on the first tool call, so startup is fast. At initialization time it precomputes two lookup structures for O(1) access:

- A **chunk source map** for chunk-ID lookups used by `get_yaml_definition`.
- A **chunk index** for list membership queries used by `get_list_members` and table membership queries used by `get_table_members`.

The two backing services are:

- **`opencrane/mcp/services/milvus_client.py`** — Manages the Milvus connection and loads the collection into memory at startup for low-latency vector search.
- **`opencrane/mcp/services/keyword_search.py`** — Builds a Best Match 25 (BM25) index lazily from `chunks.json` on the first keyword or hybrid query.

### Configuration (`opencrane/config.py`, `opencrane/shared/config.py`)

`OpenCraneConfig` is the base class for all project-level configuration. It holds three extension-point attributes:

- **`fence_types`** — A dict of fence type handlers. Defaults include OpenAPI, AsyncAPI, CRD, and JSON Schema.
- **`chunking_strategies`** — An ordered list of chunking strategy instances. Evaluated in order; first match wins.
- **`yaml_tree_walkers`** — A list of tree walker classes. Evaluated in the order listed.

`Config` in `opencrane/shared/config.py` is the environment-based runtime configuration. It reads all settings from environment variables at process startup.

## Extension points

You extend OpenCrane by subclassing `OpenCraneConfig` in `.opencrane/extensions.py`. OpenCrane auto-discovers this file. Three extension points are available.

### Custom fence types

Fence types handle structured content embedded as fenced code blocks during the `llms` stage. To add a fence type, add an entry to `fence_types` with a `CodeFenceConfig` that names the fence and provides a handler function:

```python
class Config(OpenCraneConfig):
    fence_types = {
        **OpenCraneConfig.fence_types,
        "terraform": CodeFenceConfig(fence_type="terraform", handler=my_handler),
    }
```

The handler signature is:

```python
def my_handler(
    content: str,
    file_path: Path,
    project_dir: Path,
    project_name: str,
) -> str: ...
```

### Custom chunking strategies

To add a chunking strategy, insert it into the `chunking_strategies` list at the priority position you want. The first strategy that matches a fragment handles it — place more specific strategies before more general ones.

```python
class Config(OpenCraneConfig):
    chunking_strategies = [
        YamlChunkingStrategy(),
        MyCustomStrategy(),   # runs before Code and Prose
        CodeChunkingStrategy(),
        ProseChunkingStrategy(),
    ]
```

### Custom YAML tree walkers

To add a tree walker, append it to `yaml_tree_walkers`. Each walker must implement two methods:

- **`can_handle(cls, doc: dict) -> bool`** — Returns `True` if this walker handles the given YAML document.
- **`walk(self) -> List[Chunk]`** — Returns typed `Chunk` objects for the document.

```python
class TerraformTreeWalker(YamlTreeWalker):
    @classmethod
    def can_handle(cls, doc: dict) -> bool:
        return "terraform" in doc

    def walk(self) -> list[Chunk]:
        ...
```

## Data model

The `Chunk` model (`opencrane/shared/models/chunk.py`) is the core data structure that flows through all pipeline stages:

| Field | Type | Description |
|---|---|---|
| **chunk_id** | `str` (UUID) | Deterministic UUID, stable across pipeline runs |
| **content** | `str` or `dict` or `list` | String for prose and code; dict or list for YAML |
| **source_file** | `str` | Relative path from the workspace root |
| **source_name** | `str` or `None` | Resolved from **source_url**; `None` if no mapping exists |
| **chunk_type** | `str` | One of the chunk type literals (see the Chunk step above) |
| **metadata** | `dict` | Type-specific metadata fields |
| **token_count** | `int` | Token count using `cl100k_base` encoding |
| **line_start** | `int` or `None` | Reserved for future line-level source tracking; currently always `None` |

`VectorChunk` extends `Chunk` with an `embedding` field (a list of floats) and is used only during the `embed` and `index` stages.

## External dependencies

| Dependency | Purpose |
|---|---|
| Milvus | Vector database for embedding storage and similarity search |
| sentence-transformers | Embedding model (`nomic-ai/nomic-embed-text-v1.5` by default) |
| rank-bm25 | BM25 scoring for keyword search |
| PyGithub | GitHub API client for repository discovery and cloning |
| Docling | Document parsing for PDF, DOCX, and other non-Markdown formats |
| tiktoken | Token counting using the `cl100k_base` encoding |
| Pydantic | Data model validation |
| Click | CLI framework |
| MCP SDK | Model Context Protocol server implementation |
