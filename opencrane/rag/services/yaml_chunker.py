"""YAML chunking strategy for CRD and configuration content."""

import yaml
import logging
from typing import List, Dict, Any
from pathlib import Path
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.shared.models.chunk import Chunk
from opencrane.shared.utils.token_counter import get_token_count
from opencrane.shared.utils.metadata_helpers import extract_crd_identity, is_openapi_spec, extract_openapi_metadata, is_json_schema
from opencrane.shared.config import get_config

logger = logging.getLogger(__name__)


def _is_k8s_crd(doc: Dict[str, Any]) -> bool:
    """Check if document is a K8s CRD (CustomResourceDefinition)."""
    return (
        doc.get("apiVersion", "").startswith("apiextensions.k8s.io/") and
        doc.get("kind") == "CustomResourceDefinition"
    )


def _has_yaml_tree_chunking_support(doc: Dict[str, Any]) -> bool:
    """Check if document type is supported by tree walkers."""
    return _is_k8s_crd(doc) or is_openapi_spec(doc) or is_json_schema(doc)


class YamlChunkingStrategy(ProcessingStrategy):
    """Strategy for processing YAML/CRD content with intelligent splitting."""

    def __init__(self, yaml_tree_walkers=None):
        """Initialize YamlChunkingStrategy.

        Args:
            yaml_tree_walkers: Optional list of walker classes to use.  When
                None, falls back to the built-in defaults (K8sCRD, OpenAPI,
                JsonSchema) so existing call-sites keep working unchanged.
        """
        if yaml_tree_walkers is None:
            from opencrane.rag.services.chunking_strategies.k8s_crd_tree_walker import K8sCRDTreeWalker
            from opencrane.rag.services.chunking_strategies.openapi_tree_walker import OpenAPITreeWalker
            from opencrane.rag.services.chunking_strategies.json_schema_tree_walker import JsonSchemaTreeWalker
            self.yaml_tree_walkers = [K8sCRDTreeWalker, OpenAPITreeWalker, JsonSchemaTreeWalker]
        else:
            self.yaml_tree_walkers = yaml_tree_walkers

    def can_process(self, node) -> bool:
        """Check if node contains YAML content (excludes front matter)."""
        if not hasattr(node, 'text'):
            return False
        text = node.text.strip()

        # Skip YAML front matter — flat key: value metadata blocks
        if self._is_front_matter(text):
            return False

        # Strong indicators of YAML
        if text.startswith('---') or text.startswith('apiVersion:') or text.startswith('kind:'):
            return True

        # Check for key: value patterns typical of YAML, but exclude prose
        # YAML typically has keys at line starts with colons
        lines = text.split('\n')[:10]  # Check first 10 lines
        yaml_like_lines = 0
        for line in lines:
            stripped = line.strip()
            # Skip empty lines and comments
            if not stripped or stripped.startswith('#'):
                continue
            # Check if line matches key: value pattern (key at start, colon, space/value)
            if ':' in stripped and not stripped.startswith('#'):
                # Split at first colon
                parts = stripped.split(':', 1)
                key = parts[0].strip()
                # Valid YAML key should be a single word or have quotes
                # Avoid matching prose like "text text: more text" or URLs
                if (len(key.split()) <= 2 and
                    not key.endswith(')') and
                    not '/' in key and
                    not '.' in key[-5:]):  # Avoid URLs and sentences
                    yaml_like_lines += 1

        # If we have multiple YAML-like lines, it's probably YAML
        return yaml_like_lines >= 2

    @staticmethod
    def _is_front_matter(text: str) -> bool:
        """Detect YAML front matter — flat key: scalar metadata blocks.

        Front matter is typically document metadata (title, author, date, etc.)
        with only flat key-value pairs and no nested structures.  We parse it
        as YAML and reject anything with non-scalar values or domain-specific
        keys like ``apiVersion`` / ``kind``.
        """
        import yaml as _yaml

        # Strip leading --- delimiter if present
        body = text.lstrip('-').strip() if text.startswith('---') else text.strip()
        if not body:
            return False

        try:
            parsed = _yaml.safe_load(body)
        except _yaml.YAMLError:
            return False

        if not isinstance(parsed, dict):
            return False

        # Domain YAML keys → not front matter
        if parsed.get("apiVersion") or parsed.get("kind") or parsed.get("openapi"):
            return False

        # Every value must be a scalar (str, int, float, bool, None) — no lists or dicts
        for value in parsed.values():
            if isinstance(value, (dict, list)):
                return False

        return True

    def process(self, node, source_file: Path) -> List[Chunk]:
        """Process YAML node into chunks.
        
        Args:
            node: Docling document node to process.
            source_file: Path to source file.
        """
        config = get_config()
        chunks = []

        candidate_source_url = getattr(node, 'source_url', None)
        base_source_url = candidate_source_url if isinstance(candidate_source_url, str) else None

        text = node.text.strip()
        
        # Strip markdown fenced code block markers if present
        # This handles YAML embedded in markdown (e.g., in llms-full.txt)
        if text.startswith('```'):
            lines = text.split('\n')
            # Remove first line (```yaml or ```) and last line (```)
            if lines[-1].strip() == '```':
                lines = lines[1:-1]
            else:
                lines = lines[1:]  # Only remove opening fence
            text = '\n'.join(lines).strip()
        
        try:
            # Parse YAML - handle multi-doc
            data = list(yaml.safe_load_all(text))
            if not data:
                return []
        except yaml.YAMLError as e:
            logger.debug(f"Failed to parse YAML: {e}")
            return []

        for doc in data:
            if not isinstance(doc, dict):  # pragma: no cover
                logger.debug(f"Skipping non-dict YAML document: {type(doc).__name__}")
                continue
            
            # If tree chunking is enabled and this is a supported type, use tree walkers
            if config.yaml_tree_chunking_enabled and self._has_yaml_tree_chunking_support(doc):
                logger.debug(f"Using tree walker for {source_file}")
                tree_chunks = self._process_with_tree_walker(doc, source_file, base_source_url)
                chunks.extend(tree_chunks)
            else:
                # Fall back to legacy processing
                doc_chunks = self._process_yaml_doc(doc, source_file, config, base_source_url)
                chunks.extend(doc_chunks)

        return chunks

    def _has_yaml_tree_chunking_support(self, doc: Dict[str, Any]) -> bool:
        """Check if document type is supported by any configured tree walker."""
        return any(walker_cls.can_handle(doc) for walker_cls in self.yaml_tree_walkers)

    def _process_with_tree_walker(self, doc: Dict[str, Any], source_file: Path, base_source_url: str | None) -> List[Chunk]:
        """Process YAML using tree walkers for rich metadata.

        Iterates through the configured walker classes, instantiates the first
        one whose ``can_handle`` classmethod returns True, and invokes its
        ``walk`` method.

        Args:
            doc: Parsed YAML document.
            source_file: Path to source file.
            base_source_url: Optional source URL.
        """
        source_url = base_source_url or str(source_file)
        for walker_cls in self.yaml_tree_walkers:
            if walker_cls.can_handle(doc):
                walker = walker_cls(
                    yaml_dict=doc,
                    source_url=source_url,
                    source_file=source_file
                )
                return walker.walk()
        return []  # No walker matched

    def _process_yaml_doc(self, doc: Dict[str, Any], source_file: Path, config, base_source_url: str | None = None) -> List[Chunk]:
        """Process a single YAML document (legacy fallback for non-CRD/OpenAPI).
        
        Args:
            doc: Parsed YAML document.
            source_file: Path to source file.
            config: Configuration object.
            base_source_url: Optional source URL.
        """
        text = yaml.dump(doc, default_flow_style=False, sort_keys=False)
        token_count = get_token_count(text)
        
        # For non-tree-walker YAML, use yaml_content type
        # This avoids validation errors for missing tree metadata
        metadata = {}
        source_url = self._extract_source_url(text) or base_source_url
        if source_url:
            metadata["source_url"] = source_url
        
        # Check if this looks like a CRD (but not a full K8s CRD definition)
        identity = extract_crd_identity(doc)
        if identity:
            metadata["root_identity"] = identity.model_dump()
        
        # Generate deterministic chunk ID based on content
        from .utils.chunk_id_generator import generate_unique_chunk_id
        chunk_id = generate_unique_chunk_id(
            content=text,
            source_file=str(source_file),
            chunk_type="yaml_content",
            metadata=metadata
        )

        chunk = Chunk(
            chunk_id=chunk_id,
            content=text,
            source_file=str(source_file),
            chunk_type="yaml_content",  # Use generic type for non-tree-walker YAML
            metadata=metadata,
            token_count=token_count,
        )
        return [chunk]

    @staticmethod
    def _extract_source_url(text: str) -> str | None:
        import re
        match = re.search(r'https://github\.com/[^\s\]]+', text)
        return match.group(0) if match else None