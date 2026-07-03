from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class IndexEntry:
    """One entry in a generated llms.txt index: a page title and its URL."""
    source: str
    title: str
    url: str


_H1_RE = re.compile(r'^#\s+(.*)$')
_H2_RE = re.compile(r'^##\s+(.*)$')
_LINK_RE = re.compile(r'^-\s*\[(?P<title>.*?)\]\((?P<url>[^)]+)\)\s*$')


def _norm_title(title: str) -> str:
    """Case-insensitive, whitespace-normalized title key for matching."""
    return ' '.join(title.split()).lower()


class LlmsIndex:
    """Parsed ``llms.txt`` index used to join clean content back to page URLs.

    The index is a list of :class:`IndexEntry` objects in file order, grouped
    into source sections (``## {source}`` headings).  Links that appear before
    any ``##`` heading are assigned to the ``""`` (empty) section.
    """

    def __init__(self, entries: list[IndexEntry]):
        self._entries = list(entries)

    @classmethod
    def parse(cls, text: str) -> "LlmsIndex":
        """Parse ``#``/``##``/``- [title](url)`` lines preserving order + section."""
        entries: list[IndexEntry] = []
        current_source = ""
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            h2 = _H2_RE.match(line)
            if h2:
                current_source = h2.group(1).strip()
                continue
            # Skip the top-level project ``# {title}`` heading (but not ``##``).
            if _H1_RE.match(line) and not line.startswith('##'):
                continue
            link = _LINK_RE.match(line)
            if link:
                entries.append(IndexEntry(
                    source=current_source,
                    title=link.group('title').strip(),
                    url=link.group('url').strip(),
                ))
        return cls(entries)

    def sources(self) -> list[str]:
        """Ordered distinct source-section names."""
        seen: list[str] = []
        for entry in self._entries:
            if entry.source not in seen:
                seen.append(entry.source)
        return seen

    def entries_for(self, source: str) -> list[IndexEntry]:
        """That section's entries in order."""
        return [e for e in self._entries if e.source == source]

    def match_page(self, source: str, page_title: str, cursor: int) -> tuple[str | None, int]:
        """Positional, title-validated join within a source section.

        Starting at ``cursor`` in :meth:`entries_for`: if the entry at
        ``cursor`` matches ``page_title`` (case-insensitive, whitespace
        normalized), return ``(url, cursor + 1)``.  Otherwise scan ahead within
        the section for a title match and return ``(url, matched_index + 1)``.
        If no match is found, return ``(None, cursor)`` (cursor unchanged).
        """
        entries = self.entries_for(source)
        target = _norm_title(page_title)
        if 0 <= cursor < len(entries) and _norm_title(entries[cursor].title) == target:
            return entries[cursor].url, cursor + 1
        for i in range(max(cursor, 0), len(entries)):
            if _norm_title(entries[i].title) == target:
                return entries[i].url, i + 1
        return None, cursor


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
