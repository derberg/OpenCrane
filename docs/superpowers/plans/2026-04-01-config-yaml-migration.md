# config.yaml Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `.opencrane/sources.yaml` + `.opencrane/config.py` with a unified `.opencrane/config.yaml` that holds sources, ignore patterns, and an optional `extensions` reference to a Python file.

**Architecture:** `config.yaml` is the single config file. `SourceMapping` reads/writes only the `sources:` section, preserving other top-level keys. `load_config` reads the `extensions` key to discover a Python module. `filter_markdown_files` reads `ignore_patterns` from config.yaml (global) and per-source entries. The `init` command generates `config.yaml` instead of `sources.yaml` + `config.py`.

**Tech Stack:** Python, Click, PyYAML, Pydantic

---

### Task 1: Update default mapping file path in shared config

**Files:**
- Modify: `opencrane/shared/config.py:39`

- [ ] **Step 1: Change default from `sources.yaml` to `config.yaml`**

In `opencrane/shared/config.py`, change line 39:

```python
# Before:
mapping_file: Path = field(default_factory=lambda: Path(os.getenv("MAPPING_FILE", ".opencrane/sources.yaml")))

# After:
mapping_file: Path = field(default_factory=lambda: Path(os.getenv("MAPPING_FILE", ".opencrane/config.yaml")))
```

- [ ] **Step 2: Commit**

```bash
git add opencrane/shared/config.py
git commit -m "refactor: change default mapping file to .opencrane/config.yaml"
```

---

### Task 2: Make SourceMapping preserve non-sources keys

**Files:**
- Modify: `opencrane/rag/services/source_mapping.py`
- Modify: `tests/unit/rag/services/test_source_mapping.py`

Currently `SourceMapping._load_mapping()` returns the full YAML dict, and `save()` dumps `self.data`. This already preserves extra keys. But we need to verify it and add a method to read `ignore_patterns`.

- [ ] **Step 1: Add `get_ignore_patterns` method to SourceMapping**

In `opencrane/rag/services/source_mapping.py`, add after `get_all_sources()`:

```python
def get_ignore_patterns(self, source_key: str | None = None) -> list[str]:
    """Get ignore patterns — global patterns extended by per-source patterns.

    Args:
        source_key: Optional source path key. When provided, the source's
            own ignore_patterns are appended to the global list.

    Returns:
        Combined list of ignore pattern strings.
    """
    global_patterns = list(self.data.get("ignore_patterns") or [])
    if source_key:
        source = self.data.get("sources", {}).get(source_key, {})
        source_patterns = source.get("ignore_patterns") or []
        return global_patterns + list(source_patterns)
    return global_patterns
```

- [ ] **Step 2: Add `get_extensions_path` method**

```python
def get_extensions_path(self) -> str | None:
    """Get the extensions file path from config, or None if not set."""
    return self.data.get("extensions")
```

- [ ] **Step 3: Update docstring in `__init__` to say `config.yaml` instead of `sources.yaml`**

- [ ] **Step 4: Add tests for new methods**

In `tests/unit/rag/services/test_source_mapping.py`, add:

```python
def test_get_ignore_patterns_global_only(tmp_path):
    mapping_file = tmp_path / "config.yaml"
    mapping_file.write_text("ignore_patterns:\n  - devel\n  - .draft\nsources: {}\n")
    mapping = SourceMapping(mapping_file)
    assert mapping.get_ignore_patterns() == ["devel", ".draft"]

def test_get_ignore_patterns_with_source(tmp_path):
    mapping_file = tmp_path / "config.yaml"
    mapping_file.write_text(
        "ignore_patterns:\n  - devel\n"
        "sources:\n  my-repo:\n    url: https://github.com/x/y\n    ignore_patterns:\n      - internal\n"
    )
    mapping = SourceMapping(mapping_file)
    assert mapping.get_ignore_patterns("my-repo") == ["devel", "internal"]

def test_get_ignore_patterns_empty(tmp_path):
    mapping_file = tmp_path / "config.yaml"
    mapping_file.write_text("sources: {}\n")
    mapping = SourceMapping(mapping_file)
    assert mapping.get_ignore_patterns() == []

def test_get_extensions_path(tmp_path):
    mapping_file = tmp_path / "config.yaml"
    mapping_file.write_text("extensions: extensions.py\nsources: {}\n")
    mapping = SourceMapping(mapping_file)
    assert mapping.get_extensions_path() == "extensions.py"

def test_get_extensions_path_none(tmp_path):
    mapping_file = tmp_path / "config.yaml"
    mapping_file.write_text("sources: {}\n")
    mapping = SourceMapping(mapping_file)
    assert mapping.get_extensions_path() is None

def test_save_preserves_non_sources_keys(tmp_path):
    mapping_file = tmp_path / "config.yaml"
    mapping_file.write_text("ignore_patterns:\n  - devel\nextensions: extensions.py\nsources: {}\n")
    mapping = SourceMapping(mapping_file)
    mapping.add_source("test", url="https://github.com/x/y", manual=True)
    mapping.save()
    import yaml
    saved = yaml.safe_load(mapping_file.read_text())
    assert saved["ignore_patterns"] == ["devel"]
    assert saved["extensions"] == "extensions.py"
    assert "test" in saved["sources"]
```

- [ ] **Step 5: Run tests**

Run: `./pytest.sh tests/unit/rag/services/test_source_mapping.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add opencrane/rag/services/source_mapping.py tests/unit/rag/services/test_source_mapping.py
git commit -m "feat: add ignore_patterns and extensions_path support to SourceMapping"
```

---

### Task 3: Replace `is_in_devel_folder` with configurable `filter_markdown_files`

**Files:**
- Modify: `opencrane/rag/generate_llms_txt.py:70-77`

- [ ] **Step 1: Replace hardcoded devel filter with configurable ignore patterns**

In `opencrane/rag/generate_llms_txt.py`, replace lines 70-77:

```python
# Before:
def is_in_devel_folder(file_path: Path) -> bool:
    """Check if a file is within a 'devel' directory at any level."""
    return "devel" in file_path.parts


def filter_markdown_files(files: Iterable[Path]) -> List[Path]:
    """Filter out markdown files that are in 'devel' folders."""
    return [f for f in files if not is_in_devel_folder(f)]

# After:
def _matches_ignore_pattern(file_path: Path, patterns: List[str]) -> bool:
    """Check if a file path contains any of the ignore pattern directory names."""
    return any(pattern in file_path.parts for pattern in patterns)


def filter_markdown_files(files: Iterable[Path], ignore_patterns: List[str] | None = None) -> List[Path]:
    """Filter out markdown files matching ignore patterns.

    Args:
        files: Iterable of file paths to filter.
        ignore_patterns: Directory names to exclude. Defaults to ["devel"]
            when None (preserves legacy behavior for callers that don't
            pass patterns).
    """
    if ignore_patterns is None:
        ignore_patterns = ["devel"]
    if not ignore_patterns:
        return list(files)
    return [f for f in files if not _matches_ignore_pattern(f, ignore_patterns)]
```

- [ ] **Step 2: Update all `filter_markdown_files` call sites to pass ignore_patterns**

In the `generate_outputs` function, the `filter_markdown_files` calls at lines ~537, ~543, ~551, ~562 are inside a loop over `source_dirs`. At each call site, we need to pass the ignore patterns from the mapping. The mapped_path is available in the filtering branch.

For the **mapping-filtered branch** (line ~537), where we know the `mapped_path`:
```python
ignore_patterns = mapping.get_ignore_patterns(mapped_path)
md_files = filter_markdown_files(sorted(full_path.rglob("*.md")), ignore_patterns)
```

For the **unfiltered discovery branch** (lines ~543, ~551, ~562), use global patterns only:
```python
ignore_patterns = mapping.get_ignore_patterns()
```

For the **legacy `selected_projects` path** (line ~420), use default (no mapping available):
```python
md_files = filter_markdown_files(sorted(project_dir.rglob("*.md")))
```

And for `build_project_output` (line ~293):
```python
md_files = md_files or filter_markdown_files(sorted(project_dir.rglob("*.md")))
```
This is called with pre-filtered `md_files` from the caller, so the default is fine as a fallback.

- [ ] **Step 3: Run tests**

Run: `./pytest.sh tests/unit/rag/test_generate_llms_txt.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add opencrane/rag/generate_llms_txt.py
git commit -m "feat: replace hardcoded devel filter with configurable ignore_patterns"
```

---

### Task 4: Update `load_config` to read extensions from config.yaml

**Files:**
- Modify: `opencrane/cli.py:33-80`

- [ ] **Step 1: Rewrite `load_config` auto-discovery**

Replace the current auto-discovery logic. Instead of looking for `.opencrane/config.py`, read `.opencrane/config.yaml` and check for `extensions` key:

```python
def load_config(config_arg: str | None):
    """Load OpenCraneConfig from a module:Class string, or auto-discover from config.yaml.

    Resolution order:
    1. Explicit ``--config`` flag or ``OPENCRANE_CONFIG`` env var
    2. Auto-discovery: ``.opencrane/config.yaml`` with an ``extensions`` key
    3. Base ``OpenCraneConfig`` (no customisation)
    """
    import os
    from opencrane.config import OpenCraneConfig

    if config_arg is None:
        config_arg = os.environ.get("OPENCRANE_CONFIG")

    # Auto-discover extensions from .opencrane/config.yaml
    if config_arg is None:
        from pathlib import Path
        config_yaml = Path(".opencrane/config.yaml")
        if config_yaml.exists():
            import yaml
            try:
                data = yaml.safe_load(config_yaml.read_text(encoding="utf-8")) or {}
            except Exception:
                data = {}
            extensions = data.get("extensions")
            if extensions:
                ext_path = config_yaml.parent / extensions
                if ext_path.exists():
                    import importlib.util
                    opencrane_dir = str(ext_path.parent.resolve())
                    if opencrane_dir not in sys.path:
                        sys.path.insert(0, opencrane_dir)
                    spec = importlib.util.spec_from_file_location("_opencrane_extensions", ext_path.resolve())
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    return getattr(module, "Config")()
        return OpenCraneConfig()

    if ":" in config_arg:
        # Python class: "module.path:ClassName"
        module_path, class_name = config_arg.rsplit(":", 1)
        import importlib
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls()
    else:
        # Treat as path to Python file
        from pathlib import Path
        import importlib.util
        ext_path = Path(config_arg)
        if ext_path.exists():
            opencrane_dir = str(ext_path.parent.resolve())
            if opencrane_dir not in sys.path:
                sys.path.insert(0, opencrane_dir)
            spec = importlib.util.spec_from_file_location("_opencrane_config", ext_path.resolve())
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return getattr(module, "Config")()
        return OpenCraneConfig()
```

- [ ] **Step 2: Run tests**

Run: `./pytest.sh tests/unit/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add opencrane/cli.py
git commit -m "feat: load_config reads extensions from .opencrane/config.yaml"
```

---

### Task 5: Update templates

**Files:**
- Modify: `opencrane/templates.py`

- [ ] **Step 1: Rename `SOURCES_YAML` → `CONFIG_YAML` and update content**

Replace the `SOURCES_YAML` template with:

```python
CONFIG_YAML = '''\
# OpenCrane configuration
# Tip: Run `opencrane add` to interactively add sources instead of editing this file.

# Ignore patterns — directory names to exclude from llms-full.txt generation.
# Applied globally to all sources. Per-source patterns can extend this list.
ignore_patterns:
  - devel

# Optional: Python module with custom extensions (fence types, chunking strategies, walkers).
# Path is relative to .opencrane/ directory.
# extensions: extensions.py

# Documentation sources.
# Each entry maps a source name to its configuration.
#
# GitHub repository example:
#   external-sources/my-repo:
#     url: https://github.com/my-org/my-repo
#     docs_path: docs        # subdirectory inside the repo to fetch (empty = root)
#     manual: true           # true = always fetch, false = only if repo has the configured topic
#     ignore_patterns:       # optional, extends global ignore_patterns
#       - internal
#
# Pre-existing llms.txt example:
#   anthropic-docs:
#     type: llmstxt
#     url: https://docs.anthropic.com/llms-full.txt
#     docs_url: https://docs.anthropic.com  # optional, for source links
#     manual: true

sources:
'''
```

- [ ] **Step 2: Rename `CONFIG_PY` → `EXTENSIONS_PY`**

Just rename the variable. Content stays the same.

- [ ] **Step 3: Update `README_MD` template**

In the Structure table, replace:
```
| `config.py` | Custom fence types, chunking strategies, tree walkers | Yes |
| `sources.yaml` | Which repos/directories to fetch documentation from | Yes |
```
with:
```
| `config.yaml` | Sources, ignore patterns, and optional extensions reference | Yes |
| `extensions.py` | Custom fence types, chunking strategies, tree walkers (optional) | Yes |
```

- [ ] **Step 4: Commit**

```bash
git add opencrane/templates.py
git commit -m "refactor: rename templates for config.yaml migration"
```

---

### Task 6: Update `init` command

**Files:**
- Modify: `opencrane/cli.py` — the `init` function

- [ ] **Step 1: Update init to generate config.yaml + optional extensions.py**

Change the `init` function:
- Replace import of `CONFIG_PY, SOURCES_YAML` with `CONFIG_YAML, EXTENSIONS_PY`
- Replace `write_file(opencrane_dir / "config.py", CONFIG_PY)` and `write_file(opencrane_dir / "sources.yaml", SOURCES_YAML, user_managed=True)` with `write_file(opencrane_dir / "config.yaml", CONFIG_YAML, user_managed=True)`
- Add `--extensions` flag: when passed, also generate `extensions.py`

```python
@main.command(cls=_ColorCommand)
@click.option("--podman", is_flag=True, default=False,
              help="Generate Containerfile instead of Dockerfile")
@click.option("--force", is_flag=True, default=False,
              help="Overwrite existing files")
@click.option("--no-add", is_flag=True, default=False,
              help="Skip the interactive source addition prompt")
@click.option("--extensions", "with_extensions", is_flag=True, default=False,
              help="Generate extensions.py for custom Python extensions")
def init(podman, force, no_add, with_extensions):
```

Inside the function:
```python
from opencrane.templates import CONFIG_YAML, EXTENSIONS_PY, DOCKERFILE, DOCKER_COMPOSE, readme

# ...
write_file(opencrane_dir / "config.yaml", CONFIG_YAML, user_managed=True)
if with_extensions:
    write_file(opencrane_dir / "extensions.py", EXTENSIONS_PY)
write_file(opencrane_dir / "README.md", readme(podman=podman))
```

- [ ] **Step 2: Run tests**

Run: `./pytest.sh tests/unit/ -v`
Expected: PASS (init tests may need updating)

- [ ] **Step 3: Commit**

```bash
git add opencrane/cli.py
git commit -m "feat: init generates config.yaml, optional --extensions flag for extensions.py"
```

---

### Task 7: Update test fixtures and test files

**Files:**
- Modify: `tests/fixtures/test-mapping.yaml` — add `ignore_patterns` example
- Modify: `tests/unit/rag/services/test_source_mapping.py` — update file references
- Modify: `tests/unit/rag/test_generate_llms_txt.py` — update references to `sources.yaml`
- Modify: `tests/unit/rag/test_fetch_docs.py` — update references
- Modify: `tests/unit/test_add_source.py` — update references
- Modify: `tests/unit/rag/test_llms_combine.py` — update references
- Modify: `tests/conftest.py` — update references
- Modify: `tests/integration/test_full_workflow.py` — update references

- [ ] **Step 1: Search-and-replace `sources.yaml` → `config.yaml` across all test files**

In each file, replace string references to `sources.yaml` with `config.yaml`. This includes:
- File path strings like `"sources.yaml"`, `".opencrane/sources.yaml"`
- Variable names like `sources_yaml` (rename to `config_yaml` where it's a path variable)
- YAML content that creates test fixtures

Also replace references to `config.py` auto-discovery with `extensions.py` if any tests reference it.

- [ ] **Step 2: Run full test suite**

Run: `./pytest.sh`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "test: update all test references from sources.yaml to config.yaml"
```

---

### Task 8: Update documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Update CLAUDE.md**

Replace all references to `sources.yaml` with `config.yaml` and `config.py` with `extensions.py` (optional). Update the project structure section and any relevant descriptions.

- [ ] **Step 2: Update README.md**

- Replace `.opencrane/sources.yaml` references with `.opencrane/config.yaml`
- Replace `.opencrane/config.py` references with `.opencrane/extensions.py`
- Update the source mapping file section title and description
- Update the `MAPPING_FILE` env var default in the env var table
- Add `ignore_patterns` to the config.yaml example

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: update CLAUDE.md and README.md for config.yaml migration"
```

---

### Task 9: Run full test suite and fix any remaining issues

- [ ] **Step 1: Run all unit tests with coverage**

Run: `./pytest.sh --check-coverage`
Expected: PASS

- [ ] **Step 2: Fix any failures or coverage gaps**

- [ ] **Step 3: Final commit if needed**
