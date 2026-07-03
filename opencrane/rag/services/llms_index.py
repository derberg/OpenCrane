from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexEntry:
    """One entry in a generated llms.txt index: a page title and its URL."""
    source: str
    title: str
    url: str


def render_llms_txt(project_title: str, sections: list[tuple[str, list[IndexEntry]]]) -> str:
    """Render a standard llms.txt index file.

    Format:
        # {project_title}

        ## {source_name}
        - [{title}]({url})
        ...

    Sections with an empty entry list are skipped.
    """
    lines: list[str] = [f"# {project_title}"]
    for source_name, entries in sections:
        if not entries:
            continue
        lines.append("")
        lines.append(f"## {source_name}")
        for entry in entries:
            lines.append(f"- [{entry.title}]({entry.url})")
    return "\n".join(lines)
