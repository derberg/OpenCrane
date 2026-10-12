"""Templates for opencrane init command."""

EXTENSIONS_PY = '''\
from opencrane import OpenCraneConfig
# Uncomment the imports that your chosen examples need:
# from opencrane import ExtraTool
# from opencrane.fences import CodeFenceConfig


class Config(OpenCraneConfig):
    """Project-specific OpenCrane configuration.

    OpenCrane loads this class when the `extensions` key in config.yaml
    names this file, or when --config or OPENCRANE_CONFIG passes its path.
    The class must be named Config.
    For all extension points with examples, see
    https://github.com/derberg/OpenCrane#extend-opencrane
    """

    # Fence-block handlers for llms-full.txt generation. A handler receives
    # the block content, the Markdown file path, the project root, and the
    # project name, and returns the text that replaces the block. A plain
    # dict replaces the built-in fence types (openapi, asyncapi, crd,
    # json-schema), so unpack them as in this example to keep them.
    # fence_types = {
    #     **OpenCraneConfig.fence_types,
    #     "terraform": CodeFenceConfig(fence_type="terraform", handler=my_terraform_handler),
    # }

    # Chunking strategies, as ProcessingStrategy instances. OpenCrane uses
    # the first strategy that accepts a block, so list yours first.
    # chunking_strategies = [MyTabsStrategy(), *OpenCraneConfig.chunking_strategies]

    # YAML tree walkers, as YamlTreeWalker subclasses from opencrane.walkers.
    # List the classes, not instances.
    # yaml_tree_walkers = [*OpenCraneConfig.yaml_tree_walkers, MyCustomWalker]

    # Section-anchor slugs. Override this method when no
    # `section_anchor_style` value in config.yaml matches the anchors of your
    # docs host. The override takes precedence over that setting. Return None
    # to record no anchor.
    # def section_anchor_for(self, heading):
    #     if not heading:
    #         return None
    #     # For example, a host that keeps case and uses underscores:
    #     return heading.strip().replace(" ", "_")

    # Custom MCP tools, served next to the built-in tools. OpenCrane does not
    # filter their output. If you restrict the sources a caller can read,
    # call context.allowed_sources() in each handler that returns
    # documentation. For a complete handler, see
    # https://github.com/derberg/OpenCrane#add-custom-mcp-tools
    # extra_tools = [
    #     ExtraTool(
    #         name="read_chunk",
    #         description="Returns the full stored content of a chunk by its ID.",
    #         input_schema={"type": "object",
    #                       "properties": {"chunk_id": {"type": "string"}},
    #                       "required": ["chunk_id"]},
    #         handler=read_chunk,  # your function: read_chunk(arguments, context)
    #     ),
    # ]
'''

CONFIG_YAML = '''\
# OpenCrane configuration
# To add sources interactively instead of editing this file, run `opencrane add`.

# Directory names to exclude from llms-full.txt generation, for all sources.
# The ignore_patterns list of a source adds to this list.
ignore_patterns:
  - devel

# Optional: Python file with your Config class, relative to .opencrane/.
# OpenCrane ignores extensions.py until this key names it, or until
# --config or OPENCRANE_CONFIG passes its path.
# To create a starter file, run `opencrane init --extensions`.
# extensions: extensions.py

# Optional: section anchors. Each Markdown sub-section chunk records a
# `section_anchor` (the in-page slug of its heading), so a client can link to
# `{source_url}#{section_anchor}`. `generic` (the default) matches GitBook and
# GitHub slugs. `none` records no anchors. For another slug rule, override
# `section_anchor_for` in extensions.py.
# section_anchor_style: generic

# Optional: clause IDs for the MCP `get_section` tool. Each prose chunk takes
# its `clause_id` from the start of its section heading, for example `5.4.1.2a`
# or `Annex C`. By default, OpenCrane recognizes numbered headings and annexes.
# For another rule, set a regular expression whose first capture group is the
# ID. To record no clause IDs, set `none`.
# section_clause_pattern: none

# Documentation sources, keyed by source name.
#
# GitHub repository example:
#   external-sources/my-repo:
#     url: https://github.com/my-org/my-repo
#     docs_path: docs     # folder to fetch (default `docs`); an empty string fetches the repo root
#     docs_url: https://docs.example.com  # optional: published site, for page links
#     tag: v1.2.0         # optional: pin to one sha, tag, release, or branch
#     manual: true        # true: always fetch; false: fetch only when auto-discovery finds the repo
#     ignore_patterns:    # optional: added to the global ignore_patterns
#       - internal
#
# Pre-existing llms-full.txt example:
#   example-docs:
#     type: llmstxt
#     url: https://docs.example.com/llms-full.txt  # URL or local file path
#     docs_url: https://docs.example.com  # optional: published site, for page links
#     manual: true

sources:
'''

DOCKERFILE = '''\
# syntax=docker/dockerfile:1.4
# Multi-stage build for OpenCrane MCP Server with embedded Milvus Lite
# Optimized for fast rebuilds when only Python code or data changes
# Generated by: opencrane init

# =============================================================================
# Stage 1: Dependencies (cached unless opencrane version changes)
# =============================================================================
FROM python:3.11-slim AS deps

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \\
    gcc \\
    g++ \\
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/root/.cache/pip \\
    pip install opencrane

# =============================================================================
# Stage 2: Model download (cached unless EMBEDDING_MODEL or RERANKER_MODEL changes)
# =============================================================================
FROM deps AS model

ARG EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL}
# Optional reranker. The runtime image is offline, so the model must be baked in.
ARG RERANKER_MODEL=

RUN --mount=type=cache,target=/root/.cache/huggingface \\
    echo "Downloading embedding model..." && \\
    python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer(\'${EMBEDDING_MODEL}\', trust_remote_code=True)" && \\
    if [ -n "${RERANKER_MODEL}" ]; then \\
        echo "Downloading reranker model..." && \\
        python3 -c "from sentence_transformers import CrossEncoder; CrossEncoder(\'${RERANKER_MODEL}\', trust_remote_code=True)"; \\
    fi && \\
    mkdir -p /build/hf_cache && cp -r /root/.cache/huggingface /build/hf_cache/

# =============================================================================
# Stage 3: Milvus init (bake vector database into image at build time)
# =============================================================================
FROM deps AS milvus

WORKDIR /build

COPY .opencrane/ ./.opencrane/

ENV MILVUS_DB_PATH=/build/milvus_data/milvus.db
ENV COLLECTION_NAME=opencrane_chunks
ENV DROP_EXISTING=true
ENV PYTHONPATH=/build

RUN mkdir -p /build/milvus_data && opencrane index

# =============================================================================
# Stage 4: Final runtime image
# =============================================================================
FROM python:3.11-slim

ARG RERANKER_MODEL=

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY --from=model /build/hf_cache/huggingface /root/.cache/huggingface

COPY --from=milvus /build/milvus_data /app/milvus_data

COPY .opencrane/ /app/.opencrane/

ENV MILVUS_DB_PATH=/app/milvus_data/milvus.db
ENV COLLECTION_NAME=opencrane_chunks
ENV MCP_HTTP_PORT=8000
ENV PYTHONUNBUFFERED=1
ENV TRANSFORMERS_OFFLINE=1
ENV RERANKER_MODEL=${RERANKER_MODEL}

EXPOSE 8000

ENTRYPOINT ["opencrane", "serve", "--transport", "http"]
'''

DOCKER_COMPOSE = '''\
# Generated by: opencrane init
services:
  opencrane-mcp:
    build:
      context: ..
      dockerfile: .opencrane/Dockerfile
      args:
        EMBEDDING_MODEL: "${EMBEDDING_MODEL:-nomic-ai/nomic-embed-text-v1.5}"
        RERANKER_MODEL: "${RERANKER_MODEL:-}"
    ports:
      - "8000:8000"
    environment:
      MILVUS_DB_PATH: /app/milvus_data/milvus.db
      COLLECTION_NAME: opencrane_chunks
      EMBEDDING_QUERY_PROMPT: "${EMBEDDING_QUERY_PROMPT:-}"
'''

README_MD = '''\
# .opencrane

This directory holds the OpenCrane configuration of this project and the files that the pipeline generates.

## Directory contents

The following table lists the files in this directory and whether to commit them:

| Path | Description | Commit |
|---|---|---|
| `config.yaml` | Sources, ignore patterns, and other settings | Yes |
| `extensions.py` | Optional Python extensions, created by `opencrane init --extensions` | Yes |
| `Dockerfile` or `Containerfile`, `docker-compose.yml` | Container build for the HTTP Model Context Protocol (MCP) server | Yes |
| `sources/`, `llmstxt/` | Fetched sources and generated `llms-full.txt` files | Optional |
| `chunks.json`, `embeddings.json` | Chunks and their embedding vectors, which `opencrane index` loads | Yes, if a continuous integration (CI) pipeline builds the container image |
| `milvus.db` | Milvus Lite database that `opencrane index` writes | No, the image build creates its own |

## Build and serve the index

The `build` command needs the `pipeline` extra, which `pip install 'opencrane[pipeline]'` installs.

> [!CAUTION]
> The fetch step of `opencrane build` deletes the fetched files of every auto-discovered source that auto-discovery no longer returns. To keep a source, set `manual: true` on its entry in `config.yaml`. See [How the fetch removes stale sources](https://github.com/derberg/OpenCrane/blob/main/docs/fetching.md#how-the-fetch-removes-stale-sources).

To build the index and start the server, run the following commands:

```bash
# 1. Add documentation sources interactively
opencrane add

# 2. Run the pipeline: fetch, llms, chunk, embed, and index
opencrane build

# 3. Start the MCP server over stdio
opencrane serve
```

`opencrane serve` prints how to connect common MCP clients. To test the tools in a browser, run `opencrane inspect`, which needs Node.js.

## Run the server in a container

The container image serves MCP over HTTP on port 8000. The image build creates the Milvus Lite database inside the image, so the container starts without indexing. If you ran `opencrane init --podman`, first change the `dockerfile` value in `docker-compose.yml` to `.opencrane/Containerfile`.

To build and start the container, run the following command from the project root:

```bash
{container_tool}-compose -f .opencrane/docker-compose.yml up --build
```

To change the embedding model, set the `EMBEDDING_MODEL` environment variable before the build, so the image contains the model. Also add `EMBEDDING_MODEL` to the `environment` section of `docker-compose.yml`, because the server reads it at runtime. Use the model that `opencrane embed` used, because the server embeds search queries with it. To add the optional reranker model to the image, set `RERANKER_MODEL` the same way.

> [!CAUTION]
> Do not mount a volume over `/app/milvus_data`. Milvus Lite cannot open a database file on a bind mount and fails with `Open local milvus failed`. Use the database that the image build creates.

### Configure health checks

The server answers `GET /health` on port 8000. Each request runs a real search query and checks the free memory. The endpoint returns `200` when the instance can serve (`healthy` or `degraded`), and `503` when it cannot (`unhealthy`, or `initializing` while the services load).

Point the liveness and readiness probes of your platform, for example Kubernetes or Cloud Run, at `/health`. Give the startup probe enough time for the model to load. Use a long liveness period, because every probe runs a search.

### Build and publish the image

To build, push, and run the image, run the following commands from the project root. If you ran `opencrane init --podman`, the build file is `.opencrane/Containerfile`.

```bash
{container_tool} build -t {REGISTRY}/opencrane-mcp:latest -f .opencrane/Dockerfile .
{container_tool} push {REGISTRY}/opencrane-mcp:latest
{container_tool} run -p 8000:8000 {REGISTRY}/opencrane-mcp:latest
```

### Connect an MCP client over HTTP

The MCP endpoint of the container is `http://localhost:8000/mcp`. To add the endpoint to Claude Code, run the following command:

```bash
claude mcp add opencrane --transport http http://localhost:8000/mcp
```

To add the endpoint to Cursor, add the following entry to `mcp.json`:

```json
{
  "mcpServers": {
    "opencrane": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

## Commands

`opencrane build` runs the pipeline steps from `fetch` to `index` in order. To repeat one step, for example to chunk again after a configuration change without a new fetch, run that step alone. The following table lists the commands:

| Command | Description |
|---|---|
| `opencrane add` | Adds documentation sources interactively |
| `opencrane fetch` | Downloads the GitHub and llms-full.txt sources |
| `opencrane llms` | Generates the `llms-full.txt` files and their `llms.txt` index |
| `opencrane chunk` | Splits the documentation into chunks |
| `opencrane embed` | Generates an embedding vector for each chunk |
| `opencrane index` | Loads the chunks and vectors into Milvus |
| `opencrane serve` | Starts the MCP server over stdio, or over HTTP on port 8000 with `--transport http` |
| `opencrane inspect` | Opens the MCP Inspector web UI, connected to the server |
| `opencrane pack` | Packages the server and its data for `uvx` |
| `opencrane tokens` | Writes a token count report for the `llms-full.txt` files |
| `opencrane visualize` | Writes an HTML map of the embeddings, and needs the `viz` extra |
'''

PACK_MAIN_PY = '''\
"""MCP server with bundled documentation data."""
import os
from pathlib import Path


def main():
    data_dir = Path(__file__).parent / "data"
    os.environ.setdefault("MILVUS_DB_PATH", str(data_dir / "milvus.db"))
    os.environ.setdefault("AI_DOCS_CHUNKS_FILE", str(data_dir / "chunks.json"))

    import asyncio
    from opencrane.mcp.server import main as serve_main
    asyncio.run(serve_main())


if __name__ == "__main__":
    main()
'''

PACK_PYPROJECT = '''\
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "{name}"
version = "{version}"
description = "MCP server for documentation search — built with OpenCrane"
requires-python = ">=3.11"
dependencies = [
    "opencrane>={opencrane_version}",
{extra_deps}]

[project.scripts]
{name} = "{module_name}.__main__:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["{module_name}*"]

[tool.setuptools.package-data]
{module_name} = ["data/**"]
'''

PACK_README = '''\
# {name}

This package is a Model Context Protocol (MCP) server for documentation search, built with [OpenCrane](https://github.com/derberg/OpenCrane). It contains the search index, so it needs no build step.

## Use the package locally

To add the server to Claude Code from this directory, run the following command:

```bash
claude mcp add {name} -- uvx --from {{PATH_TO_THIS_DIRECTORY}} {name}
```

## Share the package through GitHub

Push this directory to a GitHub repository. Others can then add the server with the following command:

```bash
claude mcp add {name} -- uvx --from "git+https://github.com/{{OWNER}}/{name}" {name}
```

## Share the package through PyPI

> [!CAUTION]
> `twine upload` publishes the package, including the search index of your documentation, on the public PyPI. PyPI does not accept the same version again, even after you delete it. Upload only documentation that anyone may read.

To build the package and upload it to PyPI, run the following commands in this directory:

```bash
pip install build twine
python -m build .
twine upload dist/*
```

Others can then add the server with the following command:

```bash
claude mcp add {name} -- uvx {name}
```

> [!NOTE]
> PyPI limits each file to 100 MB. If `milvus.db` is larger, share the package through GitHub or a local path.

> [!IMPORTANT]
> When you pack updated documentation again, increase the `--version` value. Otherwise, `uvx` serves its cached copy of the old version.

## Share the server as a container image

The container image builds from the OpenCrane project, not from this package. To build, push, and run the image, run the following commands from the project root:

```bash
docker build -t {{REGISTRY}}/{name}:latest -f .opencrane/Dockerfile .
docker push {{REGISTRY}}/{name}:latest
docker run -p 8000:8000 {{REGISTRY}}/{name}:latest
```

The MCP endpoint of the container is `http://localhost:8000/mcp`.

## Configure an MCP client

The following sections show the client settings for the stdio and HTTP transports.

### Connect over stdio with uvx

To add the server to Claude Code, run the following command:

```bash
claude mcp add {name} -- uvx {name}
```

To add the server to Cursor, add the following entry to `mcp.json`:

```json
{{
  "mcpServers": {{
    "{name}": {{
      "command": "uvx",
      "args": ["{name}"]
    }}
  }}
}}
```

To add the server to Zed, add the following entry to `settings.json`:

```json
{{
  "context_servers": {{
    "{name}": {{
      "command": {{
        "path": "uvx",
        "args": ["{name}"]
      }}
    }}
  }}
}}
```

### Connect over HTTP to the container

To add the container endpoint to Claude Code, run the following command:

```bash
claude mcp add {name} --transport http http://localhost:8000/mcp
```

To add the container endpoint to Cursor, add the following entry to `mcp.json`:

```json
{{
  "mcpServers": {{
    "{name}": {{
      "url": "http://localhost:8000/mcp"
    }}
  }}
}}
```
'''

def readme(podman: bool = False) -> str:
    tool = "podman" if podman else "docker"
    return README_MD.replace("{container_tool}", tool)
