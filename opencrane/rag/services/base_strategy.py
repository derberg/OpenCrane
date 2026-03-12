"""Base strategy interface for processing different content types."""

from abc import ABC, abstractmethod
from typing import List
from pathlib import Path
from opencrane.shared.models.chunk import Chunk


class ProcessingStrategy(ABC):
    """Abstract base class for content processing strategies."""

    @abstractmethod
    def can_process(self, node) -> bool:
        """Check if this strategy can process the given node.

        Args:
            node: Docling document node.

        Returns:
            True if this strategy can handle the node.
        """
        pass  # pragma: no cover

    @abstractmethod
    def process(self, node, source_file: Path) -> List[Chunk]:
        """Process a node into chunks.

        Args:
            node: Docling document node.
            source_file: Path to the source file.

        Returns:
            List of Chunk objects.
        """
        pass  # pragma: no cover