"""Public API for OpenCrane fence type configuration."""

from pathlib import Path

from opencrane.rag.generate_llms_txt import CodeFenceConfig, get_source_url


def inline_file(content: str, file_path: Path, project_dir: Path, project_name: str) -> str:
    """Fence handler that resolves a relative file path and inlines its content.

    Intended for use with ``openapi``, ``asyncapi``, ``crd``, and ``json-schema``
    fence types. The fence block content must be a path to a file, relative to the
    markdown file that contains the fence.

    Returns a ``### URL`` section marker (so the chunker assigns the correct
    source URL to resulting chunks) followed by the file content in a fenced
    code block. Falls back to a ``# Source missing`` comment when the file does
    not exist or references a path outside the project directory.
    """
    project_dir_resolved = project_dir.resolve()
    output_language = "json" if Path(content.strip()).suffix.lower() == ".json" else "yaml"

    try:
        target = (file_path.parent / content.strip()).resolve()
        target.relative_to(project_dir_resolved)
    except ValueError:
        return f"```{output_language}\n# Source missing: {content.strip()}\n```\n"

    if not target.exists():
        return f"```{output_language}\n# Source missing: {content.strip()}\n```\n"

    rel_with_project = Path(project_name) / target.relative_to(project_dir_resolved)
    source_url = get_source_url(rel_with_project, project_name)
    file_content = target.read_text(encoding="utf-8").rstrip("\n")

    header = f"### {source_url}\n\n" if source_url else ""
    return f"{header}```{output_language}\n{file_content}\n```\n"


__all__ = [
    "CodeFenceConfig",
    "get_source_url",
    "inline_file",
]
