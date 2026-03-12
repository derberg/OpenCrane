"""Unit tests for metadata helpers."""

from opencrane.shared.utils.metadata_helpers import (
    extract_crd_identity,
    is_openapi_spec,
    extract_openapi_metadata,
    is_json_schema,
    extract_json_schema_metadata
)


class TestMetadataHelpers:
    """Test cases for metadata helper functions."""

    def test_extract_crd_identity_complete(self):
        """Test CRD identity extraction with all fields."""
        yaml_data = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "test-pod", "namespace": "default"}
        }
        identity = extract_crd_identity(yaml_data)
        assert identity is not None
        assert identity.apiVersion == "v1"
        assert identity.kind == "Pod"
        assert identity.name == "test-pod"
        assert identity.namespace == "default"

    def test_extract_crd_identity_missing_fields(self):
        """Test CRD identity extraction with missing fields."""
        yaml_data = {"apiVersion": "v1"}  # Missing kind and metadata
        identity = extract_crd_identity(yaml_data)
        assert identity is None

    def test_extract_crd_identity_invalid_data(self):
        """Test CRD identity extraction with invalid data types."""
        yaml_data = {
            "apiVersion": 123,  # Should be string
            "kind": "Pod",
            "metadata": {"name": "test-pod"}
        }
        identity = extract_crd_identity(yaml_data)
        assert identity is None  # Should return None due to ValidationError

    def test_is_openapi_spec_openapi_3(self):
        """Test OpenAPI 3.x detection."""
        yaml_data = {"openapi": "3.0.0", "info": {"title": "Test API"}}
        assert is_openapi_spec(yaml_data) is True

    def test_is_openapi_spec_openapi_31(self):
        """Test OpenAPI 3.1 detection."""
        yaml_data = {"openapi": "3.1.0", "info": {"title": "Test API"}}
        assert is_openapi_spec(yaml_data) is True

    def test_is_openapi_spec_swagger_2(self):
        """Test Swagger 2.0 detection."""
        yaml_data = {"swagger": "2.0", "info": {"title": "Test API"}}
        assert is_openapi_spec(yaml_data) is True

    def test_is_openapi_spec_swagger_2_numeric(self):
        """Test Swagger 2.0 detection with numeric version."""
        yaml_data = {"swagger": 2.0, "info": {"title": "Test API"}}
        assert is_openapi_spec(yaml_data) is True

    def test_is_openapi_spec_not_openapi(self):
        """Test non-OpenAPI YAML."""
        yaml_data = {"apiVersion": "v1", "kind": "Pod"}
        assert is_openapi_spec(yaml_data) is False

    def test_is_openapi_spec_empty(self):
        """Test empty YAML."""
        yaml_data = {}
        assert is_openapi_spec(yaml_data) is False

    def test_extract_openapi_metadata_openapi_3(self):
        """Test OpenAPI 3.x metadata extraction."""
        yaml_data = {
            "openapi": "3.0.0",
            "info": {
                "title": "Test API",
                "version": "1.0.0",
                "description": "Test description"
            }
        }
        metadata = extract_openapi_metadata(yaml_data)
        assert metadata["openapi_version"] == "3.0.0"
        assert metadata["title"] == "Test API"
        assert metadata["version"] == "1.0.0"

    def test_extract_openapi_metadata_swagger_2(self):
        """Test Swagger 2.0 metadata extraction."""
        yaml_data = {
            "swagger": "2.0",
            "info": {
                "title": "Test API",
                "version": "1.0.0"
            }
        }
        metadata = extract_openapi_metadata(yaml_data)
        assert metadata["openapi_version"] == "swagger-2.0"
        assert metadata["title"] == "Test API"
        assert metadata["version"] == "1.0.0"

    def test_extract_openapi_metadata_no_info(self):
        """Test OpenAPI metadata extraction without info section."""
        yaml_data = {"openapi": "3.0.0"}
        metadata = extract_openapi_metadata(yaml_data)
        assert metadata["openapi_version"] == "3.0.0"
        assert "title" not in metadata
        assert "version" not in metadata

    def test_extract_openapi_metadata_partial_info(self):
        """Test OpenAPI metadata extraction with partial info."""
        yaml_data = {
            "openapi": "3.0.0",
            "info": {"title": "Test API"}
        }
        metadata = extract_openapi_metadata(yaml_data)
        assert metadata["openapi_version"] == "3.0.0"
        assert metadata["title"] == "Test API"
        assert metadata["version"] == ""

    def test_is_json_schema_with_schema_field(self):
        """Test JSON Schema detection with $schema field."""
        yaml_data = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"name": {"type": "string"}}
        }
        assert is_json_schema(yaml_data) is True

    def test_is_json_schema_with_id_field(self):
        """Test JSON Schema detection with $id field."""
        yaml_data = {
            "$id": "https://example.com/schemas/user.json",
            "type": "object",
            "properties": {"name": {"type": "string"}}
        }
        assert is_json_schema(yaml_data) is True

    def test_is_json_schema_with_old_id_field(self):
        """Test JSON Schema detection with old id field (pre-draft 2019-09)."""
        yaml_data = {
            "id": "https://example.com/schemas/user.json",
            "type": "object",
            "properties": {"name": {"type": "string"}}
        }
        assert is_json_schema(yaml_data) is True

    def test_is_json_schema_implicit_structure(self):
        """Test JSON Schema detection with implicit structure (no $schema)."""
        yaml_data = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"}
            }
        }
        assert is_json_schema(yaml_data) is True

    def test_is_json_schema_with_defs(self):
        """Test JSON Schema detection with $defs."""
        yaml_data = {
            "type": "object",
            "$defs": {
                "address": {
                    "type": "object",
                    "properties": {"street": {"type": "string"}}
                }
            }
        }
        assert is_json_schema(yaml_data) is True

    def test_is_json_schema_with_definitions(self):
        """Test JSON Schema detection with old definitions keyword."""
        yaml_data = {
            "type": "object",
            "definitions": {
                "address": {
                    "type": "object",
                    "properties": {"street": {"type": "string"}}
                }
            }
        }
        assert is_json_schema(yaml_data) is True

    def test_is_json_schema_not_k8s_resource(self):
        """Test that K8s resources are not detected as JSON Schema."""
        yaml_data = {
            "apiVersion": "v1",
            "kind": "Pod",
            "type": "object",
            "properties": {"name": {"type": "string"}}
        }
        assert is_json_schema(yaml_data) is False

    def test_is_json_schema_not_openapi(self):
        """Test that OpenAPI specs are not detected as JSON Schema."""
        yaml_data = {
            "openapi": "3.0.0",
            "info": {"title": "Test API"}
        }
        assert is_json_schema(yaml_data) is False

    def test_is_json_schema_incomplete_structure(self):
        """Test that incomplete structures are not detected as JSON Schema."""
        yaml_data = {
            "type": "object"
            # Missing properties, items, $defs, etc.
        }
        assert is_json_schema(yaml_data) is False

    def test_extract_json_schema_metadata_complete(self):
        """Test JSON Schema metadata extraction with all fields."""
        yaml_data = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://example.com/schemas/user.json",
            "title": "User Schema",
            "description": "Schema for user objects"
        }
        metadata = extract_json_schema_metadata(yaml_data)
        assert metadata["schema_version"] == "https://json-schema.org/draft/2020-12/schema"
        assert metadata["schema_id"] == "https://example.com/schemas/user.json"
        assert metadata["title"] == "User Schema"
        assert metadata["description"] == "Schema for user objects"

    def test_extract_json_schema_metadata_minimal(self):
        """Test JSON Schema metadata extraction with minimal fields."""
        yaml_data = {
            "type": "object",
            "properties": {"name": {"type": "string"}}
        }
        metadata = extract_json_schema_metadata(yaml_data)
        assert "schema_version" not in metadata
        assert "schema_id" not in metadata
        assert "title" not in metadata
        assert "description" not in metadata

    def test_extract_json_schema_metadata_old_id(self):
        """Test JSON Schema metadata extraction with old id field."""
        yaml_data = {
            "id": "https://example.com/schemas/user.json",
            "title": "User Schema"
        }
        metadata = extract_json_schema_metadata(yaml_data)
        assert metadata["schema_id"] == "https://example.com/schemas/user.json"
        assert metadata["title"] == "User Schema"