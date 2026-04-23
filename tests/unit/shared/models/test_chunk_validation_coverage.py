"""Tests for Chunk model validation to achieve 100% coverage."""

import pytest
from pydantic import ValidationError
from opencrane.shared.models.chunk import Chunk


class TestChunkValidationCoverage:
    """Test coverage for all validation paths in Chunk model."""

    def test_empty_string_content(self):
        """Test validation error for empty string content."""
        with pytest.raises(ValidationError, match="string content must not be empty"):
            Chunk(
                content="   ",  # Empty after strip
                source_file="test.md",
                chunk_type="prose",
                metadata={},
                token_count=0
            )

    def test_empty_dict_content(self):
        """Test validation error for empty dict content."""
        with pytest.raises(ValidationError, match="dict content must not be empty"):
            Chunk(
                content={},
                source_file="test.yaml",
                chunk_type="crd_definition",
                metadata={
                    "breadcrumb_path": "spec.test",
                    "logical_parent": "spec",
                    "neighbor_chunks": [],
                    "crd_kind": "Test",
                    "crd_api_version": "v1",
                    "crd_version": "v1",
                    "crd_property_path": "spec.test"
                },
                token_count=0
            )

    def test_empty_list_content(self):
        """Test validation error for empty list content."""
        with pytest.raises(ValidationError, match="list content must not be empty"):
            Chunk(
                content=[],
                source_file="test.yaml",
                chunk_type="openapi_spec",
                metadata={
                    "breadcrumb_path": "paths",
                    "logical_parent": "root",
                    "neighbor_chunks": [],
                    "openapi_version": "3.0.0",
                    "openapi_element": "paths"
                },
                token_count=0
            )

    def test_crd_definition_missing_metadata(self):
        """Test validation error when crd_definition is missing required metadata."""
        with pytest.raises(ValidationError, match="crd_definition chunks must have"):
            Chunk(
                content={"test": "data"},
                source_file="test.yaml",
                chunk_type="crd_definition",
                metadata={
                    # Missing all required fields
                },
                token_count=10
            )

    def test_crd_definition_non_dict_content(self):
        """Test validation error when crd_definition has non-dict content."""
        with pytest.raises(ValidationError, match="crd_definition chunks must have dict content"):
            Chunk(
                content="string content",
                source_file="test.yaml",
                chunk_type="crd_definition",
                metadata={
                    "breadcrumb_path": "spec.test",
                    "logical_parent": "spec",
                    "neighbor_chunks": [],
                    "crd_kind": "Test",
                    "crd_api_version": "v1",
                    "crd_version": "v1",
                    "crd_property_path": "spec.test"
                },
                token_count=10
            )

    def test_openapi_spec_missing_metadata(self):
        """Test validation error when openapi_spec is missing required metadata."""
        with pytest.raises(ValidationError, match="openapi_spec chunks must have"):
            Chunk(
                content={"test": "data"},
                source_file="test.yaml",
                chunk_type="openapi_spec",
                metadata={
                    # Missing all required fields
                },
                token_count=10
            )

    def test_openapi_spec_invalid_content_type(self):
        """Test validation error when openapi_spec has string content."""
        with pytest.raises(ValidationError, match="openapi_spec chunks must have dict or list content"):
            Chunk(
                content="string content",
                source_file="test.yaml",
                chunk_type="openapi_spec",
                metadata={
                    "breadcrumb_path": "info",
                    "logical_parent": "root",
                    "neighbor_chunks": [],
                    "openapi_version": "3.0.0",
                    "openapi_element": "info"
                },
                token_count=10
            )

    def test_refresh_token_count_with_dict(self):
        """Test refresh_token_count with dict content."""
        chunk = Chunk(
            content={"test": "data"},
            source_file="test.yaml",
            chunk_type="crd_definition",
            metadata={
                "breadcrumb_path": "spec.test",
                "logical_parent": "spec",
                "neighbor_chunks": [],
                "crd_kind": "Test",
                "crd_api_version": "v1",
                "crd_version": "v1",
                "crd_property_path": "spec.test"
            },
            token_count=999  # Wrong count
        )
        chunk.refresh_token_count()
        assert chunk.token_count != 999  # Should be recalculated

    def test_refresh_token_count_with_list(self):
        """Test refresh_token_count with list content."""
        chunk = Chunk(
            content=[{"test": "data"}],
            source_file="test.yaml",
            chunk_type="openapi_spec",
            metadata={
                "breadcrumb_path": "paths",
                "logical_parent": "root",
                "neighbor_chunks": [],
                "openapi_version": "3.0.0",
                "openapi_element": "paths"
            },
            token_count=999  # Wrong count
        )
        chunk.refresh_token_count()
        assert chunk.token_count != 999  # Should be recalculated

    def test_json_schema_missing_metadata(self):
        """Test validation error when json_schema is missing required metadata."""
        with pytest.raises(ValidationError, match="json_schema chunks must have"):
            Chunk(
                content={"type": "object"},
                source_file="test.json",
                chunk_type="json_schema",
                metadata={
                    # Missing all required fields
                },
                token_count=10
            )

    def test_json_schema_invalid_content_type(self):
        """Test validation error when json_schema has string content."""
        with pytest.raises(ValidationError, match="json_schema chunks must have dict or list content"):
            Chunk(
                content="string content",
                source_file="test.json",
                chunk_type="json_schema",
                metadata={
                    "breadcrumb_path": "properties.name",
                    "logical_parent": "root",
                    "neighbor_chunks": [],
                    "schema_version": "https://json-schema.org/draft/2020-12/schema",
                    "schema_element": "properties"
                },
                token_count=10
            )

    def _valid_list_item_metadata(self):
        return {
            "breadcrumb_path": "Section",
            "list_id": "abc123",
            "list_style": "ordered",
            "position": 1,
            "total_siblings": 1,
            "sibling_ids": [],
            "sibling_previews": [],
            "parent_item_id": None,
            "depth": 0,
        }

    def test_list_item_missing_metadata(self):
        """list_item with a missing required field reports it by name."""
        md = self._valid_list_item_metadata()
        md.pop("list_id")
        with pytest.raises(ValidationError, match="list_item chunks must have list_id in metadata"):
            Chunk(
                content="# S\nText",
                source_file="test.md",
                chunk_type="list_item",
                metadata=md,
                token_count=3,
            )

    def test_list_item_invalid_list_style(self):
        md = self._valid_list_item_metadata()
        md["list_style"] = "bullets"
        with pytest.raises(ValidationError, match="list_style must be 'ordered' or 'unordered'"):
            Chunk(
                content="# S\nText",
                source_file="test.md",
                chunk_type="list_item",
                metadata=md,
                token_count=3,
            )

    def test_list_item_non_string_content(self):
        md = self._valid_list_item_metadata()
        with pytest.raises(ValidationError, match="list_item chunks must have string content"):
            Chunk(
                content={"k": "v"},
                source_file="test.md",
                chunk_type="list_item",
                metadata=md,
                token_count=3,
            )
