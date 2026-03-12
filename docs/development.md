# Development

## Setting Up Virtual Environment Manually

You can set up the Python virtual environment manually:

1. **Create the virtual environment**:
   ```bash
   python -m venv .venv
   ```

2. **Activate the virtual environment**:
   - On macOS/Linux: `source .venv/bin/activate`
   - On Windows: `.venv\Scripts\activate`

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

Ensure Python 3.11+ is used when creating the virtual environment.

## Running Tests

Using the wrapper script:

```bash
# Run all tests
./pytest.sh

# Run tests with coverage check (enforces 100% threshold)
./pytest.sh --check-coverage

# Run with detailed coverage report
./pytest.sh --check-coverage --cov-report=term-missing
```

## Running Specific Test Types

- **Unit tests only**: `./pytest.sh tests/unit/`
- **Integration tests only**: `./pytest.sh tests/integration/`
- **Specific test file**: `./pytest.sh tests/unit/test_github_client.py`

## Additional Options

- **Verbose output**: `./pytest.sh -v`
- **HTML coverage report**: `./pytest.sh --cov=opencrane --cov-report=html` (generates in `htmlcov/`)
