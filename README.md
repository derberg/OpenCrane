<img src="assets/logo.png" alt="OpenCrane logo" width="25%">

A standalone, extensible RAG/MCP pipeline for building AI-powered documentation search. Fetch docs from GitHub, generate `llms-full.txt` bundles, chunk and embed them, index into Milvus, and serve via an MCP server — all from one CLI.

## Table of Contents

- [Features](#features)
- [Credits](#credits)
- [Quick start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
  - [CLI](#cli)
    - [init](#opencrane-init----scaffold-a-new-project)
    - [add](#opencrane-add----add-documentation-sources)
    - [build](#opencrane-build----full-pipeline)
    - [fetch](#opencrane-fetch----fetch-docs-from-github)
    - [llms](#opencrane-llms----generate-llms-fulltxt-bundles)
    - [tokens](#opencrane-tokens----token-count-report)
    - [chunk](#opencrane-chunk----chunk-docs-into-rag-chunksjson)
    - [embed](#opencrane-embed----generate-embeddings)
    - [index](#opencrane-index----load-into-milvus)
    - [serve](#opencrane-serve----start-mcp-server)
    - [inspect](#opencrane-inspect----launch-mcp-inspector)
  - [Default file and directory names](#default-file-and-directory-names)
  - [Environment variables](#environment-variables)
  - [Source mapping file](#source-mapping-file-opencraneourcesyaml)
- [Extending OpenCrane](#extending-opencrane)
  - [Extension points](#extension-points)
  - [Built-in YAML tree walkers](#built-in-yaml-tree-walkers)
  - [Writing a custom fence type](#writing-a-custom-fence-type)
  - [Writing a custom YAML tree walker](#writing-a-custom-yaml-tree-walker)
- [Development](#development)
- [License](#license)

## Features

- **Flexible RAG pipeline**: run the full flow (fetch → generate llms-full.txt → chunk → embed → index → serve) or use only the steps you need
- **MCP server**: exposes search tools consumable by Claude, Cursor, and any MCP-compatible client
- **Extensible**: subclass `OpenCraneConfig` to add custom fence types, chunking strategies, and YAML tree walkers
- **CLI**: every pipeline step is a subcommand; works in CI/CD and non-Python projects


## Credits

OpenCrane was born from a real-world use case at [Cennso](https://cennso.com) — building AI-powered search over telco product documentation.

This project stands on the shoulders of some excellent open-source work:

- [Milvus](https://milvus.io) — vector database powering similarity search
- [Docling](https://github.com/DS4SD/docling) — document parsing and chunking
- [sentence-transformers](https://www.sbert.net) — embedding generation
- [rank-bm25](https://github.com/dorianbrown/rank_bm25) — BM25 keyword search that complements vector similarity search
- [Model Context Protocol](https://modelcontextprotocol.io) — MCP server standard that makes the search tools consumable by AI clients

## Quick start

Scaffold a new project without installing anything:

```bash
uvx --from "opencrane @ git+https://github.com/derberg/OpenCrane.git" opencrane init
```

This creates `.opencrane/`, `Dockerfile`, and `docker-compose.yml` in the current directory and walks you through adding documentation sources interactively. Then run `opencrane build` and `opencrane serve`.

## Installation

```bash
# with pip
pip install git+https://github.com/derberg/OpenCrane.git

# with uv
uv pip install git+https://github.com/derberg/OpenCrane.git
```

## Usage

### CLI

All commands accept `--config myproject.config:MyConfig` to load a custom `OpenCraneConfig` subclass.

#### `opencrane init` — scaffold a new project

```bash
opencrane init [--podman] [--force] [--no-add]
```

Creates the `.opencrane/` directory and container files in the current directory:

| Generated file | Description |
|---|---|
| `.opencrane/config.py` | `OpenCraneConfig` subclass template with commented extension points |
| `.opencrane/sources.yaml` | Source mapping template with commented remote and local examples |
| `.opencrane/README.md` | Quick reference for the `.opencrane/` directory |
| `Dockerfile` | Multi-stage build: deps → model download → Milvus index → runtime |
| `docker-compose.yml` | Builds and runs the MCP server on port 8000 |

| Flag | Description |
|---|---|
| `--podman` | Generate `Containerfile` instead of `Dockerfile`; README uses `podman` commands |
| `--force` | Overwrite existing files (default: skip) |
| `--no-add` | Skip the interactive source addition prompt (useful for CI/scripts) |

> **Convention**: OpenCrane auto-discovers `.opencrane/config.py` as the project config, so no `--config` flag or `OPENCRANE_CONFIG` env var is needed when using the `.opencrane/` layout.

After scaffolding, `init` prompts you to add documentation sources interactively (same flow as `opencrane add`). Use `--no-add` to skip the prompt.

#### `opencrane add` — add documentation sources

```bash
opencrane add
```

Interactively add documentation sources to your project. The command loops, asking for each source:

1. **GitHub repository** — adds an entry to `.opencrane/sources.yaml` with the repo URL, docs path, and optional published docs URL. The `fetch` step will clone it on the next `opencrane build`.
2. **Existing llms.txt file** — provide a URL or local file path. OpenCrane downloads/copies it into `.opencrane/llmstxt/<name>/llms-full.txt`, ready for chunking. No `fetch` or `llms` step needed for these sources.

After each source, you're asked whether to add another or finish.

#### `opencrane build` — full pipeline

```bash
opencrane build [--config CLASS] [--sources-dir PATH]... [--llmstxt-dir PATH]
                [--chunks-file PATH] [--embeddings-file PATH]
```

Runs all steps in sequence: fetch → llms → chunk → embed → index.

| Flag | Description |
|---|---|
| `--sources-dir PATH` | Source directory to process; repeat for multiple dirs (overrides `AI_DOCS_SOURCES_DIRS` env var) |
| `--llmstxt-dir PATH` | Output directory for llms-full.txt files, and input directory for the chunk step (overrides `AI_DOCS_LLMSTXT_DIR` env var) |
| `--chunks-file PATH` | Output path for chunks JSON, and input for the embed step (overrides `AI_DOCS_CHUNKS_FILE` env var) |
| `--embeddings-file PATH` | Output path for embeddings JSON (overrides `AI_DOCS_EMBEDDINGS_FILE` env var) |

#### `opencrane fetch` — fetch docs from GitHub

```bash
opencrane fetch [--config CLASS] [--org NAME] [--repo PATH_KEY]
```

| Flag | Description |
|---|---|
| `--org NAME` | GitHub organisation to fetch from (overrides `ORG_NAME` env var) |
| `--repo PATH_KEY` | Fetch only this one repo by its path key in `.opencrane/sources.yaml`, e.g. `external-sources/my-repo` (overrides `FETCH_REPO` env var) |

#### `opencrane llms` — generate llms-full.txt bundles

```bash
opencrane llms [--config CLASS] [--sources-dir PATH]... [--llmstxt-dir PATH] [--force]
```

| Flag | Description |
|---|---|
| `--sources-dir PATH` | Source directory to process; repeat for multiple dirs (overrides `AI_DOCS_SOURCES_DIRS` env var) |
| `--llmstxt-dir PATH` | Output directory for llms-full.txt files (overrides `AI_DOCS_LLMSTXT_DIR` env var) |
| `--force` | Regenerate even if no git changes are detected in source directories |

#### `opencrane tokens` — token count report

```bash
opencrane tokens [--source-dir PATH] [--output-file PATH]
```

| Flag | Description |
|---|---|
| `--source-dir PATH` | Directory containing llmstxt output to count (overrides `TOKEN_SOURCE_DIR` env var) |
| `--output-file PATH` | Output path for the markdown report (overrides `TOKEN_OUTPUT_FILE` env var) |

#### `opencrane chunk` — chunk docs into .opencrane/chunks.json

```bash
opencrane chunk [--config CLASS] [--llmstxt-dir PATH] [--chunks-file PATH]
```

| Flag | Description |
|---|---|
| `--llmstxt-dir PATH` | Directory containing llms-full.txt (overrides `AI_DOCS_LLMSTXT_DIR` env var) |
| `--chunks-file PATH` | Output path for chunks JSON (overrides `AI_DOCS_CHUNKS_FILE` env var) |

#### `opencrane embed` — generate embeddings

```bash
opencrane embed [--config CLASS] [--chunks-file PATH] [--embeddings-file PATH]
```

| Flag | Description |
|---|---|
| `--chunks-file PATH` | Input chunks JSON file (overrides `AI_DOCS_CHUNKS_FILE` env var) |
| `--embeddings-file PATH` | Output embeddings JSON file (overrides `AI_DOCS_EMBEDDINGS_FILE` env var) |

#### `opencrane index` — load into Milvus

```bash
opencrane index [--config CLASS]
```

#### `opencrane serve` — start MCP server

```bash
opencrane serve [--config CLASS] [--transport stdio|http]
```

| Flag | Description |
|---|---|
| `--transport stdio` | *(default)* stdio transport for local MCP clients. Prints integration instructions for Claude Code, Cursor, Windsurf, VS Code, Zed, and Docker/Podman on startup |
| `--transport http` | HTTP transport on port 8000 (Streamable HTTP, stateless). Used inside Docker/Podman containers. Port configurable via `MCP_HTTP_PORT` env var |

#### `opencrane inspect` — launch MCP Inspector

```bash
opencrane inspect [--config CLASS]
```

Launches the [MCP Inspector](https://github.com/modelcontextprotocol/inspector) web UI connected to the server via stdio — no Docker required. Requires `npx` (Node.js).

Web UI available at `http://localhost:5173`.

### Debugging

Enable verbose logging for any command:

```bash
LOG_LEVEL=DEBUG opencrane build
LOG_LEVEL=DEBUG opencrane add
```

### Default file and directory names

OpenCrane uses these defaults for all pipeline output. Override them with CLI flags (one-off) or environment variables (persistent):

| File / directory | Default | CLI flag | Env var |
|---|---|---|---|
| llms-full.txt output dir | `.opencrane/llmstxt` | `--llmstxt-dir` | `AI_DOCS_LLMSTXT_DIR` |
| Chunks file | `.opencrane/chunks.json` | `--chunks-file` | `AI_DOCS_CHUNKS_FILE` |
| Embeddings file | `.opencrane/embeddings.json` | `--embeddings-file` | `AI_DOCS_EMBEDDINGS_FILE` |
| Token report output | `.opencrane/llmstxt/README.md` | `--output-file` | `TOKEN_OUTPUT_FILE` |
| Source mapping file | `.opencrane/sources.yaml` | — | `MAPPING_FILE` |
| Milvus database file (Lite mode) | _(server mode)_ | — | `MILVUS_DB_PATH` |

### Environment variables

CLI flags take precedence over environment variables. Use env vars for persistent defaults (e.g. in CI/CD), and flags for one-off overrides.

**`fetch` and `llms` steps** — shared configuration for source tracking:

| Variable | Default | Description |
|---|---|---|
| `MAPPING_FILE` | `.opencrane/sources.yaml` | Path to the source mapping file used by `fetch` (to record cloned repos) and `llms` (to embed source links) |

**`fetch` step** — only needed if you use `opencrane fetch` to pull docs from GitHub:

| Variable | Default | Description |
|---|---|---|
| `ORG_NAME` | `` | GitHub organisation to fetch repositories from (see also `--org` flag) |
| `FETCH_REPO` | `` | Restrict fetch to a single repo by path key (see also `--repo` flag) |
| `GITHUB_TOKEN` | `` | GitHub API token for authenticated requests |
| `DOCS_TOPIC` | `documentation` | GitHub topic used to discover repositories automatically within the org |
| `AUTO_DISCOVERY_ORGS` | `` | Whitelist of orgs where topic-based auto-discovery is enabled |
| `TARGET_DIR` | `external-sources` | Local directory where fetched docs are stored |

**`llms` step** — only needed if you use `opencrane llms` to generate llms-full.txt bundles:

| Variable | Default | Description |
|---|---|---|
| `AI_DOCS_SOURCES_DIRS` | `TARGET_DIR` | **Required when not using `opencrane fetch`.** Comma-separated list of source directories to process (see also `--sources-dir` flag) |
| `AI_DOCS_LLMSTXT_DIR` | `.opencrane/llmstxt` | Output directory for generated llms-full.txt files (see also `--llmstxt-dir` flag) |

**`tokens` step** — only needed if you use `opencrane tokens`:

| Variable | Default | Description |
|---|---|---|
| `TOKEN_SOURCE_DIR` | `.opencrane/llmstxt` | Directory containing llmstxt output to count (see also `--source-dir` flag) |
| `TOKEN_OUTPUT_FILE` | `.opencrane/llmstxt/README.md` | Output path for the markdown report (see also `--output-file` flag) |

**`chunk` step** — only needed if you use `opencrane chunk`:

| Variable | Default | Description |
|---|---|---|
| `AI_DOCS_LLMSTXT_DIR` | `.opencrane/llmstxt` | Directory containing llms-full.txt (see also `--llmstxt-dir` flag) |
| `AI_DOCS_CHUNKS_FILE` | `.opencrane/chunks.json` | Output path for the generated chunks (see also `--chunks-file` flag) |

**`embed` step** — only needed if you use `opencrane embed`:

| Variable | Default | Description |
|---|---|---|
| `AI_DOCS_CHUNKS_FILE` | `.opencrane/chunks.json` | Input chunks JSON file (see also `--chunks-file` flag) |
| `AI_DOCS_EMBEDDINGS_FILE` | `.opencrane/embeddings.json` | Output path for the generated embeddings (see also `--embeddings-file` flag) |
| `EMBEDDING_MODEL` | `nomic-ai/nomic-embed-text-v1.5` | HuggingFace embedding model to use |

**`index` and `serve` steps** — needed when loading into Milvus or running the MCP server:

OpenCrane supports two Milvus modes. Set `MILVUS_DB_PATH` to use **Milvus Lite** (a local file, no server needed — good for local dev). Leave it unset to connect to a **Milvus server** via `MILVUS_HOST` and `MILVUS_PORT`.

| Variable | Default | Description |
|---|---|---|
| `MILVUS_DB_PATH` | `` | Path to a local Milvus Lite database file (e.g. `./milvus.db`). When set, `MILVUS_HOST` and `MILVUS_PORT` are ignored |
| `MILVUS_HOST` | `localhost` | Milvus server host (server mode only) |
| `MILVUS_PORT` | `19530` | Milvus server port (server mode only) |
| `MILVUS_COLLECTION` | `ai_docs_chunks_v1` | Milvus collection name |
| `HYBRID_ALPHA` | `0.6` | Weight of vector search vs keyword search (1.0 = pure vector, 0.0 = pure BM25) |

### Source mapping file (`.opencrane/sources.yaml`)

OpenCrane maintains a file called `.opencrane/sources.yaml` that records where each documentation source lives and where its content can be found online. It is used by the `fetch` step (to track cloned repos) and by the `llms` step (to embed source links in llms-full.txt). The `fetch` step populates it automatically; for manually managed sources you can edit it directly.

Each entry supports the following fields:

| Field | Required | Description |
|---|---|---|
| `github_url` | Yes (for `fetch`) | GitHub repository URL — used by `opencrane fetch` to clone the repo and as a fallback source link in llms-full.txt |
| `docs_path` | No | Path within the repo where docs are stored (e.g. `docs`) |
| `docs_url` | No | Base URL of the published documentation site (e.g. `https://docs.example.com/product`). When set, this is used instead of `github_url` when embedding source links in llms-full.txt — lets AI agents point users to rendered docs rather than raw GitHub files. If neither is set, no source links are embedded. |
| `manual` | No | When `true`, the entry is user-managed and will not be overwritten by `opencrane fetch` auto-discovery |

Example:

```yaml
sources:
  external-sources/my-product:
    github_url: https://github.com/myorg/my-product
    docs_path: docs
    docs_url: https://docs.myorg.com/my-product
    manual: true
```

## Extending OpenCrane

Subclass `OpenCraneConfig` to register project-specific extensions:

```python
# myproject/config.py
from opencrane import OpenCraneConfig
from opencrane.fences import CodeFenceConfig
from opencrane.rag.services.yaml_chunker import YamlChunkingStrategy
from opencrane.rag.services.code_chunker import CodeChunkingStrategy
from opencrane.rag.services.prose_chunker import ProseChunkingStrategy
from myproject.strategies.custom import CustomChunkingStrategy
from myproject.walkers.terraform import TerraformTreeWalker

def my_openapi_handler(content: str) -> str:
    # content is the raw text inside the ```openapi ... ``` block
    # process it however you like and return the replacement string
    return f"```yaml\n{content}\n```\n"

class MyConfig(OpenCraneConfig):
    fence_types = {
        "openapi": CodeFenceConfig(fence_type="openapi", handler=my_openapi_handler),
    }
    chunking_strategies = [
        YamlChunkingStrategy(),
        CustomChunkingStrategy(),
        CodeChunkingStrategy(),
        ProseChunkingStrategy(),
    ]
    yaml_tree_walkers = [
        *OpenCraneConfig.yaml_tree_walkers,  # keep CRD, OpenAPI, JSON Schema
        TerraformTreeWalker,
    ]
```

Then use it:

```bash
opencrane build --config myproject.config:MyConfig
```

### Extension points

| Extension point | Pipeline step | What it does |
|---|---|---|
| `fence_types` | `llms` | Register custom fence language identifiers and control how matching blocks are transformed during llms-full.txt generation |
| `chunking_strategies` | `chunk` | Add or replace chunking strategies for different content types |
| `yaml_tree_walkers` | `chunk` | Add walkers for custom YAML document formats |

### Built-in YAML tree walkers

- `K8sCRDTreeWalker` — Kubernetes CustomResourceDefinitions
- `OpenAPITreeWalker` — OpenAPI 3.x specs
- `JsonSchemaTreeWalker` — JSON Schema documents

### Writing a custom fence type

Register a fence language identifier and provide a `handler` function. When a ` ```my-type ... ``` ` block is encountered during `llms` generation, OpenCrane calls your handler with the raw block content plus the file context, and replaces the block with the returned string.

```python
from pathlib import Path
from opencrane.fences import CodeFenceConfig

def my_handler(content: str, file_path: Path, project_dir: Path, project_name: str) -> str:
    # content      — raw text inside the fence block
    # file_path    — path of the markdown file containing the block
    # project_dir  — root directory of the project being processed
    # project_name — name of the project (used for source URL building)
    # return the full replacement string
    return f"```yaml\n# processed\n{content}\n```\n"

fence_types = {
    "my-type": CodeFenceConfig(fence_type="my-type", handler=my_handler),
}
```

To inline a file referenced by path inside the block, use `get_github_url` from `opencrane.fences` to add a source annotation:

```python
from pathlib import Path
from opencrane.fences import CodeFenceConfig, get_github_url

def inline_handler(content: str, file_path: Path, project_dir: Path, project_name: str) -> str:
    target = (file_path.parent / content.strip()).resolve()
    language = "json" if target.suffix == ".json" else "yaml"
    gh_url = get_github_url(Path(project_name) / target.relative_to(project_dir), project_name)
    file_content = target.read_text(encoding="utf-8").rstrip("\n")
    if gh_url:
        return f"```{language}\n# Source: {gh_url}\n{file_content}\n```\n"
    return f"```{language}\n{file_content}\n```\n"

fence_types = {
    "my-type": CodeFenceConfig(fence_type="my-type", handler=inline_handler),
}
```

### Writing a custom YAML tree walker

```python
from opencrane.walkers.base import YamlTreeWalker

class TerraformTreeWalker(YamlTreeWalker):
    @classmethod
    def can_handle(cls, doc: dict) -> bool:
        return "terraform" in doc

    def walk(self):
        # return List[Chunk]
        ...
```

## Development

```bash
git clone https://github.com/derberg/OpenCrane.git
cd OpenCrane

# with pip
pip install -e ".[dev]"

# with uv
uv sync --extra dev

pytest
```

## License

Apache-2.0
