"""Templates for opencrane init command."""

import importlib.metadata

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
# Stage 1: Dependencies (cached until `opencrane init --force` writes another
# opencrane version below)
# =============================================================================
FROM python:3.11-slim AS deps

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \\
    gcc \\
    g++ \\
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/root/.cache/pip \\
    pip install {opencrane_requirement}

# =============================================================================
# Stage 2: Embedding model
# The settings stage checks the build args against .opencrane/embeddings.json and
# writes /build/image.env, which the model download, the index build and the
# runtime entrypoint all source.
# =============================================================================
FROM deps AS settings

# EMBEDDING_MODEL defaults to the model that `opencrane embed` recorded in
# .opencrane/embeddings.json. The index records that model, and the server
# refuses to start with another one, so a different value fails the build.
# EMBEDDING_QUERY_PROMPT has no default: when unset, the server uses the query
# prompt that the index records. When set, even to empty, it must match the
# prompt in embeddings.json. EMBEDDING_TRUST_REMOTE_CODE and
# RERANKER_TRUST_REMOTE_CODE take true or false, and default to true only for
# nomic-ai/* models. An empty value of the other args counts as not set.
ARG EMBEDDING_MODEL=
ARG EMBEDDING_QUERY_PROMPT
ARG EMBEDDING_TRUST_REMOTE_CODE=
ARG EMBEDDING_DTYPE=
ARG EMBEDDING_DEVICE=
ARG RERANKER_MODEL=
ARG RERANKER_TRUST_REMOTE_CODE=

RUN --mount=type=bind,source=.opencrane,target=/build/.opencrane \\
    python3 -m opencrane.container_env .opencrane/embeddings.json /build/image.env

# Model download (cached unless the resolved settings or RERANKER_MODEL change)
FROM deps AS model

# Optional reranker. The runtime image is offline, so the model must be baked in.
ARG RERANKER_MODEL=

COPY --from=settings /build/image.env /build/image.env

RUN --mount=type=cache,target=/root/.cache/huggingface \\
    . /build/image.env && \\
    echo "Downloading embedding model ${EMBEDDING_MODEL}..." && \\
    python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer(\'${EMBEDDING_MODEL}\', trust_remote_code=\'${EMBEDDING_TRUST_REMOTE_CODE}\' == \'true\')" && \\
    if [ -n "${RERANKER_MODEL}" ]; then \\
        echo "Downloading reranker model..." && \\
        python3 -c "from sentence_transformers import CrossEncoder; CrossEncoder(\'${RERANKER_MODEL}\', trust_remote_code=\'${RERANKER_TRUST_REMOTE_CODE}\' == \'true\')"; \\
    fi && \\
    mkdir -p /build/hf_cache && cp -r /root/.cache/huggingface /build/hf_cache/

# =============================================================================
# Stage 3: Milvus init (bake vector database into image at build time)
# =============================================================================
FROM deps AS milvus

WORKDIR /build

COPY .opencrane/ ./.opencrane/
COPY --from=settings /build/image.env /build/image.env

ENV MILVUS_DB_PATH=/build/milvus_data/milvus.db
ENV MILVUS_COLLECTION=opencrane_chunks
ENV DROP_EXISTING=true
ENV PYTHONPATH=/build

RUN mkdir -p /build/milvus_data && . /build/image.env && opencrane index

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

# The server must encode queries with the model that built the index and that
# the image contains. The entrypoint sources these settings; a variable set at
# run time, for example with `docker run -e`, wins over the baked value.
COPY --from=settings /build/image.env /app/image.env

ENV MILVUS_DB_PATH=/app/milvus_data/milvus.db
ENV MILVUS_COLLECTION=opencrane_chunks
ENV MCP_HTTP_PORT=8000
ENV PYTHONUNBUFFERED=1
ENV TRANSFORMERS_OFFLINE=1
ENV RERANKER_MODEL=${RERANKER_MODEL}

EXPOSE 8000

ENTRYPOINT ["/bin/sh", "-c", ". /app/image.env && exec opencrane serve --transport http \\"$@\\"", "opencrane"]
'''

DOCKER_COMPOSE = '''\
# Generated by: opencrane init
services:
  opencrane-mcp:
    build:
      context: ..
      dockerfile: .opencrane/Dockerfile
      # A bare key passes the variable only when your shell sets it.
      # An unset EMBEDDING_MODEL means the model in .opencrane/embeddings.json.
      args:
        EMBEDDING_MODEL:
        EMBEDDING_QUERY_PROMPT:
        EMBEDDING_TRUST_REMOTE_CODE:
        EMBEDDING_DTYPE:
        EMBEDDING_DEVICE:
        RERANKER_MODEL: "${RERANKER_MODEL:-}"
        RERANKER_TRUST_REMOTE_CODE:
    ports:
      - "8000:8000"
    environment:
      MILVUS_DB_PATH: /app/milvus_data/milvus.db
      MILVUS_COLLECTION: opencrane_chunks
      # No value: passed from your shell when set, left unset otherwise so the
      # server uses the query prompt that the index records.
      EMBEDDING_QUERY_PROMPT:
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

The container image serves MCP over HTTP on port 8000. The image build creates the Milvus Lite database inside the image, so the container starts without indexing.

To build and start the container, run the following command from the project root:

```bash
{container_tool}-compose -f .opencrane/docker-compose.yml up --build
```

The image build reads the embedding model from `embeddings.json`, which records the model and the prompts that `opencrane embed` used. The image contains that model, and the index records the model and the prompts. The server embeds search queries with the recorded settings, so you do not need to set `EMBEDDING_MODEL` or `EMBEDDING_QUERY_PROMPT`. If you set either one before the build, it must match `embeddings.json`, or the build fails.

`EMBEDDING_TRUST_REMOTE_CODE` and `RERANKER_TRUST_REMOTE_CODE` set whether the build and the server run the code that a model ships. When unset, they are `true` for `nomic-ai/*` models and `false` for other models. To add the optional reranker model, set `RERANKER_MODEL` before the build. To pass these settings to `{container_tool} build`, use `--build-arg`, for example `--build-arg RERANKER_MODEL={RERANKER_MODEL_ID}`.

`EMBEDDING_DTYPE` and `EMBEDDING_DEVICE` set the precision and the device of the embedding model. Only the server uses them, so set them when you start the container, for example with `{container_tool} run -e EMBEDDING_DTYPE=bfloat16`. A build argument with the same name only sets the default value in the image. The compose file passes both from your shell as build arguments. A variable that you set when you start the container overrides the value from the build.

> [!CAUTION]
> Do not mount a volume over `/app/milvus_data`. Milvus Lite cannot open a database file on a bind mount and fails with `Open local milvus failed`. Use the database that the image build creates.

### Configure health checks

The server answers `GET /health` on port 8000. Each request runs a real search query and checks the free memory. The endpoint returns `200` when the instance can serve (`healthy` or `degraded`), and `503` when it cannot (`unhealthy`, or `initializing` when the services failed to load at startup).

The server loads the embedding model and its other services before it accepts connections. After that, `/health` returns `200` without a previous MCP request. Point the startup, readiness, and liveness probes of your platform, for example Kubernetes or Cloud Run, at `/health`. The first probe succeeds only after the model loads, so give the startup probe enough time for a large model. Use a long liveness period, because every probe runs a search.

### Build and publish the image

To build, push, and run the image, run the following commands from the project root:

```bash
{container_tool} build -t {REGISTRY}/opencrane-mcp:latest -f .opencrane/{container_file} .
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


def opencrane_requirement() -> str:
    """Return the pip requirement for the opencrane that renders the Dockerfile.

    The image needs at least this version, because the Dockerfile runs modules
    that older releases lack. The version in the requirement also changes the
    ``pip install`` line, so a rebuild does not reuse a cached layer that holds
    an older opencrane. A version that cannot be pinned, for example ``0.0.0``
    from a source checkout without metadata, gives the unpinned name.
    """
    try:
        from packaging.version import InvalidVersion, Version
    except ImportError:
        return "opencrane"
    try:
        version = Version(importlib.metadata.version("opencrane"))
    except (importlib.metadata.PackageNotFoundError, InvalidVersion):
        return "opencrane"
    if not any(version.release):
        return "opencrane"
    # A local label, such as +g1234abc, is not allowed in a >= specifier.
    return f'"opencrane>={version.public}"'


def dockerfile() -> str:
    """Render the Dockerfile with the opencrane version that writes it."""
    return DOCKERFILE.replace("{opencrane_requirement}", opencrane_requirement())


def docker_compose(dockerfile_name: str = "Dockerfile") -> str:
    """Render the compose file so its build points at the container file ``init`` wrote."""
    return DOCKER_COMPOSE.replace(
        "dockerfile: .opencrane/Dockerfile", f"dockerfile: .opencrane/{dockerfile_name}"
    )


def readme(podman: bool = False) -> str:
    tool, container_file = ("podman", "Containerfile") if podman else ("docker", "Dockerfile")
    return README_MD.replace("{container_tool}", tool).replace("{container_file}", container_file)


def config_yaml(extensions: bool = False) -> str:
    """Render config.yaml, with the ``extensions`` key enabled when ``init`` wrote extensions.py."""
    if not extensions:
        return CONFIG_YAML
    return CONFIG_YAML.replace("# extensions: extensions.py", "extensions: extensions.py")
