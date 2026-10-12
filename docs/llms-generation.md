# Generate llms-full.txt bundles

The `llms` step combines the fetched documentation into single text files for a large language model (LLM) to read. Each of these bundles is an `llms-full.txt` file. The step writes one bundle for each source, and a combined bundle with all sources in `.opencrane/llmstxt/llms-full.txt`. The combined bundle also includes the existing bundles of `llmstxt` sources.

To process every source in the source mapping file, run the following command:

```bash
opencrane llms
```

## Process specific directories

To process only specific directories, pass each one with the `--sources-dir` flag, or list them in the `AI_DOCS_SOURCES_DIRS` environment variable, separated by commas.

> [!CAUTION]
> A run with `--sources-dir` or `AI_DOCS_SOURCES_DIRS` rewrites the combined `llms-full.txt` and its `llms.txt` index around only the directories you pass. Other sources lose their page URLs, and some can drop out of the combined bundle. Run `opencrane llms` without these settings before you run `opencrane chunk`.

To process two directories, run the following command:

```bash
opencrane llms --sources-dir {SOURCE_DIR} --sources-dir {OTHER_SOURCE_DIR}
```

In this mode, the step skips regeneration when Git reports no uncommitted or untracked changes in those directories. Git never reports changes in a directory it ignores, so if Git ignores every directory you pass, the step always skips. Outside a Git repository, the step always regenerates. To regenerate the bundles anyway, add the `--force` flag.

## Choose what each bundle contains

The source mapping file, `.opencrane/config.yaml` by default, controls which directories get an `llms-full.txt` file. The file shapes the output in the following ways:

- Only paths listed under the `sources:` key get an `llms-full.txt` file.
- Each bundle includes every `.md` file from the directory of the source and its subdirectories, except files under a directory listed in `ignore_patterns`. See [Top-level keys](source-mapping.md#top-level-keys).
- Subdirectories do not get their own bundles.

For example, consider a source mapping file with the following content:

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

From this file, the `llms` step generates the following bundles:

- `.opencrane/llmstxt/my-project/llms-full.txt`, from `.opencrane/sources/my-project/`
- `.opencrane/llmstxt/another-project/llms-full.txt`, from `.opencrane/sources/another-project/`
- `.opencrane/llmstxt/content-guidelines/writing/llms-full.txt`, from the local `content-guidelines/writing/` directory of the project

A file in a subdirectory, for example `.opencrane/sources/my-project/guides/setup.md`, goes into the `my-project` bundle. OpenCrane writes no `.opencrane/llmstxt/my-project/guides/llms-full.txt`.

If the source mapping file lists no sources, the step combines the `llms-full.txt` files that already exist in the subdirectories of `.opencrane/llmstxt/`.

## Bundle structure

The following table lists the markers that separate content within `llms-full.txt`:

| Marker | Separates |
|---|---|
| `<!-- opencrane:page -->` | The individual files (pages) that make up one source |
| `======` | One source's block from the next in the combined bundle |

The page marker is an HTML comment, so it does not show when the Markdown is rendered. To split a bundle into pages, split on the page marker, not on `---`, because page content can contain Markdown thematic breaks.

Each page begins with a `# {TITLE}` heading. See [Page titles](#page-titles).

The bundle holds no page URLs. OpenCrane records them in the companion `llms.txt` index. See [Companion `llms.txt` index](#companion-llmstxt-index). The exception is a block that a built-in fence type inlines, which starts with a `### {SOURCE_URL}` heading. See [Built-in fence types](../README.md#built-in-fence-types).

OpenCrane changes the content of each page in the following ways:

- Images become an `[Image removed: {ALT_TEXT}]` note. Without alt text, the note names the image file.
- A relative link to a Markdown file or an anchor becomes its link text. A link to a path without an extension counts as a link to a Markdown file.
- An absolute-path link becomes `{LABEL} (link removed: {PATH})`.
- A `data:` link becomes `{LABEL} (inline data removed)`.
- Fenced blocks of a [fence type](../README.md#built-in-fence-types) become the output of its handler.

External links and relative links to other file types, for example a `.pdf` file, stay as they are.

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

For how OpenCrane builds each page URL, see [Page URLs](source-mapping.md#page-urls). A page without a URL gets no link. A source with no URLs at all gets an empty `- []()` placeholder, so the section order still matches the blocks in the bundle.

The `chunk` step uses this shared order to give each chunk the URL of its page. See [Document boundaries and page URLs](chunking.md#document-boundaries-and-page-urls).

## Page titles

OpenCrane removes from the bundle any YAML front matter that parses as a mapping. It chooses the title of each page from the first of the following that exists:

1. The `title` field of the front matter, when it is present and not empty
2. The first Markdown heading of any level in the body
3. A title derived from the file name, for example "Getting Started" from `getting-started.md`

OpenCrane adds a `# {TITLE}` heading with the chosen title at the start of each page block in `llms-full.txt`, unless the body already starts with exactly that heading. An existing H1 with different text stays in place under the new heading. The first heading of each page block then matches its entry in the `llms.txt` index.
