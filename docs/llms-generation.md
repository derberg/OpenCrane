# Generating llms-full.txt bundles

Use the `llms` command to create flattened text bundles for LLM ingestion:

```bash
opencrane llms --config yourproject.config:YourConfig  # Default: processes configured source directories

# Multiple source directories
opencrane llms --config yourproject.config:YourConfig --sources-dir external-sources --sources-dir external/docs
```

## Output Control via Source Mapping Config

The source mapping config file (e.g., `source-mapping.yaml`) controls which directories get `llms-full.txt` files generated. This provides fine-grained control over the output structure and prevents unwanted file generation.

**How it works:**
- Only paths explicitly listed in the source mapping under the `sources:` key get `llms-full.txt` files generated
- Each generated file includes ALL markdown from that directory and subdirectories recursively
- No automatic subdirectory file generation - one file per mapped path
- **Automatically maintained** during documentation fetch - adds new repos and removes stale ones (only `manual: false` entries)

**Example:**

If your source mapping config contains:
```yaml
sources:
  external-sources/my-project:
    url: https://github.com/my-org/my-project
    docs_path: docs
    manual: false
  external-sources/another-project:
    url: https://github.com/my-org/another-project
    docs_path: docs
    manual: false
  content-guidelines/writing:
    local: true
```

Then generation produces:
- `llmstxt/external-sources/my-project/llms-full.txt` (includes all markdown from `guides/`, `releases/`, `technical-reference/`, etc.)
- `llmstxt/external-sources/another-project/llms-full.txt` (includes all markdown recursively)
- `llmstxt/content-guidelines/writing/llms-full.txt` (reads directly from local `content-guidelines/writing/` directory)
- No files for `my-project/guides/` or other subdirectories

**Local sources** (`local: true`) are resolved relative to the workspace root instead of `.opencrane/sources/`. This is useful for documentation that already exists in the same repository — no fetching or copying needed.

**Why this matters:**
- Prevents file explosion with hundreds of small files
- Gives you explicit control over what gets generated
- Makes it easy to include/exclude specific documentation sets
- Simplifies consumption for LLM agents (one file per product/extension)
- Automatically stays in sync with active repositories (stale entries are cleaned up during fetch)

## Document Structure

The `llms` step emits a **clean** `llms-full.txt` — source URLs are **not** injected into headings, and there is no per-file `### {url}` boundary line. Instead, the bundle carries only the documentation content, and per-page source URLs are recorded in a companion `llms.txt` index written alongside it (see below).

Within `llms-full.txt`, boundaries are marked structurally:

1. `<!-- opencrane:page -->` — separates the individual files (pages) that make up one source. This is a collision-proof HTML-comment sentinel (invisible when rendered) rather than a dash rule, because a markdown thematic break (`---`, `-----`) in page content would be indistinguishable from a dash-based separator and silently split the page.
2. `======` — separates one source's block from the next in the combined bundle

Each page begins with a single `# {title}` H1 heading (see [Page titles](#page-titles)). Image references are stripped and relative links are rewritten so they continue to work in the flattened output.

Example structure of the combined `llms-full.txt`:
```markdown
# Home

Welcome to the home page.

## Overview

...

<!-- opencrane:page -->

# Setup Guide

Installation instructions...

======

# Overview

A page from a different source...
```

## Companion `llms.txt` index

Next to every `llms-full.txt`, the `llms` step writes a standard `llms.txt` index that maps each page's title to its specific URL. The combined `.opencrane/llmstxt/llms.txt` follows the `llms.txt` convention:

```markdown
# Documentation

## source-alpha
- [Home](https://alpha.example.com/docs/home)
- [Setup Guide](https://alpha.example.com/docs/setup)

## source-beta
- [Overview](https://beta.example.com/docs/overview)
```

- A top-level `# {project}` H1.
- One `## {source}` section per source, in the **same order** as the corresponding `======` blocks in `llms-full.txt`.
- One `- [{title}]({page_url})` link per page, in the **same order** as the `<!-- opencrane:page -->`-separated pages inside that source's block.

Per-source `llms.txt` files are also written next to each per-source `llms-full.txt`. The URL for each entry comes from `get_source_url(...)`, which is page-specific for GitHub sources and for sources configured with a `docs_url`.

This positional, per-source alignment is what lets the `chunk` step recover each chunk's specific page `source_url` from clean content — see [Chunking](chunking.md).

## Page titles

Each page's title is chosen with this precedence:

1. **Frontmatter `title`** — YAML frontmatter is stripped from the emitted content, and its `title` field (when present and non-empty) is used.
2. **First heading** — the first Markdown heading in the body.
3. **Filename** — derived from the file stem (e.g. `getting-started.md` → "Getting Started").

The page block's leading H1 in `llms-full.txt` is normalized to equal the chosen title (a synthetic `# {title}` is prepended when the body has no matching leading H1). This keeps the H1 exactly equal to the matching `llms.txt` index entry so the title-validated join stays exact.
