"""Metadata helper functions for chunk processing."""

from typing import List, Dict, Any
from pydantic import ValidationError
from opencrane.shared.models.root_identity import RootIdentity


def is_openapi_spec(yaml_data: Dict[str, Any]) -> bool:
    """Check if YAML data is an OpenAPI specification.

    Args:
        yaml_data: Parsed YAML dictionary.

    Returns:
        True if it looks like an OpenAPI spec, False otherwise.
    """
    # Check for OpenAPI 3.x
    if "openapi" in yaml_data:
        version = yaml_data.get("openapi", "")
        if isinstance(version, str) and version.startswith("3."):
            return True
    
    # Check for Swagger 2.0
    if "swagger" in yaml_data:
        version = yaml_data.get("swagger", "")
        if version == "2.0" or version == 2.0:
            return True
    
    return False


def extract_openapi_metadata(yaml_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract metadata from OpenAPI spec.

    Args:
        yaml_data: Parsed YAML dictionary of OpenAPI spec.

    Returns:
        Dictionary with openapi_version and info (if present).
    """
    metadata = {}
    
    if "openapi" in yaml_data:
        metadata["openapi_version"] = yaml_data.get("openapi")
    elif "swagger" in yaml_data:
        metadata["openapi_version"] = f"swagger-{yaml_data.get('swagger')}"
    
    if "info" in yaml_data and isinstance(yaml_data["info"], dict):
        metadata["title"] = yaml_data["info"].get("title", "")
        metadata["version"] = yaml_data["info"].get("version", "")
    
    return metadata


def is_json_schema(yaml_data: Dict[str, Any]) -> bool:
    """Check if YAML data is a JSON Schema document.

    Args:
        yaml_data: Parsed YAML dictionary.

    Returns:
        True if it looks like a JSON Schema, False otherwise.
    """
    # Check for JSON Schema version marker
    if "$schema" in yaml_data:
        schema_value = yaml_data.get("$schema", "")
        if isinstance(schema_value, str) and "json-schema.org" in schema_value:
            return True

    # Check for JSON Schema ID markers
    if "$id" in yaml_data or "id" in yaml_data:
        # Additional check: must have typical schema structure
        if "type" in yaml_data or "properties" in yaml_data or "$defs" in yaml_data or "definitions" in yaml_data:
            return True

    # Check for schema-like structure without explicit $schema
    # Must have 'type' field and at least one of: properties, items, $defs, definitions
    if "type" in yaml_data and isinstance(yaml_data.get("type"), str):
        schema_keys = {"properties", "items", "$defs", "definitions", "oneOf", "anyOf", "allOf"}
        if any(key in yaml_data for key in schema_keys):
            # Additional validation: not a Kubernetes resource (those have apiVersion/kind)
            if "apiVersion" not in yaml_data and "kind" not in yaml_data:
                return True

    return False


def extract_json_schema_metadata(yaml_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract metadata from JSON Schema document.

    Args:
        yaml_data: Parsed YAML dictionary of JSON Schema.

    Returns:
        Dictionary with schema_version, schema_id, title, and description (if present).
    """
    metadata = {}

    # Extract schema version
    if "$schema" in yaml_data:
        metadata["schema_version"] = yaml_data.get("$schema")

    # Extract schema ID (draft 2019-09+ uses $id, older drafts use id)
    if "$id" in yaml_data:
        metadata["schema_id"] = yaml_data.get("$id")
    elif "id" in yaml_data:
        metadata["schema_id"] = yaml_data.get("id")

    # Extract title and description
    if "title" in yaml_data:
        metadata["title"] = yaml_data.get("title")
    if "description" in yaml_data:
        metadata["description"] = yaml_data.get("description")

    return metadata


def extract_crd_identity(yaml_data: Dict[str, Any]) -> RootIdentity | None:
    """Extract RootIdentity from YAML data if present.

    Args:
        yaml_data: Parsed YAML dictionary.

    Returns:
        RootIdentity if all required fields present, None otherwise.
    """
    if not yaml_data.get("apiVersion") or not yaml_data.get("kind") or not yaml_data.get("metadata", {}).get("name"):
        return None

    try:
        return RootIdentity(
            apiVersion=yaml_data.get("apiVersion"),
            kind=yaml_data.get("kind"),
            name=yaml_data.get("metadata", {}).get("name"),
            namespace=yaml_data.get("metadata", {}).get("namespace"),
        )
    except ValidationError:
        return None