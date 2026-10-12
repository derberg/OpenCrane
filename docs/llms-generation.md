# Generate llms-full.txt bundles

The `llms` step combines the fetched documentation into single text files for a large language model (LLM) to read. Each of these bundles is an `llms-full.txt` file. The step writes one bundle for each source and a combined bundle with all sources in `.opencrane/llmstxt/llms-full.txt`. The combined bundle also includes the existing bundles of `llmstxt` sources.

OpenCrane loads the `Config` class from the file named in the `extensions` key of `.opencrane/config.yaml`. To load a class from another module, add `--config {MODULE}:{CLASS}` to the commands on this page, or set the `OPENCRANE_CONFIG` environment variable.

To process every source in the source mapping file, run the following command:

```bash
opencrane llms
```

> [!CAUTION]
> A run with `--sources-dir` rebuilds the combined `llms-full.txt` and its `llms.txt` index from only the directories you pass. Sources outside them lose their page URLs, so their chunks get no `source_url`. Run `opencrane llms` without `--sources-dir` before you run `opencrane chunk`.

To process only specific directories, pass each one with the `--sources-dir` flag:

```bash
opencrane llms --sources-dir {SOURCE_DIR} --sources-dir {OTHER_SOURCE_DIR}
```

With `--sources-dir`, or with directories set in the `AI_DOCS_SOURCES_DIRS` environment variable, the step skips regeneration when those directories have no uncommitted or untracked changes in Git. Git never reports changes in a directory it ignores. If Git ignores every directory you pass, the step always skips. To regenerate the bundles anyway, add the `--force` flag.

## Control the output with the source mapping file

The source mapping file, `.opencrane/config.yaml` by default, controls which directories get an `llms-full.txt` file. With one bundle for each mapped path, you choose which documentation sets the output includes. An LLM agent then reads one file for each source. The file shapes the output in the following ways:

- Only paths listed under the `sources:` key get an `llms-full.txt` file.
- Each generated file includes all Markdown from that directory and its subdirectories, except directories listed in `ignore_patterns`.
- Subdirectories do not get their own files. Each mapped path produces one file.

The documentation fetch keeps the source mapping file up to date. It adds new repositories and removes only auto-discovered entries that auto-discovery no longer returns. It never removes entries with `manual: true` or `local: true`, or `llmstxt` entries. See [How the fetch removes stale sources](fetching.md#how-the-fetch-removes-stale-sources).

### Example output

Consider a source mapping file with the following content:

```yaml
sources:
  my-project:
    url: https://github.com/my-org/my-project
    docs_path: docs
    manual: false
  another-project:
    url: https://github.com/my-org/another-project
    docs_path: docs
    manual: false
  content-guidelines/writing:
    local: true
```

From this file, the `llms` step generates the following output:

- `.opencrane/llmstxt/my-project/llms-full.txt`, which includes all Markdown from the fetched documentation of `my-project`
- `.opencrane/llmstxt/another-project/llms-full.txt`, which includes all Markdown from the fetched documentation of `another-project`
- `.opencrane/llmstxt/content-guidelines/writing/llms-full.txt`, built directly from the local `content-guidelines/writing/` directory

OpenCrane resolves local sources (`local: true`) relative to the project root instead of `.opencrane/sources/`. Use local sources for documentation that already exists in the same repository, because they need no fetching or copying.

## Bundle structure

The bundle holds the documentation content without page URLs. OpenCrane records the URL of each page in the companion `llms.txt` index next to the combined bundle. See [Companion `llms.txt` index](#companion-llmstxt-index).

The following table lists the markers that separate content within `llms-full.txt`:

| Marker | Separates |
|---|---|
| `<!-- opencrane:page -->` | The individual files (pages) that make up one source |
| `======` | One source's block from the next in the combined bundle |

The page marker is an HTML comment, so it does not show when the Markdown is rendered. To split a bundle into pages, split on the page marker, not on `---`, because page content can contain Markdown thematic breaks.

Each page begins with a `# {TITLE}` heading. See [Page titles](#page-titles).

OpenCrane replaces each image with an `[Image removed: {ALT_TEXT}]` note. It replaces each relative link to a Markdown file or an anchor with its link text, and an absolute-path link becomes `{LABEL} (link removed: {PATH})`. External links stay as they are.

The following example shows the structure of the combined `llms-full.txt`:

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

Next to the combined `llms-full.txt`, the `llms` step writes a standard `llms.txt` index that maps the title of each page to its URL. The index follows the [llms.txt convention](https://llmstxt.org/). The per-source bundles get no index of their own. The exception is an `llmstxt` source whose companion `llms.txt` the fetch downloaded. The following example shows the combined `.opencrane/llmstxt/llms.txt`:

```markdown
# Documentation

## source-alpha
- [Home](https://alpha.example.com/docs/home)
- [Setup Guide](https://alpha.example.com/docs/setup)

## source-beta
- [Overview](https://beta.example.com/docs/overview)
```

The index has the following structure:

- One top-level `# Documentation` heading
- A `## {SOURCE}` section for each source, in the same order as the matching `======` blocks in `llms-full.txt`
- Under each section, a `- [{TITLE}]({PAGE_URL})` link for each page that has a URL, in the same order as the pages in that source's block

Each link points to the specific page for GitHub sources and for sources configured with a `docs_url`. For GitHub sources, the link always points to the `main` branch, even when the fetch used a release or a pinned commit. A page without a URL gets no link. A source with no URLs at all gets an empty `- []()` placeholder, so the section order still matches the blocks in the bundle.

The `chunk` step uses this shared order to give each chunk the URL of its page. See [Document boundaries and page URLs](chunking.md#document-boundaries-and-page-urls).

## Page titles

OpenCrane removes from the bundle any YAML front matter that parses as a mapping. It chooses the title of each page from the first of the following that exists:

1. The `title` field of the front matter, when it is present and not empty
2. The first Markdown heading of any level in the body
3. A title derived from the file name, for example "Getting Started" from `getting-started.md`

OpenCrane adds a `# {TITLE}` heading with the chosen title at the start of each page block in `llms-full.txt`, unless the body already starts with exactly that heading. An existing H1 with different text stays in place under the new heading. The first heading of each page block then matches its entry in the `llms.txt` index.
