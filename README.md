<img src="assets/logo.png" alt="OpenCrane logo" width="25%">

# OpenCrane

OpenCrane is a standalone, extensible pipeline for AI-powered documentation search, based on retrieval-augmented generation (RAG) and the Model Context Protocol (MCP). With its command-line interface (CLI), you can do the following:

- Fetch documentation from GitHub.
- Generate `llms-full.txt` bundles.
- Chunk and embed the bundles.
- Index the embeddings into Milvus.
- Serve the index through an MCP server.

## Table of contents

This README covers the following topics:

- [Features](#features)
- [Quick start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
  - [CLI](#cli)
    - [init](#create-a-project-with-opencrane-init)
    - [add](#add-documentation-sources-with-opencrane-add)
    - [build](#run-the-full-pipeline-with-opencrane-build)
    - [fetch](#fetch-documentation-from-github-with-opencrane-fetch)
    - [llms](#generate-llms-fulltxt-bundles-with-opencrane-llms)
    - [tokens](#count-tokens-with-opencrane-tokens)
    - [chunk](#chunk-the-documentation-with-opencrane-chunk)
    - [embed](#generate-embeddings-with-opencrane-embed)
    - [index](#index-the-embeddings-in-milvus-with-opencrane-index)
    - [serve](#start-the-mcp-server-with-opencrane-serve)
    - [pack](#package-the-server-with-opencrane-pack)
    - [inspect](#open-the-mcp-inspector-with-opencrane-inspect)
    - [visualize](#compare-a-paragraph-with-the-indexed-documentation-with-opencrane-visualize)
  - [Health endpoint](#health-endpoint)
  - [Default file and directory names](#default-file-and-directory-names)
  - [Environment variables](#environment-variables)
  - [Source mapping file](#source-mapping-file)
- [Extend OpenCrane](#extend-opencrane)
  - [Extension points](#extension-points)
  - [Section anchors](#section-anchors)
  - [Built-in fence types](#built-in-fence-types)
  - [Built-in YAML tree walkers](#built-in-yaml-tree-walkers)
  - [Write a custom fence type](#write-a-custom-fence-type)
  - [Write a custom YAML tree walker](#write-a-custom-yaml-tree-walker)
- [Authentication and authorization](#authentication-and-authorization)
- [Development](#development)
- [Credits](#credits)
- [License](#license)

## Features

OpenCrane provides the following features:

- Flexible RAG pipeline: OpenCrane runs the full flow, or only the steps you need. The full flow is fetch → generate `llms-full.txt` → chunk → embed → index → serve.
- MCP server: the server exposes search tools that any MCP-compatible client can use, for example Claude or Cursor.
- Extensibility: an `OpenCraneConfig` subclass adds your own code at the [extension points](#extension-points), for example a custom chunking strategy. Built-in [fence types](#built-in-fence-types) insert the content of API and schema files, for example OpenAPI specs, into the documentation bundle.
- Section anchors: each chunk records a `section_anchor`, so citations link to the exact section of a page (`{source_url}#{section_anchor}`). Section anchors are on by default. Each project can choose the anchor style or override the anchors.
- Command-line interface: every pipeline step is a subcommand. The CLI works in continuous integration and continuous delivery (CI/CD) pipelines and in projects that don't use Python.

## Quick start

To create a project without installing OpenCrane, run the following command:

```bash
uvx opencrane init
```

The command creates the `.opencrane/` directory with the project configuration and the container files. It then prompts you to add documentation sources.

To build and serve the index, install OpenCrane with the `pipeline` extra, as described in [Installation](#installation). Then run `opencrane build` and `opencrane serve`.

## Installation

OpenCrane requires Python 3.11 or later. The base package runs the MCP server on an index that is already built. To install only the base package, run the following command:

```bash
pip install opencrane
```

To build an index, install the `pipeline` extra. The following commands need it:

- `fetch`
- `llms`
- `chunk`
- `embed`
- `tokens`

To install the `pipeline` extra, run one of the following commands:

```bash
# with pip
pip install 'opencrane[pipeline]'

# with uv
uv pip install 'opencrane[pipeline]'
```

To run a command with the `pipeline` extra without installing OpenCrane, use `uvx`:

```bash
uvx --from 'opencrane[pipeline]' opencrane {COMMAND}
```

## Usage

This section is the reference for the OpenCrane CLI and its configuration.

### CLI

Each pipeline step and each project task has its own `opencrane` command. Commands that show `[--config {MODULE}:{CLASS}]` in their usage line accept the `--config` flag, which loads a custom `OpenCraneConfig` subclass. Pass the module and the class name, or the path to a Python file that defines a class named `Config`. The `OPENCRANE_CONFIG` environment variable takes the same value. For `opencrane serve`, the server takes `middleware`, `token_verifier`, and `auth_provider` only from `OPENCRANE_CONFIG` or the `extensions:` key, not from `--config`.

#### Create a project with `opencrane init`

The `opencrane init` command creates a new project. It has the following syntax:

```bash
opencrane init [--podman] [--force] [--no-add] [--extensions]
```

The command creates the `.opencrane/` directory with the following files:

| Generated file | Description |
|---|---|
| `.opencrane/config.yaml` | Template for the source mapping and the project configuration, with commented examples of remote and local sources |
| `.opencrane/README.md` | Quick reference for the `.opencrane/` directory |
| `.opencrane/Dockerfile` | Multi-stage build: dependencies → model download → Milvus index → runtime |
| `.opencrane/docker-compose.yml` | Builds and runs the MCP server on port 8000 |
| `.opencrane/extensions.py` | Template for custom Python extensions. The command generates it only with `--extensions`. |

> [!CAUTION]
> `--force` replaces every file that the command generates, except `.opencrane/config.yaml`, with a fresh template. You lose your changes to those files. With `--extensions`, this includes `.opencrane/extensions.py`. Commit or back up those files before you run `opencrane init --force`.

The command accepts the following flags:

| Flag | Description |
|---|---|
| `--podman` | Generates `.opencrane/Containerfile` instead of `.opencrane/Dockerfile`. The generated README uses `podman` commands. |
| `--force` | Overwrites existing generated files. By default, the command skips them. The command never overwrites `.opencrane/config.yaml`. |
| `--no-add` | Skips the interactive prompt to add sources, which is useful in CI or in scripts. |
| `--extensions` | Generates `.opencrane/extensions.py` for custom Python extensions. |

> [!IMPORTANT]
> To load `.opencrane/extensions.py` without the `--config` flag, set `extensions: extensions.py` in `.opencrane/config.yaml`. The generated `config.yaml` has this key commented out, so uncomment it. Name the class in the file `Config`.

After it creates the files, `opencrane init` prompts you to add documentation sources, in the same way as [`opencrane add`](#add-documentation-sources-with-opencrane-add). To skip the prompt, use `--no-add`.

#### Add documentation sources with `opencrane add`

The `opencrane add` command adds documentation sources to your project interactively. Run `opencrane init` first, because the command needs the `.opencrane/` directory. The command has the following syntax:

```bash
opencrane add
```

The command runs in a loop. For each source, it asks you to choose one of the following kinds of source:

1. GitHub repository: the command asks for the repository URL, the path to the documentation in the repository, and an optional published documentation URL. It then adds an entry to `.opencrane/config.yaml`. You can also pin the entry to a Git ref, as described in [Source mapping file](docs/source-mapping.md). The `fetch` step downloads the repository's documentation on the next `opencrane build`.
2. Existing `llms.txt` file: you provide a URL or a local file path, and the command adds an entry to `.opencrane/config.yaml`. On the next `fetch`, OpenCrane downloads or copies the file into `.opencrane/llmstxt/{NAME}/llms-full.txt`. When the upstream companion `llms.txt` is available, OpenCrane also fetches it into the same directory, so each page gets its own source URL.

After each source, the command asks whether to add another source or to finish.

#### Run the full pipeline with `opencrane build`

The `opencrane build` command runs all steps in sequence: fetch → llms → chunk → embed → index. It has the following syntax:

```bash
opencrane build [--config {MODULE}:{CLASS}] [--sources-dir {PATH}]... [--llmstxt-dir {PATH}]
                [--chunks-file {PATH}] [--embeddings-file {PATH}]
```

The command accepts the following flags:

| Flag | Description |
|---|---|
| `--sources-dir {PATH}` | Source directory to process. Repeat the flag for several directories. Overrides the `AI_DOCS_SOURCES_DIRS` environment variable. |
| `--llmstxt-dir {PATH}` | Output directory for the `llms-full.txt` files, and input directory for the chunk step. Overrides the `AI_DOCS_LLMSTXT_DIR` environment variable. |
| `--chunks-file {PATH}` | Output path for the chunks JSON file, and input path for the embed step. Overrides the `AI_DOCS_CHUNKS_FILE` environment variable. |
| `--embeddings-file {PATH}` | Output path for the embeddings JSON file. Overrides the `AI_DOCS_EMBEDDINGS_FILE` environment variable. |

The `index` step does not use `--chunks-file` or `--embeddings-file`. It reads the chunks and embeddings from the paths in `AI_DOCS_CHUNKS_FILE` and `AI_DOCS_EMBEDDINGS_FILE`, by default `.opencrane/chunks.json` and `.opencrane/embeddings.json`. To build with other paths, set these environment variables instead of the flags.

#### Fetch documentation from GitHub with `opencrane fetch`

The `opencrane fetch` command fetches documentation from GitHub repositories. It has the following syntax:

```bash
opencrane fetch [--config {MODULE}:{CLASS}] [--org {NAME}] [--source {NAMES}]
```

The command accepts the following flags:

| Flag | Description |
|---|---|
| `--org {NAME}` | GitHub organization to fetch from. The flag also turns on auto-discovery for that organization. Auto-discovery fetches every repository of the organization that has the GitHub topic set in `DOCS_TOPIC` (default `documentation`). Overrides the `ORG_NAME` environment variable. |
| `--source {NAMES}` | Fetches only these sources, by their key under `sources:` in `.opencrane/config.yaml`. Takes one name or a comma-separated list, for example `my-repo,other-repo`. The `--repo` flag is an alias. Overrides the `FETCH_REPO` environment variable. |

For details about fetching, see [Fetch documentation sources](docs/fetching.md).

#### Generate `llms-full.txt` bundles with `opencrane llms`

The `opencrane llms` command writes one `llms-full.txt` file for each source, in `.opencrane/llmstxt/{SOURCE}/`. It also writes a combined `llms-full.txt` bundle of all sources in `.opencrane/llmstxt/`. Next to the bundle, it writes a companion `llms.txt` index that maps each page title to the page URL. The `chunk` step reads the combined bundle and the index to assign each chunk the `source_url` of its page. For details, see [the `llms-full.txt` generation guide](docs/llms-generation.md).

The command has the following syntax:

```bash
opencrane llms [--config {MODULE}:{CLASS}] [--sources-dir {PATH}]... [--llmstxt-dir {PATH}] [--force]
```

The command accepts the following flags:

| Flag | Description |
|---|---|
| `--sources-dir {PATH}` | Source directory to process. Repeat the flag for several directories. Overrides the `AI_DOCS_SOURCES_DIRS` environment variable. |
| `--llmstxt-dir {PATH}` | Output directory for the `llms-full.txt` files. Overrides the `AI_DOCS_LLMSTXT_DIR` environment variable. |
| `--force` | Regenerates the bundles even when Git detects no changes in the directories passed with `--sources-dir` or set in `AI_DOCS_SOURCES_DIRS`. Without either, the step always regenerates the bundles. Git never reports changes in directories it ignores, so pass `--force` for those directories. |

#### Count tokens with `opencrane tokens`

The `opencrane tokens` command writes a Markdown report with the number of tokens in each `llms-full.txt` file. Use the report to check how much of a model's context window each bundle takes. The command has the following syntax:

```bash
opencrane tokens [--source-dir {PATH}] [--output-file {PATH}]
```

The command accepts the following flags:

| Flag | Description |
|---|---|
| `--source-dir {PATH}` | Directory with the `llms-full.txt` files to count. Overrides the `TOKEN_SOURCE_DIR` environment variable. |
| `--output-file {PATH}` | Output path for the Markdown report. Overrides the `TOKEN_OUTPUT_FILE` environment variable. |

#### Chunk the documentation with `opencrane chunk`

The `opencrane chunk` command splits the documentation into chunks and writes them to `.opencrane/chunks.json`. It has the following syntax:

```bash
opencrane chunk [--config {MODULE}:{CLASS}] [--llmstxt-dir {PATH}] [--chunks-file {PATH}]
```

When the companion `llms.txt` index exists, the command reads it together with `llms-full.txt` and assigns each chunk the `source_url` of its page. For bundles from earlier OpenCrane versions, which have no index, the command reads the page URLs from the bundle itself.

The command accepts the following flags:

| Flag | Description |
|---|---|
| `--llmstxt-dir {PATH}` | Directory with `llms-full.txt` and its companion `llms.txt`. Overrides the `AI_DOCS_LLMSTXT_DIR` environment variable. |
| `--chunks-file {PATH}` | Output path for the chunks JSON file. Overrides the `AI_DOCS_CHUNKS_FILE` environment variable. |

> [!TIP]
> To learn how to structure Markdown so that its chunks are high quality and easy to retrieve, see the [authoring guide](docs/authoring-guide.md).

#### Generate embeddings with `opencrane embed`

The `opencrane embed` command generates the vector embeddings for the chunks. It has the following syntax:

```bash
opencrane embed [--config {MODULE}:{CLASS}] [--chunks-file {PATH}] [--embeddings-file {PATH}] [--force]
```

The command accepts the following flags:

| Flag | Description |
|---|---|
| `--chunks-file {PATH}` | Input chunks JSON file. Overrides the `AI_DOCS_CHUNKS_FILE` environment variable. |
| `--embeddings-file {PATH}` | Output embeddings JSON file. Overrides the `AI_DOCS_EMBEDDINGS_FILE` environment variable. |
| `--force` | Regenerates the embeddings even when the chunks have not changed since the last run. Without this flag, the command skips the step when the chunks are unchanged. |

#### Index the embeddings in Milvus with `opencrane index`

The `opencrane index` command loads the chunks and their embeddings into Milvus. It has the following syntax:

```bash
opencrane index [--config {MODULE}:{CLASS}]
```

When the Milvus collection already has rows, the command skips indexing and keeps the existing data. This also applies to the index step of `opencrane build`. As a result, after a documentation update, `opencrane build` leaves the old data in Milvus.

> [!CAUTION]
> After an OpenCrane upgrade, `opencrane index` can delete and rebuild the collection. On a Milvus server that an MCP server already uses, searches fail until the rebuild finishes.

When the collection lacks fields that the current OpenCrane version needs, the command drops and rebuilds the collection automatically.

The command reads the chunks and embeddings from the paths in the `AI_DOCS_CHUNKS_FILE` and `AI_DOCS_EMBEDDINGS_FILE` environment variables, by default `.opencrane/chunks.json` and `.opencrane/embeddings.json`.

> [!CAUTION]
> `DROP_EXISTING=true` deletes the Milvus collection before the command rebuilds it. On a Milvus server that an MCP server already uses, searches fail until the rebuild finishes. Before you run the command, confirm that `MILVUS_COLLECTION` and the connection variables point to the collection that you want to replace. The connection variables are `MILVUS_DB_PATH` in Lite mode, or `MILVUS_HOST` and `MILVUS_PORT` in server mode.

To replace the existing data, set `DROP_EXISTING=true`:

```bash
DROP_EXISTING=true opencrane index
```

#### Start the MCP server with `opencrane serve`

The `opencrane serve` command starts the MCP server. It has the following syntax:

```bash
opencrane serve [--config {MODULE}:{CLASS}] [--transport stdio|http]
```

The `--transport` flag accepts the following values:

| Value | Description |
|---|---|
| `stdio` | Default. Standard input and output (stdio) transport for local MCP clients. At startup, the server prints integration instructions for Claude Code, Cursor, Windsurf, VS Code, Zed, Amazon Q, and Docker or Podman. |
| `http` | HTTP transport on port 8000, using Streamable HTTP in stateless mode. The MCP endpoint is `http://localhost:8000/mcp`. Docker and Podman containers use this transport. The `MCP_HTTP_PORT` environment variable sets the port. |

The server always exposes the following MCP tools:

- `search_docs`: searches the indexed documentation
- `health`: returns the same report as the [health endpoint](#health-endpoint)

The server adds the following tools only when the index contains the chunk types they need:

| Tool | Description | Required chunk types |
|---|---|---|
| `get_list_members` | Returns every chunk of a Markdown list, in order. | List item |
| `get_table_members` | Returns every row chunk of a Markdown table, in order. | Table row |
| `get_yaml_definition` | Returns the full YAML definition behind a structured YAML chunk, for example a field of a Kubernetes CustomResourceDefinition. | CustomResourceDefinition, OpenAPI, or JSON Schema |
| `get_metadata_schema` | Describes the metadata fields of the chunks. | List item, table row, CustomResourceDefinition, OpenAPI, or JSON Schema |

The HTTP transport also exposes a health endpoint. For details, see [Health endpoint](#health-endpoint).

> [!IMPORTANT]
> Do not bind-mount the Milvus Lite database. Milvus Lite cannot open its `.db` file from a bind-mounted volume and fails with `Open local milvus failed`. Copy the database into the image with `COPY` instead. The generated `.opencrane/Dockerfile` does this in a dedicated build stage.

#### Package the server with `opencrane pack`

The `opencrane pack` command packages the built MCP server and its data into a standalone Python package that others can run with `uvx`. Before you pack, run `opencrane build`. The command packs `.opencrane/milvus.db` and `.opencrane/chunks.json` from these fixed paths. The command has the following syntax:

```bash
opencrane pack [--name {NAME}] [--output {PATH}] [--version {VERSION}]
```

The command accepts the following flags:

| Flag | Default | Description |
|---|---|---|
| `--name {NAME}` | none | Package name. Without this flag, the command prompts for the name. |
| `--output {PATH}` | `.opencrane/pack/` | Output directory for the package |
| `--version {VERSION}` | `1.0.0` | Package version |

To generate a wheel, the command needs the optional `build` Python package. To install it, run `pip install 'opencrane[pack]'`.

After you pack, share one of the following commands with the people who use the server:

```bash
# From PyPI (after publishing)
claude mcp add {SERVER_NAME} -- uvx {PACKAGE_NAME}

# From GitHub
claude mcp add {SERVER_NAME} -- uvx --from "git+https://github.com/{OWNER}/{PACKAGE_NAME}" {PACKAGE_NAME}

# From local path
claude mcp add {SERVER_NAME} -- uvx --from .opencrane/pack {PACKAGE_NAME}
```

The generated package includes the Milvus database and the chunks file, so the people you share it with don't need to rebuild anything. The server downloads the embedding model on the first search or `health` call.

When you pack updated documentation again, raise the version with `--version` above the previous one. Otherwise, `uvx` serves the package from its cache instead of pulling the new version.

#### Open the MCP Inspector with `opencrane inspect`

The `opencrane inspect` command opens the [MCP Inspector](https://github.com/modelcontextprotocol/inspector) web interface, connected to the server over stdio. Use the MCP Inspector to call the server's tools from a browser and check the results. The command starts the server as a local process, so you can test it before you build a container image. The command has the following syntax:

```bash
opencrane inspect [--config {MODULE}:{CLASS}]
```

The command requires `npx`, which comes with Node.js. The web interface is available at `http://localhost:5173`.

#### Compare a paragraph with the indexed documentation with `opencrane visualize`

The `opencrane visualize` command shows how close a paragraph is to the indexed chunks. Use it for the following checks:

- Detect duplicates: if the top neighbor has a very high similarity, the content you are writing might already exist.
- Find the right source: the per-source alignment chart shows which source has the closest existing content.
- Check new documentation: if the neighbors are a random mix of unrelated sources with low similarity, your paragraph does not match any existing documentation.

You can pass the paragraph as text, as a file, or through standard input:

```bash
opencrane visualize --text "{PARAGRAPH}"
opencrane visualize --file {PATH_TO_FILE}
echo "{PARAGRAPH}" | opencrane visualize
```

The command encodes the paragraph with the same model as the indexed chunks. It then renders an interactive HTML page with the following views side by side:

- Scatter: a projection of the indexed chunks, or of a random sample of them when you set `--sample`. The new paragraph is a highlighted diamond, and the chart draws a ring around each nearest neighbor.
- Local neighborhood: a projection of only the paragraph and its nearest neighbors. Because the projection uses only these points, the distances between the neighbors are meaningful.
- Per-source alignment: a horizontal bar chart of the highest similarity in each source, with a tick for the mean of its 30 closest chunks. The chart shows which source the paragraph is closest to.

The scatter view uses one of the following dimensionality-reduction methods:

- Principal component analysis (PCA)
- Uniform manifold approximation and projection (UMAP)
- t-distributed stochastic neighbor embedding (t-SNE)

The local neighborhood view always uses PCA.

The following table lists the main flags:

| Flag | Default | Description |
|---|---|---|
| `--method pca\|umap\|tsne` | `umap` | Dimensionality-reduction method |
| `--dim 2\|3` | `3` | Number of dimensions of the scatter view |
| `--viz scatter\|neighbors\|sources\|all` | `all` | Views to render |
| `--sample {N}` | `0` (all chunks) | Limits the scatter view to `{N}` randomly sampled chunks. The scatter view always includes the nearest neighbors. If the browser slows down, or if UMAP or t-SNE is too slow, use a smaller `{N}`. The neighbor search always runs on all chunks. |
| `--neighbors {K}` | `12` | Number of nearest neighbors to highlight |
| `--seed {N}` | `42` | Random seed for sampling and for the dimensionality-reduction methods, for repeatable output |
| `--embeddings-file {PATH}` | `.opencrane/embeddings.json` | Embeddings to place the paragraph against |
| `--chunks-file {PATH}` | `.opencrane/chunks.json` | Chunks that match the embeddings |
| `--output {PATH}` | `.opencrane/visualization.html` | Output path for the HTML page |
| `--no-open` | Off | Does not open the HTML page in a browser |

The command requires the optional `viz` extra, which adds the following packages:

- plotly
- scikit-learn
- umap-learn

To install the `viz` extra, run the following command:

```bash
pip install 'opencrane[viz]'
```

### Health endpoint

The HTTP transport of `opencrane serve` exposes `GET /health` for the liveness and readiness probes of a container platform, for example Cloud Run. The endpoint reports the following checks:

- Embedding service and Milvus service state
- Collection statistics, such as the row count
- A test search for one result, with a timeout
- Free memory, read from the cgroup
- Whether the keyword search index, which uses the Best Matching 25 (BM25) ranking function, is already loaded in memory

The overall `status` is the worst status of the individual checks. The following table lists the statuses:

| `status` | HTTP code | Meaning |
|---|---|---|
| `healthy` | `200` | Serving queries normally |
| `degraded` | `200` | Still serving, but a check found a problem: a slow probe, low memory headroom, or missing collection stats |
| `unhealthy` | `503` | Cannot serve a query, because a service is down or the probe failed or timed out |
| `initializing` | `503` | Services are still loading at startup |

The following example shows a response with the `200` status code:

```json
{
  "status": "healthy",
  "checks": {
    "embeddings_service": "healthy",
    "milvus_service": "healthy",
    "collection_stats": { "row_count": 1234 },
    "heavy_maps": {
      "keyword_index_resident": true
    },
    "memory": {
      "source": "cgroup_v2",
      "used_bytes": 536870912,
      "limit_bytes": 2147483648,
      "headroom_pct": 75.0,
      "status": "healthy"
    },
    "query_probe": {
      "status": "healthy",
      "latency_ms": 143.7
    }
  }
}
```

When OpenCrane finds no readable cgroup memory files, for example outside a container, `memory.status` is `unavailable` and the response leaves out the byte fields. The `health` MCP tool returns the same report. To tune the probe and the memory threshold, use the [health check environment variables](#variables-for-the-health-check).

To use the endpoint on a container platform, configure the probes as follows:

- Point the liveness and readiness probes at `GET /health` on port 8000.
- Set the startup or initial delay long enough for the embedding model to load. Until the model loads, `/health` returns `503 initializing`.
- Use a long liveness period, so that the probe does not run a real search every few seconds.

### Default file and directory names

To override a default for one run, use the CLI flag. To override it persistently, set the environment variable. CLI flags take precedence over environment variables. The following table lists the default files and directories of the pipeline:

| File or directory | Default | CLI flag | Environment variable |
|---|---|---|---|
| Fetched documentation | `.opencrane/sources` | none | `TARGET_DIR` |
| Output directory for `llms-full.txt` | `.opencrane/llmstxt` | `--llmstxt-dir` | `AI_DOCS_LLMSTXT_DIR` |
| Chunks file | `.opencrane/chunks.json` | `--chunks-file` | `AI_DOCS_CHUNKS_FILE` |
| Embeddings file | `.opencrane/embeddings.json` | `--embeddings-file` | `AI_DOCS_EMBEDDINGS_FILE` |
| Token report output | `.opencrane/llmstxt/README.md` | `--output-file` | `TOKEN_OUTPUT_FILE` |
| Source mapping file | `.opencrane/config.yaml` | none | `MAPPING_FILE` |
| Milvus database file (Lite mode) | `.opencrane/milvus.db` | none | `MILVUS_DB_PATH` |

### Environment variables

Environment variables set persistent defaults, for example in a CI/CD pipeline. The following sections list the variables for each pipeline step and for the health check.

#### Variables for the `fetch` and `llms` steps

The `fetch` and `llms` steps share the following variable for source tracking:

| Variable | Default | Description |
|---|---|---|
| `MAPPING_FILE` | `.opencrane/config.yaml` | Path to the source mapping file. The `fetch` step records the fetched repositories in it. The `llms` step uses it to build the source URL of each page in the companion `llms.txt` index. The MCP server also reads it. |

#### Variables for the `fetch` step

You need the following variables only if you run the `fetch` step, directly or through `opencrane build`, to pull documentation from GitHub:

| Variable | Default | Description |
|---|---|---|
| `ORG_NAME` | none | GitHub organization to auto-discover repositories from. Auto-discovery runs only when `AUTO_DISCOVERY_ORGS` also lists the organization. The `--org` flag adds the organization to `AUTO_DISCOVERY_ORGS`. |
| `FETCH_REPO` | none | Limits the fetch to one or more sources, by their key under `sources:`, as a comma-separated list. See also the `--source` flag. |
| `GITHUB_TOKEN` | none | GitHub API token. Required: `opencrane fetch` fails without it. |
| `DOCS_TOPIC` | `documentation` | GitHub topic that marks the repositories of an organization for auto-discovery |
| `AUTO_DISCOVERY_ORGS` | none | Comma-separated list of the organizations where topic-based auto-discovery runs |
| `TARGET_DIR` | `.opencrane/sources` | Local directory where OpenCrane stores the fetched documentation |

#### Variables for the `llms` step

You need the following variables only if you run the `llms` step, directly or through `opencrane build`:

| Variable | Default | Description |
|---|---|---|
| `AI_DOCS_SOURCES_DIRS` | none | Comma-separated list of source directories to process. See also the `--sources-dir` flag. When the variable is empty, the `llms` step processes the sources listed in the source mapping file. |
| `AI_DOCS_LLMSTXT_DIR` | `.opencrane/llmstxt` | Output directory for the generated `llms-full.txt` files. See also the `--llmstxt-dir` flag. |

#### Variables for the `tokens` step

You need the following variables only if you use `opencrane tokens`:

| Variable | Default | Description |
|---|---|---|
| `TOKEN_SOURCE_DIR` | `.opencrane/llmstxt` | Directory with the `llms-full.txt` files to count. See also the `--source-dir` flag. |
| `TOKEN_OUTPUT_FILE` | `.opencrane/llmstxt/README.md` | Output path for the Markdown report. See also the `--output-file` flag. |

#### Variables for the `chunk` step

You need the following variables only if you run the `chunk` step, directly or through `opencrane build`:

| Variable | Default | Description |
|---|---|---|
| `AI_DOCS_LLMSTXT_DIR` | `.opencrane/llmstxt` | Directory with the `llms-full.txt` files. See also the `--llmstxt-dir` flag. |
| `AI_DOCS_CHUNKS_FILE` | `.opencrane/chunks.json` | Output path for the generated chunks. See also the `--chunks-file` flag. |

#### Variables for the `embed` step

You need the following variables only if you run the `embed` step, directly or through `opencrane build`:

| Variable | Default | Description |
|---|---|---|
| `AI_DOCS_CHUNKS_FILE` | `.opencrane/chunks.json` | Input chunks JSON file. See also the `--chunks-file` flag. |
| `AI_DOCS_EMBEDDINGS_FILE` | `.opencrane/embeddings.json` | Output path for the generated embeddings. See also the `--embeddings-file` flag. |
| `EMBEDDING_MODEL` | `nomic-ai/nomic-embed-text-v1.5` | Hugging Face embedding model to use |

#### Variables for the `index` and `serve` steps

You need the following variables when you load data into Milvus or run the MCP server. OpenCrane supports two Milvus modes:

- Lite mode: the default. Milvus Lite stores the data in a local file at `.opencrane/milvus.db` and needs no server.
- Server mode: a separate Milvus server. To use it, set `MILVUS_DB_PATH` to an empty string, and set `MILVUS_HOST` and `MILVUS_PORT`.

The following table lists the variables:

| Variable | Default | Description |
|---|---|---|
| `MILVUS_DB_PATH` | `.opencrane/milvus.db` | Path to the Milvus Lite database file. To connect to a Milvus server through `MILVUS_HOST` and `MILVUS_PORT`, set it to an empty string. |
| `MILVUS_HOST` | `localhost` | Milvus server host, in server mode only |
| `MILVUS_PORT` | `19530` | Milvus server port, in server mode only |
| `MILVUS_COLLECTION` | `ai_docs_chunks_v1` | Milvus collection name |
| `AI_DOCS_CHUNKS_FILE` | `.opencrane/chunks.json` | Chunks file that `index` loads and that the MCP server reads for keyword search. `index` reads only this variable, not the `--chunks-file` flag. |
| `AI_DOCS_EMBEDDINGS_FILE` | `.opencrane/embeddings.json` | Embeddings file that `index` loads. `index` reads only this variable, not the `--embeddings-file` flag. |
| `MILVUS_INSERT_BATCH_SIZE` | `2000` | Maximum number of chunks in each insert call during `index`. This limit keeps each call short enough to finish before the Milvus keepalive timeouts. A timeout makes the client retry, and the retries duplicate rows. If `index` creates duplicate rows, lower this value. |
| `HYBRID_ALPHA` | `0.6` | Weight of vector search compared to keyword search. `1.0` is pure vector search, and `0.0` is pure BM25 keyword search. |
| `DROP_EXISTING` | `false` | When `true`, `index` deletes and rebuilds the Milvus collection. Without it, `index` skips a collection that already has rows. See [`opencrane index`](#index-the-embeddings-in-milvus-with-opencrane-index). |

#### Variables for the health check

The following variables tune the search probe and the memory threshold of the [health endpoint](#health-endpoint). All of them are optional.

| Variable | Default | Description |
|---|---|---|
| `OPENCRANE_HEALTH_PROBE_QUERY` | `documentation` | Query for the search probe |
| `OPENCRANE_HEALTH_PROBE_TIMEOUT` | `10` | Hard timeout for the probe, in seconds. A probe that exceeds it reports `unhealthy`. |
| `OPENCRANE_HEALTH_PROBE_BUDGET` | `2` | Soft latency budget, in seconds. A probe that succeeds but takes longer reports `degraded`. |
| `OPENCRANE_HEALTH_MEM_WARN_HEADROOM` | `0.15` | Minimum fraction of free memory. Below it, the memory check reports `degraded`. |

### Source mapping file

The source mapping file, `.opencrane/config.yaml`, lists the documentation sources under the `sources:` key. For each source, it records the location of the documentation and the URL of the published documentation site. The same file also holds other project settings, for example `section_anchor_style`. For details, see [Source mapping file](docs/source-mapping.md).

The following steps use the file:

- `fetch`: tracks the fetched repositories
- `llms`: builds the companion `llms.txt` index with the source URL of each page

The `fetch` step fills in the file automatically. For sources that you manage yourself, edit the file directly.

Each entry under `sources:` supports the following fields:

| Field | Required | Description |
|---|---|---|
| `url` | Yes, for `fetch` | GitHub repository URL. `opencrane fetch` uses it to download the documentation and to build the GitHub source URL of each page in the companion `llms.txt` index. For a `type: llmstxt` source, the URL or local path of the `llms-full.txt` file. |
| `docs_path` | No | Path to the documentation in the repository, for example `docs` |
| `docs_url` | No | Base URL of the published documentation site, for example `https://docs.example.com/product`. When it is set, OpenCrane builds the page URLs from it instead of from `url`. AI agents can then point users to the rendered documentation instead of the raw GitHub files. |
| `manual` | No | When `true`, you manage the entry yourself, and `opencrane fetch` auto-discovery does not overwrite it. The `opencrane add` command sets this field. |
| `local` | No | When `true`, the key of the entry under `sources:` is the path to a local directory in the project. `opencrane fetch` skips the entry, and the pipeline reads directly from that path. |
| `type` | No | `llmstxt` for an existing `llms-full.txt` file. Without this field, the entry is a GitHub repository. |
| `branch` | No | Branch to pin the source to, for example `develop` |
| `tag` | No | Git tag to pin the source to, for example `v2.1.0` |
| `release` | No | GitHub release to pin the source to, by its tag name, for example `v2.1.0`. OpenCrane validates it through the Releases API. |
| `sha` | No | Commit SHA to pin the source to |

For a `type: llmstxt` source without a companion `llms.txt`, every page in the bundle gets `docs_url` as its base URL. If neither `url` nor `docs_url` is set, chunks from the source get no `source_url`.

By default, `opencrane fetch` pulls from the latest GitHub release. If a repository has no releases, `opencrane fetch` uses the default branch.

To pin a source to a specific Git ref instead, set one of the `branch`, `tag`, `release`, or `sha` fields. OpenCrane applies a pin only to entries with `manual: true`. Set only one of these fields. If you set several, OpenCrane logs a warning and uses the first one in the following order:

1. `sha`
2. `tag`
3. `release`
4. `branch`

The following example pins a manually managed source to a tag:

```yaml
sources:
  my-product:
    url: https://github.com/myorg/my-product
    docs_path: docs
    docs_url: https://docs.example.com/my-product
    manual: true
    tag: v2.1.0
```

## Extend OpenCrane

To register extensions for your project, subclass `OpenCraneConfig`, as in the following example:

```python
# myproject/config.py
from opencrane import OpenCraneConfig
from opencrane.fences import CodeFenceConfig, inline_file
from opencrane.rag.services.yaml_chunker import YamlChunkingStrategy
from opencrane.rag.services.code_chunker import CodeChunkingStrategy
from opencrane.rag.services.table_chunker import TableChunkingStrategy
from opencrane.rag.services.list_chunker import ListChunkingStrategy
from opencrane.rag.services.prose_chunker import ProseChunkingStrategy
from myproject.strategies.custom import CustomChunkingStrategy
from myproject.walkers.terraform import TerraformTreeWalker

class MyConfig(OpenCraneConfig):
    fence_types = {
        **OpenCraneConfig.fence_types,  # keep openapi, asyncapi, crd, json-schema
        "terraform": CodeFenceConfig(fence_type="terraform", handler=inline_file),
    }
    chunking_strategies = [
        YamlChunkingStrategy(),
        CustomChunkingStrategy(),
        CodeChunkingStrategy(),
        TableChunkingStrategy(),
        ListChunkingStrategy(),
        ProseChunkingStrategy(),
    ]
    yaml_tree_walkers = [
        *OpenCraneConfig.yaml_tree_walkers,  # keep CRD, OpenAPI, JSON Schema
        TerraformTreeWalker,
    ]
```

To use the subclass, pass it to the `--config` flag:

```bash
opencrane build --config myproject.config:MyConfig
```

OpenCrane tries the chunking strategies in list order and uses the first one that matches the content. Put a custom strategy before the general strategies that would otherwise match first.

### Extension points

Each extension point is an attribute or a method of `OpenCraneConfig`. The following table lists the pipeline step that uses each one:

| Extension point | Pipeline step | Description |
|---|---|---|
| `fence_types` | `llms` | Registers custom fence language identifiers and controls how OpenCrane transforms matching blocks during `llms-full.txt` generation. |
| `chunking_strategies` | `chunk` | Adds or replaces chunking strategies for different content types. |
| `yaml_tree_walkers` | `chunk` | Adds walkers for custom YAML document formats. |
| `section_anchor_for` | `chunk` | Builds the in-page anchor that each chunk records in its `section_anchor` metadata. |
| `middleware` | `serve` | Adds Asynchronous Server Gateway Interface (ASGI) middleware around the HTTP MCP server, for example for custom authorization. See [Authentication and authorization](#authentication-and-authorization). |
| `token_verifier`, `auth_provider` | `serve` | Replaces token validation or the authorization server in `custom` authentication mode. See [Authentication and authorization](#authentication-and-authorization). |

### Section anchors

Each chunk from a Markdown section records a `section_anchor` in its metadata. The value is the in-page anchor of the nearest heading above the chunk, at H2 or deeper. OpenCrane skips the page title (H1). The anchor is a slug: the URL fragment that the documentation site generates from the heading text. `source_url` holds the page URL without a fragment. MCP clients and AI agents build a direct link to the section by joining the two values:

```text
{source_url}#{section_anchor}
```

For example, a chunk under the "Who We Serve" heading of the About page gets `source_url: https://docs.example.com/guide/about` and `section_anchor: who-we-serve`. The direct link is `https://docs.example.com/guide/about#who-we-serve`. The `search_docs` results show the anchor on a `Section Anchor:` line, and `get_metadata_schema` documents it.

#### Choose an anchor style

To choose the slug style, set `section_anchor_style` in `.opencrane/config.yaml`. You don't need a config subclass for this setting. The setting accepts the following values:

- `generic`: builds GitBook-style and GitHub-style slugs. This is the default.
- `none`: turns section anchors off.

Any other value also turns section anchors off. The following example sets the default style:

```yaml
section_anchor_style: generic   # default: GitBook/GitHub-style slugs
# section_anchor_style: none    # disable section anchors entirely
```

#### Write a custom anchor builder

If your documentation host builds heading slugs in a different way, override `section_anchor_for` in your config subclass, for example the `Config` class in `.opencrane/extensions.py`. Your override receives the nearest heading. It must return the fragment slug without the `#`, or `None` to skip the anchor. The following example shows an override:

```python
from opencrane import OpenCraneConfig


class Config(OpenCraneConfig):
    def section_anchor_for(self, heading):
        if not heading:
            return None
        # Example: a host that lowercases and uses underscores instead of hyphens
        return heading.strip().lower().replace(" ", "_")
```

An override takes precedence over `section_anchor_style`.

### Built-in fence types

A fence type is the language identifier after the opening backticks of a code block, for example `openapi` in ```` ```openapi ````. `OpenCraneConfig` registers the following fence types by default:

- `openapi`
- `asyncapi`
- `crd`
- `json-schema`

Each type uses the `opencrane.fences.inline_file` handler. The handler reads the file path written inside the fence block and replaces the block with the file content. The path is relative to the Markdown file, and the file must be inside the project. If the file is missing or outside the project, the handler writes a `# Source missing` comment instead. The handler also adds a `### {source_url}` heading above the content, so the chunker assigns the source URL of each file to the resulting chunks.

The following Markdown example uses two of the built-in fence types:

````markdown
```openapi
path/to/openapi.json
```

```asyncapi
path/to/asyncapi.yaml
```
````

You don't need a config subclass to use these types. To keep these built-in types when you add your own, include `**OpenCraneConfig.fence_types` when you define `fence_types` in your config subclass. The example in [Extend OpenCrane](#extend-opencrane) shows how.

### Built-in YAML tree walkers

A YAML tree walker splits one kind of structured YAML document into chunks that follow the structure of the document. OpenCrane includes the following YAML tree walkers:

- `K8sCRDTreeWalker`: Kubernetes CustomResourceDefinitions
- `OpenAPITreeWalker`: OpenAPI 3.x specs
- `JsonSchemaTreeWalker`: JSON Schema documents

### Write a custom fence type

To add a fence type, register a fence language identifier and provide a `handler` function. The fence language identifier is the word after the opening backticks of a fence block. When the `llms` step finds a fence block of that type, OpenCrane calls your handler with the raw block content and the file context. OpenCrane then replaces the block with the string that the handler returns. The following example registers a handler for the `my-type` fence type:

```python
from pathlib import Path
from opencrane import OpenCraneConfig
from opencrane.fences import CodeFenceConfig

def my_handler(content: str, file_path: Path, project_dir: Path, project_name: str) -> str:
    # content:      raw text inside the fence block
    # file_path:    path of the Markdown file that contains the block
    # project_dir:  root directory of the project being processed
    # project_name: name of the project, used to build source URLs
    # return the full replacement string
    return f"```yaml\n# processed\n{content}\n```\n"

class MyConfig(OpenCraneConfig):
    fence_types = {
        **OpenCraneConfig.fence_types,
        "my-type": CodeFenceConfig(fence_type="my-type", handler=my_handler),
    }
```

To inline a file that the block references by path, use the built-in `inline_file` handler from `opencrane.fences`:

```python
from opencrane import OpenCraneConfig
from opencrane.fences import CodeFenceConfig, inline_file

class MyConfig(OpenCraneConfig):
    fence_types = {
        **OpenCraneConfig.fence_types,
        "my-type": CodeFenceConfig(fence_type="my-type", handler=inline_file),
    }
```

The `inline_file` handler works as described in [Built-in fence types](#built-in-fence-types).

### Write a custom YAML tree walker

To support a custom YAML document format, subclass `YamlTreeWalker`, as in the following example:

```python
from opencrane.walkers import YamlTreeWalker

class TerraformTreeWalker(YamlTreeWalker):
    @classmethod
    def can_handle(cls, doc: dict) -> bool:
        return "terraform" in doc

    def walk(self):
        # return List[Chunk]
        ...
```

The `can_handle` method returns `True` for the documents that the walker supports. The `walk` method returns the chunks of the document. To register the walker, add it to `yaml_tree_walkers`, as in the example in [Extend OpenCrane](#extend-opencrane).

## Authentication and authorization

The HTTP transport (`opencrane serve --transport http`) supports OAuth 2.1 authentication and scope-based authorization of content. The stdio transport has no authentication, following the MCP specification.

You choose the authentication mode with the `auth.type` key in `.opencrane/config.yaml`. Every mode needs the `PUBLIC_URL` environment variable, set to the public base URL of the server, except `oauth` with `allow_anonymous: true`. The following table lists the modes:

| Mode | Who issues the tokens | Configuration |
|---|---|---|
| `local` | OpenCrane acts as its own authorization server. When an MCP client starts authorization, OpenCrane redirects the browser to its `/login` form. | Set `auth.type: local` and `OPENCRANE_ACCESS_TOKEN`. For a username and password instead of a token, set `auth.local.method: password`, `OPENCRANE_LOGIN_USER`, and `OPENCRANE_LOGIN_PASS`. |
| `oauth` | An external identity provider, such as Keycloak or Microsoft Entra ID. OpenCrane is an OAuth resource server. | Install the `auth` extra with `pip install 'opencrane[auth]'`. Set `auth.type: oauth` with the OpenID Connect (OIDC) settings `oidc.issuer` and `oidc.audience`. |
| `custom` | Your own code, for full control over token validation or the authorization server. | Set `auth.type: custom`, and supply your own `token_verifier` or `auth_provider` on `OpenCraneConfig`. |

To limit which sources a caller can search, set `scope_sources`. It maps OAuth scopes to sets of documentation sources. Callers get content only from the sources that the scopes of their token allow.

For authorization that the configuration cannot express, register a custom ASGI middleware on your `OpenCraneConfig` subclass. Your middleware can call `set_allowed_sources(...)` from `opencrane.mcp.auth.runtime` to declare the sources that a request may access. For example, the middleware can get the allowed sources from an external permissions service.

The [authentication and authorization guide](docs/auth.md) has the full configuration reference, including the environment variables and a complete middleware example.

## Development

The following commands clone the repository and install the development dependencies with pip or with uv:

```bash
git clone https://github.com/derberg/OpenCrane.git
cd OpenCrane

# with pip
pip install -e ".[dev]"

# with uv
uv sync --extra dev
```

To run the tests, use the following command:

```bash
./pytest.sh
```

For more test options, see [Run the tests](docs/running-tests.md).

## Credits

OpenCrane started from a real-world use case at [Cennso](https://cennso.com): AI-powered search over telecommunications product documentation.

OpenCrane builds on the following open-source projects:

- [Milvus](https://milvus.io): vector database that runs the similarity search
- [Docling](https://github.com/docling-project/docling): document parsing and chunking
- [sentence-transformers](https://www.sbert.net): embedding generation
- [rank-bm25](https://github.com/dorianbrown/rank_bm25): keyword search with the BM25 ranking function, which complements vector similarity search
- [Model Context Protocol](https://modelcontextprotocol.io): the protocol that lets AI clients call the search tools

## License

OpenCrane uses the Apache License 2.0. For the full text, see [LICENSE](LICENSE).
