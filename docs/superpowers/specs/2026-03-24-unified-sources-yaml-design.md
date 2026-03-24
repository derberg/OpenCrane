# Unified sources.yaml for GitHub and llmstxt Sources

## Problem

`opencrane add` supports two source types: GitHub repos and pre-existing llms-full.txt files. GitHub sources are registered in `sources.yaml` and re-fetched on every build. llmstxt sources are downloaded immediately to `.opencrane/llmstxt/` but never recorded in `sources.yaml` — making them one-time imports that can't be re-fetched.

## Solution

Unify both source types under `sources.yaml` with a `type` discriminator. Rename `github_url` to `url`. Move llmstxt download/copy logic from `add_source.py` to `fetch_docs.py` so that `opencrane fetch` (and therefore `opencrane build`) re-downloads llmstxt sources on every run.

## Schema

```yaml
sources:
  # GitHub source (type defaults to "github" when omitted)
  MicrosoftDocs/microsoft-style-guide:
    url: https://github.com/MicrosoftDocs/microsoft-style-guide
    docs_path: styleguide
    docs_url: https://learn.microsoft.com/en-us/style-guide
    manual: true

  # llmstxt from URL
  anthropic-docs:
    type: llmstxt
    url: https://docs.anthropic.com/llms-full.txt
    docs_url: https://docs.anthropic.com
    manual: true

  # llmstxt from local file path
  internal-style:
    type: llmstxt
    url: /home/user/docs/llms-full.txt
    manual: true
```

### Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `type` | no | `github` | Source type: `github` or `llmstxt` |
| `url` | yes | — | GitHub URL, llmstxt URL, or local file path |
| `docs_path` | no | `""` | GitHub-only: subdirectory within repo containing docs. Ignored for `type: llmstxt`. |
| `docs_url` | no | — | Published docs base URL for source link injection |
| `manual` | no | `false` | Protects entry from auto-refresh overwrites. Always `true` for entries added via `opencrane add`. |

No backward compatibility for `github_url` — clean rename to `url` everywhere.

## Changes by Module

### `opencrane/rag/services/source_mapping.py`

- `add_source()`: replace `github_url` parameter with `url`, add `type` parameter (default `"github"`)
- Entry dict uses `url` instead of `github_url`, includes `type` when not `github`
- All other methods (`get_all_sources`, `cleanup_stale_sources`, `find_source_for_file`, `remove_source`) unchanged

### `opencrane/add_source.py`

- `add_github_source()`: pass `url=` instead of `github_url=` to `mapping.add_source()`
- `add_llmstxt_source()`: remove all download/copy logic. Register the source in `sources.yaml` via `mapping.add_source(type="llmstxt", url=location, ...)` and call `mapping.save()`. No file I/O.
- Remove `shutil`, `urllib` imports (no longer needed)

### `opencrane/rag/fetch_docs.py`

- The existing manual-repo loop must filter OUT `type: llmstxt` entries — only process entries where `type` is `github` (or absent). This prevents `parse_github_url()` from being called on non-GitHub URLs.
- New separate loop: iterate sources with `type == "llmstxt"`
- For URL sources (`http://` / `https://`): download to `.opencrane/llmstxt/<name>/llms-full.txt`
- For local path sources: copy to `.opencrane/llmstxt/<name>/llms-full.txt`
- Same destination structure as current `add_llmstxt_source()` uses
- Download/copy logic moves here from `add_source.py`
- `--repo` filtering applies to llmstxt sources too (filter by path key)
- Error handling: if an llmstxt download/copy fails, log the error and continue with other sources (don't fail the entire fetch step)
- `cleanup_stale_sources`: llmstxt path keys must be included in the `active_repos` set so they are not cleaned up

### `opencrane/rag/generate_llms_txt.py`

- `_combine_existing_llmstxt()` continues to work as-is (combines files from `.opencrane/llmstxt/`)
- New: when `docs_url` is set on an llmstxt source entry, inject URL prefixes into headings of the pre-existing llms-full.txt content before combining — same heading rewrite pattern used for GitHub sources
- Source mapping lookup works since llmstxt entries are now in `sources.yaml`

### `opencrane/cli.py`

- `add` interactive flow: unchanged from user perspective. Choice 2 (llmstxt) now calls the simplified `add_llmstxt_source()` that only registers in `sources.yaml`
- Add optional `docs_url` prompt when adding llmstxt sources (same as GitHub sources)
- Pass `url=` instead of `github_url=` where applicable

### Rename `github_url` → `url`

Grep the entire repo for `github_url` and rename all occurrences. Known files:
- `opencrane/rag/services/source_mapping.py`
- `opencrane/rag/fetch_docs.py`
- `opencrane/rag/generate_llms_txt.py` — includes `get_github_url()` function
- `opencrane/cli.py`
- `opencrane/add_source.py`
- `opencrane/fences/__init__.py` — re-exports `get_github_url` as public API
- `opencrane/shared/utils/github_url_parser.py` — utility module
- `opencrane/templates.py` — `SOURCES_YAML` scaffold template
- All tests and fixtures (including `tests/fixtures/test-mapping.yaml`)
- Documentation files (`docs/source-mapping.md`, `docs/llms-generation.md`)

### Public API rename: `get_github_url` → `get_source_url`

The `get_github_url()` function in `generate_llms_txt.py` is re-exported from `opencrane/fences/__init__.py` as a user-facing extension point. Rename to `get_source_url()` since it now resolves URLs for both GitHub and llmstxt sources. Update `fences/__init__.py` exports accordingly.

## Pipeline Flow (After)

```
add (github)  → sources.yaml (type: github)  → fetch (git clone) → llms → chunk → embed → index
add (llmstxt) → sources.yaml (type: llmstxt) → fetch (download/copy) → llms → chunk → embed → index
```

Both source types now follow the same lifecycle: register in config, fetch on build, process through pipeline.

## Tests

No new tests or test modifications without explicit user approval, per project policy. Existing tests will be updated to reflect `github_url` → `url` rename and the new `add_llmstxt_source()` behavior (registration only, no download).
