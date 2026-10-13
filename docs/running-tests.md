# Run the tests

The OpenCrane test suite has unit tests and integration tests, and every pull request to `main` must keep the test coverage at 100%. To set up the environment first, see [Development](development.md).

## Test types

The following table describes the test types:

| Test type | Location | Description |
|---|---|---|
| Unit tests | `tests/unit/` | Fast tests with mocked dependencies. |
| Integration tests | `tests/integration/` | Slower end-to-end tests. Some of them run against an embedded Milvus Lite database. The base install includes Milvus Lite, so these tests need no Milvus server. |

The integration tests include acceptance tests, which call the tools through the Model Context Protocol (MCP) server, for example `tests/integration/test_mcp_tools_acceptance.py`.

## What the `pytest.sh` script does

Run the tests with `./pytest.sh`, not with `pytest` directly. The script does the following:

- Activates `.venv` in the project root, if it exists.
- Adds the project root to `PYTHONPATH`. With this setting, `opencrane` imports load the source tree, and `from mcp import ...` loads the installed MCP SDK instead of the `opencrane/mcp/` directory.
- Runs all tests, unit and integration, unless you pass your own `-m` marker expression.
- Provides the `--check-coverage` flag, described in [Check the coverage](#check-the-coverage).

The script passes all other options to pytest unchanged.

## Common test commands

The following commands cover the common test runs:

```bash
# Run all tests
./pytest.sh

# Run only the unit tests, for quick iterations during development
./pytest.sh tests/unit/

# Run only the integration tests
./pytest.sh tests/integration/

# Run a specific test file
./pytest.sh tests/integration/test_mcp_tools_acceptance.py

# Show verbose output
./pytest.sh -v

# Write an HTML coverage report to htmlcov/
./pytest.sh --cov=opencrane --cov-report=html
```

To select tests, pass a path. Not every test has the `unit` or `integration` marker, so a marker expression such as `-m integration` misses tests.

## Check the coverage

The `--check-coverage` flag measures the coverage of the `opencrane` package and fails the run when the total is below 100%. The following commands run the check:

```bash
# Fail the run below 100% coverage
./pytest.sh --check-coverage

# Also list the uncovered lines
./pytest.sh --check-coverage --cov-report=term-missing
```

By default, the flag adds `--cov=opencrane --cov-report=term`. A `--cov=` or `--cov-report=` option that you pass replaces the matching default. The check measures the whole package, so a check on part of the test suite usually fails.

The continuous integration (CI) workflow in `.github/workflows/test-coverage.yml` runs `./pytest.sh --check-coverage --cov-report=term-missing` on Python 3.11 for every pull request to `main`.
