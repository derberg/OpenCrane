# Unified `.opencrane/config.yaml` Design

## Goal

Replace `.opencrane/sources.yaml` and `.opencrane/config.py` with a single `.opencrane/config.yaml` that holds sources, ignore patterns, and an optional reference to a Python extensions file.

## Architecture

`config.yaml` is the single configuration file. It contains all declarative config (sources, ignore patterns). Python extension points (fence handlers, chunking strategies, YAML tree walkers) move to an optional `extensions.py` file referenced by `config.yaml`. Most users never need the extensions file.

## File format

```yaml
# Global ignore patterns — directory names matched against file paths
# Applied to all sources during llms generation
ignore_patterns:
  - devel

# Optional: Python module with custom extensions (fence types, chunking strategies, walkers)
# Path is relative to .opencrane/ directory
# extensions: extensions.py

sources:
  MicrosoftDocs/microsoft-style-guide:
    url: https://github.com/MicrosoftDocs/microsoft-style-guide
    docs_path: styleguide
    manual: true
    docs_url: https://learn.microsoft.com/en-us/style-guide
    # Per-source ignore patterns — extend the global list
    ignore_patterns:
      - includes

  likec4:
    type: llmstxt
    url: https://likec4.dev/llms-full.txt
    docs_url: https://likec4.dev
    manual: true

  my-local-docs:
    local: true
    docs_path: docs
```

## What changes

### 1. File rename: `sources.yaml` → `config.yaml`

- All references to `.opencrane/sources.yaml` become `.opencrane/config.yaml`
- `MAPPING_FILE` env var default changes from `.opencrane/sources.yaml` to `.opencrane/config.yaml`
- `config.mapping_file` in `opencrane/shared/config.py` default changes
- `SourceMapping` class reads/writes the `sources:` section within `config.yaml`, preserving other top-level keys (`ignore_patterns`, `extensions`)

### 2. File rename: `config.py` → `extensions.py`

- `.opencrane/config.py` becomes `.opencrane/extensions.py`
- Only generated when `opencrane init --extensions` is passed
- Referenced via `extensions: extensions.py` key in `config.yaml`
- Still subclasses `OpenCraneConfig` with a `Config` class
- `load_config` in `cli.py` reads the `extensions` key from `config.yaml` and loads the Python module from `.opencrane/<extensions_value>`
- Falls back to base `OpenCraneConfig()` when no extensions key is present

### 3. New: `ignore_patterns`

- Global `ignore_patterns` list at root level of `config.yaml`
- Optional per-source `ignore_patterns` list that extends the global list
- Patterns match directory names in file paths (same semantics as current `is_in_devel_folder` but generalized)
- `filter_markdown_files` reads patterns from config instead of hardcoding `devel`
- Default template includes `devel` to preserve current behavior

### 4. `opencrane init` changes

- Generates `config.yaml` instead of `sources.yaml` + `config.py`
- `config.yaml` template includes commented examples for sources, ignore patterns, and extensions
- `--extensions` flag generates `extensions.py` alongside `config.yaml` with the current `config.py` template content
- `--force` behavior unchanged

### 5. Template updates

- `SOURCES_YAML` template → `CONFIG_YAML` template (with ignore_patterns + extensions + sources sections)
- `CONFIG_PY` template → `EXTENSIONS_PY` template (same content, just renamed)

## What doesn't change

- Source entry fields: `url`, `docs_path`, `manual`, `type`, `docs_url`, `local`
- `OpenCraneConfig` base class and its extension points (`fence_types`, `chunking_strategies`, `yaml_tree_walkers`)
- CLI commands and their flags
- Env vars (still work as overrides)
- `SourceMapping` public API (methods, return types)

## Files affected

### Source code
- `opencrane/shared/config.py` — change `mapping_file` default
- `opencrane/cli.py` — update `load_config` to read `extensions` from config.yaml, update `init` command
- `opencrane/templates.py` — rename templates, update content
- `opencrane/rag/generate_llms_txt.py` — `is_in_devel_folder` → generalized `is_ignored`, `filter_markdown_files` reads from config
- `opencrane/rag/services/source_mapping.py` — preserve non-sources keys during save
- `opencrane/add_source.py` — no change (uses SourceMapping API)

### Tests
- All tests referencing `sources.yaml` path or `config.py` path
- Tests for `filter_markdown_files` / `is_in_devel_folder`
- `opencrane init` tests
- Test fixtures with mapping files

### Docs
- `CLAUDE.md` — update file references
- `README.md` — update references
- `docs/vector-search.md`, `docs/source-mapping.md` — update as needed
