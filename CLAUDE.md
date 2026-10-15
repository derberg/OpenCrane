# OpenCrane

A standalone, extensible RAG/MCP pipeline for building AI-powered documentation search. Fetch docs from GitHub, generate `llms-full.txt` bundles, chunk and embed them, index into Milvus, and serve them through an MCP server, all from one CLI.

## Commit rules

- **NEVER include `Co-Authored-By: Claude` or any AI co-author attribution in commit messages.** This applies to all commits, with no exceptions.
- Keep commit messages concise: `type: short description` (for example, `feat: add custom walker support`, `fix: token count for empty files`)
- Types: `feat`, `fix`, `docs`, `test`, `ci`, `chore`, `refactor`

## GitHub Actions conventions

**Always pin GitHub Actions to full commit SHA, not tags or versions.**

```yaml
# Correct:
uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2

# Incorrect:
uses: actions/checkout@v6
uses: actions/checkout@v6.0.2
```

Always include the version tag as a comment for reference.

## Project structure

```text
opencrane/                  # Main Python package
├── cli.py                  # Click CLI entry point
├── add_source.py           # Source addition logic (GitHub repos + llms.txt files)
├── config.py               # OpenCraneConfig base class (extension points)
├── templates.py            # Files that `opencrane init` and `opencrane pack` write
├── pack.py                 # `opencrane pack`: builds a uvx-installable MCP server package
├── visualize.py            # `opencrane visualize`: embedding-placement HTML (needs viz extras)
├── fences/                 # Fence type configuration API
├── mcp/                    # MCP server (stdio + HTTP transport)
│   ├── server.py           # Stdio MCP server and the tool implementations
│   ├── http_server.py      # HTTP transport for Docker
│   ├── init_vector_db.py   # `opencrane index`
│   ├── extra_tools.py      # ExtraTool API for project-defined MCP tools
│   ├── auth/               # HTTP authentication and source authorization
│   └── services/           # Milvus client, embeddings, BM25 search, reranker
├── rag/                    # RAG pipeline modules
│   ├── fetch_docs.py       # GitHub repo fetching
│   ├── generate_llms_txt.py # llms-full.txt generation with fence handlers
│   ├── chunker.py          # Chunking orchestrator, page URLs, prose navigation
│   ├── generate_embeddings.py
│   └── services/           # Chunking strategies, YAML tree walkers, llms.txt index
├── shared/                 # Shared utilities, runtime Config, Pydantic models
│   ├── models/             # Chunk, VectorChunk, EmbeddingsFile, File, Repository
│   └── utils/              # Token counter, embedding prompts, git helpers, URL parsing
└── walkers/                # Public walker API re-exports
tests/
├── unit/                   # Fast, mocked tests (no Milvus)
├── integration/            # Requires Milvus Lite
├── fixtures/               # Test data (markdown, YAML)
└── conftest.py             # Session fixtures, temp dirs
docs/                       # User documentation
scripts/worktree.sh         # Per-topic git worktrees
```

## Tech stack

- **Python >= 3.11** (uses modern type hints)
- **CLI**: Click
- **Validation**: Pydantic v2
- **Chunking**: custom strategies and YAML tree walkers (Docling only for non-`.txt` input, so the `chunk` step's `llms-full.txt` bypasses it)
- **Embeddings**: sentence-transformers (default: `nomic-ai/nomic-embed-text-v1.5`)
- **Vector DB**: Milvus (Lite mode by default, server mode optional)
- **Search**: hybrid of cosine similarity and BM25 (configurable alpha blend)
- **MCP**: stdio and HTTP transports
- **Tokens**: tiktoken (cl100k_base encoding)

## Pipeline

```text
add → fetch → llms → chunk → embed → index → serve
```

- `opencrane add`: interactively add GitHub repos or pre-existing llms.txt files as sources
- `opencrane init`: scaffolds project and offers interactive source addition (same as `add`)
- Each step is independently callable from the CLI (`opencrane <step>`) or through `opencrane build` for the full pipeline
- `build` stops gracefully after `llms` when no `llms-full.txt` was generated (suggests `opencrane add`)
- The `llms` step combines pre-existing llms-full.txt files even when `config.yaml` is empty
- The `llms` step also writes a companion `llms.txt` index next to the combined `llms-full.txt`; the `chunk` step reads both to assign each chunk its specific page `source_url`

## Development

### Running tests

**All tests must be run with `./pytest.sh` and not directly with `pytest` or `python -m pytest`.** This is mandatory because `./pytest.sh` sets PYTHONPATH to the project root. As a result, `opencrane` imports resolve to the source tree. `from mcp import ...` resolves to the pip-installed MCP SDK, not to `opencrane/mcp/`.

```bash
./pytest.sh                              # All tests, unit and integration
./pytest.sh --check-coverage             # With 100% coverage enforcement
./pytest.sh tests/unit/                  # Unit tests only
./pytest.sh tests/integration/           # Integration tests (needs Milvus Lite)
```

- **100% code coverage is enforced**: `./pytest.sh --check-coverage` fails below 100%
- Test markers: `tests/integration/conftest.py` adds the `integration` marker to every test in `tests/integration/`, so new files need no marker. Select unit tests by path (`tests/unit/`), because not every unit test has the `unit` marker
- `./pytest.sh` with no arguments runs both unit and integration tests

### Test policy

- **NEVER modify, add, or remove tests without explicit user confirmation.** Tests represent the specification of expected behavior. Changing them without approval means changing requirements.
- If tests fail during implementation, report failures to the user and request permission before making changes.
- **Test isolation is mandatory**: tests must never touch production files or directories. Always use temp directories and fixture copies. No hardcoded production paths in tests or fixtures.
- Place reusable test assets under `tests/fixtures/`.

### Debugging

`LOG_LEVEL=DEBUG` turns on debug logging for every command, for example `LOG_LEVEL=DEBUG opencrane chunk`. The log goes to stderr, never to stdout.

### Installing for development

```bash
pip install -e ".[dev]"
```

## Extension points

Subclass `OpenCraneConfig` in `.opencrane/extensions.py` to customize:

1. **`fence_types`**: custom fence block handlers for llms-full.txt generation
2. **`chunking_strategies`**: custom chunking strategies (first match wins)
3. **`yaml_tree_walkers`**: custom YAML tree walkers for structured docs (K8s CRD, OpenAPI, JSON Schema built-in)
4. **`section_anchor_for`**, **`section_clause_for`**, **`prose_navigation`**: section anchor slug, clause ID and prose navigation metadata on chunks. `section_anchor_style` and `section_clause_pattern` can also be set as keys in `.opencrane/config.yaml`
5. **`middleware`, `token_verifier`, `auth_provider`**: authentication and authorization hooks for the HTTP transport, see `docs/auth.md`
6. **`extra_tools`**: custom MCP tools (`ExtraTool`) served on both transports. An extra tool cannot reuse a built-in tool name, so add every new built-in tool to `BUILTIN_TOOL_NAMES` in `mcp/server.py`. OpenCrane does not filter extra tool output
7. **`reranker`**: optional `search_docs` reranker, `(query, candidates) -> list[dict]`

Config is auto-discovered from the file that the `extensions` key in `.opencrane/config.yaml` names, for example `extensions: extensions.py`. The class in that file must be named `Config`. The `opencrane init` template ships the key commented out. Config can also be set with `--config` / `OPENCRANE_CONFIG` env var.

## Key design decisions

- **Strategy Pattern** for chunking: extensible without modifying core
- **Milvus Lite by default**: single-file DB, no Docker needed
- **Lazy service init**: the stdio server creates its services on first use for fast startup; the HTTP server initializes them at startup
- **Token-based YAML splitting**: recursive split when chunks exceed 800 tokens
- **Hybrid search scoring**: `HYBRID_ALPHA * vector + (1 - HYBRID_ALPHA) * BM25` over min-max normalized semantic and keyword scores (default 0.6), or weighted RRF with `HYBRID_FUSION=rrf` (`HYBRID_RRF_K`, alpha 0.5 = classic RRF). `HYBRID_CANDIDATE_POOL` widens each search before fusion. Score-0 keyword hits are dropped before fusion, and ties break by `chunk_id`. The `alpha` schema is built from config, so agents see the real default and, under `rrf`, that scores are rank-only
- **Encoder settings from env**: `EMBEDDING_DTYPE`, `EMBEDDING_DEVICE`, `EMBEDDING_BATCH_SIZE`, `EMBEDDING_MAX_SEQ_LENGTH` in `shared/config.py`, validated at `Config()` time with errors that name the variable. `EMBEDDING_TRUST_REMOTE_CODE` / `RERANKER_TRUST_REMOTE_CODE` default to auto: `resolve_trust_remote_code` trusts only `REMOTE_CODE_MODEL_PREFIXES` (Nomic), so naming an arbitrary model never runs its code unless opted in. `embed`, `serve` and `visualize` all load through it. The dtype kwarg is `dtype` on transformers >= 4.56, `torch_dtype` before
- **Asymmetric embedding prompts**: `shared/utils/embedding_prompts.py` prepends the document prompt to chunks and applies the query prompt to vector queries, `visualize` included. Each prompt resolves as: env var when set (empty = no prompt, so config keeps unset as `None`), then the model's non-empty `prompts`, then `KNOWN_MODEL_PROMPTS` (nomic and e5 models that need prompts but don't ship them), then empty. BM25 gets the raw query. `embeddings.json` records the model, the effective document and query prompts and the chunks file hash, so `embed` skips an unchanged run. The skip check resolves the prompt without loading the model by reading `config_sentence_transformers.json` from a local dir or the HF cache. The check ignores the model. A skipped run still writes the current effective query prompt, because it does not change the vectors
- **Index records its embedding settings**: `index` stores model, document prompt, query prompt and dim as JSON in the collection schema `description`, the only place Milvus Lite persists (it drops collection properties and has no alter). `index` rebuilds a populated collection whose recorded settings differ from the embeddings file; a collection without them is kept with a warning. The server resolves `EMBEDDING_MODEL` / `EMBEDDING_QUERY_PROMPT` in `mcp/services/embedding_settings.py`: unset env (or empty `EMBEDDING_MODEL`) uses the index value, and without an index value the model falls back to `EMBEDDING_MODEL` or its default and the prompts to `resolve_prompt`; a different env value, an explicit empty query prompt included, raises `EmbeddingSettingsMismatch`, which stops both transports at startup. `health` reports each value and its source (`env`, `index`, `default`)
- **Opt-in identifier-aware BM25 tokenizer**: `BM25_TOKENIZER=identifier` (default `simple`) emits each `.`/`-`/`_`-joined compound (`5.4.1`, `gtp-u`) plus its de-duplicated parts, so exact identifiers outrank scattered fragments while part queries still match. Resolved once per `KeywordSearchService` so documents and queries always share it. No stopword list: BM25 IDF already discounts common words
- **Optional reranker, off by default**: after fusion, it reorders `RERANK_DEPTH` candidates (default 50, at least `limit`, capped at the Milvus topk limit). `OpenCraneConfig.reranker` overrides the built-in CrossEncoder from `RERANKER_MODEL`. A failing reranker falls back to the unreranked order, and the health probe skips it
- **Prose chunks split at heading boundaries**: preserves complete sections for semantic coherence. The `PROSE_*` variables in `docs/chunking.md` change the split
- **MCP lookups are vector-DB-backed**: semantic search and the lookup tools read from Milvus. Chunk lookups use the primary key. Member and section lookups use the `list_id`, `table_id`, `clause_id`, and `parent_chunk_id` scalar columns. These columns have `INVERTED` indexes, because Milvus Lite rejects `AUTOINDEX` on scalar fields, so lookups don't scan all documents. The only in-memory copy is the BM25 index for keyword and hybrid search, built from `chunks.json`. Member queries interpolate a sanitized, width-capped ID into the filter, because Milvus Lite has no `filter_params` templating. `index` writes these IDs to their own columns. A new column is a schema change, so the next `index` run drops and rebuilds a collection that an older version built. Every built-in tool that returns chunks applies the source policy through `resolve_allowed_sources`, and an ID from a source outside the policy gets the same answer as a missing ID
- **Vector size follows the embedding model**: `index` sizes the `embedding` field from the embeddings file and rebuilds a collection of another size. `MilvusService.search` raises on a wrong-size query vector instead of returning empty results
- **Prose navigation metadata**: `_annotate_prose_navigation` in `rag/chunker.py` adds `heading_path`, `clause_id`, `parent_chunk_id`, `position`, and `prev_chunk_id`/`next_chunk_id` to prose chunks, one page at a time (a new `source_url` or page-title H1 starts a page). `get_section` reads the indexed `clause_id`/`parent_chunk_id` columns, which upgrade like `list_id`/`table_id`. The server lists the tool only when an indexed prose chunk has `position`
- **Per-page `source_url` from the companion `llms.txt`**: `llms-full.txt` page headings carry no URLs. Only a file that the built-in `inline_file` fence handler inlines starts with a `### {source_url}` heading. The `chunk` step recovers each chunk's page URL by joining the clean content to the standard `llms.txt` index, matched positionally per source and validated by H1 title. External `llmstxt` sources contribute their fetched companion `llms.txt` (real per-page URLs) or a synthesized index from their `docs_url`

## CI/CD

- **test-coverage.yml**: runs on PRs to main, enforces 100% coverage
- **release-please.yml**: on push to `main`, maintains a release PR that computes the next version from conventional commits, writes `CHANGELOG.md` and bumps `pyproject.toml`. Merging it tags and creates the GitHub release. Never hand-edit the version, changelog or tags, because release-please owns them and `.release-please-manifest.json` tracks the current version
- **publish-pypi.yml**: publishes to PyPI on GitHub release (trusted publisher, OIDC). Also runnable manually with a tag input, needed because a release created with the default GITHUB_TOKEN cannot trigger another workflow; setting a `RELEASE_PLEASE_TOKEN` PAT removes that step
- Actions pinned by SHA with tag comments
- CI installs `pip install -e '.[dev]'`: `pyproject.toml` is the single source of dependency truth, and the `dev` extra pulls the pipeline, viz and auth deps the full suite needs. It gates on 100% coverage through `./pytest.sh --check-coverage`

## Default paths

All outputs go to `.opencrane/` directory:
- `.opencrane/sources/`: fetched documentation source files
- `.opencrane/llmstxt/`: generated `llms-full.txt` bundles plus a companion `llms.txt` index (page title → page URL) written next to the combined `llms-full.txt`
- `.opencrane/chunks.json`: chunked documents
- `.opencrane/embeddings.json`: embedding vectors
- `.opencrane/config.yaml`: source mapping and project configuration
- `.opencrane/milvus.db`: Milvus Lite database

## Documentation maintenance

When updating documentation, avoid including specific counts or numbers that will quickly become outdated (for example, "992 chunks", "349 files"). Describe capabilities and structure without hardcoded metrics.
