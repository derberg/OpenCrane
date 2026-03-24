# Unified sources.yaml Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify GitHub and llmstxt sources under a single `sources.yaml` schema so both types are tracked, re-fetchable, and flow through the same pipeline.

**Architecture:** Add a `type` discriminator field to `sources.yaml` entries (default `github`). Rename `github_url` → `url` everywhere. Move llmstxt download/copy logic from `add_source.py` to `fetch_docs.py`. Rename public API `get_github_url` → `get_source_url`.

**Tech Stack:** Python, Click, PyYAML, pytest

**Spec:** `docs/superpowers/specs/2026-03-24-unified-sources-yaml-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `opencrane/rag/services/source_mapping.py` | Modify | `github_url` → `url`, add `type` param |
| `opencrane/add_source.py` | Modify | `github_url` → `url`, strip download logic from llmstxt |
| `opencrane/rag/fetch_docs.py` | Modify | `github_url` → `url`, add llmstxt fetch loop |
| `opencrane/rag/generate_llms_txt.py` | Modify | `github_url` → `url`, rename `get_github_url` → `get_source_url` |
| `opencrane/fences/__init__.py` | Modify | Re-export `get_source_url` instead of `get_github_url` |
| `opencrane/shared/utils/github_url_parser.py` | Modify | `github_url` → `url` in param names |
| `opencrane/cli.py` | Modify | `github_url` → `url`, add `docs_url` prompt for llmstxt |
| `opencrane/templates.py` | Modify | Update SOURCES_YAML template comments |
| `tests/unit/rag/services/test_source_mapping.py` | Modify | `github_url` → `url` |
| `tests/unit/test_add_source.py` | Modify | `github_url` → `url`, update llmstxt tests |
| `tests/unit/rag/test_generate_llms_txt.py` | Modify | `github_url` → `url`, `get_github_url` → `get_source_url` |
| `tests/unit/rag/services/test_prose_chunker.py` | Modify | `github_url` → `url` |
| `tests/unit/shared/utils/test_github_url_parser.py` | Modify | param name updates |
| `tests/integration/test_full_workflow.py` | Modify | `github_url` → `url` |
| `tests/fixtures/test-mapping.yaml` | Modify | `github_url` → `url` |
| `docs/source-mapping.md` | Modify | `github_url` → `url` |
| `docs/llms-generation.md` | Modify | `github_url` → `url`, `get_github_url` → `get_source_url` |
| `README.md` | Modify | `github_url` → `url` |

---

### Task 1: Rename `github_url` → `url` in SourceMapping

**Files:**
- Modify: `opencrane/rag/services/source_mapping.py`
- Modify: `tests/unit/rag/services/test_source_mapping.py`

- [ ] **Step 1: Update `add_source()` signature and body**

In `opencrane/rag/services/source_mapping.py`, rename the `github_url` parameter to `url` and add `type` parameter:

```python
def add_source(
    self,
    path_key: str,
    url: str,
    docs_path: str = "",
    manual: bool = False,
    docs_url: str = "",
    type: str = "github",
) -> None:
```

Update the entry dict construction (line 80-86):

```python
entry = {
    "url": url,
    "docs_path": docs_path,
    "manual": manual,
}
if type != "github":
    entry["type"] = type
if docs_url:
    entry["docs_url"] = docs_url
```

- [ ] **Step 2: Update existing tests**

In `tests/unit/rag/services/test_source_mapping.py`, replace all `github_url=` keyword args with `url=` and all assertions on `entry["github_url"]` with `entry["url"]`.

- [ ] **Step 3: Add test for `type` parameter**

Add a test that verifies the `type` field behavior:

```python
@pytest.mark.unit
def test_add_source_with_llmstxt_type(tmp_mapping):
    tmp_mapping.add_source(
        path_key="my-llmstxt",
        url="https://example.com/llms-full.txt",
        manual=True,
        type="llmstxt",
    )
    entry = tmp_mapping.get_source("my-llmstxt")
    assert entry["url"] == "https://example.com/llms-full.txt"
    assert entry["type"] == "llmstxt"
    assert entry["manual"] is True


@pytest.mark.unit
def test_add_source_github_type_omitted_from_entry(tmp_mapping):
    tmp_mapping.add_source(path_key="my-repo", url="https://github.com/org/repo")
    entry = tmp_mapping.get_source("my-repo")
    assert "type" not in entry  # github is default, not stored
    assert entry["url"] == "https://github.com/org/repo"
```

- [ ] **Step 4: Run tests**

Run: `./pytest.sh tests/unit/rag/services/test_source_mapping.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add opencrane/rag/services/source_mapping.py tests/unit/rag/services/test_source_mapping.py
git commit -m "refactor: rename github_url to url in SourceMapping"
```

---

### Task 2: Rename `github_url` → `url` in test fixtures and docs

**Files:**
- Modify: `tests/fixtures/test-mapping.yaml`
- Modify: `docs/source-mapping.md`
- Modify: `docs/llms-generation.md`
- Modify: `README.md`

- [ ] **Step 1: Update test fixture**

In `tests/fixtures/test-mapping.yaml`, replace all `github_url:` keys with `url:`.

- [ ] **Step 2: Update documentation files**

In `docs/source-mapping.md`, `docs/llms-generation.md`, and `README.md`, replace all occurrences of `github_url` with `url`.

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/test-mapping.yaml docs/source-mapping.md docs/llms-generation.md README.md
git commit -m "refactor: rename github_url to url in fixtures and docs"
```

---

### Task 3: Update `add_source.py`, CLI, and templates — rename and simplify llmstxt

This task combines changes to `add_source.py`, `cli.py`, and `templates.py` because the CLI directly calls `add_llmstxt_source()`. Changing the function signature without updating the caller would break the build.

**Files:**
- Modify: `opencrane/add_source.py`
- Modify: `opencrane/cli.py`
- Modify: `opencrane/templates.py`
- Modify: `tests/unit/test_add_source.py`

- [ ] **Step 1: Update `add_github_source()`**

Rename parameter `github_url` → `url` and pass `url=` to `mapping.add_source()`:

```python
def add_github_source(
    name: str,
    url: str,
    docs_path: str = "",
    docs_url: str = "",
) -> None:
    """Add a GitHub repository source to sources.yaml."""
    mapping = _get_mapping()
    mapping.add_source(
        path_key=name,
        url=url,
        docs_path=docs_path,
        manual=True,
        docs_url=docs_url,
    )
    mapping.save()
```

- [ ] **Step 2: Replace `add_llmstxt_source()` with registration-only logic**

Replace the entire function. Remove `shutil` and `urllib` imports from the top of the file:

```python
def add_llmstxt_source(
    name: str,
    url: str,
    docs_url: str = "",
) -> None:
    """Register a pre-existing llms.txt file as a source in sources.yaml.

    The actual download/copy happens during `opencrane fetch`.

    Args:
        name: Name for this source (used as path key).
        url: URL (http/https) or local file path.
        docs_url: Optional published docs URL for source links.
    """
    mapping = _get_mapping()
    mapping.add_source(
        path_key=name,
        url=url,
        manual=True,
        docs_url=docs_url,
        type="llmstxt",
    )
    mapping.save()
```

Remove these imports from the top of the file:
```python
import shutil
from urllib.request import Request, urlopen
```

Also remove the `LLMSTXT_DIR` constant (no longer used here).

- [ ] **Step 3: Update `_add_sources_interactive()` GitHub path in cli.py**

Change `github_url=github_url` to `url=github_url` in the `add_github_source()` call:

```python
add_github_source(
    name=name,
    url=github_url,
    docs_path=docs_path,
    docs_url=docs_url,
)
```

- [ ] **Step 4: Update `_add_sources_interactive()` llmstxt path in cli.py**

Replace the llmstxt block. The function no longer does file I/O, so remove the retry loop and add a `docs_url` prompt:

```python
elif choice == 2:
    name = click.prompt("Name for this source (used as directory name)")
    location = click.prompt("llms.txt URL or local file path")
    docs_url = click.prompt("Published docs URL (optional, for source links)", default="")
    try:
        add_llmstxt_source(name=name, url=location, docs_url=docs_url)
        click.echo(f"Added llmstxt source '{name}' to .opencrane/sources.yaml")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
```

- [ ] **Step 5: Update SOURCES_YAML template**

In `opencrane/templates.py`, update the SOURCES_YAML template comments to use `url:` instead of `github_url:` and add an llmstxt example:

```python
SOURCES_YAML = '''\
# OpenCrane source mapping
# Tip: Run `opencrane add` to interactively add sources instead of editing this file.
# Defines repositories and pre-existing llms.txt files to include in the knowledge base.
#
# Each entry maps a source name to its configuration.
#
# GitHub repository example:
# external-sources/my-repo:
#   url: https://github.com/my-org/my-repo
#   docs_path: docs        # subdirectory inside the repo to fetch (empty = root)
#   manual: true           # true = always fetch, false = only if repo has the configured topic
#
# Pre-existing llms.txt example:
# anthropic-docs:
#   type: llmstxt
#   url: https://docs.anthropic.com/llms-full.txt
#   docs_url: https://docs.anthropic.com  # optional, for source links
#   manual: true

sources:
'''
```

- [ ] **Step 6: Update tests**

In `tests/unit/test_add_source.py`:

- `test_add_github_source`: change `github_url=` to `url=`, assert on `entry["url"]` instead of `entry["github_url"]`
- `test_add_github_source_with_docs_url`: change `github_url=` to `url=`
- `test_add_llmstxt_source_from_local_file`: change to test that it registers in sources.yaml instead of copying file. Call `add_llmstxt_source(name="my-project", url=str(local_file))` and assert `sources["sources"]["my-project"]["type"] == "llmstxt"` and `sources["sources"]["my-project"]["url"] == str(local_file)`
- `test_add_llmstxt_source_from_url`: change to test registration. Call `add_llmstxt_source(name="remote-project", url="https://example.com/llms-full.txt")` and assert the entry has `type: llmstxt` and the correct `url`. Remove the `urlopen` mock.
- `test_add_llmstxt_source_local_file_not_found`: remove this test (no file I/O in add anymore)
- CLI tests for llmstxt — update prompt inputs to match new flow (choice, name, location, docs_url, add-another):
  - `test_cli_add_llmstxt_source`: input becomes `f"2\nmy-project\n{local_file}\n\nn\n"`. Assert sources.yaml entry instead of file existence.
  - `test_cli_add_multiple_sources`: similar prompt changes for both sources.
  - `test_init_with_add_sources`: similar prompt changes.
  - `test_cli_add_llmstxt_file_not_found`: remove (no file I/O error path anymore).

- [ ] **Step 7: Run tests**

Run: `./pytest.sh tests/unit/test_add_source.py -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add opencrane/add_source.py opencrane/cli.py opencrane/templates.py tests/unit/test_add_source.py
git commit -m "feat: unify add_source for both github and llmstxt types"
```

---

### Task 4: Rename `get_github_url` → `get_source_url` and update `github_url` refs in generate_llms_txt

**Files:**
- Modify: `opencrane/rag/generate_llms_txt.py`
- Modify: `opencrane/fences/__init__.py`
- Modify: `tests/unit/rag/test_generate_llms_txt.py`

- [ ] **Step 1: Rename function in generate_llms_txt.py**

Rename `def get_github_url(` to `def get_source_url(` at line 157. Inside the function body, rename `github_url = source.get("github_url", "")` to `url = source.get("url", "")` and update all references to this variable. Search the entire file for other `github_url` references and rename to `url`.

- [ ] **Step 2: Update all callers within generate_llms_txt.py**

Search the file for calls to `get_github_url(` and rename to `get_source_url(`.

- [ ] **Step 3: Update fences public API**

In `opencrane/fences/__init__.py`:

```python
"""Public API for OpenCrane fence type configuration."""

from opencrane.rag.generate_llms_txt import CodeFenceConfig, get_source_url

__all__ = [
    "CodeFenceConfig",
    "get_source_url",
]
```

- [ ] **Step 4: Update tests**

In `tests/unit/rag/test_generate_llms_txt.py`, replace all `github_url` references with `url` and all `get_github_url` references with `get_source_url`.

- [ ] **Step 5: Run tests**

Run: `./pytest.sh tests/unit/rag/test_generate_llms_txt.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add opencrane/rag/generate_llms_txt.py opencrane/fences/__init__.py tests/unit/rag/test_generate_llms_txt.py
git commit -m "refactor: rename get_github_url to get_source_url"
```

---

### Task 5: Rename `github_url` → `url` in fetch_docs.py

**Files:**
- Modify: `opencrane/rag/fetch_docs.py`
- Modify: `opencrane/shared/utils/github_url_parser.py`
- Modify: `tests/unit/shared/utils/test_github_url_parser.py`
- Modify: `tests/unit/rag/services/test_prose_chunker.py`
- Modify: `tests/integration/test_full_workflow.py`

- [ ] **Step 1: Update fetch_docs.py**

Replace all occurrences of `github_url` with `url` in `opencrane/rag/fetch_docs.py`. Key locations (line numbers are approximate — search by context):
- In the manual-repo loop: `source_config.get("github_url")` → `source_config.get("url")`
- Warning messages referencing `github_url`
- `parse_github_url(github_url)` → `parse_github_url(url)`
- `manual_repo_metadata` dict: `"github_url": github_url` → `"url": url`
- Protection loop: `source_config.get("github_url")` → `source_config.get("url")`
- `process_repo()` closure: metadata access and URL construction
- `source_mapping.add_source()` call: `github_url=` → `url=`

Also add a filter to skip llmstxt entries in the manual-repo loop (right after checking `source_config.get("manual")`):

```python
if source_config.get("type", "github") != "github":
    continue
```

- [ ] **Step 2: Update github_url_parser.py param names**

In `opencrane/shared/utils/github_url_parser.py`, rename the `github_url` parameter to `url` in `parse_github_url()`. Update docstring and internal references.

- [ ] **Step 3: Update remaining test files**

In `tests/unit/shared/utils/test_github_url_parser.py`, `tests/unit/rag/services/test_prose_chunker.py`, and `tests/integration/test_full_workflow.py`, replace all `github_url` references with `url`.

- [ ] **Step 4: Run tests**

Run: `./pytest.sh tests/unit/ -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add opencrane/rag/fetch_docs.py opencrane/shared/utils/github_url_parser.py tests/unit/shared/utils/test_github_url_parser.py tests/unit/rag/services/test_prose_chunker.py tests/integration/test_full_workflow.py
git commit -m "refactor: rename github_url to url in fetch_docs and parser"
```

---

### Task 6: Add llmstxt fetching to fetch_docs.py

**Files:**
- Modify: `opencrane/rag/fetch_docs.py`

- [ ] **Step 1: Add llmstxt fetch logic**

After the existing manual-repo loop (after line 113), add a new loop to fetch llmstxt sources. Add `shutil` import at the top (already imported) and `from urllib.request import Request, urlopen`:

```python
# Fetch llmstxt sources
llmstxt_sources = {}
for path_key, source_config in source_mapping.get_all_sources().items():
    if source_config.get("type", "github") != "llmstxt":
        continue
    if fetch_repo_filter and path_key != fetch_repo_filter:
        logger.debug(f"Skipping llmstxt {path_key} (--repo filter active: {fetch_repo_filter})")
        continue

    url = source_config.get("url", "")
    if not url:
        logger.warning(f"llmstxt entry {path_key} has no url, skipping")
        continue

    dest_dir = workspace_root / ".opencrane" / "llmstxt" / path_key
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / "llms-full.txt"

    try:
        if url.startswith("http://") or url.startswith("https://"):
            logger.info(f"Downloading llmstxt: {path_key} from {url}")
            req = Request(url, headers={"User-Agent": "OpenCrane"})
            with urlopen(req) as response:
                content = response.read()
            logger.debug(f"Downloaded {len(content)} bytes for {path_key}")
            dest_file.write_bytes(content)
        else:
            source_path = Path(url).resolve()
            if not source_path.exists():
                logger.error(f"Local file not found for {path_key}: {source_path}")
                continue
            logger.info(f"Copying llmstxt: {path_key} from {source_path}")
            shutil.copy2(source_path, dest_file)

        llmstxt_sources[path_key] = source_config
        active_repos.add(path_key)
        logger.info(f"Fetched llmstxt source: {path_key} -> {dest_file}")
    except Exception as e:
        logger.error(f"Failed to fetch llmstxt source {path_key}: {e}")
        active_repos.add(path_key)  # Don't clean up on transient failure
```

- [ ] **Step 2: Add `urlopen` import**

At the top of `fetch_docs.py`, add:
```python
from urllib.request import Request, urlopen
```

- [ ] **Step 3: Add llmstxt path keys to active_repos in the protection loop**

In the loop that protects entries from cleanup, also protect llmstxt entries. The llmstxt check must come after the `fetch_repo_filter` guard (which already adds + continues), so it only matters for the non-filtered case:

```python
for path_key, source_config in source_mapping.get_all_sources().items():
    if fetch_repo_filter and path_key != fetch_repo_filter:
        logger.debug(f"Marking {path_key} as active (--repo filter active, protected from cleanup)")
        active_repos.add(path_key)
        continue
    # Protect all llmstxt entries from stale cleanup — they are always user-managed
    if source_config.get("type", "github") == "llmstxt":
        active_repos.add(path_key)
        continue
    url = source_config.get("url")
    if url:
        parsed = parse_github_url(url)
        if parsed:
            org_name, repo_name = parsed
            if org_name != config.org_name:
                logger.debug(f"Marking {org_name}/{repo_name} as active (different org, protected from cleanup)")
                active_repos.add(path_key)
```

- [ ] **Step 4: Write tests for llmstxt fetching**

Add tests to the appropriate fetch_docs test file. These must cover the new code paths:

```python
@pytest.mark.unit
def test_fetch_llmstxt_from_url(workspace, source_mapping, monkeypatch):
    """llmstxt sources with http URLs are downloaded during fetch."""
    source_mapping.add_source(
        path_key="remote-docs",
        url="https://example.com/llms-full.txt",
        manual=True,
        type="llmstxt",
    )
    source_mapping.save()
    mock_content = b"# Remote docs content"
    with patch("opencrane.rag.fetch_docs.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = mock_content
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response
        fetch_main(config=config)
    dest = workspace / ".opencrane" / "llmstxt" / "remote-docs" / "llms-full.txt"
    assert dest.exists()
    assert dest.read_bytes() == mock_content


@pytest.mark.unit
def test_fetch_llmstxt_from_local_file(workspace, source_mapping):
    """llmstxt sources with local paths are copied during fetch."""
    local_file = workspace / "my-docs.txt"
    local_file.write_text("# Local docs")
    source_mapping.add_source(
        path_key="local-docs",
        url=str(local_file),
        manual=True,
        type="llmstxt",
    )
    source_mapping.save()
    fetch_main(config=config)
    dest = workspace / ".opencrane" / "llmstxt" / "local-docs" / "llms-full.txt"
    assert dest.exists()
    assert "Local docs" in dest.read_text()


@pytest.mark.unit
def test_fetch_llmstxt_skips_no_url(workspace, source_mapping, caplog):
    """llmstxt entries with empty url are skipped with a warning."""
    source_mapping.add_source(
        path_key="bad-entry", url="", manual=True, type="llmstxt",
    )
    source_mapping.save()
    fetch_main(config=config)
    assert "has no url" in caplog.text


@pytest.mark.unit
def test_fetch_llmstxt_repo_filter(workspace, source_mapping):
    """--repo filter applies to llmstxt sources too."""
    source_mapping.add_source(
        path_key="included",
        url="https://example.com/a.txt",
        manual=True, type="llmstxt",
    )
    source_mapping.add_source(
        path_key="excluded",
        url="https://example.com/b.txt",
        manual=True, type="llmstxt",
    )
    source_mapping.save()
    config.fetch_repo = "included"
    with patch("opencrane.rag.fetch_docs.urlopen") as mock_urlopen:
        # ... mock setup ...
        fetch_main(config=config)
    assert (workspace / ".opencrane" / "llmstxt" / "included" / "llms-full.txt").exists()
    assert not (workspace / ".opencrane" / "llmstxt" / "excluded" / "llms-full.txt").exists()


@pytest.mark.unit
def test_fetch_llmstxt_error_continues(workspace, source_mapping, caplog):
    """Failed llmstxt download logs error and continues."""
    source_mapping.add_source(
        path_key="broken",
        url="https://example.com/broken.txt",
        manual=True, type="llmstxt",
    )
    source_mapping.save()
    with patch("opencrane.rag.fetch_docs.urlopen", side_effect=Exception("network error")):
        fetch_main(config=config)  # should not raise
    assert "Failed to fetch llmstxt" in caplog.text


@pytest.mark.unit
def test_fetch_llmstxt_protected_from_cleanup(workspace, source_mapping):
    """llmstxt entries are not removed by cleanup_stale_sources."""
    source_mapping.add_source(
        path_key="my-llmstxt",
        url="https://example.com/llms-full.txt",
        manual=True, type="llmstxt",
    )
    source_mapping.save()
    # active_repos will include llmstxt entries per the protection loop
    fetch_main(config=config)
    assert source_mapping.get_source("my-llmstxt") is not None
```

Note: These test outlines use the existing test fixture patterns in the fetch_docs test file. Adapt to match the exact fixture names and config setup used in the existing tests.

- [ ] **Step 5: Run tests**

Run: `./pytest.sh tests/unit/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add opencrane/rag/fetch_docs.py tests/
git commit -m "feat: add llmstxt source fetching to fetch_docs"
```

---

### Task 7: Add `docs_url` heading injection for llmstxt sources

The spec requires that when `docs_url` is set on an llmstxt source, URL prefixes are injected into headings of the pre-existing llms-full.txt content before combining.

**Files:**
- Modify: `opencrane/rag/generate_llms_txt.py`
- Modify: `tests/unit/rag/test_llms_combine.py`

- [ ] **Step 1: Understand the existing heading prefix pattern**

In `generate_llms_txt.py`, the function `prefix_headings_with_path()` (or similar) adds `[url]` prefixes to markdown headings. The `_combine_existing_llmstxt()` function currently concatenates files without any heading rewriting. We need to add source mapping lookup when combining llmstxt files.

- [ ] **Step 2: Modify `_combine_existing_llmstxt()` to inject `docs_url` headings**

When combining llmstxt subdirectories, look up each subdirectory name in the source mapping. If the entry has `docs_url`, prefix all markdown headings (`# ...`) with the docs_url. This follows the same pattern used for GitHub source headings.

```python
import re

def _combine_existing_llmstxt(llmstxt_dir: Path) -> str | None:
    """Combine pre-existing llms-full.txt files from subdirectories."""
    # ... existing directory scanning logic ...

    parts = []
    for subdir in sorted(llmstxt_dir.iterdir()):
        if not subdir.is_dir():
            continue
        llms_file = subdir / "llms-full.txt"
        if not llms_file.exists():
            continue
        content = llms_file.read_text()

        # Inject docs_url into headings if configured
        mapping = get_source_mapping()
        source = mapping.get_source(subdir.name)
        if source and source.get("docs_url"):
            docs_url = source["docs_url"].rstrip("/")
            content = re.sub(
                r"^(#{1,6})\s+(.+)$",
                rf"\1 [{docs_url}] \2",
                content,
                flags=re.MULTILINE,
            )

        parts.append(content)

    if not parts:
        return None
    return "\n======\n".join(parts)
```

- [ ] **Step 3: Write test for heading injection**

In `tests/unit/rag/test_llms_combine.py`:

```python
@pytest.mark.unit
def test_combine_injects_docs_url_into_headings(llmstxt_workspace, monkeypatch):
    """When a llmstxt source has docs_url, headings get URL prefixes."""
    # Write sources.yaml with a docs_url entry
    sources_yaml = llmstxt_workspace / ".opencrane" / "sources.yaml"
    sources_yaml.write_text(
        "sources:\n"
        "  project-a:\n"
        "    type: llmstxt\n"
        "    url: https://example.com/a.txt\n"
        "    docs_url: https://docs.example.com\n"
        "    manual: true\n"
    )
    monkeypatch.setenv("MAPPING_FILE", str(sources_yaml))
    monkeypatch.chdir(llmstxt_workspace)

    llmstxt_dir = llmstxt_workspace / ".opencrane" / "llmstxt"
    generate_outputs(force=True, llmstxt_dir=llmstxt_dir)

    combined = llmstxt_dir / "llms-full.txt"
    content = combined.read_text()
    assert "[https://docs.example.com]" in content
    assert "# [https://docs.example.com] Project A docs" in content


@pytest.mark.unit
def test_combine_no_docs_url_leaves_headings_unchanged(llmstxt_workspace, monkeypatch):
    """Without docs_url, headings are not modified."""
    monkeypatch.chdir(llmstxt_workspace)
    llmstxt_dir = llmstxt_workspace / ".opencrane" / "llmstxt"
    generate_outputs(force=True, llmstxt_dir=llmstxt_dir)

    combined = llmstxt_dir / "llms-full.txt"
    content = combined.read_text()
    assert "# Project A docs" in content  # no URL prefix
    assert "[" not in content.split("\n")[0]  # first heading has no brackets
```

- [ ] **Step 4: Run tests**

Run: `./pytest.sh tests/unit/rag/test_llms_combine.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add opencrane/rag/generate_llms_txt.py tests/unit/rag/test_llms_combine.py
git commit -m "feat: inject docs_url into llmstxt headings during combine"
```

---

### Task 8: Run full test suite and fix any remaining issues

- [ ] **Step 1: Run all unit tests with coverage**

Run: `./pytest.sh --check-coverage`
Expected: All tests PASS with 100% coverage

- [ ] **Step 2: Fix any failures or coverage gaps**

If tests fail, fix the root cause. If coverage is below 100%, identify uncovered lines and report to user before adding tests.

- [ ] **Step 3: Final commit**

Stage only the specific files that were modified, then commit:

```bash
git add <specific files that were changed>
git commit -m "fix: address remaining test and coverage issues"
```
