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
    github_url: https://github.com/my-org/my-project
    docs_path: docs
    manual: false
  external-sources/another-project:
    github_url: https://github.com/my-org/another-project
    docs_path: docs
    manual: false
```

Then generation produces:
- `llmstxt/external-sources/my-project/llms-full.txt` (includes all markdown from `guides/`, `releases/`, `technical-reference/`, etc.)
- `llmstxt/external-sources/another-project/llms-full.txt` (includes all markdown recursively)
- No files for `my-project/guides/` or other subdirectories

**Why this matters:**
- Prevents file explosion with hundreds of small files
- Gives you explicit control over what gets generated
- Makes it easy to include/exclude specific documentation sets
- Simplifies consumption for LLM agents (one file per product/extension)
- Automatically stays in sync with active repositories (stale entries are cleaned up during fetch)

## Document Structure

The generated llms-full.txt files use visual and structural markers to separate documents:

1. `-----` - Visual separator between documents
2. `### https://github.com/.../file.md` - H3 document boundary marker with GitHub source URL

These markers serve dual purposes:
- Visual clarity: Easy to identify document boundaries when reading
- Programmatic recognition: Chunking logic can detect document transitions

Example structure:
```markdown
### https://github.com/org/repo/blob/main/docs/file1.md

# https://github.com/.../file1.md Title
Content...
## https://github.com/.../file1.md Section
More content...

-----

### https://github.com/org/repo/blob/main/docs/file2.md

# https://github.com/.../file2.md Another Title
...
```

Note that every heading includes the full GitHub URL prefix to ensure:
- Unique anchor IDs across all documents
- Source traceability for every section
- Working internal links in the flattened format
