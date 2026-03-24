"""JSON Schema tree walker for chunking JSON Schema documents."""

from typing import List, Dict, Any
from opencrane.rag.services.chunking_strategies.yaml_tree_walker import YamlTreeWalker
from opencrane.shared.models.chunk import Chunk
import yaml


class JsonSchemaTreeWalker(YamlTreeWalker):
    """Walk JSON Schema trees and generate property-based chunks."""

    def __init__(self, yaml_dict: Dict[str, Any], source_url: str, source_file = None, original_yaml_file: str | None = None):
        """Initialize JSON Schema tree walker.

        Args:
            yaml_dict: Parsed JSON Schema as Python dict
            source_url: GitHub URL of the markdown page
            source_file: Local file path (Path object or str)
            original_yaml_file: Optional original YAML file path
        """
        super().__init__(yaml_dict, source_url, source_file, original_yaml_file)
        self.schema_version = self._extract_schema_version()
        self.schema_id = self._extract_schema_id()
        self.schema_title = self.yaml_dict.get("title", "")

    def _extract_schema_version(self) -> str:
        """Extract JSON Schema version from $schema field."""
        return self.yaml_dict.get("$schema", "unknown")

    def _extract_schema_id(self) -> str:
        """Extract JSON Schema ID from $id or id field."""
        return self.yaml_dict.get("$id", self.yaml_dict.get("id", ""))

    @classmethod
    def can_handle(cls, doc: dict) -> bool:
        """Return True if this walker can process a JSON Schema document."""
        from opencrane.shared.utils.metadata_helpers import is_json_schema
        return is_json_schema(doc)

    def walk(self) -> List[Chunk]:
        """Walk JSON Schema tree and generate chunks.

        Chunks are created for:
        - Root schema metadata (if present)
        - Each top-level property in 'properties'
        - Each definition in '$defs' or 'definitions'

        Returns:
            List of Chunk objects with dict content
        """
        self.chunks = []

        # Extract root schema metadata if significant
        if self._has_root_metadata():
            self._extract_root_schema()

        # Extract top-level properties
        if "properties" in self.yaml_dict:
            self._extract_properties(
                self.yaml_dict["properties"],
                path=["properties"],
                parent_path=["root"]
            )

        # Extract definitions ($defs in newer drafts, definitions in older drafts)
        if "$defs" in self.yaml_dict:
            self._extract_definitions(
                self.yaml_dict["$defs"],
                path=["$defs"],
                definitions_key="$defs"
            )
        elif "definitions" in self.yaml_dict:
            self._extract_definitions(
                self.yaml_dict["definitions"],
                path=["definitions"],
                definitions_key="definitions"
            )

        # Post-process: Identify neighbors for all chunks
        self._assign_neighbor_relationships()

        return self.chunks

    def _has_root_metadata(self) -> bool:
        """Check if root schema has significant metadata worth chunking."""
        metadata_keys = {"title", "description", "$comment", "examples", "default"}
        return any(key in self.yaml_dict for key in metadata_keys)

    def _extract_root_schema(self) -> None:
        """Extract root schema metadata as a single chunk."""
        from opencrane.shared.utils.token_counter import get_token_count

        # Extract only metadata fields (not structural fields)
        metadata_fields = {}
        for key in ["title", "description", "$comment", "examples", "default", "type"]:
            if key in self.yaml_dict:
                metadata_fields[key] = self.yaml_dict[key]

        breadcrumb = "root"

        # Calculate token count
        yaml_str = yaml.dump(metadata_fields, default_flow_style=False, allow_unicode=True)
        token_count = get_token_count(yaml_str)

        chunk = self._create_chunk(
            content=metadata_fields,
            breadcrumb_path=breadcrumb,
            logical_parent="root",
            schema_element="root",
            token_count=token_count
        )
        self.chunks.append(chunk)

    def _extract_properties(
        self,
        properties: Dict[str, Any],
        path: List[str],
        parent_path: List[str]
    ) -> None:
        """Extract each property as a separate chunk, recursively chunking if too large.

        Args:
            properties: Dict of property definitions
            path: Current path in tree
            parent_path: Parent path for logical_parent metadata
        """
        for prop_name, prop_schema in properties.items():
            # Skip boolean property schemas (true/false in JSON Schema mean allow/disallow)
            # These don't have semantic content useful for RAG
            if isinstance(prop_schema, bool):
                continue

            # Sanitize content to ensure JSON serializability
            sanitized_content = self._sanitize_yaml_content(prop_schema)

            # Calculate token count
            token_count = self._calculate_token_count(sanitized_content)

            # Check if we should chunk recursively
            if self._should_chunk_recursively(sanitized_content, token_count):
                # Property is too large and has nested structure - recurse deeper
                if "properties" in sanitized_content and isinstance(sanitized_content["properties"], dict):
                    # Recursively process nested properties
                    nested_path = path + [prop_name, "properties"]
                    nested_parent_path = path + [prop_name]
                    self._extract_properties(
                        sanitized_content["properties"],
                        path=nested_path,
                        parent_path=nested_parent_path
                    )
                    # Don't create a chunk for the parent property itself
                    continue
                elif "items" in sanitized_content and isinstance(sanitized_content["items"], dict):
                    # Array items schema - check if it has properties to recurse into
                    items_schema = sanitized_content["items"]
                    if "properties" in items_schema and isinstance(items_schema["properties"], dict):
                        # Recursively process properties within the array items
                        nested_path = path + [prop_name, "items", "properties"]
                        nested_parent_path = path + [prop_name, "items"]
                        self._extract_properties(
                            items_schema["properties"],
                            path=nested_path,
                            parent_path=nested_parent_path
                        )
                        # Don't create a chunk for the parent array property itself
                        continue

            # Create chunk for this property
            breadcrumb = self._generate_breadcrumb(path + [prop_name])

            # Generate property_path from path (e.g., "properties.config.database" -> "config.database")
            # Remove "properties" keywords from path
            clean_path = [p for p in (path + [prop_name]) if p != "properties"]
            property_path = ".".join(clean_path)

            chunk = self._create_chunk(
                content=sanitized_content,
                breadcrumb_path=breadcrumb,
                logical_parent=self._generate_breadcrumb(parent_path),
                schema_element="properties",
                token_count=token_count,
                property_path=property_path,
                property_name=prop_name
            )
            self.chunks.append(chunk)

    def _extract_definitions(
        self,
        definitions: Dict[str, Any],
        path: List[str],
        definitions_key: str
    ) -> None:
        """Extract each definition/component as a separate chunk, recursively chunking if too large.

        Args:
            definitions: Dict of schema definitions
            path: Current path in tree
            definitions_key: Either '$defs' or 'definitions'
        """
        for def_name, def_schema in definitions.items():
            # Skip boolean definition schemas (true/false mean allow/disallow)
            if isinstance(def_schema, bool):
                continue

            # Sanitize content
            sanitized_content = self._sanitize_yaml_content(def_schema)

            # Calculate token count
            token_count = self._calculate_token_count(sanitized_content)

            # Check if we should chunk recursively
            if self._should_chunk_recursively(sanitized_content, token_count):
                # Definition is too large and has nested structure - recurse deeper
                if "properties" in sanitized_content and isinstance(sanitized_content["properties"], dict):
                    # Recursively process nested properties within this definition
                    nested_path = path + [def_name, "properties"]
                    nested_parent_path = path + [def_name]
                    self._extract_properties(
                        sanitized_content["properties"],
                        path=nested_path,
                        parent_path=nested_parent_path
                    )
                    # Don't create a chunk for the parent definition itself
                    continue
                elif "items" in sanitized_content and isinstance(sanitized_content["items"], dict):
                    # Array items schema - check if it has properties to recurse into
                    items_schema = sanitized_content["items"]
                    if "properties" in items_schema and isinstance(items_schema["properties"], dict):
                        # Recursively process properties within the array items
                        nested_path = path + [def_name, "items", "properties"]
                        nested_parent_path = path + [def_name, "items"]
                        self._extract_properties(
                            items_schema["properties"],
                            path=nested_path,
                            parent_path=nested_parent_path
                        )
                        # Don't create a chunk for the parent definition itself
                        continue

            breadcrumb = self._generate_breadcrumb(path + [def_name])

            chunk = self._create_chunk(
                content=sanitized_content,
                breadcrumb_path=breadcrumb,
                logical_parent=definitions_key,
                schema_element="definitions",
                token_count=token_count,
                definition_name=def_name
            )
            self.chunks.append(chunk)

    def _assign_neighbor_relationships(self) -> None:
        """Post-process chunks to identify and assign neighbor relationships.

        Neighbors are sibling elements at the same tree level (same logical_parent).
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

    def _create_chunk(
        self,
        content: Dict[str, Any] | list,
        breadcrumb_path: str,
        logical_parent: str,
        schema_element: str,
        token_count: int,
        **extra_metadata
    ) -> Chunk:
        """Create a chunk with JSON Schema-specific metadata.

        Args:
            content: Chunk content (dict or list)
            breadcrumb_path: Full path in schema tree
            logical_parent: Parent path
            schema_element: Schema element type (root, properties, definitions)
            token_count: Number of tokens in content
            **extra_metadata: Additional metadata fields

        Returns:
            Chunk object
        """
        metadata = {
            "source_url": self.source_url,
            "breadcrumb_path": breadcrumb_path,
            "logical_parent": logical_parent,
            "neighbor_chunks": [],  # Will be populated by _assign_neighbor_relationships
            "original_format": "yaml",
            "schema_type": "json_schema",
            "schema_version": self.schema_version,
            "schema_element": schema_element,
        }

        # Add schema ID and title if available
        if self.schema_id:
            metadata["schema_id"] = self.schema_id
        if self.schema_title:
            metadata["schema_title"] = self.schema_title

        # Add extra metadata (property_path, definition_name, etc.)
        metadata.update(extra_metadata)

        if self.original_yaml_file:
            metadata["original_yaml_file"] = self.original_yaml_file

        chunk = Chunk(
            chunk_id=self._generate_chunk_id(
                content=content,
                chunk_type="json_schema",
                metadata=metadata,
                source_file=self.source_file or self.source_url
            ),
            content=content,
            source_file=self.source_file or self.source_url,
            chunk_type="json_schema",
            metadata=metadata,
            token_count=token_count,
        )

        return chunk
