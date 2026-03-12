"""OpenAPI tree walker for chunking OpenAPI specifications."""

from typing import List, Dict, Any
from opencrane.rag.services.chunking_strategies.yaml_tree_walker import YamlTreeWalker
from opencrane.shared.models.chunk import Chunk
from opencrane.shared.utils.category import infer_category_from_path
import yaml


class OpenAPITreeWalker(YamlTreeWalker):
    """Walk OpenAPI specification trees and generate element-based chunks."""
    
    def __init__(self, yaml_dict: Dict[str, Any], source_url: str, source_file = None, original_yaml_file: str | None = None):
        """Initialize OpenAPI tree walker.
        
        Args:
            yaml_dict: Parsed OpenAPI spec as Python dict
            source_url: GitHub URL of the markdown page
            source_file: Local file path (Path object or str)
            original_yaml_file: Optional original YAML file path
        """
        super().__init__(yaml_dict, source_url, source_file, original_yaml_file)
        self.openapi_version = self._extract_openapi_version()
        
    def _extract_openapi_version(self) -> str:
        """Extract OpenAPI/Swagger version from spec."""
        if "openapi" in self.yaml_dict:
            return self.yaml_dict["openapi"]
        elif "swagger" in self.yaml_dict:
            return self.yaml_dict["swagger"]
        return "unknown"
    
    @classmethod
    def can_handle(cls, doc: dict) -> bool:
        """Return True if this walker can process an OpenAPI/Swagger document."""
        from opencrane.shared.utils.metadata_helpers import is_openapi_spec
        return is_openapi_spec(doc)

    def walk(self) -> List[Chunk]:
        """Walk OpenAPI tree and generate chunks for each element.
        
        Returns:
            List of Chunk objects with dict content
        """
        self.chunks = []
        
        # Extract root-level elements
        if "info" in self.yaml_dict:
            self._extract_info()
        
        if "servers" in self.yaml_dict:
            self._extract_servers()
        
        if "security" in self.yaml_dict:
            self._extract_security()
        
        if "tags" in self.yaml_dict:
            self._extract_tags()
        
        if "paths" in self.yaml_dict:
            self._extract_paths()
        
        if "components" in self.yaml_dict:
            self._extract_components()
        
        # Post-process: Identify neighbors for all chunks
        self._assign_neighbor_relationships()
        
        return self.chunks
    
    def _extract_info(self) -> None:
        """Extract info object as a single chunk."""
        from opencrane.shared.utils.token_counter import get_token_count
        
        info_content = self.yaml_dict["info"]
        breadcrumb = "info"
        
        # Calculate token count
        yaml_str = yaml.dump(info_content, default_flow_style=False, allow_unicode=True)
        token_count = get_token_count(yaml_str)
        
        chunk = self._create_chunk(
            content=info_content,
            breadcrumb_path=breadcrumb,
            logical_parent="root",
            openapi_element="info",
            token_count=token_count
        )
        self.chunks.append(chunk)
    
    def _extract_servers(self) -> None:
        """Extract each server as a separate chunk."""
        from opencrane.shared.utils.token_counter import get_token_count
        
        servers = self.yaml_dict["servers"]
        
        for idx, server in enumerate(servers):
            breadcrumb = f"servers[{idx}]"
            server_url = server.get("url", "")
            
            # Calculate token count
            yaml_str = yaml.dump(server, default_flow_style=False, allow_unicode=True)
            token_count = get_token_count(yaml_str)
            
            chunk = self._create_chunk(
                content=server,
                breadcrumb_path=breadcrumb,
                logical_parent="servers",
                openapi_element="servers",
                token_count=token_count,
                server_url=server_url
            )
            self.chunks.append(chunk)
    
    def _extract_security(self) -> None:
        """Extract security array as a single chunk."""
        from opencrane.shared.utils.token_counter import get_token_count
        
        security_content = self.yaml_dict["security"]
        breadcrumb = "security"
        
        # Calculate token count
        yaml_str = yaml.dump(security_content, default_flow_style=False, allow_unicode=True)
        token_count = get_token_count(yaml_str)
        
        chunk = self._create_chunk(
            content=security_content,
            breadcrumb_path=breadcrumb,
            logical_parent="root",
            openapi_element="security",
            token_count=token_count
        )
        self.chunks.append(chunk)
    
    def _extract_tags(self) -> None:
        """Extract tags array as a single chunk."""
        from opencrane.shared.utils.token_counter import get_token_count
        
        tags_content = self.yaml_dict["tags"]
        breadcrumb = "tags"
        
        # Calculate token count
        yaml_str = yaml.dump(tags_content, default_flow_style=False, allow_unicode=True)
        token_count = get_token_count(yaml_str)
        
        chunk = self._create_chunk(
            content=tags_content,
            breadcrumb_path=breadcrumb,
            logical_parent="root",
            openapi_element="tags",
            token_count=token_count
        )
        self.chunks.append(chunk)
    
    def _extract_paths(self) -> None:
        """Extract each path operation as a separate chunk."""
        from opencrane.shared.utils.token_counter import get_token_count
        
        paths = self.yaml_dict["paths"]
        
        for path_name, path_item in paths.items():
            # Each HTTP method is a separate chunk
            for method in ["get", "post", "put", "delete", "patch", "options", "head", "trace"]:
                if method in path_item:
                    operation = path_item[method]
                    
                    # Skip if operation is None or empty
                    if not operation:
                        continue
                    
                    breadcrumb = f"paths.{path_name}.{method}"
                    logical_parent = f"paths.{path_name}"
                    
                    # Calculate token count
                    yaml_str = yaml.dump(operation, default_flow_style=False, allow_unicode=True)
                    token_count = get_token_count(yaml_str)
                    
                    chunk = self._create_chunk(
                        content=operation,
                        breadcrumb_path=breadcrumb,
                        logical_parent=logical_parent,
                        openapi_element="paths",
                        token_count=token_count,
                        endpoint_path=path_name,
                        http_method=method
                    )
                    self.chunks.append(chunk)
    
    def _extract_components(self) -> None:
        """Extract components (schemas, securitySchemes, etc.) as separate chunks."""
        components = self.yaml_dict["components"]

        # Iterate through component types
        for component_type in ["schemas", "securitySchemes", "responses", "parameters", "examples", "requestBodies", "headers", "links", "callbacks"]:
            if component_type in components:
                items = components[component_type]

                for item_name, item_content in items.items():
                    # Sanitize content
                    sanitized_content = self._sanitize_yaml_content(item_content)

                    # Calculate token count
                    token_count = self._calculate_token_count(sanitized_content)

                    # Check if we should chunk recursively (primarily for schemas)
                    if component_type == "schemas" and self._should_chunk_recursively(sanitized_content, token_count):
                        # Schema is too large and has nested structure - recurse deeper
                        if "properties" in sanitized_content and isinstance(sanitized_content["properties"], dict):  # pragma: no cover
                            # Recursively process nested properties within this schema
                            self._extract_schema_properties(
                                sanitized_content["properties"],
                                schema_name=item_name,
                                path=["components", component_type, item_name, "properties"],
                                parent_path=["components", component_type, item_name]
                            )
                            # Don't create a chunk for the parent schema itself
                            continue
                        elif "items" in sanitized_content and isinstance(sanitized_content["items"], dict):
                            # Array items schema - check if it has properties to recurse into
                            items_schema = sanitized_content["items"]
                            if "properties" in items_schema and isinstance(items_schema["properties"], dict):
                                # Recursively process properties within the array items
                                self._extract_schema_properties(
                                    items_schema["properties"],
                                    schema_name=item_name,
                                    path=["components", component_type, item_name, "items", "properties"],
                                    parent_path=["components", component_type, item_name, "items"]
                                )
                                # Don't create a chunk for the parent array schema itself
                                continue

                    breadcrumb = f"components.{component_type}.{item_name}"
                    logical_parent = f"components.{component_type}"

                    # Add type-specific metadata
                    extra_metadata = {"component_type": component_type}
                    if component_type == "schemas":
                        extra_metadata["schema_name"] = item_name
                    elif component_type == "securitySchemes":
                        extra_metadata["security_scheme_name"] = item_name

                    chunk = self._create_chunk(
                        content=sanitized_content,
                        breadcrumb_path=breadcrumb,
                        logical_parent=logical_parent,
                        openapi_element="components",
                        token_count=token_count,
                        **extra_metadata
                    )
                    self.chunks.append(chunk)
    
    def _extract_schema_properties(
        self,
        properties: Dict[str, Any],
        schema_name: str,
        path: List[str],
        parent_path: List[str]
    ) -> None:
        """Extract nested properties from an OpenAPI schema, recursively chunking if too large.

        Args:
            properties: Dict of property definitions
            schema_name: Name of the parent schema
            path: Current path in tree
            parent_path: Parent path for logical_parent metadata
        """
        for prop_name, prop_schema in properties.items():
            # Skip boolean property schemas
            if isinstance(prop_schema, bool):  # pragma: no cover
                continue

            # Sanitize content
            sanitized_content = self._sanitize_yaml_content(prop_schema)

            # Calculate token count
            token_count = self._calculate_token_count(sanitized_content)

            # Check if we should chunk recursively
            if self._should_chunk_recursively(sanitized_content, token_count):  # pragma: no cover
                # Property is too large and has nested structure - recurse deeper
                if "properties" in sanitized_content and isinstance(sanitized_content["properties"], dict):
                    # Recursively process nested properties
                    nested_path = path + [prop_name, "properties"]
                    nested_parent_path = path + [prop_name]
                    self._extract_schema_properties(
                        sanitized_content["properties"],
                        schema_name=schema_name,
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
                        self._extract_schema_properties(
                            items_schema["properties"],
                            schema_name=schema_name,
                            path=nested_path,
                            parent_path=nested_parent_path
                        )
                        # Don't create a chunk for the parent array property itself
                        continue

            # Create chunk for this property
            breadcrumb = self._generate_breadcrumb(path + [prop_name])
            logical_parent = self._generate_breadcrumb(parent_path)

            # Generate property path (e.g., "User.profile.address")
            clean_path = [p for p in (path + [prop_name]) if p != "properties"]
            # Remove "components", "schemas" from path
            schema_idx = -1
            for i, p in enumerate(clean_path):
                if clean_path[i:i+2] == ["components", "schemas"]:
                    schema_idx = i + 2
                    break
            if schema_idx >= 0 and schema_idx < len(clean_path):
                property_path = ".".join(clean_path[schema_idx:])
            else:  # pragma: no cover
                property_path = f"{schema_name}.{prop_name}"

            chunk = self._create_chunk(
                content=sanitized_content,
                breadcrumb_path=breadcrumb,
                logical_parent=logical_parent,
                openapi_element="components",
                token_count=token_count,
                component_type="schemas",
                schema_name=schema_name,
                property_name=prop_name,
                property_path=property_path
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
        openapi_element: str,
        token_count: int,
        **extra_metadata
    ) -> Chunk:
        """Create a chunk with OpenAPI-specific metadata.
        
        Args:
            content: Chunk content (dict or list)
            breadcrumb_path: Full path in OpenAPI tree
            logical_parent: Parent path
            openapi_element: OpenAPI element type (info, paths, components, etc.)
            token_count: Number of tokens in content
            **extra_metadata: Additional metadata fields
        
        Returns:
            Chunk object
        """
        # Sanitize content to ensure JSON serializability (convert datetime objects to strings)
        sanitized_content = self._sanitize_yaml_content(content)
        
        metadata = {
            "source_url": self.source_url,
            "breadcrumb_path": breadcrumb_path,
            "logical_parent": logical_parent,
            "neighbor_chunks": [],  # Will be populated by _assign_neighbor_relationships
            "original_format": "yaml",
            "schema_type": "openapi",
            "openapi_version": self.openapi_version,
            "openapi_element": openapi_element,
        }
        
        # Add extra metadata (server_url, endpoint_path, http_method, etc.)
        metadata.update(extra_metadata)
        
        if self.original_yaml_file:
            metadata["original_yaml_file"] = self.original_yaml_file
        
        # Use source_url from metadata for category if available (for llms-full.txt chunks),
        # otherwise use source_file
        category_path = metadata.get("source_url") or self.source_file or self.source_url

        chunk = Chunk(
            chunk_id=self._generate_chunk_id(
                content=sanitized_content,
                chunk_type="openapi_spec",
                metadata=metadata,
                source_file=self.source_file or self.source_url
            ),
            content=sanitized_content,
            source_file=self.source_file or self.source_url,
            chunk_type="openapi_spec",
            metadata=metadata,
            token_count=token_count,
            category=infer_category_from_path(category_path)
        )

        return chunk
