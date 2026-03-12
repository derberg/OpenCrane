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

from opencrane.rag.services.source_mapping import SourceMapping
from opencrane.shared.config import get_config
from opencrane.shared.utils.git import has_changes

# Path: src/rag/generate_llms_txt.py -> parent.parent.parent = project root
ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES_BASE = ROOT
LLMSTXT_BASE = ROOT / ".opencrane" / "llmstxt"
# Legacy paths for tests/backward compatibility
SOURCE_ROOT = SOURCES_BASE
OUTPUT_ROOT = LLMSTXT_BASE

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


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


def is_in_devel_folder(file_path: Path) -> bool:
    """Check if a file is within a 'devel' directory at any level."""
    return "devel" in file_path.parts


def filter_markdown_files(files: Iterable[Path]) -> List[Path]:
    """Filter out markdown files that are in 'devel' folders."""
    return [f for f in files if not is_in_devel_folder(f)]


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


def get_github_url(rel_with_project: Path, project_name: str) -> str | None:
    """Return the source URL for a given file path and project name.

    Prefers ``docs_url`` from the source mapping when set (useful for non-GitHub
    or published docs sites). Falls back to building a GitHub blob URL from
    ``github_url``. Returns ``None`` when no mapping entry is found — callers
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
        return f"{docs_url.rstrip('/')}/{file_rel}"

    # Fall back to GitHub blob URL
    github_url = source.get("github_url", "")
    if not github_url:
        return None

    if docs_path:
        docs_prefix = f"{docs_path.rstrip('/')}/"
        file_rel = relative_after_key
        if file_rel.startswith(docs_prefix):
            file_rel = file_rel[len(docs_prefix):]
        return f"{github_url}/blob/main/{docs_path.rstrip('/')}/{file_rel}"

    return f"{github_url}/blob/main/{rel_str}"


def prefix_headings_with_path(content: str, rel_with_project: Path, project_name: str) -> str:
    """Prefix headings with GitHub source URL for traceability in llms-full.txt files.
    
    The chunker will extract clean titles from these prefixed headings,
    but keeping URLs in llms-full.txt is useful for humans reading the files directly.
    """
    output: List[str] = []
    gh_url = get_github_url(rel_with_project, project_name)

    for line in content.splitlines():
        heading_match = HEADING_RE.match(line)
        if heading_match:
            hashes, heading_text = heading_match.groups()
            heading_text = heading_text.strip()
            if gh_url:
                output.append(f"{hashes} {gh_url} {heading_text}")
            else:
                output.append(f"{hashes} {heading_text}")
        else:
            output.append(line)

    return "\n".join(output)


def process_file(file_path: Path, project_dir: Path, project_name: str) -> str:
    rel_with_project = Path(project_name) / file_path.relative_to(project_dir)

    raw_text = file_path.read_text(encoding="utf-8")
    text_no_images = strip_images(raw_text)
    text_relinked = rewrite_links(text_no_images, file_path, rel_with_project, project_dir, project_name)
    text_with_prefixed_headings = prefix_headings_with_path(text_relinked, rel_with_project, project_name)

    gh_url = get_github_url(rel_with_project, project_name)

    output_lines = []
    if gh_url:
        output_lines.append(f"### {gh_url}")  # clickable source link
    output_lines.append(text_with_prefixed_headings)
    return "\n\n".join(output_lines)



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


def build_project_output(project_dir: Path, project_name: str | None = None, md_files: List[Path] | None = None, fence_types: Dict[str, "CodeFenceConfig"] | None = None) -> str:
    """Build combined output for a project.

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

    for md_file in md_files:
        processed = process_file(md_file, project_dir, project_name)
        processed = process_fence_blocks(processed, md_file, project_dir, project_name, fence_types=fence_types)
        sections.append(processed)

    return "\n\n-----\n\n".join(sections)


def write_outputs(project_outputs: Dict[str, str], output_root: Path = OUTPUT_ROOT, root_projects: set[str] | None = None) -> None:
    root_projects = root_projects or set()
    output_root.mkdir(parents=True, exist_ok=True)

    # Per-project outputs
    for project, content in project_outputs.items():
        if project in root_projects:
            continue  # Root-level markdown lives only in the combined output
        target_dir = output_root / project
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "llms-full.txt").write_text(content, encoding="utf-8")

    # Combined output - just concatenate project contents without metadata headers
    combined_sections = []
    for project, content in project_outputs.items():
        combined_sections.append(content)

    (output_root / "llms-full.txt").write_text("\n\n".join(combined_sections), encoding="utf-8")


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

    # CLI params take precedence over env vars
    sources_override = os.environ.get("AI_DOCS_SOURCES_DIR")
    sources_dirs_override = ",".join(str(p) for p in sources_dirs) if sources_dirs else os.environ.get("AI_DOCS_SOURCES_DIRS")
    llmstxt_override = str(llmstxt_dir) if llmstxt_dir else os.environ.get("AI_DOCS_LLMSTXT_DIR")

    if sources_override:
        SOURCES_BASE = Path(sources_override)
        # Keep legacy constant in sync for tests/backward compatibility
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
        for project_dir in sorted(project_dirs, key=lambda p: p.name):
            md_files = filter_markdown_files(sorted(project_dir.rglob("*.md")))
            if not md_files:
                continue  # pragma: no cover
            project_outputs[project_dir.name] = build_project_output(project_dir, project_dir.name, md_files, fence_types=fence_types)

        output_root = OUTPUT_ROOT
        root_projects: set[str] = set()
        write_outputs(project_outputs, output_root, root_projects)
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
            print("⊘ Skipping llms-full.txt generation: no sources in mapping file and AI_DOCS_SOURCES_DIRS not set")
            return
        workspace_root = Path.cwd()
        top_level_dirs = {Path(k).parts[0] for k in sources.keys() if Path(k).parts}
        source_dirs = sorted(
            [workspace_root / d for d in top_level_dirs if (workspace_root / d).exists()],
            key=lambda p: p.name,
        )
        if not source_dirs:
            print("⊘ Skipping llms-full.txt generation: no source directories found from mapping file")
            return
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
            for mapped_path in sorted(mapped_paths.keys()):
                full_path = workspace_root / mapped_path
                if not full_path.exists() or not full_path.is_dir():  # pragma: no cover
                    continue
                
                # Only process if this path is under the current source_dir
                try:
                    full_path.relative_to(source_dir)
                except ValueError:  # pragma: no cover
                    # This mapped path is not under current source_dir, skip it
                    continue
                
                # Collect ALL markdown files recursively (excluding devel folders)
                md_files = filter_markdown_files(sorted(full_path.rglob("*.md")))
                if md_files:
                    projects.append((mapped_path, full_path, md_files, False))
        else:
            # No filtering - use old discovery logic for backward compatibility
            # Include Markdown files directly under the source root as a pseudo-project
            root_md_files = filter_markdown_files(sorted(source_dir.glob("*.md")))
            if root_md_files:
                projects.append((source_dir.name, source_dir, root_md_files, True))

            # Include child directories as projects, and go one level deeper
            project_dirs = [p for p in source_dir.iterdir() if p.is_dir()]
            for project_dir in sorted(project_dirs, key=lambda p: p.name):
                # Process markdown files directly under project_dir as a project
                direct_md_files = filter_markdown_files(sorted(project_dir.glob("*.md")))
                if direct_md_files:
                    try:
                        project_name = project_dir.relative_to(workspace_root).as_posix()
                    except ValueError:
                        project_name = project_dir.relative_to(source_dir.parent).as_posix()
                    projects.append((project_name, project_dir, direct_md_files, False))

                # Now, for each immediate subdirectory, treat as subproject
                subproject_dirs = [sp for sp in project_dir.iterdir() if sp.is_dir()]
                for subproject_dir in sorted(subproject_dirs, key=lambda p: p.name):
                    sub_md_files = filter_markdown_files(sorted(subproject_dir.rglob("*.md")))
                    if sub_md_files:
                        try:
                            subproject_name = subproject_dir.relative_to(workspace_root).as_posix()
                        except ValueError:
                            subproject_name = subproject_dir.relative_to(source_dir.parent).as_posix()
                        projects.append((subproject_name, subproject_dir, sub_md_files, False))

        if not projects:
            continue

        project_outputs: Dict[str, str] = {}
        root_projects: set[str] = set()
        for project_name, project_dir, md_files, is_root in projects:
            project_outputs[project_name] = build_project_output(project_dir, project_name, md_files, fence_types=fence_types)
            if is_root:
                root_projects.add(project_name)

        # Output root mirrors source path (relative if possible, otherwise as-is)
        try:
            source_rel = source_dir.relative_to(Path.cwd())
            output_root = LLMSTXT_BASE / source_rel
        except ValueError:  # pragma: no cover
            # source_dir not under cwd (e.g., tests with temp dirs) - use just the name
            output_root = LLMSTXT_BASE / source_dir.name
        
        # Strip source_dir prefix from project names for output paths
        # since output_root already includes it
        output_mapping = {}
        # Get source path for comparison (relative if possible)
        try:
            source_rel = source_dir.relative_to(Path.cwd())
            source_prefix = f"{source_rel.as_posix()}/"
        except ValueError:  # pragma: no cover
            source_prefix = f"{source_dir.name}/"
        
        for project_name, content in project_outputs.items():
            # Remove source directory prefix if present
            output_name = project_name
            if project_name.startswith(source_prefix):
                output_name = project_name[len(source_prefix):]
            output_mapping[output_name] = content
        
        write_outputs(output_mapping, output_root, root_projects)

    # Top-level combined output used by setup.sh (llmstxt/llms-full.txt)
    # Keep the format consistent with per-source outputs: a sequence of "# Project:" blocks.
    combined_parts: List[str] = []
    for source_dir in sorted(source_dirs, key=lambda p: p.as_posix()):
        # Get source path relative to cwd for output location
        try:
            source_rel = source_dir.relative_to(Path.cwd())
            source_llms = (LLMSTXT_BASE / source_rel / "llms-full.txt")
        except ValueError:  # pragma: no cover
            source_llms = (LLMSTXT_BASE / source_dir.name / "llms-full.txt")
        
        if source_llms.exists():
            combined_parts.append(source_llms.read_text(encoding="utf-8"))

    if combined_parts:
        LLMSTXT_BASE.mkdir(parents=True, exist_ok=True)
        (LLMSTXT_BASE / "llms-full.txt").write_text("\n\n======\n\n".join(combined_parts), encoding="utf-8")


# IMPORTANT: This block is required for setup.sh to work properly.
# setup.sh calls `python3 src/generate_llms_txt.py` directly, which executes this block.
# Do not remove without updating setup.sh accordingly.
if __name__ == "__main__":  # pragma: no cover
    generate_outputs()
