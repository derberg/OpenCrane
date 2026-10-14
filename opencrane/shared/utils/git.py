import hashlib
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List

logger = logging.getLogger(__name__)

# Paths, relative to each source directory, that ignored_fingerprint never
# hashes: OpenCrane's own output and state, and tool and dependency dirs that
# hold no docs. A file is left out when its relative path starts with one of
# these, compared component by component, so "build" skips build/x.md but not
# builder/x.md. Fetched sources in .opencrane/sources/ are still hashed.
FINGERPRINT_EXCLUDED_PATHS = (
    ".opencrane/llmstxt",
    ".opencrane/chunks.json",
    ".opencrane/embeddings.json",
    ".opencrane/milvus.db",
    ".opencrane/.milvus.db.lock",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    "dist",
    "build",
)


_repo_subdir: str | None = None


def get_repo_subdir() -> str:
    """Return the relative path from git repo root to CWD, or empty string.

    Useful for building GitHub blob URLs when the workspace is in a
    subdirectory of the repository.  The result is cached for the process
    lifetime.
    """
    global _repo_subdir
    if _repo_subdir is not None:
        return _repo_subdir

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-prefix"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            _repo_subdir = result.stdout.strip().rstrip("/")
            return _repo_subdir
    except (OSError, FileNotFoundError):
        logger.debug("git not available; cannot determine repo subdir")

    _repo_subdir = ""
    return ""


def _is_excluded(file_path: Path, excluded: List[Path]) -> bool:
    return any(file_path == e or e in file_path.parents for e in excluded)


def ignored_fingerprint(paths: List[Path], exclude: Iterable[Path] = ()) -> Dict[str, str] | None:
    """Return a SHA-256 digest for every Git-ignored file under the given paths.

    Git never reports changes in files it ignores, so :func:`has_changes`
    compares these digests with the ones recorded by the last run instead.
    Keys are absolute file paths. Files under :data:`FINGERPRINT_EXCLUDED_PATHS`
    of each path, or under any of *exclude*, are left out, so OpenCrane's own
    output, the fingerprint file among it, never counts as a change. Returns
    ``None`` when git is unavailable or fails, for example outside a
    repository, so callers assume changes.
    """
    fingerprint: Dict[str, str] = {}
    extra = [Path(os.path.abspath(e)) for e in exclude]
    for path in paths:
        root = Path(os.path.abspath(path))
        excluded = [root.joinpath(*p.split("/")) for p in FINGERPRINT_EXCLUDED_PATHS] + extra
        try:
            result = subprocess.run(
                ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="surrogateescape",
            )
        except (OSError, FileNotFoundError):
            logger.warning("git not available; assuming changes exist")
            return None
        if result.returncode != 0:
            return None
        for name in result.stdout.split("\0"):
            if not name:
                continue
            # Absolute but not resolved: a symlink's target can sit outside the
            # source dir, and load_fingerprint would then drop its key, so the
            # record would never match. os.getcwd() is already the physical path.
            file_path = Path(os.path.abspath(name))
            if _is_excluded(file_path, excluded):
                continue
            if file_path.is_file():
                with file_path.open("rb") as fh:
                    fingerprint[str(file_path)] = hashlib.file_digest(fh, "sha256").hexdigest()
    return fingerprint


def _under(key: str, paths: List[Path]) -> bool:
    return any(key.startswith(str(p.resolve()) + os.sep) for p in paths)


def _read_store(fingerprint_file: Path) -> Dict[str, str] | None:
    try:
        stored = json.loads(fingerprint_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return stored if isinstance(stored, dict) else None


def load_fingerprint(fingerprint_file: Path, paths: List[Path]) -> Dict[str, str] | None:
    """Return the recorded digests of the files under *paths*, or None when nothing was recorded."""
    stored = _read_store(fingerprint_file)
    if stored is None:
        return None
    return {k: v for k, v in stored.items() if _under(k, paths)}


def save_fingerprint(fingerprint_file: Path, paths: List[Path], fingerprint: Dict[str, str]) -> None:
    """Record *fingerprint* for *paths*, keeping the digests recorded for other paths."""
    stored = _read_store(fingerprint_file) or {}
    merged = {k: v for k, v in stored.items() if not _under(k, paths)}
    merged.update(fingerprint)
    fingerprint_file.parent.mkdir(parents=True, exist_ok=True)
    fingerprint_file.write_text(json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8")


def has_changes(
    paths: List[Path],
    fingerprint_file: Path | None = None,
    fingerprint: Dict[str, str] | None = None,
) -> bool:
    """Return True if any of the given paths changed since the last run.

    Tracked and untracked files take the fast path: ``git diff`` against HEAD
    and ``git ls-files --others``. Git reports nothing for ignored files, so
    their SHA-256 digests (*fingerprint*, computed with
    :func:`ignored_fingerprint` when not given) are compared with the digests
    recorded in *fingerprint_file* by :func:`save_fingerprint`. Ignored files
    with no recorded digests count as changed.

    Falls back to True (assume changed) when git is unavailable or the directory
    is not a git repository, so callers never silently skip work.
    """
    for path in paths:
        path_str = str(path)
        try:
            # Tracked changes against HEAD
            result = subprocess.run(
                ["git", "diff", "--quiet", "HEAD", "--", path_str],
                capture_output=True,
            )
            if result.returncode != 0:
                return True
            # Untracked files
            result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard", path_str],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                return True
        except (OSError, FileNotFoundError):
            logger.warning("git not available; assuming changes exist")
            return True
    if fingerprint is None:
        fingerprint = ignored_fingerprint(paths)
    if fingerprint is None:
        return True
    previous = load_fingerprint(fingerprint_file, paths) if fingerprint_file is not None else None
    if not fingerprint and not previous:
        # Nothing under these paths is or was ignored: the fast path above decides.
        return False
    # Ignored files with no recorded digests, or with other digests, count as
    # changed. A deleted ignored file drops out of *fingerprint* and differs too.
    return previous != fingerprint
