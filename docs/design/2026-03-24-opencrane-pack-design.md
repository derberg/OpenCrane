# Design: `opencrane pack`

## Problem

Users who build documentation search with OpenCrane locally have no simple way to share the resulting MCP server with teammates. Docker works but requires infrastructure. The ideal sharing experience is a one-liner that others paste into their Claude Code (or any MCP client) config.

## Solution

A new `opencrane pack` command that generates a standalone Python package bundling the built Milvus database, chunks, and a thin entry point that delegates to the existing OpenCrane MCP server. The package is distributable via PyPI, GitHub, or local path — and runnable via `uvx` for a zero-install experience.

## End-User Experience

After someone packs and publishes, others add the MCP with a single command:

```bash
# From PyPI
claude mcp add my-docs -- uvx my-docs-mcp

# From GitHub
claude mcp add my-docs -- uvx --from "git+https://github.com/you/my-docs-mcp" my-docs-mcp

# From local path
claude mcp add my-docs -- uvx --from /path/to/my-docs-mcp my-docs-mcp
```

Equivalent configs for Cursor, VS Code, Zed, and other MCP clients are documented in the generated README.

## CLI Interface

```
opencrane pack [--name NAME] [--output PATH] [--version VERSION]
```

| Flag | Behavior |
|---|---|
| (no flags) | Interactive prompt: "Package name (e.g. my-docs-mcp):" |
| `--name NAME` | Skip prompt, use provided name |
| `--output PATH` | Override output directory (default: `.opencrane/pack/<name>/`) |
| `--version VERSION` | Set package version (default: `1.0.0`). Important: bump when re-packing updated docs so `uvx` pulls the new version instead of using its cache. |

### Validation

Before generating, the command checks that required data files exist:
- `.opencrane/milvus.db`
- `.opencrane/chunks.json`

If missing, exits with: `Error: Required data files not found. Run 'opencrane build' first.`

### Name handling

The user-provided name (e.g. `my-docs-mcp`) is used as:
- The directory name under `.opencrane/pack/`
- The Python package name in `pyproject.toml` (hyphens converted to underscores for the module directory, per Python packaging conventions)
- The CLI entry point name (so `uvx my-docs-mcp` works)

Names are validated against PEP 508 conventions: must start with a letter, contain only alphanumerics/hyphens/underscores/dots. Invalid names produce an error with guidance.

### Overwrite behavior

If the output directory already exists, `opencrane pack` silently overwrites all generated files and data. No `--force` flag needed.

## Generated Package Structure

```
.opencrane/pack/my-docs-mcp/
├── pyproject.toml
├── my_docs_mcp/
│   ├── __init__.py
│   ├── __main__.py
│   └── data/
│       ├── milvus.db
│       ├── chunks.json
│       └── metadata-schema.md
├── dist/
│   └── my_docs_mcp-1.0.0-py3-none-any.whl
└── README.md
```

## Generated Files

### `__main__.py`

Sets environment variables pointing to the bundled data directory, then delegates to the existing OpenCrane MCP server. No new server code is generated.

```python
"""MCP server with bundled documentation data."""
import os
from pathlib import Path


def main():
    data_dir = Path(__file__).parent / "data"
    os.environ.setdefault("MILVUS_DB_PATH", str(data_dir / "milvus.db"))
    os.environ.setdefault("AI_DOCS_CHUNKS_FILE", str(data_dir / "chunks.json"))
    os.environ.setdefault("METADATA_SCHEMA_PATH", str(data_dir / "metadata-schema.md"))

    import asyncio
    from opencrane.mcp.server import main as serve_main
    asyncio.run(serve_main())


if __name__ == "__main__":
    main()
```

Key details:
- Uses `setdefault` so env vars can still be overridden at runtime
- Resolves `data_dir` from `__file__` so paths work regardless of CWD
- Imports opencrane lazily (after env vars are set) to ensure the MCP server picks up the bundled data paths

**Server change required**: `opencrane/mcp/server.py`'s `get_metadata_schema` handler currently uses hardcoded relative paths (`.opencrane/metadata-schema.md`, `docs/metadata-schema.md`). This must be updated to check the `METADATA_SCHEMA_PATH` env var first, falling back to the existing relative path logic. This is a small, backward-compatible change.

### `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "{name}"
version = "1.0.0"
description = "MCP server for documentation search — built with OpenCrane"
requires-python = ">=3.11"
dependencies = [
    "opencrane>={opencrane_version}",
]

[project.scripts]
{name} = "{module_name}.__main__:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["{module_name}*"]

[tool.setuptools.package-data]
{module_name} = ["data/**"]
```

- `{name}` — the package name as provided by the user (e.g. `my-docs-mcp`)
- `{module_name}` — Python-safe version with underscores (e.g. `my_docs_mcp`)
- `{opencrane_version}` — resolved via `importlib.metadata.version("opencrane")` (standard Python mechanism, works when opencrane is pip-installed)
- `package-data` uses `data/**` glob to include all files recursively

### `README.md`

Generated README explaining:
1. What this package is (MCP server for searching documentation)
2. How to use it locally (`uvx` from local path)
3. How to share via GitHub (push repo + `uvx --from git+...`)
4. How to share via PyPI (`pip install build && python -m build && twine upload dist/*`)
5. MCP client configuration snippets for: Claude Code, Cursor/Windsurf/VS Code, Zed, Amazon Q

### `__init__.py`

Empty file. Exists only to make the directory a Python package.

## Data Files Bundled

| File | Source | Purpose at runtime |
|---|---|---|
| `milvus.db` | `.opencrane/milvus.db` | Vector database for semantic search |
| `chunks.json` | `.opencrane/chunks.json` | BM25 keyword search index + YAML chunk re-hydration |
| `metadata-schema.md` | `docs/metadata-schema.md` | Returned by `get_metadata_schema` MCP tool |

`embeddings.json` is **not** bundled — the vectors are already indexed inside `milvus.db`. The embedding model (`nomic-ai/nomic-embed-text-v1.5`) is downloaded and cached by `sentence-transformers` on first search query.

`metadata-schema.md` is optional — if the file doesn't exist, it's skipped (the `get_metadata_schema` tool will return the default message from the server code).

## Wheel Building

After generating the source package, `opencrane pack` builds a wheel:

```python
subprocess.run([sys.executable, "-m", "build", "--wheel", output_dir], check=True)
```

This requires the `build` package. If not installed, `opencrane pack` prints a message: `"Install 'build' to generate a wheel: pip install build"` and skips wheel generation (the source package is still fully usable).

The wheel lands in `.opencrane/pack/<name>/dist/`.

## Implementation Plan

### New files

| File | Purpose |
|---|---|
| `opencrane/pack.py` | Core packing logic: validation, file generation, data copying, wheel building |

### Modified files

| File | Change |
|---|---|
| `opencrane/cli.py` | Add `pack` command wired to `pack.py` |
| `opencrane/templates.py` | Add `PACK_PYPROJECT`, `PACK_MAIN_PY`, `PACK_README` template strings |
| `opencrane/mcp/server.py` | Update `get_metadata_schema` to check `METADATA_SCHEMA_PATH` env var before falling back to relative paths |
| `pyproject.toml` (root) | Add `pack` optional dependency group: `pack = ["build>=1.0"]` |

### No changes to

- Test files — pending user approval for any test additions

## Architecture Decision: Thin Wrapper (Approach A)

The generated package is a thin wrapper that depends on `opencrane` as a pip dependency. It does not vendor or duplicate any MCP server code. This means:

- **Pros**: Minimal generated code (~20 lines of Python), MCP server behavior always matches the installed opencrane version, easy to maintain
- **Cons**: First `uvx` launch pulls opencrane + all dependencies (sentence-transformers, pymilvus, etc.) — this is a one-time cost that `uvx` caches
- **Alternative considered**: Vendoring the MCP server code into the package (rejected — fragile, code duplication, harder to update)

## CLI Output

On success, `opencrane pack` prints next-steps guidance (matching `init` and `add` patterns):

```
Packed MCP server to .opencrane/pack/my-docs-mcp/
Wheel built: .opencrane/pack/my-docs-mcp/dist/my_docs_mcp-1.0.0-py3-none-any.whl

Share it:

  1. Push to GitHub, then others run:
     claude mcp add my-docs -- uvx --from "git+https://github.com/you/my-docs-mcp" my-docs-mcp

  2. Or publish to PyPI:
     pip install build twine && python -m build .opencrane/pack/my-docs-mcp && twine upload .opencrane/pack/my-docs-mcp/dist/*
     Then others run:
     claude mcp add my-docs -- uvx my-docs-mcp

  3. Or use locally:
     claude mcp add my-docs -- uvx --from .opencrane/pack/my-docs-mcp my-docs-mcp
```

Note: The `--config` flag is intentionally omitted from `opencrane pack`. The pack command only copies built artifacts — it does not run any pipeline step that requires config resolution.

## .gitignore

The `.opencrane/pack/` directory contains large binary files and build artifacts. Users should add it to `.gitignore` in their main project. The generated package itself is meant to be published to a separate git repo or PyPI — not committed to the parent project.

## Edge Cases

- **Name collisions on PyPI**: Not handled — user's responsibility to pick a unique name
- **Large data files**: `milvus.db` can be tens/hundreds of MB. PyPI has a 100MB per-file limit. For large databases, GitHub or direct distribution is recommended. The README documents this.
- **Missing metadata-schema.md**: Skipped gracefully — the MCP server handles this case already
- **opencrane version drift**: The generated `pyproject.toml` pins `opencrane>={current_version}`. If the MCP server protocol changes in a future opencrane release, the pack may need to be regenerated.
- **uvx caching on re-pack**: If a user re-packs with updated docs but the same version number, `uvx` will serve the cached old version. The `--version` flag and the generated README both call this out.
