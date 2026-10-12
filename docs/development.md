# Development

This page describes how to set up a local development environment for OpenCrane and how to run the tests.

## Set up the virtual environment

The following steps create a virtual environment in `.venv`:

1. Create the virtual environment with Python 3.11 or later:

   ```bash
   python -m venv .venv
   ```

2. Activate the virtual environment. If you use macOS or Linux, run the following command:

   ```bash
   source .venv/bin/activate
   ```

   If you use Windows, run the following command:

   ```bat
   .venv\Scripts\activate
   ```

3. Install the dependencies:

   ```bash
   pip install -e '.[dev]'
   ```

The virtual environment in `.venv` now contains OpenCrane and its development dependencies.

## Run the tests

To run the tests, use the `./pytest.sh` wrapper script. For the reasons, see [What the `pytest.sh` script does](running-tests.md#what-the-pytestsh-script-does). The following commands show its common uses:

```bash
# Run all tests
./pytest.sh

# Run tests with coverage check (enforces 100% threshold)
./pytest.sh --check-coverage

# Run with a coverage report that lists the uncovered lines
./pytest.sh --check-coverage --cov-report=term-missing
```

## Run part of the test suite

To run only part of the test suite, pass a path to `./pytest.sh`. The following table lists the commands for each scope:

| Scope | Command |
|---|---|
| Unit tests only | `./pytest.sh tests/unit/` |
| Integration tests only | `./pytest.sh tests/integration/` |
| A specific test file | `./pytest.sh tests/unit/test_cli.py` |

## Additional test options

The wrapper script passes any other option to pytest unchanged. The following table lists some of these options:

| Output | Command |
|---|---|
| Verbose output | `./pytest.sh -v` |
| HTML coverage report in `htmlcov/` | `./pytest.sh --cov=opencrane --cov-report=html` |
