# Fetch documentation sources

The `opencrane fetch` command copies documentation from GitHub repositories into `.opencrane/sources/`. The `TARGET_DIR` environment variable changes this directory, but the `llms` step reads fetched files from `.opencrane/sources/` unless you pass it `--sources-dir`. If you change `TARGET_DIR`, pass the same directory to the `llms` step. For each repository, the command copies every file under the `docs_path` of the entry, by default `docs`. The command reads the latest release of the repository. If the repository has no releases, or OpenCrane cannot read the release, the command reads the default branch.

For an entry with `manual: true`, you can pin the fetch to a fixed Git ref instead. Set the matching field on the entry, as described in the [source mapping file](source-mapping.md). If you set more than one of these fields, OpenCrane logs a warning and uses the first one in the following order:

1. `sha`
2. `tag`
3. `release`, by its tag name
4. `branch`

OpenCrane ignores these fields on auto-discovered entries.

Run the fetch on a schedule, for example in a scheduled GitHub Actions workflow, so the indexed documentation stays current.

## Choose which repositories to fetch

OpenCrane finds the repositories to fetch in two ways:

- Auto-discovery: OpenCrane fetches every repository with the discovery topic in the organization you fetch from.
- Manual entries: OpenCrane fetches every repository whose entry in the source mapping file sets `manual: true`, regardless of its topics. The fetch skips a manual entry for the repository that you run the fetch in, when that repository belongs to the `ORG_NAME` organization.

The discovery topic is `documentation` by default. To use another topic, set the `DOCS_TOPIC` environment variable.

Each fetch discovers repositories in one organization only: the one that the `--org` flag or the `ORG_NAME` environment variable names. When you pass `--org`, auto-discovery always runs for that organization.

When `ORG_NAME` selects the organization, as in a continuous integration (CI) workflow, auto-discovery runs only if the organization is in the `AUTO_DISCOVERY_ORGS` environment variable. The variable takes a comma-separated list and is empty by default. The following command allows auto-discovery for two organizations:

```bash
export AUTO_DISCOVERY_ORGS={ORG_NAME},{OTHER_ORG_NAME}
```

If `ORG_NAME` names an organization that is not in `AUTO_DISCOVERY_ORGS` and you do not pass `--org`, the fetch discovers no repositories in it. Every auto-discovered entry of that organization then counts as stale. See [How the fetch removes stale sources](#how-the-fetch-removes-stale-sources).

## How the fetch removes stale sources

A source is stale when auto-discovery no longer returns its repository. Auto-discovery stops returning a repository in the following cases:

- The repository lost the discovery topic.
- OpenCrane could not read the topics of the repository after retries.
- The token cannot see the repository, for example because it was deleted or renamed.

Each fetch removes stale sources, so outdated documentation does not accumulate.

The following table shows what the fetch does with each kind of source during cleanup:

| Source | Cleanup behavior |
|---|---|
| Stale auto-discovered entry (`manual: false`) | Removed from the source mapping file, with its directories in `.opencrane/sources/` and `.opencrane/llmstxt/` |
| Entry with `manual: true` | Never removed |
| Entry with `local: true` | Never fetched or removed, because it points to a directory in the project |
| Entry with `type: llmstxt` | Never removed |
| Auto-discovered entry from another organization | Not fetched, and kept |
| Entry that `--source` does not name, when you pass `--source` | Not fetched, and kept |
| Discovered repository whose files fail to download, for example after a network error, or that has no files | Kept |

## Run the fetch locally

Run the fetch on your own machine for the following purposes:

- To test a configuration
- To troubleshoot a source
- To refresh a source after the scheduled run fails

Run the commands from the project root, the directory that contains `.opencrane/config.yaml`. Before you start, make sure you have the following:

- OpenCrane installed with the `pipeline` extra, on Python 3.11 or later (see [Installation](../README.md#installation))
- A GitHub token in the `GITHUB_TOKEN` environment variable. The fetch fails without it, even when you have only `llmstxt` sources.

### Fetch the repositories of an organization

The `opencrane fetch --org` command fetches every repository in the organization that has the discovery topic. It also fetches every entry with `manual: true` and every `llmstxt` source, and then removes stale sources.

> [!CAUTION]
> This command deletes the local source directory and the generated `llmstxt/` output of every auto-discovered repository in the organization that auto-discovery no longer returns. To keep such a source, set `manual: true` on its entry before you run the command. The command also deletes and rewrites `.opencrane/sources/{PATH_KEY}/` for every source it fetches, and overwrites any change you made in that directory. It also removes fields such as `docs_url` and `ignore_patterns` from the `config.yaml` entries it fetches.

To fetch the repositories of an organization, run the following command:

```bash
opencrane fetch --org {ORG_NAME}
```

The fetched files appear in `.opencrane/sources/`, in one directory for each source.

### Fetch specific sources

To refresh only some sources, pass their path keys to `--source`, or set them in the `FETCH_REPO` environment variable. The path key is the top-level key under `sources:` in the source mapping file. Separate several keys with commas. An entry with `manual: true` needs no `--org`. An auto-discovered entry needs auto-discovery for its organization, so pass `--org {ORG_NAME}` too.

> [!CAUTION]
> If you name an auto-discovered source and auto-discovery does not return its repository, this command deletes its local source directory and its generated `llmstxt/` output. This also happens when you omit `--org`, `ORG_NAME` names the organization of the source, and `AUTO_DISCOVERY_ORGS` does not list it. The command also deletes and rewrites `.opencrane/sources/{PATH_KEY}/` for every source it fetches, and overwrites any change you made in that directory. It also removes fields such as `docs_url` and `ignore_patterns` from the `config.yaml` entries it fetches.

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

If the download fails, the fetch continues without the index. With the index, each chunk gets the URL of its own page. Without it, the pages of the source share the `docs_url` of the source, or get no URL. See [`docs_url` for external `llmstxt` sources](source-mapping.md#docs_url-for-external-llmstxt-sources).

The `llms.txt` index from GitBook and similar tools often lists URLs that end in `.md` or `/index.md`. If the source has a `docs_url`, the `llms` step converts these URLs to the URL of the published page. It removes the `.md` extension and maps `/index.md` to its parent path. Without a `docs_url`, OpenCrane uses the URLs as they are.

## Next steps

After the fetch, generate the bundles from the fetched files. See [Generate llms-full.txt bundles](llms-generation.md).
