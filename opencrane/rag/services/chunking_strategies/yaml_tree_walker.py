"""Base class for YAML tree walking strategies."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any
import uuid
from datetime import datetime, date
from opencrane.shared.models.chunk import Chunk
import yaml


# Token thresholds for granular chunking
MIN_CHUNK_TOKEN_TARGET = 300  # Ideal chunk size target
MAX_CHUNK_TOKEN_LIMIT = 800   # If exceeded AND has nested structure, split recursively


class YamlTreeWalker(ABC):
    """Abstract base class for type-specific YAML tree walkers.

    Subclasses implement schema-specific chunking logic for:
    - Kubernetes CRDs (K8sCRDTreeWalker)
    - OpenAPI specs (OpenAPITreeWalker)
    - JSON Schema (JsonSchemaTreeWalker)
    """

    def __init__(self, yaml_dict: Dict[str, Any], source_url: str, source_file = None, original_yaml_file: str | None = None):
        """Initialize tree walker.

        Args:
            yaml_dict: Parsed YAML as Python dict
            source_url: GitHub URL of the markdown page
            source_file: Local file path (Path object or str)
            original_yaml_file: Optional original YAML file path
        """
        self.yaml_dict = yaml_dict
        self.source_url = source_url
        self.source_file = str(source_file) if source_file else None
        self.original_yaml_file = original_yaml_file
        self.chunks: List[Chunk] = []
    
    @staticmethod
    def _sanitize_yaml_content(content: Any) -> Any:
        """Sanitize YAML content for JSON serialization.
        
        Converts datetime objects to ISO format strings to prevent
        JSON serialization errors.
        
        Args:
            content: YAML content (dict, list, or primitive)
            
        Returns:
            Sanitized content with datetime objects converted to strings
        """
        if isinstance(content, (datetime, date)):
            return content.isoformat()
        elif isinstance(content, dict):
            return {k: YamlTreeWalker._sanitize_yaml_content(v) for k, v in content.items()}
        elif isinstance(content, list):
            return [YamlTreeWalker._sanitize_yaml_content(item) for item in content]
        else:
            return content
    
    @classmethod
    @abstractmethod
    def can_handle(cls, doc: dict) -> bool:
        """Return True if this walker can process the given YAML document.

        Subclasses must implement this classmethod so the pipeline can select
        the appropriate walker without pre-instantiating it.

        Args:
            doc: Parsed YAML document as a Python dict.

        Returns:
            True if this walker handles the document, False otherwise.
        """
        pass  # pragma: no cover

    @abstractmethod
    def walk(self) -> List[Chunk]:
        """Walk YAML tree and generate chunks.

        Returns:
            List of Chunk objects with dict content and metadata
        """
        pass  # pragma: no cover
    
    def _generate_breadcrumb(self, path: List[str]) -> str:
        """Generate dot-notation path for breadcrumb.
        
        Args:
            path: List of keys representing tree path
            
        Returns:
            Dot-separated path string (e.g., "paths./users.post")
        """
        return ".".join(path)
    
    def _identify_neighbors(self, parent_node: Dict[str, Any], current_key: str) -> List[str]:
        """Identify sibling chunk UUIDs at the same tree level.
        
        This is a placeholder that returns empty list. Subclasses should override
        after chunks are created and UUIDs assigned.
        
        Args:
            parent_node: Parent dict containing siblings
            current_key: Key of the current node
            
        Returns:
            List of sibling chunk UUIDs (empty in base implementation)
        """
        return []  # pragma: no cover
    
    def _generate_chunk_id(self, content: Any, chunk_type: str, metadata: Dict[str, Any], source_file: str) -> str:
        """Generate deterministic chunk ID based on content.

        Args:
            content: The chunk content
            chunk_type: Type of chunk being created
            metadata: Chunk metadata for uniqueness
            source_file: Source file path

        Returns:
            Deterministic hash-based ID
        """
        from ..utils.chunk_id_generator import generate_unique_chunk_id
        return generate_unique_chunk_id(
            content=content,
            source_file=source_file,
            chunk_type=chunk_type,
            metadata=metadata
        )

    def _calculate_token_count(self, content: Any) -> int:
        """Calculate token count for content.

        Args:
            content: Content to calculate tokens for (dict, list, or str)

        Returns:
            Token count
        """
        from opencrane.shared.utils.token_counter import get_token_count

        if isinstance(content, str):  # pragma: no cover
            return get_token_count(content)
        else:
            # Convert dict/list to YAML for token counting
            yaml_str = yaml.dump(content, default_flow_style=False, allow_unicode=True)
            return get_token_count(yaml_str)

    def _should_chunk_recursively(self, content: Dict[str, Any], token_count: int) -> bool:
        """Determine if content should be chunked recursively.

        Returns True if:
        - Token count exceeds MAX_CHUNK_TOKEN_LIMIT
        - Content has nested structure that can be chunked (properties, items, schemas)

        Args:
            content: Schema content to evaluate
            token_count: Calculated token count for content

        Returns:
            True if should recurse, False otherwise
        """
        if token_count <= MAX_CHUNK_TOKEN_LIMIT:
            return False

        if not isinstance(content, dict):  # pragma: no cover
            return False

        # Check for nested structure that can be chunked
        # Properties in objects
        if "properties" in content and isinstance(content["properties"], dict):
            if len(content["properties"]) > 0:
                return True

        # Items in arrays (if items is an object schema)
        if "items" in content and isinstance(content["items"], dict):
            return True

        # Composition keywords (allOf, oneOf, anyOf) with multiple schemas
        for keyword in ["allOf", "oneOf", "anyOf"]:  # pragma: no cover
            if keyword in content and isinstance(content[keyword], list):
                if len(content[keyword]) > 1:
                    return True

        return False

    def _has_nested_properties(self, content: Dict[str, Any]) -> bool:  # pragma: no cover
        """Check if content has nested properties that can be chunked.

        Args:
            content: Schema content to check

        Returns:
            True if has nested properties, False otherwise
        """
        if not isinstance(content, dict):
            return False

        return "properties" in content and isinstance(content["properties"], dict) and len(content["properties"]) > 0
