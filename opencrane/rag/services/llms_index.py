from dataclasses import dataclass


@dataclass(frozen=True)
class IndexEntry:
    """One entry in a generated llms.txt index: a page title and its URL."""
    source: str
    title: str
    url: str
