# Source mapping file

The source mapping file is the central configuration file for documentation processing in an OpenCrane project. By default, it is `.opencrane/config.yaml`. It defines which documentation sources exist, where they come from, and how OpenCrane processes them.

## What the source mapping file controls

The source mapping file does the following:

- Lists all documentation sources
- Sets which directories get a generated `llms-full.txt` file
- Provides the URLs that link generated content to its source page
- Defines the source names that agents can filter searches on

Each entry in the file has a path key, for example `my-project`. The path key becomes the `source_name` of each chunk from that entry. The Model Context Protocol (MCP) `search_docs` tool exposes the source names as the `source_names` filter, so agents can limit a query to specific sources. OpenCrane assigns a chunk to an entry by prefix-matching the `source_url` of the chunk against the `url` and `docs_url` of the entry.

## Structure of a source entry

The following example shows the structure of a source entry:

```yaml
sources:
  my-project:                            # Path key: the source name
    url: https://github.com/my-org/my-project
    docs_path: docs                       # Path within the repository
    manual: false                         # false: the fetch updates the entry; true: you maintain it

  content-guidelines/writing:            # Local source (no fetching)
    local: true
```

The following table describes each field:

| Field | Description |
|---|---|
| Path key, for example `my-project` | The source name. OpenCrane stores a fetched source in `.opencrane/sources/{PATH_KEY}`. For a local source, the path key is the directory path relative to the project root. |
| `url` | The source repository URL, used for page URLs and for the fetch. For a `type: llmstxt` source, the URL or local path of the `llms-full.txt` file. |
| `type` | `github` (the default) or `llmstxt`. An `llmstxt` source is an existing `llms-full.txt` bundle. The fetch writes it to `.opencrane/llmstxt/{PATH_KEY}/llms-full.txt`, and stale cleanup never removes it. |
| `docs_url` | The base URL of the published documentation site. When set, OpenCrane builds page URLs from it instead of from `url`. |
| `docs_path` | The path within the source repository where the documentation is. An empty string means the repository root. If you leave the field out, the fetch uses `docs`. |
| `manual` | `false` means OpenCrane generates the entry and updates it during the fetch. `true` means you added the entry and maintain it yourself. |
| `local` | When `true`, the path key points to a local directory in the project. OpenCrane does not fetch it, and the pipeline reads directly from this path. |
| `sha`, `tag`, `release`, `branch` | Pin the fetch to one commit, tag, release, or branch. The fetch reads these fields only on entries with `manual: true`. |

## Use a different source mapping file

To use a different file, set the `MAPPING_FILE` environment variable. The default is `.opencrane/config.yaml`. The CLI still reads the `extensions` and `section_anchor_style` keys from `.opencrane/config.yaml`, and `opencrane add` still writes new sources there.

## Automatic updates during the fetch

> [!CAUTION]
> When auto-discovery no longer returns a repository (it lost the discovery topic, its topics could not be read, or the token cannot see it), `opencrane fetch` removes its entry from the source mapping file. It also deletes its local source directory and its generated `llmstxt/` output. To keep the source, set `manual: true` on its entry.

When `opencrane fetch` runs, it updates the source mapping file automatically in the following order:

1. Uses the GitHub API to find the repositories that carry the discovery topic.
2. Adds or updates an entry in the source mapping file for each repository:
   - Sets `manual: false` for auto-discovered sources
   - Keeps `manual: true` entries and does not overwrite them
3. Removes stale entries. A stale entry has `manual: false` and points to a repository that auto-discovery no longer returns. For each stale entry, the fetch does the following:
   - Removes the entry from the source mapping file
   - Deletes the local source directory, for example `.opencrane/sources/repo-name/`
   - Deletes the generated output directory, for example `.opencrane/llmstxt/repo-name/`

The fetch never removes the following entries, and it keeps their directories:

- `manual: true` entries
- `local: true` entries
- `llmstxt` entries

## How the file controls `llms-full.txt` output

OpenCrane generates one `llms-full.txt` file for each mapped path, not one for every subdirectory, so you control the output structure directly.

### Output location

The path key in the source mapping file sets where OpenCrane writes the generated file. Take the following entry as an example:

```yaml
my-project:
  url: https://github.com/my-org/my-project
  docs_path: docs
  manual: false
```

OpenCrane writes the bundle for that entry to the following path:

```text
.opencrane/llmstxt/my-project/llms-full.txt
```

The output directory has the same name as the path key, so you can see which source a file came from.

### Files included in a bundle

When OpenCrane generates `llms-full.txt` for a mapped path, it does the following:

1. Starts at the mapped directory, for example `.opencrane/sources/my-project/`.
2. Collects all Markdown files recursively, from every subdirectory, for example `guides/` or `releases/`.
3. Writes all the content into one `llms-full.txt` file at the mapped path.

OpenCrane creates no `llms-full.txt` file in a subdirectory, even when that subdirectory, for example `guides/`, contains Markdown.

The following example shows a source directory and the bundles that OpenCrane generates and does not generate from it:

```text
Source structure:
  .opencrane/sources/my-project/
    README.md
    installation.md
    guides/
      mesh.md
    releases/
      1.0.0.md
    technical-reference/
      config.md

Generated output:
  .opencrane/llmstxt/my-project/llms-full.txt  ← Contains all five files

Not generated:
  .opencrane/llmstxt/my-project/guides/llms-full.txt  ✗
  .opencrane/llmstxt/my-project/releases/llms-full.txt  ✗
```

## Page URLs

OpenCrane uses the `url` and `docs_url` fields to build a source URL for each page. It does not add these URLs to the `llms-full.txt` headings. Instead, it writes them to the companion `llms.txt` index, with one `- [title](page_url)` link for each page. During chunking, OpenCrane joins each URL back to its chunks. For details, see [Generate llms-full.txt bundles](llms-generation.md) and [Document boundaries and page URLs](chunking.md#document-boundaries-and-page-urls).

When only `url` is set, OpenCrane builds a GitHub URL. Take the following mapping as an example:

```yaml
my-project:
  url: https://github.com/my-org/my-project
  docs_path: docs
```

For the file `.opencrane/sources/my-project/guides/setup.md`, OpenCrane builds the URL in the following order:

1. Takes `url`: `https://github.com/my-org/my-project`
2. Adds `/blob/main`. OpenCrane always links to the `main` branch, even when the fetch used a release or a pinned commit, tag, or branch.
3. Adds `docs_path`, if present: `/docs`
4. Adds the path of the file relative to the mapped directory, without a leading `docs_path`: `/guides/setup.md`

OpenCrane writes the resulting entry to `llms.txt`:

```markdown
## my-project
- [Setup Guide](https://github.com/my-org/my-project/blob/main/docs/guides/setup.md)
```

When `docs_url` is set, it takes precedence over `url`. OpenCrane builds a URL for each page on the published documentation site in the following way:

1. Takes the path of the file relative to the mapped directory, without a leading `docs_path`.
2. Removes the `.md` extension, and maps an `index.md` file to its parent directory.
3. Adds the result to `docs_url`.

For example, `guides/setup.md` with `docs_url: https://docs.example.com/product` becomes `https://docs.example.com/product/guides/setup`. Agents can then point users to the rendered documentation rather than to the raw GitHub files.

### `docs_url` for external `llmstxt` sources

For an existing external `llmstxt` bundle, the role of `docs_url` depends on whether `opencrane fetch` found a companion `llms.txt`. For details, see [Companion llms.txt index for llmstxt sources](fetching.md#companion-llmstxt-index-for-llmstxt-sources). The following table shows both cases:

| Companion `llms.txt` | Role of `docs_url` |
|---|---|
| Fetched | OpenCrane uses the real URL of each page from the companion file. It does not need `docs_url` to resolve URLs. |
| Not fetched | The `llms` step treats each H1 heading as the start of a page, and builds one index entry for each page. Every entry carries the same base `docs_url`. If no `docs_url` is set, those chunks get no `source_url`. |

## Who maintains each entry

The `manual` and `local` fields set who maintains each entry in the source mapping file. This section describes each kind of entry.

### Auto-generated entries

Auto-generated entries have `manual: false`. The following rules apply to them:

- OpenCrane discovers the external repository through the GitHub API.
- The fetch creates and updates the entry automatically.
- `opencrane fetch` downloads the documentation each time it runs, locally or in a continuous integration and delivery (CI/CD) pipeline.

### Manual entries

Manual entries have `manual: true`. The following rules apply to them:

- You add the entry for the external repository and maintain it yourself.
- OpenCrane does not discover the repository or overwrite the entry, but it still fetches the documentation from GitHub.

### Local entries

Local entries have `local: true`. The following rules apply to them:

- Documentation for the entry already exists in the project, for example content in the same repository.
- No fetch happens. The pipeline reads directly from the local path.
- The path key is the local directory path, relative to the project root.
- `url` is optional. If you set it, OpenCrane uses it to build the GitHub page URLs for the local files.
- Stale cleanup never removes a local entry.

Local entries fit content that lives next to the OpenCrane project, for example:

- Content guidelines
- Writing standards
- Templates

The following example shows a local entry and a manual entry:

```yaml
sources:
  # Local content: no fetching, reads content-guidelines/writing in the project
  content-guidelines/writing:
    local: true

  # Remote content: fetched from GitHub
  my-project:
    url: https://github.com/my-org/my-project
    docs_path: docs
    manual: true
```
