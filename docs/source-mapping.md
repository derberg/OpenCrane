# Source mapping file

The source mapping file lists the documentation sources of an OpenCrane project, where they come from, and how OpenCrane processes them. By default, it is `.opencrane/config.yaml`. The same file holds other project settings.

Each entry under `sources:` has a path key, for example `my-project`. The path key becomes the `source_name` of each chunk from that entry. The Model Context Protocol (MCP) `search_docs` tool exposes the source names as the `source_names` filter, so agents can limit a query to specific sources. OpenCrane assigns a chunk to an entry by matching the `source_url` of the chunk against the `url` and `docs_url` of each entry. The longest matching prefix wins. A chunk without a `source_url` gets no source name.

## Top-level keys

The following table lists the top-level keys of the file:

| Key | Description |
|---|---|
| `sources` | The documentation sources. See [Fields of a source entry](#fields-of-a-source-entry). |
| `ignore_patterns` | A list of directory names. The `llms` step leaves out every `.md` file under a directory with one of these names, at any depth. The match also covers the directories above the project, so a name that appears in the project path leaves out every file. The key applies to all sources. The `opencrane init` template sets it to `devel`. Without the key, OpenCrane ignores no directories. |
| `extensions` | Path to the Python file with your `Config` class, relative to `.opencrane/`, for example `extensions.py`. See [Extend OpenCrane](../README.md#extend-opencrane). |
| `section_anchor_style` | The slug style of section anchors. See [Choose an anchor style](../README.md#choose-an-anchor-style). |
| `section_clause_pattern` | The regular expression for clause IDs. See [Section navigation and clause IDs](../README.md#section-navigation-and-clause-ids). |
| `auth` | Authentication for the HTTP transport. See [Authentication and authorization](auth.md). |

## Fields of a source entry

The following example shows a GitHub source and a local source:

```yaml
sources:
  my-project:                            # Path key: the source name
    url: https://github.com/my-org/my-project
    docs_path: docs                       # Path within the repository
    manual: true                          # You maintain this entry

  content-guidelines/writing:            # Local source: no fetch
    local: true
```

The following table describes each field:

| Field | Description |
|---|---|
| Path key, for example `my-project` | The source name. OpenCrane stores a fetched source in `.opencrane/sources/{PATH_KEY}/`. For a local source without `docs_path`, the path key is the directory path relative to the project root. |
| `url` | The source repository URL, used for page URLs and for the fetch. For a `type: llmstxt` source, the URL or local path of the `llms-full.txt` file. |
| `type` | `github` (the default) or `llmstxt`. An `llmstxt` source is an existing `llms-full.txt` bundle. The fetch writes it to `.opencrane/llmstxt/{PATH_KEY}/llms-full.txt`, and stale cleanup never removes it. |
| `docs_url` | The base URL of the published documentation site. When set, OpenCrane builds page URLs from it instead of from `url`. A fetch can remove this field. See [Entries that the fetch maintains](#entries-that-the-fetch-maintains). |
| `docs_path` | The path within the source repository where the documentation is. An empty string means the repository root. If you leave the field out, the fetch uses `docs`. For a local source, `docs_path` names the directory to read, relative to the project root, in place of the path key. |
| `manual` | `false` means auto-discovery created the entry, and each fetch rewrites or removes it. `true` means you maintain the entry. `opencrane add` sets `true`. |
| `local` | When `true`, the entry is a directory in the project. OpenCrane does not fetch it, and the `llms` step reads the directory directly. |
| `ignore_patterns` | More directory names to leave out of this source. OpenCrane adds them to the top-level `ignore_patterns`. A fetch can remove this field. See [Entries that the fetch maintains](#entries-that-the-fetch-maintains). |
| `sha`, `tag`, `release`, `branch` | Pin the fetch to one commit, tag, release, or branch. The fetch reads these fields only on entries with `manual: true`. For the order of precedence, see [Fetch documentation sources](fetching.md). |

For which files a bundle includes, see [Choose what each bundle contains](llms-generation.md#choose-what-each-bundle-contains).

## Use a different source mapping file

To use a different file, set the `MAPPING_FILE` environment variable. OpenCrane then reads the source mapping file from that path, with the following exceptions:

- The CLI reads the `extensions` key and the `section_*` keys from `.opencrane/config.yaml`.
- `opencrane add` writes new sources to `.opencrane/config.yaml`.

## Entries that the fetch maintains

For each repository that auto-discovery returns, `opencrane fetch` writes an entry with only `url`, `docs_path: docs`, and `manual: false`. The fetch never changes an entry with `manual: true` into an auto-discovered one, and never removes it. For the cleanup rules, see [How the fetch removes stale sources](fetching.md#how-the-fetch-removes-stale-sources).

Each fetch rewrites every GitHub entry that it fetches, including entries with `manual: true`. The rewritten entry keeps only the following fields:

- `url`
- `docs_path`
- `manual`
- `sha`, `tag`, `release`, and `branch`

The fetch drops every other field, for example `docs_url` and `ignore_patterns`.

## Page URLs

OpenCrane uses the `url` and `docs_url` fields to build a URL for each page. For where OpenCrane stores the URLs, see [Companion `llms.txt` index](llms-generation.md#companion-llmstxt-index).

When only `url` is set, OpenCrane builds a GitHub URL. Take the following mapping as an example:

```yaml
my-project:
  url: https://github.com/my-org/my-project
  docs_path: docs
```

For the file `.opencrane/sources/my-project/guides/setup.md`, OpenCrane builds the URL in the following order:

1. Takes `url`: `https://github.com/my-org/my-project`
2. Adds `/blob/` and the Git ref that the fetch read, for example `/blob/v1.2.0`. For how the fetch picks the ref, see [Fetch documentation sources](fetching.md).
3. Adds `docs_path`, if present: `/docs`
4. Adds the path of the file relative to the directory of the source: `/guides/setup.md`

For a fetched source, a missing `docs_path` counts as `docs`, the directory that the fetch copies, and an empty `docs_path` adds nothing in step 3. A local source keeps its path key in the URL, because the key is a directory of the repository.

The fetch skips local sources, so their URLs use the `main` branch. A source that an older OpenCrane version fetched also uses `main` until you run the fetch again.

If the fetch read the `v1.2.0` release, OpenCrane writes the following entry to `llms.txt`:

```markdown
## my-project
- [Setup Guide](https://github.com/my-org/my-project/blob/v1.2.0/docs/guides/setup.md)
```

For a local source in a project that sits in a subdirectory of its Git repository, OpenCrane also adds the path of that subdirectory after `/blob/main`.

When `docs_url` is set, it takes precedence over `url`. OpenCrane builds a URL for each page on the published documentation site in the following way:

1. Takes the path of the file relative to the directory of the source, without a leading `docs_path`.
2. Removes the `.md` extension, and maps an `index.md` file to its parent directory.
3. Adds the result to `docs_url`.

For example, `guides/setup.md` with `docs_url: https://docs.example.com/product` becomes `https://docs.example.com/product/guides/setup`. Agents can then point users to the rendered documentation rather than to the raw GitHub files.

### `docs_url` for external `llmstxt` sources

For an external `llmstxt` bundle, the role of `docs_url` depends on whether `opencrane fetch` found a companion `llms.txt`. See [Companion llms.txt index for llmstxt sources](fetching.md#companion-llmstxt-index-for-llmstxt-sources). The following table shows both cases:

| Companion `llms.txt` | Role of `docs_url` |
|---|---|
| Fetched | OpenCrane uses the URL of each page from the companion file. `docs_url` is optional. |
| Not fetched | The `llms` step treats each H1 heading outside code blocks as the start of a page, and builds one index entry for each page. Every entry carries the same base `docs_url`. If no `docs_url` is set, those chunks get no `source_url`. |

## Local entries

A local entry has `local: true` and reads documentation that already exists in the project, for example content guidelines in the same repository. The following rules apply to it:

- No fetch happens, and stale cleanup never removes the entry.
- The path key is the local directory path, relative to the project root, unless `docs_path` is set.
- `url` is optional. If you set it, OpenCrane uses it to build the GitHub page URLs for the local files. Without `url` or `docs_url`, the chunks of the entry get no `source_url` and no source name.

The following example shows a local entry and a manual entry:

```yaml
sources:
  # Local content: no fetch, reads content-guidelines/writing in the project
  content-guidelines/writing:
    local: true
    url: https://github.com/my-org/my-docs-project

  # Remote content: fetched from GitHub
  my-project:
    url: https://github.com/my-org/my-project
    docs_path: docs
    manual: true
```
