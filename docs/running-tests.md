# Running Tests

## Testing Strategy

- **Unit tests** (`tests/unit/`) - Fast, mocked dependencies, run during development (~10s)
- **Integration tests** (`tests/integration/`) - Real services, slower, marked with `@pytest.mark.integration` (~2-3min)
  - Includes **acceptance tests** - end-to-end tests via MCP protocol using production data
- **Coverage requirement** - 100% enforced by pytest.ini

## Quick Reference

```bash
# Run all tests (unit + integration)
./pytest.sh

# Run with 100% coverage check
./pytest.sh --check-coverage

# Run only unit tests (fast iteration)
./pytest.sh tests/unit/
# or
pytest

# Run only integration tests
./pytest.sh -m integration

# Run specific test file
./pytest.sh tests/integration/test_mcp_tools_acceptance.py
```

## Why pytest.sh?

The `./pytest.sh` script runs ALL tests by default (overriding pytest.ini which skips integration tests). It also:
- Auto-activates `.venv`
- Sets PYTHONPATH correctly
- Provides `--check-coverage` flag for CI/CD

Use `pytest` directly for quick unit-test-only iterations during development.
