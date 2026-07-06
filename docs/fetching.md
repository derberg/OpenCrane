# Fetch Documentation Sources

OpenCrane can automatically fetch documentation files from GitHub repositories. Documentation is fetched from the **latest release** of each repository. The primary mechanism for fetching is through a scheduled GitHub Actions workflow that runs on a defined cadence to keep documentation up-to-date.

## GitHub Actions Workflow

A typical `update-docs.yml` workflow fetches documentation from one or more organizations or repositories:

- **Auto-discovery**: Repos tagged with a specific topic (e.g., `"documentation"`) are discovered automatically
- **Manual repositories**: Specific repos can be added in your source mapping config with `manual: true`

**Auto-discovery configuration**: The `AUTO_DISCOVERY_ORGS` environment variable (in your project's config class) controls which orgs have auto-discovery enabled. To enable auto-discovery for additional orgs, set `AUTO_DISCOVERY_ORGS=my-org,other-org`.

The workflow makes sure that your project always operates on the latest docs.

## Automatic Cleanup

The fetch process automatically cleans up stale documentation sources:

- **Stale Detection**: Repositories that **lose the discovery topic** are identified and removed
- **Mapping Cleanup**: Removes entries from your source mapping config (only auto-generated entries with `manual: false`)
- **Directory Cleanup**: Deletes both source directories and generated output (`llmstxt/`)
- **Manual Entry Protection**: Entries marked as `manual: true` are never automatically removed
- **Local Entry Protection**: Entries marked as `local: true` are never fetched or removed (they reference local filesystem paths)
- **Org Filtering**: The `--org` flag filters which repos are processed - repos from other orgs are skipped (not removed)
- **Failure Protection**: Repos that **fail to fetch** (network errors, no files, etc.) are NOT removed - only repos that lose the topic are removed

This prevents accumulation of outdated documentation while protecting against temporary failures.

## Local Execution

Running locally is intended **only for testing purposes** or in exceptional cases where manual fetching is required (e.g., troubleshooting issues, one-off updates, or when the automated workflow fails). It requires setting up a GitHub token and Python environment locally.

### Fetch from a specific organization

```bash
# Fetch from an organization (auto-discovers repos with the configured topic)
opencrane fetch --config yourproject.config:YourConfig --org my-org

# Force fetch regardless of changes
opencrane fetch --config yourproject.config:YourConfig --org my-org --force
```

### Fetch a single repository

Use `--repo <path_key>` to restrict the fetch to one specific entry from your source mapping config. The path key is the top-level key under `sources:` in that file (e.g. `external-sources/my-repo`). The org filter is bypassed automatically when `--repo` is used, so no `--org` flag is needed.

```bash
# Fetch only one repo — no --org needed
opencrane fetch --config yourproject.config:YourConfig --repo external-sources/my-repo
```

This is useful when you need to refresh a single source without re-fetching the entire set of repositories.

## Companion `llms.txt` for external `llmstxt` sources

When a source is added as a pre-existing `llmstxt` bundle (a URL or local path to an `llms-full.txt`), fetch also tries to retrieve the upstream **companion `llms.txt`** index next to it — the standard `llms.txt` file that carries real per-page URLs. It is saved alongside the bundle in `.opencrane/llmstxt/<name>/llms.txt`.

- **Remote sources**: the companion URL is derived by swapping a trailing `llms-full.txt` for `llms.txt`, or, when that does not apply, by appending `/llms.txt` to the source's `docs_url`. If the companion returns a 404 or any error, fetch proceeds without it — no hard failure.
- **Local sources**: a sibling `llms.txt` next to the source file is copied when present.

When a companion index is available, the `chunk` step uses its per-page URLs so each chunk carries its specific page `source_url`. When it is absent, the `llms` step synthesizes an index from the source's `docs_url` (the base URL, repeated for every page) — see [Source mapping](source-mapping.md).

### Generate LLM bundles

```bash
opencrane llms --config yourproject.config:YourConfig
```
