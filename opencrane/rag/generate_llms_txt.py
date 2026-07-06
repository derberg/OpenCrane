#!/usr/bin/env python3
"""
Generate llms-full.txt files for documentation from configured source directories.

Creates hierarchical llms-full.txt files:
- Top level: .opencrane/llmstxt/llms-full.txt (combines all sources)
- Per source: .opencrane/llmstxt/{source}/llms-full.txt (combines projects in source)
- Per project: .opencrane/llmstxt/{source}/{project}/llms-full.txt
- Per subproject: .opencrane/llmstxt/{source}/{project}/{subproject}/llms-full.txt

- Removes images and notes their removal
- Rewrites relative links to intra-file anchors so they continue to work in the flattened output
- Adds stable anchors per file and heading to support rewritten links
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, NamedTuple, Optional

import yaml

from opencrane.rag.services.llms_index import PAGE_SEPARATOR, IndexEntry, LlmsIndex, render_llms_txt
from opencrane.rag.services.source_mapping import SourceMapping
from opencrane.shared.config import get_config
from opencrane.shared.utils.git import get_repo_subdir, has_changes

# Default paths are relative to cwd (resolved at call time via generate_outputs).
# These module-level values are only used as fallbacks and by legacy __main__ invocation.
ROOT = Path.cwd()
SOURCES_BASE = ROOT
LLMSTXT_BASE = ROOT / ".opencrane" / "llmstxt"
# Legacy paths for tests/backward compatibility
SOURCE_ROOT = SOURCES_BASE
OUTPUT_ROOT = LLMSTXT_BASE

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def strip_frontmatter(text: str) -> tuple[dict, str]:
    """Split leading YAML frontmatter from body. Returns ({}, text) if absent."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return data, text[match.end():]


def filename_to_title(stem: str) -> str:
    """Turn a file stem into a human title: 'getting-started' -> 'Getting Started'."""
    words = re.split(r"[-_]+", stem.strip())
    return " ".join(w.capitalize() for w in words if w) or stem


def derive_title(frontmatter: dict, body: str, file_path: Path) -> str:
    """Priority: frontmatter title -> first heading -> filename-derived."""
    fm_title = frontmatter.get("title")
    if isinstance(fm_title, str) and fm_title.strip():
        return fm_title.strip()
    for line in body.splitlines():
        m = HEADING_RE.match(line)
        if m:
            return m.group(2).strip()
    return filename_to_title(file_path.stem)


class CodeFenceConfig(NamedTuple):
    """Configuration for a custom code fence type.

    Attributes:
        fence_type: The code fence language identifier (e.g., 'openapi', 'terraform').
        handler: Callable that receives the raw content of the matched fence block,
            the path of the markdown file being processed, the root directory of the
            project, and the project name — and returns the replacement string
            (including any wrapping).
    """
    fence_type: str
    handler: Callable[[str, Path, Path, str], str]


# Global source mapping instance
_source_mapping: Optional[SourceMapping] = None


def get_source_mapping() -> SourceMapping:
    """Get or initialize global source mapping."""
    global _source_mapping
    if _source_mapping is None:
        config = get_config()
        mapping_file = config.mapping_file
        if not mapping_file.is_absolute():
            # Resolve relative to cwd (the workspace the script is run from)
            mapping_file = Path.cwd() / mapping_file
        _source_mapping = SourceMapping(mapping_file)
    return _source_mapping


def _matches_ignore_pattern(file_path: Path, patterns: List[str]) -> bool:
    """Check if a file path contains any of the ignore pattern directory names."""
    return any(pattern in file_path.parts for pattern in patterns)


def filter_markdown_files(files: Iterable[Path], ignore_patterns: List[str] | None = None) -> List[Path]:
    """Filter out markdown files matching ignore patterns.

    Args:
        files: Iterable of file paths to filter.
        ignore_patterns: Directory names to exclude. Defaults to ["devel"]
            when None (preserves legacy behavior for callers that don't
            pass patterns).
    """
    if ignore_patterns is None:
        ignore_patterns = ["devel"]
    if not ignore_patterns:
        return list(files)
    return [f for f in files if not _matches_ignore_pattern(f, ignore_patterns)]


def slugify(text: str) -> str:
    """Convert text to a URL/anchor-friendly slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "section"


def build_anchor(rel_path: Path, heading: str | None = None) -> str:
    """Build a stable anchor using the path (including project) and optional heading."""
    base = slugify(rel_path.as_posix())
    if heading:
        return f"{base}-{slugify(heading)}"
    return base


def strip_images(text: str) -> str:
    """Remove image embeds and replace with a plain-text note."""

    def md_image_repl(match: re.Match[str]) -> str:
        alt, src = match.group(1), match.group(2)
        hint = alt.strip() or Path(src).name
        return f"[Image removed: {hint}]"

    def html_image_repl(match: re.Match[str]) -> str:
        attrs = match.group(1) or ""
        alt_match = re.search(r"alt=\"(.*?)\"", attrs, flags=re.IGNORECASE)
        hint = alt_match.group(1).strip() if alt_match else "image"
        return f"[Image removed: {hint}]"

    text = re.sub(r"!\[(.*?)\]\((.*?)\)", md_image_repl, text)
    text = re.sub(r"<img(.*?)>", html_image_repl, text, flags=re.IGNORECASE)
    return text


def rewrite_links(
    text: str,
    file_path: Path,
    rel_with_project: Path,
    project_dir: Path,
    project_name: str,
) -> str:
    """Rewrite relative links by removing URLs and keeping only labels for AI agent consumption."""

    def replace(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)

        # Strip images (handled elsewhere); this guard is for safety
        if url.startswith("data:"):
            return f"{label} (inline data removed)"

        # Leave external links untouched
        if SCHEME_RE.match(url) or url.startswith("//"):
            return match.group(0)

        # Absolute path links are not resolvable in flattened output
        if url.startswith("/"):
            return f"{label} (link removed: {url})"

        # For all internal links (same-file anchors or cross-document), just keep the label
        # AI agents will use semantic search to find referenced content rather than navigation
        
        # Only rewrite markdown-ish targets; leave other file types (pdf, zip, etc.) untouched
        if "#" in url:
            path_part = url.split("#", 1)[0]
        else:
            path_part = url
            
        if path_part:  # Has a file path component
            target_ext = Path(path_part).suffix.lower()
            if target_ext and target_ext not in {".md", ".markdown"}:
                return match.group(0)
        
        # Return just the label - AI agents will search for content by keywords
        return label

    return re.sub(r"\[(.*?)\]\((.*?)\)", replace, text)


def _docs_site_page_path(file_rel: str) -> str:
    """Map a markdown file path to its rendered docs-site page path.

    Rendered docs sites serve markdown pages without the source extension
    (``code-contributor-guide.md`` → ``code-contributor-guide``) and serve an
    ``index`` page as its containing directory (``community/index.md`` →
    ``community``, root ``index.md`` → ``""``). Used only for ``docs_url``;
    GitHub blob links keep the raw ``.md`` path.
    """
    for ext in (".md", ".markdown"):
        if file_rel.endswith(ext):
            file_rel = file_rel[: -len(ext)]
            break
    if file_rel == "index":
        return ""
    if file_rel.endswith("/index"):
        file_rel = file_rel[: -len("/index")]
    return file_rel


def get_source_url(rel_with_project: Path, project_name: str) -> str | None:
    """Return the source URL for a given file path and project name.

    Prefers ``docs_url`` from the source mapping when set (useful for non-GitHub
    or published docs sites). Falls back to building a GitHub blob URL from
    ``url``. Returns ``None`` when no mapping entry is found — callers
    should skip URL embedding in that case.
    """
    mapping = get_source_mapping()
    found = mapping.find_source_for_file(rel_with_project)
    if not found:
        return None
    source, matched_path = found

    rel_str = rel_with_project.as_posix()

    # Compute path relative to the mapped key
    relative_after_key = rel_str
    if matched_path:
        matched_prefix = f"{matched_path.rstrip('/')}/"
        if rel_str.startswith(matched_prefix):
            relative_after_key = rel_str[len(matched_prefix):]

    docs_path = source.get("docs_path", "")

    # Prefer docs_url when explicitly set — supports any URL, not just GitHub
    docs_url = source.get("docs_url", "")
    if docs_url:
        file_rel = relative_after_key
        if docs_path:
            docs_prefix = f"{docs_path.rstrip('/')}/"
            if file_rel.startswith(docs_prefix):
                file_rel = file_rel[len(docs_prefix):]
        # docs_url points at a rendered docs site, which serves markdown without
        # the source file extension (and an index page as its directory). Keeping
        # the raw ``.md`` path produces dead links, so normalise it here. The
        # GitHub blob fallback below intentionally keeps the extension.
        page_path = _docs_site_page_path(file_rel)
        base = docs_url.rstrip("/")
        return f"{base}/{page_path}" if page_path else base

    # Fall back to GitHub blob URL
    url = source.get("url", "")
    if not url:
        return None

    # For local sources the workspace may sit inside a repo subdirectory.
    # Prepend that prefix so the GitHub blob URL points to the correct path.
    repo_prefix = ""
    if source.get("local"):
        subdir = get_repo_subdir()
        if subdir:
            repo_prefix = f"{subdir}/"

    if docs_path:
        docs_prefix = f"{docs_path.rstrip('/')}/"
        file_rel = relative_after_key
        if file_rel.startswith(docs_prefix):
            file_rel = file_rel[len(docs_prefix):]
        return f"{url}/blob/main/{repo_prefix}{docs_path.rstrip('/')}/{file_rel}"

    return f"{url}/blob/main/{repo_prefix}{rel_str}"


def ensure_leading_h1(body: str, title: str) -> str:
    """Guarantee the block starts with ``# {title}``.

    If the body's first non-blank line is already ``# {title}`` (exact match),
    the body is returned unchanged; otherwise ``# {title}`` is prepended.
    """
    stripped = body.lstrip("\n")
    first_line = stripped.split("\n", 1)[0].strip()
    if first_line == f"# {title}":
        return body
    return f"# {title}\n\n{body.lstrip(chr(10))}"


def process_file(file_path: Path, project_dir: Path, project_name: str) -> tuple[str, IndexEntry | None]:
    """Process a markdown file and return ``(content, entry)``.

    ``content`` is the clean file text (no URL injections, no ``### {url}``
    boundary line) with a guaranteed leading ``# {title}`` heading.
    ``entry`` is an :class:`~opencrane.rag.services.llms_index.IndexEntry`
    for this file, or ``None`` when no source URL can be resolved.
    """
    rel_with_project = Path(project_name) / file_path.relative_to(project_dir)
    raw_text = file_path.read_text(encoding="utf-8")
    frontmatter, body = strip_frontmatter(raw_text)
    body = strip_images(body)
    body = rewrite_links(body, file_path, rel_with_project, project_dir, project_name)
    title = derive_title(frontmatter, body, file_path)
    content = ensure_leading_h1(body, title)
    url = get_source_url(rel_with_project, project_name)
    entry = IndexEntry(source=project_name, title=title, url=url) if url else None
    return content, entry



def process_fence_blocks(text: str, file_path: Path, project_dir: Path, project_name: str, fence_types: Dict[str, "CodeFenceConfig"] | None = None) -> str:
    """Process code fence blocks using registered fence handlers.

    For each registered fence type, calls its handler with the raw block content
    and replaces the fence block with the handler's return value.

    Args:
        text: Source text to transform.
        file_path: Path of the markdown file being processed.
        project_dir: Root directory of the project.
        project_name: Name of the project.
        fence_types: Mapping of fence-type key → CodeFenceConfig.
            When None or empty, the text is returned unchanged.
    """
    if not fence_types:
        return text

    def replace_block(match: re.Match[str]) -> str:
        fence_type = match.group(1)
        raw_content = match.group(2).strip()
        return fence_types[fence_type].handler(raw_content, file_path, project_dir, project_name)

    fence_types_pattern = "|".join(re.escape(ft) for ft in fence_types.keys())
    pattern = rf"```({fence_types_pattern})\s+([^`]+?)```"

    text = re.sub(pattern, replace_block, text, flags=re.MULTILINE)
    return text


def build_project_output(project_dir: Path, project_name: str | None = None, md_files: List[Path] | None = None, fence_types: Dict[str, "CodeFenceConfig"] | None = None) -> tuple[str, list[IndexEntry]]:
    """Build combined output for a project.

    Returns a tuple ``(content, entries)`` where *content* is the sections
    joined by the collision-proof page separator
    (``\\n\\n<!-- opencrane:page -->\\n\\n``) and *entries* is the ordered list of
    :class:`~opencrane.rag.services.llms_index.IndexEntry` objects collected
    from each processed file.

    Args:
        project_dir: Root directory of the project.
        project_name: Name of the project; defaults to ``project_dir.name``.
        md_files: Markdown files to include; defaults to all ``*.md`` files
            under *project_dir* (excluding ``devel`` folders).
        fence_types: Optional fence-type registry forwarded to
            ``process_fence_blocks``.  When None or empty, no fence blocks
            are processed.
    """
    # project_name/md_files optional for backward compatibility with older callers/tests
    project_name = project_name or project_dir.name
    md_files = md_files or filter_markdown_files(sorted(project_dir.rglob("*.md")))
    sections: List[str] = []
    entries: List[IndexEntry] = []

    for md_file in md_files:
        processed, entry = process_file(md_file, project_dir, project_name)
        processed = process_fence_blocks(processed, md_file, project_dir, project_name, fence_types=fence_types)
        sections.append(processed)
        if entry is not None:
            entries.append(entry)

    # If this project contributed content but resolved no URLs for any file, emit a
    # single fallback IndexEntry so render_llms_txt never drops the ## {source}
    # section.  A dropped section causes the combined llms.txt to have fewer
    # sections than the combined llms-full.txt has ====== blocks; the chunker then
    # falls back to legacy marker detection (finds nothing in clean content) and
    # sets source_url=None for EVERY chunk in the bundle — poisoning even correctly-
    # mapped sources.  The empty-title placeholder keeps the section present while
    # leaving this unmapped source's own chunks with source_url=None, which is the
    # pre-existing behaviour for an unmapped source in isolation.
    if sections and not entries:
        entries.append(IndexEntry(source=project_name, title="", url=""))

    return f"\n\n{PAGE_SEPARATOR}\n\n".join(sections), entries


def write_outputs(project_outputs: Dict[str, str], output_root: Path = OUTPUT_ROOT, root_projects: set[str] | None = None, project_entries: Dict[str, list[IndexEntry]] | None = None) -> None:
    root_projects = root_projects or set()
    project_entries = project_entries or {}
    output_root.mkdir(parents=True, exist_ok=True)

    # Per-project outputs
    for project, content in project_outputs.items():
        if project in root_projects:
            continue  # Root-level markdown lives only in the combined output
        target_dir = output_root / project
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "llms-full.txt").write_text(content, encoding="utf-8")

    # Combined output - concatenate project contents with a ====== separator
    # between each project so the number of ====== blocks equals the number of
    # ## {source} sections in the companion llms.txt. The chunker aligns the Nth
    # block to the Nth index section by count+position; joining projects with a
    # plain "\n\n" would collapse N projects into a single block and force the
    # chunker into the legacy marker path (dropping every source_url).
    combined_sections = []
    for project, content in project_outputs.items():
        combined_sections.append(content)

    (output_root / "llms-full.txt").write_text("\n\n======\n\n".join(combined_sections), encoding="utf-8")

    # Write per-source llms.txt index alongside the combined llms-full.txt
    if project_entries:
        sections = [
            (project, project_entries.get(project, []))
            for project in project_outputs
        ]
        index_content = render_llms_txt("Documentation", sections)
        (output_root / "llms.txt").write_text(index_content, encoding="utf-8")


def _synthesize_entries_from_full(source_name: str, full_text: str, docs_url: str) -> list[IndexEntry]:
    """Synthesize one index entry per H1 page in a pre-existing llms-full.txt.

    Splits *full_text* on ``^#\\s+`` H1 lines (FENCE-AWARE — ``#`` lines inside
    ```` ``` ```` fenced code blocks are ignored so they are not mistaken for
    page boundaries, mirroring the chunker's ``_split_block_into_pages``). Each
    H1 becomes one entry: title = the H1 text, url = *docs_url* (the source's
    base URL, repeated for every page) when set, else ``""``.

    The entry count matches the number of H1-delimited pages the chunker will
    detect in the same block, so the positional join aligns.
    """
    titles: list[str] = []
    in_fence = False
    for line in full_text.split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^#\s+(.*)$", line)
        if m:
            titles.append(m.group(1).strip())
    if not titles:
        # No H1 headings found — emit a single fallback entry so the section is
        # never dropped from the index and block/section counts stay aligned.
        return [IndexEntry(source=source_name, title="", url=docs_url or "")]
    return [IndexEntry(source=source_name, title=title, url=docs_url) for title in titles]


def _strip_docs_md_suffix(url: str) -> str:
    """Normalize a companion source-file URL to its rendered docs-site page.

    GitBook-style companions list source-file URLs ending in ``.md`` (or
    ``/index.md``); the rendered site serves those without the extension
    (``.../the-foundation.md`` → ``.../the-foundation``) and an ``index`` page as
    its containing directory (``.../section/index.md`` → ``.../section``),
    mirroring :func:`_docs_site_page_path` but on an absolute URL. A plain suffix
    strip: companion URLs carry no query/fragment, so we do not special-case one
    (a ``.md`` preceding a ``?``/``#`` would be left intact — not a concern here).
    """
    for ext in (".md", ".markdown"):
        if url.endswith(ext):
            url = url[: -len(ext)]
            break
    else:
        return url
    if url.endswith("/index"):
        url = url[: -len("/index")]
    return url


def _external_index_section(
    subdir: Path,
    full_text: str,
    mapped_paths: Dict[str, dict],
) -> tuple[str, list[IndexEntry]]:
    """Build the combined-llms.txt ``## {source}`` section for an external bundle.

    Prefers the fetched companion ``{subdir}/llms.txt`` — its entries carry real
    per-page URLs. Re-tags every parsed entry under *subdir*'s name so section
    ordering matches the appended ``llms-full.txt`` block. When the source has a
    ``docs_url`` in the mapping, each companion URL is normalized to its rendered
    docs-site page (trailing ``.md`` stripped) via :func:`_strip_docs_md_suffix`.
    When no companion exists, synthesizes one entry per H1 page from *full_text*,
    using the source's ``docs_url`` (repeated for every page) when set.
    """
    source_name = subdir.name
    cfg = mapped_paths.get(source_name)
    docs_url = (cfg.get("docs_url", "") or "") if cfg else ""
    companion = subdir / "llms.txt"
    if companion.exists():
        parsed = LlmsIndex.parse(companion.read_text(encoding="utf-8"))
        # When docs_url is set the companion URLs point at rendered docs-site
        # pages, which are served without the ``.md`` source extension. Strip it
        # so the per-page source_url matches the canonical page (consistent with
        # get_source_url). Without docs_url, leave companion URLs verbatim.
        entries = [
            IndexEntry(
                source=source_name,
                title=e.title,
                url=_strip_docs_md_suffix(e.url) if docs_url else e.url,
            )
            for e in parsed._entries
        ]
        return source_name, entries
    return source_name, _synthesize_entries_from_full(source_name, full_text, docs_url)


def _combine_existing_llmstxt(llmstxt_base: Path) -> List[Path]:
    """Scan llmstxt subdirectories for existing llms-full.txt files and combine them.

    Used when no sources are configured in config.yaml but pre-existing
    llms-full.txt files exist (e.g., added via ``opencrane add``).

    Returns the list of found files (empty if none exist).
    """
    if not llmstxt_base.exists():
        return []

    existing = sorted(
        p for p in llmstxt_base.iterdir()
        if p.is_dir() and (p / "llms-full.txt").exists()
    )

    if not existing:
        return []

    try:
        mapped_paths = get_source_mapping().data.get("sources", {})
    except Exception:  # pragma: no cover
        mapped_paths = {}

    combined_parts = []
    index_sections: List[tuple[str, list[IndexEntry]]] = []
    for subdir in existing:
        llms_file = subdir / "llms-full.txt"
        content = llms_file.read_text(encoding="utf-8")
        combined_parts.append(content)
        # One ## {source} section per ====== block, same order — so the chunker's
        # count-based block/section alignment always matches.
        index_sections.append(_external_index_section(subdir, content, mapped_paths))

    llmstxt_base.mkdir(parents=True, exist_ok=True)
    (llmstxt_base / "llms-full.txt").write_text(
        "\n\n======\n\n".join(combined_parts), encoding="utf-8"
    )
    (llmstxt_base / "llms.txt").write_text(
        render_llms_txt("Documentation", index_sections), encoding="utf-8"
    )

    print(f"Combined {len(existing)} existing llms-full.txt files into {llmstxt_base / 'llms-full.txt'}")
    return [subdir / "llms-full.txt" for subdir in existing]


def generate_outputs(selected_projects: Iterable[str] | None = None, config=None, sources_dirs: List[Path] | None = None, llmstxt_dir: Path | None = None, force: bool = False) -> None:
    """Generate llms-full.txt output files.

    Args:
        selected_projects: Optional iterable of project names to process.
            When None, all projects are processed.
        config: Optional ``OpenCraneConfig`` instance.  When supplied, its
            ``fence_types`` dict controls which fence blocks are processed.
            When None, no fence blocks are processed.
        sources_dirs: Source directories to process. Falls back to
            ``AI_DOCS_SOURCES_DIRS`` env var.
        llmstxt_dir: Output directory for llms-full.txt files. Falls back to
            ``AI_DOCS_LLMSTXT_DIR`` env var, then ``llmstxt``.
        force: When True, skip the git-change check and always regenerate.
    """
    fence_types: Dict[str, CodeFenceConfig] = config.fence_types if config is not None else {}

    global SOURCES_BASE, LLMSTXT_BASE, SOURCE_ROOT, OUTPUT_ROOT

    # Reset LLMSTXT_BASE to cwd so the function works regardless of where the
    # package is installed.  Explicit overrides below take precedence.
    # SOURCE_ROOT/SOURCES_BASE are only used by the legacy selected_projects
    # path and are set via env var overrides when needed.
    cwd = Path.cwd()
    LLMSTXT_BASE = cwd / ".opencrane" / "llmstxt"
    OUTPUT_ROOT = LLMSTXT_BASE

    # CLI params take precedence over env vars
    sources_override = os.environ.get("AI_DOCS_SOURCES_DIR")
    sources_dirs_override = ",".join(str(p) for p in sources_dirs) if sources_dirs else os.environ.get("AI_DOCS_SOURCES_DIRS")
    llmstxt_override = str(llmstxt_dir) if llmstxt_dir else os.environ.get("AI_DOCS_LLMSTXT_DIR")

    if sources_override:
        SOURCES_BASE = Path(sources_override)
        SOURCE_ROOT = SOURCES_BASE
    if llmstxt_override:
        LLMSTXT_BASE = Path(llmstxt_override)
        OUTPUT_ROOT = LLMSTXT_BASE

    # Legacy path for selected projects (tests expect SOURCE_ROOT behavior)
    if selected_projects is not None:
        source_root = SOURCE_ROOT
        if not source_root.exists():
            raise FileNotFoundError(f"Source directory not found: {source_root}")

        project_dirs = [p for p in source_root.iterdir() if p.is_dir()]
        if selected_projects:
            project_dirs = [p for p in project_dirs if p.name in selected_projects]

        project_outputs: Dict[str, str] = {}
        project_entries: Dict[str, list[IndexEntry]] = {}
        for project_dir in sorted(project_dirs, key=lambda p: p.name):
            md_files = filter_markdown_files(sorted(project_dir.rglob("*.md")))
            if not md_files:
                continue  # pragma: no cover
            project_outputs[project_dir.name], project_entries[project_dir.name] = build_project_output(project_dir, project_dir.name, md_files, fence_types=fence_types)

        output_root = OUTPUT_ROOT
        root_projects: set[str] = set()
        write_outputs(project_outputs, output_root, root_projects, project_entries=project_entries)
        return

    # Multiple source directories support
    if sources_dirs_override:
        # Explicit list of source directories - treat each as a source, not a container
        source_dirs = [Path(p.strip()).resolve() for p in sources_dirs_override.split(",") if p.strip()]
        # Filter out non-existent directories with warnings
        valid_sources = []
        for src in source_dirs:
            if not src.exists():
                print(f"Warning: Source directory not found: {src}")
            else:
                valid_sources.append(src)
        source_dirs = valid_sources

        if not force and not has_changes(source_dirs):
            print("⊘ Skipping --generate-llms: no changes detected in source directories")
            print("  To force regeneration, use: --force")
            return

    else:
        # Fall back to deriving source dirs from the mapping file
        mapping = get_source_mapping()
        sources = mapping.data.get("sources", {})
        if not sources:
            # No sources in mapping — but there may be pre-existing llms-full.txt
            # files placed by `opencrane add` or manually. Combine them if found.
            existing_files = _combine_existing_llmstxt(LLMSTXT_BASE)
            if not existing_files:
                print("⊘ No sources configured and no existing llms-full.txt files found.")
                print("  Add sources with: opencrane add")
            return
        workspace_root = Path.cwd()
        sources_base = workspace_root / ".opencrane" / "sources"

        source_dirs = []
        # Check if .opencrane/sources/ has fetched (non-local) content
        non_local_keys = [k for k, v in sources.items() if not v.get("local")]
        if sources_base.exists() and any((sources_base / k).exists() for k in non_local_keys):
            source_dirs.append(sources_base)
        elif non_local_keys:
            top_level_dirs = {Path(k).parts[0] for k in non_local_keys if Path(k).parts}
            source_dirs.extend(sorted(
                [sources_base / d for d in top_level_dirs if (sources_base / d).exists()],
                key=lambda p: p.name,
            ))

        # Add workspace root if any local sources exist (local paths are relative to workspace root)
        has_local = any(v.get("local") for v in sources.values())
        if has_local and workspace_root not in source_dirs:
            source_dirs.append(workspace_root)

        if not source_dirs:
            # All sources may be of type llmstxt (no local directories). Fall back
            # to combining pre-existing llms-full.txt files with docs_url injection.
            existing_files = _combine_existing_llmstxt(LLMSTXT_BASE)
            if not existing_files:
                print("⊘ Skipping llms-full.txt generation: no source directories found from mapping file")
                print(f"  Expected sources in: {sources_base}")
            return
    # Resolved source dirs are used to detect overlapping roots: when one
    # source_dir is nested inside another (e.g. .opencrane/sources lives under
    # the workspace root for mixed remote + local: true projects), a mapped
    # path must be owned by the most specific (deepest) source_dir only, so it
    # is not processed — and combined — more than once.
    resolved_source_dirs = [sd.resolve() for sd in source_dirs]

    # Per-source contributions accumulated across all source_dirs. Each
    # source_dir contributes its combined content exactly once; the top-level
    # combined file is assembled from these at the end so overlapping roots
    # cannot duplicate content.
    loop_contributions: List[tuple[str, str]] = []
    # Parallel accumulator: (source_dir_posix, output_name, entries) — keyed so
    # top_entry_sections can be sorted by the same key as loop_contributions.
    loop_entry_sections: List[tuple[str, str, list[IndexEntry]]] = []
    loop_covered: set[str] = set()

    for source_dir in sorted(source_dirs, key=lambda p: p.name):
        # Store workspace root for relative path computation
        workspace_root = Path.cwd()
        
        # Load source mapping to determine which exact paths to process
        # Filtering can be disabled via AI_DOCS_NO_FILTER env var (useful for tests)
        mapping = get_source_mapping()
        mapped_paths = mapping.data.get("sources", {})
        
        # Determine if we should use mapping-based filtering
        if os.environ.get("AI_DOCS_NO_FILTER"):
            should_filter = False
        else:
            try:
                source_dir.relative_to(workspace_root)
                should_filter = len(mapped_paths) > 0
            except ValueError:
                # Source dir not under workspace root (e.g., temp dir in tests)
                should_filter = False
        
        projects: List[tuple[str, Path, List[Path], bool]] = []

        if should_filter:
            # ONLY process paths explicitly listed in mapping - no directory discovery
            # When sources come from mapping (no explicit --sources-dir), files are
            # stored under .opencrane/sources/. When --sources-dir is explicit, the
            # user already told us where the files are.
            # When --sources-dir is explicit, resolve mapped paths relative to
            # workspace root (mapped paths may reference the source dir by name).
            # When using mapping-based discovery, sources live under .opencrane/sources/.
            path_base_candidates = [workspace_root / ".opencrane" / "sources", workspace_root]
            for mapped_path in sorted(mapped_paths.keys()):
                source_config = mapped_paths[mapped_path]
                # For local sources with docs_path, use docs_path as the
                # filesystem directory instead of the config key.
                resolve_path = mapped_path
                if source_config.get("local") and source_config.get("docs_path"):
                    resolve_path = source_config["docs_path"]

                full_path = None
                for pb in path_base_candidates:
                    candidate = pb / resolve_path
                    if candidate.exists() and candidate.is_dir():
                        full_path = candidate
                        break
                if full_path is None:
                    continue

                # Only process if this path is under the current source_dir
                try:
                    full_path.relative_to(source_dir)
                except ValueError:
                    # This mapped path is not under current source_dir, skip it
                    continue

                # If another, more specific (deeper) source_dir also contains
                # this path, let that source_dir own it. Prevents the same files
                # being emitted twice when source_dirs overlap (e.g. the nested
                # .opencrane/sources vs the workspace root).
                resolved_full = full_path.resolve()
                current_resolved = source_dir.resolve()
                owned_by_deeper = False
                for other in resolved_source_dirs:
                    if other == current_resolved:
                        continue
                    try:
                        resolved_full.relative_to(other)
                    except ValueError:
                        continue
                    if len(other.parts) > len(current_resolved.parts):
                        owned_by_deeper = True
                        break
                if owned_by_deeper:
                    continue

                # Collect ALL markdown files recursively (excluding ignore pattern folders)
                ignore_patterns = mapping.get_ignore_patterns(mapped_path)
                md_files = filter_markdown_files(sorted(full_path.rglob("*.md")), ignore_patterns)
                if md_files:
                    projects.append((mapped_path, full_path, md_files, False))
        else:
            # No filtering - use old discovery logic for backward compatibility
            # Include Markdown files directly under the source root as a pseudo-project
            ignore_patterns = mapping.get_ignore_patterns()
            root_md_files = filter_markdown_files(sorted(source_dir.glob("*.md")), ignore_patterns)
            if root_md_files:
                projects.append((source_dir.name, source_dir, root_md_files, True))

            # Include child directories as projects, and go one level deeper
            project_dirs = [p for p in source_dir.iterdir() if p.is_dir()]
            for project_dir in sorted(project_dirs, key=lambda p: p.name):
                # Process markdown files directly under project_dir as a project
                direct_md_files = filter_markdown_files(sorted(project_dir.glob("*.md")), ignore_patterns)
                if direct_md_files:
                    try:
                        project_name = project_dir.relative_to(workspace_root).as_posix()
                    except ValueError:
                        project_name = project_dir.relative_to(source_dir.parent).as_posix()
                    projects.append((project_name, project_dir, direct_md_files, False))

                # Now, for each immediate subdirectory, treat as subproject
                subproject_dirs = [sp for sp in project_dir.iterdir() if sp.is_dir()]
                for subproject_dir in sorted(subproject_dirs, key=lambda p: p.name):
                    sub_md_files = filter_markdown_files(sorted(subproject_dir.rglob("*.md")), ignore_patterns)
                    if sub_md_files:
                        try:
                            subproject_name = subproject_dir.relative_to(workspace_root).as_posix()
                        except ValueError:
                            subproject_name = subproject_dir.relative_to(source_dir.parent).as_posix()
                        projects.append((subproject_name, subproject_dir, sub_md_files, False))

        if not projects:
            continue

        project_outputs: Dict[str, str] = {}
        project_entries_map: Dict[str, list[IndexEntry]] = {}
        root_projects: set[str] = set()
        for project_name, project_dir, md_files, is_root in projects:
            project_outputs[project_name], project_entries_map[project_name] = build_project_output(project_dir, project_name, md_files, fence_types=fence_types)
            if is_root:
                root_projects.add(project_name)

        # Output root: strip .opencrane/sources/ prefix so output paths are clean
        # e.g., .opencrane/sources/MicrosoftDocs → .opencrane/llmstxt/MicrosoftDocs
        sources_base = Path.cwd() / ".opencrane" / "sources"
        try:
            source_rel = source_dir.relative_to(sources_base)
        except ValueError:
            # source_dir not under .opencrane/sources/ (explicit --sources-dir or tests)
            try:
                source_rel = source_dir.relative_to(Path.cwd())
            except ValueError:  # pragma: no cover
                source_rel = Path(source_dir.name)
        output_root = LLMSTXT_BASE / source_rel

        # Strip source_dir prefix from project names for output paths
        # since output_root already includes it
        output_mapping: Dict[str, str] = {}
        output_entries: Dict[str, list[IndexEntry]] = {}
        source_prefix = f"{source_rel.as_posix()}/"

        for project_name, content in project_outputs.items():
            # Remove source directory prefix if present
            output_name = project_name
            if project_name.startswith(source_prefix):
                output_name = project_name[len(source_prefix):]
            output_mapping[output_name] = content
            output_entries[output_name] = project_entries_map.get(project_name, [])
            # Mark the top-level subdir this bundle lives under as covered so the
            # pre-existing llmstxt sweep below does not re-append it.
            loop_covered.add((source_rel / output_name).parts[0])

        write_outputs(output_mapping, output_root, root_projects, project_entries=output_entries)

        # Record this source_dir's combined content (mirrors write_outputs'
        # combined section) for the single authoritative top-level assembly.
        # Projects are joined with ====== so each carries its own block, matching
        # its ## {source} index section (see write_outputs for the rationale).
        loop_contributions.append(
            (source_dir.as_posix(), "\n\n======\n\n".join(output_mapping.values()))
        )
        # Accumulate per-project entries for the top-level llms.txt, tagged with
        # source_dir.as_posix() so the final sort order matches loop_contributions.
        for output_name in output_mapping:
            loop_entry_sections.append((source_dir.as_posix(), output_name, output_entries.get(output_name, [])))

    # Top-level combined output used by setup.sh (llmstxt/llms-full.txt)
    # When there's a single source_dir that maps to output_root == LLMSTXT_BASE,
    # write_outputs already wrote the combined file directly to LLMSTXT_BASE/llms-full.txt.
    # Skip the combiner to avoid duplicating content.
    # This covers two cases:
    #   1. source_dirs[0] == .opencrane/sources (remote sources fetched to sources_base)
    #   2. source_dirs[0] == workspace_root (local sources, source_rel resolves to '.')
    sources_base = Path.cwd() / ".opencrane" / "sources"
    single_source_is_base = len(source_dirs) == 1 and (
        source_dirs[0].resolve() == sources_base.resolve()
        or source_dirs[0].resolve() == Path.cwd().resolve()
    )

    if single_source_is_base:
        # write_outputs already produced the correct combined file — just
        # pick up any pre-existing llmstxt sources not covered by mapping.
        covered_subdirs: set[str] = set()
        combined_parts: List[str] = []
        # The combined file already exists; read it so we can append extras
        top_llms = LLMSTXT_BASE / "llms-full.txt"
        if top_llms.exists():
            combined_parts.append(top_llms.read_text(encoding="utf-8"))
            # Mark all project subdirs as covered
            for sd in LLMSTXT_BASE.iterdir():
                if sd.is_dir():
                    covered_subdirs.add(sd.name)
        # In single_source_is_base the per-source llms.txt was already written
        # by write_outputs (to the same output_root == LLMSTXT_BASE). Seed
        # top_entry_sections from that existing index so any external blocks
        # appended below can extend it — keeping section count == block count.
        top_entry_sections: List[tuple[str, list[IndexEntry]]] = []
        top_llms_index = LLMSTXT_BASE / "llms.txt"
        if top_llms_index.exists():
            existing_index = LlmsIndex.parse(top_llms_index.read_text(encoding="utf-8"))
            top_entry_sections = [
                (src, existing_index.entries_for(src))
                for src in existing_index.sources()
            ]
    else:
        # Assemble the top-level combined from the per-source contributions
        # captured during processing — each source_dir exactly once. Building
        # from the in-memory contributions (rather than re-reading the top-level
        # file) is what prevents overlapping roots, both of which resolve to a
        # '.' source_rel and write the same llms-full.txt, from doubling content.
        combined_parts = [
            content for _, content in sorted(loop_contributions, key=lambda c: c[0])
        ]
        covered_subdirs = set(loop_covered)
        # Sort by the same key (source_dir.as_posix()) used for combined_parts so
        # the Nth ## section in llms.txt corresponds to the Nth block in llms-full.txt.
        top_entry_sections = [
            (output_name, entries)
            for _, output_name, entries in sorted(loop_entry_sections, key=lambda e: e[0])
        ]

    # Include pre-existing llmstxt sources (e.g., added via `opencrane add` with
    # type: llmstxt) that weren't already covered by source-dir processing above.
    # For every external ====== block appended here, build one matching
    # ## {source} index section (in the SAME order) so the chunker's count-based
    # block/section alignment always holds: companion llms.txt → real per-page
    # URLs; no companion → synthesized H1 entries carrying the base docs_url.
    appended_external = False
    if LLMSTXT_BASE.exists():
        mapped_paths = get_source_mapping().data.get("sources", {})
        for subdir in sorted(LLMSTXT_BASE.iterdir()):
            if not subdir.is_dir():
                continue
            if subdir.name in covered_subdirs:
                continue
            llms_file = subdir / "llms-full.txt"
            if not llms_file.exists():
                continue
            content = llms_file.read_text(encoding="utf-8")
            combined_parts.append(content)
            top_entry_sections.append(_external_index_section(subdir, content, mapped_paths))
            appended_external = True

    if combined_parts:
        LLMSTXT_BASE.mkdir(parents=True, exist_ok=True)
        (LLMSTXT_BASE / "llms-full.txt").write_text("\n\n======\n\n".join(combined_parts), encoding="utf-8")
        # Write the top-level llms.txt index. In single_source_is_base,
        # write_outputs already wrote a base index; only rewrite here when
        # external blocks were appended (so section count == block count).
        # In the multi-source case, top_entry_sections is always authoritative.
        if top_entry_sections and (not single_source_is_base or appended_external):
            index_content = render_llms_txt("Documentation", top_entry_sections)
            (LLMSTXT_BASE / "llms.txt").write_text(index_content, encoding="utf-8")


# IMPORTANT: This block is required for setup.sh to work properly.
# setup.sh calls `python3 src/generate_llms_txt.py` directly, which executes this block.
# Do not remove without updating setup.sh accordingly.
if __name__ == "__main__":  # pragma: no cover
    generate_outputs()
