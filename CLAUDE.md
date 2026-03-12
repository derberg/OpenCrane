# OpenCrane

A standalone, extensible RAG/MCP pipeline for building AI-powered documentation search. Fetch docs from GitHub, generate `llms-full.txt` bundles, chunk and embed them, index into Milvus, and serve via an MCP server — all from one CLI.

## Commit Rules

- **NEVER include `Co-Authored-By: Claude` or any AI co-author attribution in commit messages.** This applies to all commits — no exceptions.
- Keep commit messages concise: `type: short description` (e.g., `feat: add custom walker support`, `fix: token count for empty files`)
- Types: `feat`, `fix`, `docs`, `test`, `ci`, `chore`, `refactor`

## GitHub Actions Conventions

**Always pin GitHub Actions to full commit SHA, not tags or versions.**

```yaml
# Correct:
uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2

# Incorrect:
uses: actions/checkout@v6
uses: actions/checkout@v6.0.2
```

Always include the version tag as a comment for reference.

## Project Structure

```
opencrane/                  # Main Python package
├── cli.py                  # Click CLI entry point (11 subcommands)
├── config.py               # OpenCraneConfig base class (extension points)
├── fences/                 # Fence type configuration API
├── mcp/                    # MCP server (stdio + HTTP transport)
│   ├── server.py           # Stdio MCP server
│   ├── http_server.py      # HTTP transport for Docker
│   └── services/           # Milvus client, embeddings, BM25 search
├── rag/                    # RAG pipeline modules
│   ├── fetch_docs.py       # GitHub repo fetching
│   ├── generate_llms_txt.py # llms-full.txt generation with fence handlers
│   ├── chunker.py          # Chunking orchestrator
│   ├── generate_embeddings.py
│   └── services/           # Chunking strategies and YAML tree walkers
├── shared/                 # Shared utilities and Pydantic models
│   ├── models/             # Chunk, VectorChunk, File, Repository
│   └── utils/              # Token counter, git helpers, URL parsing
└── walkers/                # Public walker API re-exports
tests/
├── unit/                   # Fast, mocked tests (no Milvus)
├── integration/            # Requires Milvus Lite
├── fixtures/               # Test data (markdown, YAML)
└── conftest.py             # Session fixtures, temp dirs
```

## Tech Stack

- **Python >= 3.11** (uses modern type hints, match statements)
- **CLI**: Click
- **Validation**: Pydantic v2
- **Chunking**: Docling, custom YAML tree walkers
- **Embeddings**: sentence-transformers (default: `nomic-ai/nomic-embed-text-v1.5`)
- **Vector DB**: Milvus (Lite mode by default, server mode optional)
- **Search**: Hybrid — cosine similarity + BM25 (configurable alpha blend)
- **MCP**: stdio and HTTP transports
- **Tokens**: tiktoken (cl100k_base encoding)

## Pipeline

```
fetch → llms → chunk → embed → index → serve
```

Each step is independently callable via CLI (`opencrane <step>`) or via `opencrane build` for the full pipeline.

## Development

### Running Tests

**All tests must be run via `./pytest.sh` and not directly with `pytest` or `python -m pytest`.** This is mandatory because `./pytest.sh` sets PYTHONPATH to the project root, ensuring that the pip-installed `opencrane` package is used correctly.

```bash
./pytest.sh                              # All unit tests
./pytest.sh --check-coverage             # With 100% coverage enforcement
./pytest.sh tests/unit/                  # Unit tests only
./pytest.sh tests/integration/           # Integration tests (needs Milvus Lite)
```

- **100% code coverage is enforced** — `--cov-fail-under=100` in pytest.ini
- Test markers: `@pytest.mark.unit`, `@pytest.mark.integration`
- Integration tests are skipped by default

### Test Policy

- **NEVER modify, add, or remove tests without explicit user confirmation.** Tests represent the specification of expected behavior — changing them without approval means changing requirements.
- If tests fail during implementation, report failures to the user and request permission before making changes.
- **Test isolation is mandatory**: tests must never touch production files or directories. Always use temp directories and fixture copies. No hardcoded production paths in tests or fixtures.
- Place reusable test assets under `tests/fixtures/`.

### Installing for Development

```bash
pip install -e ".[dev]"
```

### Debugging

Enable debug logging via `LOG_LEVEL` environment variable:

```bash
LOG_LEVEL=DEBUG opencrane chunk
LOG_LEVEL=DEBUG opencrane serve
```

## Extension Points

Subclass `OpenCraneConfig` in `.opencrane/config.py` to customize:

1. **`fence_types`** — custom fence block handlers for llms-full.txt generation
2. **`chunking_strategies`** — custom chunking strategies (first match wins)
3. **`yaml_tree_walkers`** — custom YAML tree walkers for structured docs (K8s CRD, OpenAPI, JSON Schema built-in)

Config is auto-discovered from `.opencrane/config.py:Config` or set via `--config` / `OPENCRANE_CONFIG` env var.

## Key Design Decisions

- **Strategy Pattern** for chunking — extensible without modifying core
- **Milvus Lite by default** — single-file DB, no Docker needed
- **Lazy service init** — MCP server initializes on first search for fast startup
- **Token-based YAML splitting** — recursive split when chunks exceed 800 tokens
- **Hybrid search scoring** — `HYBRID_ALPHA * vector + (1 - HYBRID_ALPHA) * BM25` (default 0.6)
- **Prose chunks split at heading boundaries only** — preserves complete sections for semantic coherence, no token-based splitting within sections

## CI/CD

- **test-coverage.yml**: runs on PRs to main, enforces 100% coverage
- **publish-pypi.yml**: publishes to PyPI on GitHub release (trusted publisher, OIDC)
- Actions pinned by SHA with tag comments
- If workflows use any CLI flags, those exact flags and code paths must be exercised by the smoke test at `tests/integration/test_setup_sh_smoke.py`

## Default Paths

All outputs go to `.opencrane/` directory:
- `.opencrane/llmstxt/` — generated llms-full.txt files
- `.opencrane/chunks.json` — chunked documents
- `.opencrane/embeddings.json` — embedding vectors
- `.opencrane/sources.yaml` — source mapping
- `.opencrane/milvus.db` — Milvus Lite database

## Documentation Maintenance

When updating documentation, avoid including specific counts or numbers that will quickly become outdated (e.g., "992 chunks", "349 files"). Describe capabilities and structure without hardcoded metrics.
