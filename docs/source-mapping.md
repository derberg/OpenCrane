# Source Mapping Configuration

The source mapping config file (e.g., `source-mapping.yaml`) is the control center for documentation processing in an OpenCrane project. It defines which documentation sources exist, where they come from, and how they should be processed.

## Purpose

The source mapping serves three critical functions:

1. **Documentation Discovery**: Tracks all documentation sources
2. **Output Control**: Determines which directories get `llms-full.txt` files generated
3. **Source Attribution**: Provides GitHub URLs for proper attribution in generated content

## File Structure

Each entry in the mapping follows this structure:

```yaml
sources:
  external-sources/my-project:           # Relative path (key)
    github_url: https://github.com/my-org/my-project
    docs_path: docs                       # Path within the repository
    manual: false                         # Entry created/updated automatically vs manually maintained
```

Field Descriptions:

- Key (e.g., `external-sources/my-project`): The relative path from workspace root where documentation is stored locally
- github_url: Source repository URL for attribution and fetching
- docs_path: Path within the source repository where docs are located (empty string means root)
- manual: `false` = entry auto-generated and updated during fetch, `true` = manually added and maintained mapping

## Configuring the Source Mapping File Path

In your project config class, set the `SOURCE_MAPPING_FILE` attribute to point to your mapping file:

```python
from opencrane.config import OpenCraneConfig

class MyProjectConfig(OpenCraneConfig):
    SOURCE_MAPPING_FILE = "source-mapping.yaml"
```

## Automatic Updates During Fetching

When documentation is fetched, the mapping file is automatically updated:

1. Script discovers repositories with the configured topic via GitHub API
2. For each repository, adds or updates an entry in the source mapping file
   - Sets `manual: false` for auto-discovered sources
   - Preserves `manual: true` entries (won't overwrite)
3. **Removes stale entries** - Repositories that lose the discovery topic are automatically cleaned up:
   - Removes entry from the source mapping file (only if `manual: false`)
   - Deletes local source directory (e.g., `external-sources/repo-name/`)
   - Deletes generated output directory (e.g., `llmstxt/external-sources/repo-name/`)
   - Manual entries (`manual: true`) are never removed automatically

This ensures the mapping always reflects the current state of available documentation sources and prevents stale entries from accumulating.

## Role in llms-full.txt Generation

The source mapping is the filter that controls which directories get `llms-full.txt` files generated. This prevents file explosion and gives explicit control over output structure.

### Path-Based Output Location

The key (relative path) in the mapping determines exactly where the generated file will be placed:

Mapping entry:
```yaml
external-sources/my-project:
  github_url: https://github.com/my-org/my-project
  docs_path: docs
  manual: false
```

Generated output:
```
llmstxt/external-sources/my-project/llms-full.txt
```

The output path mirrors the source path, making it easy to understand which source a file came from.

### Content Inclusion Rules

When generating `llms-full.txt` for a mapped path:

1. Start at mapped directory: `external-sources/my-project/`
2. Recursively collect ALL markdown: Includes `guides/`, `releases/`, `technical-reference/`, etc.
3. Generate single file: All content goes into one `llms-full.txt` at the mapped path
4. No subdirectory files: Even if `guides/` has markdown, no `llms-full.txt` is created there

Example:

```
Source structure:
  external-sources/my-project/
    README.md
    installation.md
    guides/
      mesh.md
    releases/
      1.0.0.md
    technical-reference/
      config.md

Generated output:
  llmstxt/external-sources/my-project/llms-full.txt  ← Contains ALL 5 files

NOT generated:
  llmstxt/external-sources/my-project/guides/llms-full.txt  ✗
  llmstxt/external-sources/my-project/releases/llms-full.txt  ✗
```

## Building GitHub URLs

The `github_url` field is used to construct source attribution URLs in the generated content. Every heading in `llms-full.txt` includes the full GitHub URL to its source.

URL Construction:
1. Take `github_url`: `https://github.com/my-org/my-project`
2. Add Git ref: `/blob/main`
3. Add `docs_path` if present: `/docs`
4. Add file's relative path from mapped directory: `/guides/setup.md`
5. Result: `https://github.com/my-org/my-project/blob/main/docs/guides/setup.md`

This ensures every piece of content is traceable back to its source repository and file.

Mapping:
```yaml
external-sources/my-project:
  github_url: https://github.com/my-org/my-project
  docs_path: docs
```

File location: `external-sources/my-project/guides/setup.md`

Generated URL in llms-full.txt:
```markdown
### https://github.com/my-org/my-project/blob/main/docs/guides/setup.md

# https://github.com/my-org/my-project/blob/main/docs/guides/setup.md Setup Guide
```

## Manual vs Auto-Fetched Sources

The `manual` flag distinguishes between two types of documentation:

### Auto-Generated Entries (`manual: false`)
- External repositories discovered via GitHub API
- Mapping entry automatically created and updated during fetch operations
- Documentation fetched when `opencrane fetch` is run (locally or via CI/CD)

### Manual Entries (`manual: true`)
- Documentation that lives in this repository or is manually curated
- Mapping entry manually created and maintained
- Not discovered or updated automatically
- Examples: Content guidelines, writing standards, templates

The fetch operation respects this flag and won't overwrite manually configured entries.
