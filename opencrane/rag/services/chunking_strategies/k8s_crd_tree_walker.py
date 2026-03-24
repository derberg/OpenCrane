"""K8s CRD tree walker for chunking Kubernetes Custom Resource Definitions."""

from typing import List, Dict, Any
from opencrane.rag.services.chunking_strategies.yaml_tree_walker import YamlTreeWalker
from opencrane.shared.models.chunk import Chunk
import yaml


class K8sCRDTreeWalker(YamlTreeWalker):
    """Walk Kubernetes CRD trees and generate property-based chunks."""
    
    def __init__(self, yaml_dict: Dict[str, Any], source_url: str, source_file = None, original_yaml_file: str | None = None):
        """Initialize K8s CRD tree walker.
        
        Args:
            yaml_dict: Parsed CRD spec as Python dict
            source_url: GitHub URL of the markdown page
            source_file: Local file path (Path object or str)
            original_yaml_file: Optional original YAML file path
        """
        super().__init__(yaml_dict, source_url, source_file, original_yaml_file)
        self.crd_kind = self._extract_crd_kind()
        self.crd_group = self._extract_crd_group()
        
    def _extract_crd_kind(self) -> str:
        """Extract CRD kind from metadata."""
        return self.yaml_dict.get("spec", {}).get("names", {}).get("kind", "UnknownKind")
    
    def _extract_crd_group(self) -> str:
        """Extract CRD group from spec."""
        return self.yaml_dict.get("spec", {}).get("group", "unknown.group")
    
    @classmethod
    def can_handle(cls, doc: dict) -> bool:
        """Return True if this walker can process a Kubernetes CRD document."""
        return (
            doc.get("apiVersion", "").startswith("apiextensions.k8s.io/") and
            doc.get("kind") == "CustomResourceDefinition"
        )

    def walk(self) -> List[Chunk]:
        """Walk CRD tree and generate chunks for each version and property.
        
        Returns:
            List of Chunk objects with dict content
        """
        self.chunks = []
        
        # Get all versions
        versions = self.yaml_dict.get("spec", {}).get("versions", [])
        
        for version_obj in versions:
            version_name = version_obj.get("name", "v1")
            schema = version_obj.get("schema", {}).get("openAPIV3Schema", {})
            properties = schema.get("properties", {})
            
            # Only process 'spec' properties (not apiVersion, kind, metadata, status)
            if "spec" in properties and isinstance(properties["spec"], dict):
                spec_props = properties["spec"].get("properties", {})
                if spec_props:
                    self._walk_properties(
                        spec_props,
                        path=["spec", "versions[0]", "schema", "openAPIV3Schema", "properties", "spec", "properties"],
                        version=version_name,
                        parent_path=["spec", "versions[0]", "schema", "openAPIV3Schema", "properties", "spec", "properties"],
                        spec_relative_path=["spec"]  # Track path relative to spec for crd_property_path
                    )
        
        # Post-process: Identify neighbors for all chunks
        self._assign_neighbor_relationships()
        
        return self.chunks
    
    def _walk_properties(
        self,
        properties: Dict[str, Any],
        path: List[str],
        version: str,
        parent_path: List[str],
        spec_relative_path: List[str] = None
    ) -> None:
        """Walk properties and create chunks, recursively chunking if too large.

        Args:
            properties: Dict of property definitions
            path: Current path in tree (for breadcrumbs)
            version: CRD version (e.g., "v1")
            parent_path: Parent path for logical_parent metadata
            spec_relative_path: Path relative to spec (e.g., ["spec", "config"])
        """
        if spec_relative_path is None:  # pragma: no cover
            spec_relative_path = ["spec"]

        for prop_name, prop_schema in properties.items():
            # Sanitize content to ensure JSON serializability (convert datetime objects to strings)
            sanitized_content = self._sanitize_yaml_content(prop_schema)

            # Calculate token count
            token_count = self._calculate_token_count(sanitized_content)

            # Check if we should chunk recursively
            if self._should_chunk_recursively(sanitized_content, token_count):
                # Property is too large and has nested structure - recurse deeper
                if "properties" in sanitized_content and isinstance(sanitized_content["properties"], dict):
                    # Recursively process nested properties
                    nested_path = path[:-1] + [prop_name, "properties"]  # Remove trailing 'properties', add prop_name and 'properties'
                    nested_parent_path = path[:-1] + [prop_name]
                    nested_spec_relative_path = spec_relative_path + [prop_name]
                    self._walk_properties(
                        sanitized_content["properties"],
                        path=nested_path,
                        version=version,
                        parent_path=nested_parent_path,
                        spec_relative_path=nested_spec_relative_path
                    )
                    # Don't create a chunk for the parent property itself
                    continue
                elif "items" in sanitized_content and isinstance(sanitized_content["items"], dict):
                    # Array items schema - check if it has properties to recurse into
                    items_schema = sanitized_content["items"]
                    if "properties" in items_schema and isinstance(items_schema["properties"], dict):
                        # Recursively process properties within the array items
                        nested_path = path[:-1] + [prop_name, "items", "properties"]
                        nested_parent_path = path[:-1] + [prop_name, "items"]
                        nested_spec_relative_path = spec_relative_path + [prop_name, "items"]
                        self._walk_properties(
                            items_schema["properties"],
                            path=nested_path,
                            version=version,
                            parent_path=nested_parent_path,
                            spec_relative_path=nested_spec_relative_path
                        )
                        # Don't create a chunk for the parent array property itself
                        continue

            # Create chunk for this property
            breadcrumb = self._generate_breadcrumb(path[:-1] + [prop_name])  # Remove trailing 'properties' from path

            # Generate property_path using spec_relative_path (e.g., "spec.config.database")
            property_path = ".".join(spec_relative_path + [prop_name])

            metadata = {
                "source_url": self.source_url,
                "original_format": "yaml",
                "schema_type": "k8s_crd",
                "breadcrumb_path": breadcrumb,
                "logical_parent": self._generate_breadcrumb(parent_path),
                "neighbor_chunks": [],  # Will be filled in post-processing
                "crd_kind": self.crd_kind,
                "crd_api_version": f"{self.crd_group}/{version}",
                "crd_version": version,
                "crd_property_path": property_path
            }

            chunk = Chunk(
                chunk_id=self._generate_chunk_id(
                    content=sanitized_content,
                    chunk_type="crd_definition",
                    metadata=metadata,
                    source_file=self.source_file or self.source_url
                ),
                content=sanitized_content,
                source_file=self.source_file or self.source_url,
                chunk_type="crd_definition",
                token_count=token_count,
                metadata=metadata,
            )

            if self.original_yaml_file:
                chunk.metadata["original_yaml_file"] = self.original_yaml_file

            self.chunks.append(chunk)
    
    def _assign_neighbor_relationships(self) -> None:
        """Post-process chunks to identify and assign neighbor relationships.
        
        Neighbors are sibling properties at the same tree level (same logical_parent).
        """
        # Group chunks by logical_parent
        parent_groups: Dict[str, List[Chunk]] = {}
        for chunk in self.chunks:
            parent = chunk.metadata.get("logical_parent", "")
            if parent not in parent_groups:
                parent_groups[parent] = []
            parent_groups[parent].append(chunk)
        
        # For each group, set neighbors (all siblings except self)
        for parent, siblings in parent_groups.items():
            if len(siblings) <= 1:
                continue  # No neighbors if only one child
            
            for chunk in siblings:
                neighbor_ids = [s.chunk_id for s in siblings if s.chunk_id != chunk.chunk_id]
                chunk.metadata["neighbor_chunks"] = neighbor_ids
