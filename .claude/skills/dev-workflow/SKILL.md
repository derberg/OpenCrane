---
name: dev-workflow
description: Use when starting any change to OpenCrane — creating a branch, running tests, working in parallel across sessions, or cutting a PyPI release. Covers the worktree-per-topic isolation, the 100% coverage gate, and the gated release flow.
---

# OpenCrane Dev Workflow

## Step 0 — know your branch, every single time

Before reading code to answer a question OR before editing, run `git status -sb`
(shows current branch + ahead/behind). The checked-out tree may be a **stale
topic branch**: reporting "the code does X" from it is wrong if `main` already
changed X. If HEAD is behind `origin/main`, say so up front, and answer "what
does the code do *now*?" against `origin/main` (`git grep … origin/main`,
`git show origin/main:<file>`), never the stale working tree.

## Parallel topics — one worktree per topic

A single checkout has one `HEAD`, so two sessions sharing one directory fight
over the branch: one runs `git switch`, the other's files change underneath it.
Don't work around this with `git stash` juggling or extra clones. Use a **git
worktree per topic** — each is its own directory with its own checked-out
branch, all backed by this repo's single `.git` (one `fetch`, shared
branches/stash/reflog; git refuses to check out the same branch in two
worktrees, which is the guard you actually want).

Rule: **one worktree : one branch : one session.** Spin one up with the helper
(off fresh `origin/main`, creates a per-worktree `.venv` and runs the editable
install):

```bash
scripts/worktree.sh new feat/<short-name>   # creates .worktrees/<name>, .venv, pip install -e ".[dev]"
scripts/worktree.sh list
scripts/worktree.sh rm  feat/<short-name>   # removes the dir; branch stays
```

Then open `.worktrees/<name>` as the workspace for that session and work there.
`.worktrees/` is gitignored, and the branch-guard hook is worktree-aware — it
gates each file by the branch of the worktree that owns it, so topics never
gate or clobber each other.

**A worktree is required, not optional:** the PreToolUse branch-guard hook makes
the shared main checkout read-only for edits (on any branch), so all topic work
happens in a `.worktrees/<topic>` directory. This is deliberate — the main
checkout's HEAD is shared, and a concurrent session can switch it mid-task,
landing your commit on the wrong branch. A worktree pins one branch to one
directory, which git enforces.

Each worktree has its own `.venv`. `pytest.sh` activates `$SCRIPT_DIR/.venv`, so
the editable install stays pinned to that worktree's source — no cross-worktree
contamination. Run tests from inside the worktree with `./pytest.sh`.

## The one rule

**Never push to `main` or release from a dirty/unreviewed state. Always work on a
branch, open a PR, let CI pass, then merge.** Releases to PyPI happen only via a
GitHub release that triggers `publish-pypi.yml` (OIDC trusted publisher).

## The flow

```
scripts/worktree.sh new feat/<short-name>   # 1. fresh worktree off origin/main (main checkout is read-only)
# open .worktrees/feat-<short-name> and work THERE
# ... make changes ...
./pytest.sh --check-coverage                 # 2. tests must pass at 100% coverage BEFORE pushing
# before pushing: run /simplify (or /code-review) on the diff to catch
#   duplication and reuse misses while they are still cheap to fix
git push -u origin feat/<short-name>         # 3. push (needs fresh explicit user approval)
# 4. open a PR -> test-coverage.yml runs on the PR and enforces 100% coverage
# 5. review, then merge the PR to main
```

## Testing — the gate

- **Run tests only via `./pytest.sh`** — it sets `PYTHONPATH` to the project root
  and activates the worktree's `.venv`. Never call `pytest` / `python -m pytest`
  directly.
- **100% coverage is enforced** (`--cov-fail-under=100`). Verify locally before
  pushing: `./pytest.sh --check-coverage`. `test-coverage.yml` re-checks on every
  PR to main and fails the PR otherwise.
- **NEVER modify, add, or remove tests without explicit user confirmation.** Tests
  are the spec. If a test fails during implementation, report it and ask before
  changing it.
- **Test isolation is mandatory** — tests use temp dirs and fixture copies, never
  production paths or `.opencrane/`.
- No Docker needed: Milvus runs in Lite mode (single-file DB) for unit tests.
  Integration tests (`./pytest.sh tests/integration/`) use Milvus Lite too.

## Releasing to PyPI — gated, approval-first

Publishing happens when a **GitHub release** is created, which triggers
`publish-pypi.yml`. The discipline:

1. **Bump the version** on a branch, open a PR, merge it the normal way.
2. **Show the user the release notes for approval BEFORE creating the release.**
   Do not create the release until they approve the notes.
3. Order is: **bump → push → release.** Never create the release before the
   version bump and tag are on `main`.
4. **Never modify or delete an already-published release** (or re-publish a
   version) — PyPI rejects re-uploads and downstream installs break.
5. **Every push and every release needs fresh, explicit user approval.** Approval
   for one push/release does NOT carry over to the next.

## Commit rules

- **NEVER include `Co-Authored-By: Claude` or any AI co-author attribution.** No
  exceptions, all commits.
- Concise messages: `type: short description` (e.g. `feat: add custom walker
  support`, `fix: token count for empty files`).
- Types: `feat`, `fix`, `docs`, `test`, `ci`, `chore`, `refactor`.

## GitHub Actions

- **Always pin actions to a full commit SHA**, with the version tag as a trailing
  comment: `uses: actions/checkout@de0fac…  # v6.0.2`. Never a bare tag/version.
- CI installs `requirements.txt` (which pulls in `requirements/viz.txt`, so the
  visualize tests run) and gates on 100% coverage via
  `./pytest.sh --check-coverage`.

## Red flags — stop

- About to describe "what the code does" without checking the branch → STOP. Run
  `git status -sb` first; if HEAD is behind `origin/main`, reason about
  `origin/main`, not the stale working tree.
- About to edit in the shared main checkout, or `git switch -c` there instead of
  making a worktree → STOP. A concurrent session can switch the main checkout's
  HEAD out from under you, so your commit lands on another session's branch. Use
  `scripts/worktree.sh new feat/<short-name>` and work in that worktree. Before
  opening the PR, verify isolation: `git log --oneline origin/main..HEAD` must
  show **only your own commits**.
- About to `git push` to `main` directly → branch instead.
- About to push or create a release without fresh explicit approval → STOP and ask.
- About to create a GitHub release before showing the release notes for approval,
  or before the version bump is merged to main → STOP.
- About to modify or re-publish an existing release/version → never; PyPI rejects
  it and breaks installs.
- About to change or add a test to make a failure go away → STOP, report it, ask
  first.
- Tempted to run `pytest` directly → use `./pytest.sh` (PYTHONPATH + venv).
