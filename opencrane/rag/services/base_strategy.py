"""Base strategy interface for processing different content types."""

from abc import ABC, abstractmethod
from typing import Dict, List, Tuple
from pathlib import Path
from opencrane.shared.models.chunk import Chunk


class ProcessingStrategy(ABC):
    """Abstract base class for content processing strategies."""

    # Tag names of the content blocks this strategy owns, such as
    # ("details",). The page splitter keeps each such block in one piece and
    # hands it to this strategy.
    block_tags: Tuple[str, ...] = ()

    # Metadata keys this strategy adds to prose chunks, mapped to a one-line
    # description. Prose chunks accept them next to the built-in keys, and
    # get_metadata_schema lists them for agents.
    metadata_keys: Dict[str, str] = {}

    def chunk_text(self, text: str, node, source_file: Path) -> List[Chunk]:
        """Chunk ``text`` from inside ``node`` the way OpenCrane chunks a page.

        A strategy that owns a block calls this with text it cut out of the
        block, such as the body of one tab. The text goes through every
        configured strategy, so lists, tables and code inside it get their
        own chunks, and they keep the headings above the block.

        Raises:
            RuntimeError: when ``node`` does not come from FileProcessor.
        """
        run = getattr(node, "chunk_text", None)
        if run is None:
            raise RuntimeError("chunk_text needs a node that FileProcessor created")
        return run(text, source_file)

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