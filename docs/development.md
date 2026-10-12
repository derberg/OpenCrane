# Development

This page describes how to set up a development environment for OpenCrane. To run the tests, see [Run the tests](running-tests.md).

## Set up the virtual environment

OpenCrane needs Python 3.11 or later, and the continuous integration (CI) workflow tests on Python 3.11. To create a virtual environment in `.venv`, follow these steps:

1. Create the virtual environment:

   ```bash
   python3 -m venv .venv
   ```

2. Activate the virtual environment. On macOS or Linux, run the following command:

   ```bash
   source .venv/bin/activate
   ```

   On Windows, run the following command:

   ```bat
   .venv\Scripts\activate
   ```

3. Install OpenCrane in editable mode with the `dev` extra:

   ```bash
   pip install -e '.[dev]'
   ```

The `.venv` directory now contains OpenCrane with every dependency that the full test suite needs. The CI workflow installs the same extra.

## Work in a separate worktree

To work on several branches at the same time, give each branch its own Git worktree. The `scripts/worktree.sh` script creates the worktree in `.worktrees/` from the latest `origin/main`, with its own `.venv` and an editable install. In a worktree, `./pytest.sh` uses that worktree's `.venv`, so the tests run against that worktree's source code. The following commands show how to use the script:

```bash
# Create .worktrees/{BRANCH_NAME} on a new branch. A slash in the name becomes a hyphen in the directory name.
scripts/worktree.sh new {BRANCH_NAME}

# List the worktrees
scripts/worktree.sh list

# Remove the worktree directory. The branch stays.
scripts/worktree.sh rm {BRANCH_NAME}
```

The `rm` command fails for a worktree that has uncommitted changes.

## Write commit messages for releases

Write commit messages in the Conventional Commits format, for example `feat: add custom walker support` or `fix: token count for empty files`. Release Please reads these messages to compute the next version and to write `CHANGELOG.md`. Do not edit the version in `pyproject.toml`, `CHANGELOG.md`, or the release tags by hand, because Release Please manages them.
