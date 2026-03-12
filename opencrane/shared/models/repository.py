from dataclasses import dataclass
from typing import List


@dataclass
class Repository:
    """Represents a GitHub repository."""
    name: str
    topics: List[str]
    has_docs_directory: bool = False

    @property
    def has_documentation_topic(self) -> bool:
        """Check if repository has documentation topic."""
        return "documentation" in self.topics