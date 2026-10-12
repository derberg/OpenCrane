# Fetch documentation sources

The `opencrane fetch` command copies documentation from GitHub repositories into `.opencrane/sources/`. By default, it fetches the documentation from the latest release of each repository. If a repository has no releases, it uses the default branch.

For an entry with `manual: true`, you can fetch a fixed branch, tag, release, or commit instead. Set the matching field on the entry, as described in the [source mapping file](source-mapping.md). If you set more than one of these fields, `sha` takes precedence, then `tag`, `release`, and `branch`. OpenCrane ignores these fields on auto-discovered entries.

The usual setup runs the fetch on a schedule, for example in a scheduled GitHub Actions workflow, so the indexed documentation stays current.

## Choose which repositories to fetch

OpenCrane finds the repositories to fetch in two ways:

- Auto-discovery: OpenCrane fetches every repository with the discovery topic in the organization you fetch from.
- Manual entries: OpenCrane fetches every repository whose entry in the source mapping file sets `manual: true`, regardless of its topics.

The discovery topic is `documentation` by default. To use another topic, set the `DOCS_TOPIC` environment variable.

Each fetch discovers repositories in one organization only: the one that the `--org` flag or the `ORG_NAME` environment variable names. When you pass `--org`, auto-discovery always runs for that organization.

When `ORG_NAME` selects the organization, as in a continuous integration (CI) workflow, auto-discovery runs only if the organization is in the `AUTO_DISCOVERY_ORGS` environment variable. The variable takes a comma-separated list and is empty by default. The following command allows auto-discovery for two organizations:

```bash
export AUTO_DISCOVERY_ORGS={ORG_NAME},{OTHER_ORG_NAME}
```

> [!CAUTION]
> If `ORG_NAME` names an organization that is not in `AUTO_DISCOVERY_ORGS` and you do not pass `--org`, the fetch discovers no repositories in it. It then deletes the local source directory and the `llmstxt/` output of every auto-discovered entry from that organization, and removes the entries from the source mapping file. `opencrane build` never passes `--org`, so a build in this setup always deletes these entries. Pass `--org`, or add the organization to `AUTO_DISCOVERY_ORGS`.

## How the fetch removes stale sources

A source is stale when auto-discovery no longer returns its repository. Auto-discovery stops returning a repository in the following cases:

- The repository lost the discovery topic.
- OpenCrane could not read the topics of the repository after retries.
- The token cannot see the repository, for example because it was deleted or renamed.

Each fetch removes stale sources, so outdated documentation does not accumulate.

> [!CAUTION]
> When auto-discovery no longer returns a repository, `opencrane fetch` deletes its local source directory and its generated `llmstxt/` output. To keep the source, set `manual: true` on its entry.

The following table shows what the fetch does with each kind of source during cleanup:

| Source | Cleanup behavior |
|---|---|
| Stale auto-discovered entry (`manual: false`) | Removed from the source mapping file, with its directories in `.opencrane/sources/` and `.opencrane/llmstxt/` |
| Entry with `manual: true` | Never removed |
| Entry with `local: true` | Never fetched or removed, because it points to a directory in the project root |
| Entry with `type: llmstxt` | Never removed |
| Auto-discovered entry from another organization | Not fetched, and kept |
| Entry that `--source` does not name, when you pass `--source` | Not fetched, and kept |
| Repository whose files fail to download, for example after a network error, or that has no files | Kept |

## Run the fetch locally

Run the fetch on your own machine for the following purposes:

- To test a configuration
- To troubleshoot a source
- To refresh a source after the scheduled run fails

Run the commands from the project root, the directory that contains `.opencrane/config.yaml`. Before you start, make sure you have the following:

- OpenCrane installed with the `pipeline` extra, on Python 3.11 or later (see [Installation](../README.md#installation))
- A GitHub token in the `GITHUB_TOKEN` environment variable

### Fetch the repositories of an organization

The `opencrane fetch --org` command fetches every repository in the organization that has the discovery topic. It also fetches every entry with `manual: true` and every `llmstxt` source, and then removes stale sources.

> [!CAUTION]
> This command deletes the local source directory and the generated `llmstxt/` output of every auto-discovered repository in the organization that auto-discovery no longer returns. To keep such a source, set `manual: true` on its entry before you run the command.

To fetch the repositories of an organization, run the following command:

```bash
opencrane fetch --org {ORG_NAME}
```

The fetched files appear in `.opencrane/sources/`, in one directory for each source.

### Fetch specific sources

To refresh only some sources, pass their path keys to `--source`. The path key is the top-level key under `sources:` in the source mapping file. Separate several keys with commas. For entries with `manual: true`, you do not need `--org`. To refresh an auto-discovered entry, also pass `--org {ORG_NAME}`.

> [!CAUTION]
> If a source you name is auto-discovered and auto-discovery no longer returns its repository, this command deletes its local source directory and its generated `llmstxt/` output. To keep the source, set `manual: true` on its entry before you run the command.

To fetch specific sources, run the following command:

```bash
opencrane fetch --source {PATH_KEY}
```

The `--repo` flag is an alias for `--source`.

The fetched files of a GitHub source appear in `.opencrane/sources/{PATH_KEY}/`. OpenCrane saves an `llmstxt` source in `.opencrane/llmstxt/{PATH_KEY}/llms-full.txt`.

## Companion `llms.txt` index for `llmstxt` sources

A source with `type: llmstxt` points to an existing `llms-full.txt` bundle, by URL or by local path, instead of to a GitHub repository. For these sources, `opencrane fetch` also tries to get the companion `llms.txt` index, which lists the URL of each page. OpenCrane saves the index next to the bundle, in `.opencrane/llmstxt/{PATH_KEY}/llms.txt`.

OpenCrane looks for the index in the following places:

- Remote source whose `url` ends in `llms-full.txt`: OpenCrane replaces that file name with `llms.txt`.
- Other remote source: OpenCrane appends `/llms.txt` to the `docs_url` of the source.
- Local source: OpenCrane copies the `llms.txt` file from the directory of the bundle, if the file exists.

If the download fails, the fetch continues without the index.

When the index exists, the `chunk` step gives each chunk the URL of its own page. Without the index, the `llms` step builds an index from the `docs_url` of the source, and every page gets that same base URL. If the source has no `docs_url` either, its pages get no URL. For details, see [`docs_url` for external `llmstxt` sources](source-mapping.md#docs_url-for-external-llmstxt-sources).

An index entry can end with a description, as in `- [Title](https://example.com/page): some text`. OpenCrane ignores the description.

The `llms.txt` index from GitBook and similar tools often lists URLs that end in `.md` or `/index.md`. If the source has a `docs_url`, OpenCrane converts these URLs to the URL of the published page. It removes the `.md` extension and maps `/index.md` to its parent path. Without a `docs_url`, OpenCrane uses the URLs as they are.

## Next steps

After the fetch, generate the bundles from the fetched files. See [Generate llms-full.txt bundles](llms-generation.md).
