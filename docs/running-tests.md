# Run the tests

The OpenCrane test suite has unit tests and integration tests. The `./pytest.sh --check-coverage` command enforces 100% test coverage.

## Test types

The following table describes the test types:

| Test type | Location | Description |
|---|---|---|
| Unit tests | `tests/unit/` | Fast tests with mocked dependencies. |
| Integration tests | `tests/integration/` | Slower end-to-end tests. Some of them run against an embedded Milvus Lite database. |

The integration tests include acceptance tests. These tests call the tools through the Model Context Protocol (MCP) server, for example `tests/integration/test_mcp_tools_acceptance.py`.

## Common test commands

The following commands cover the common test runs:

```bash
# Run all tests (unit + integration)
./pytest.sh

# Run with 100% coverage check
./pytest.sh --check-coverage

# Run only the unit tests, for quick iterations during development
./pytest.sh tests/unit/

# Run only the integration tests
./pytest.sh tests/integration/

# Run a specific test file
./pytest.sh tests/integration/test_mcp_tools_acceptance.py
```

## What the `pytest.sh` script does

Run the tests with `./pytest.sh`, not with `pytest` directly. The script does the following:

- Activates `.venv` if it exists.
- Adds the project root to `PYTHONPATH`. With this setting, `from opencrane.mcp...` imports work, and `from mcp import Tool` loads the installed `mcp` package instead of the `opencrane/mcp/` directory.
- Provides the `--check-coverage` flag, which fails the run when coverage is below 100%. The continuous integration and delivery (CI/CD) workflow uses this flag.
