"""Unit tests for OpenAPI tree walker."""

import pytest
import yaml
from opencrane.rag.services.chunking_strategies.openapi_tree_walker import OpenAPITreeWalker


class TestOpenAPITreeWalker:
    """Test OpenAPI tree walking and chunking."""
    
    @pytest.fixture
    def sample_openapi_spec(self):
        """Create a sample OpenAPI spec for testing."""
        return {
            "openapi": "3.0.1",
            "info": {
                "title": "Test API",
                "version": "v1",
                "description": "A test API for unit tests"
            },
            "servers": [
                {"url": "https://api.example.com/v1"}
            ],
            "security": [
                {"ApiKeyAuth": []}
            ],
            "tags": [
                {"name": "users", "description": "User operations"},
                {"name": "posts", "description": "Post operations"}
            ],
            "paths": {
                "/users": {
                    "get": {
                        "tags": ["users"],
                        "summary": "List all users",
                        "operationId": "getUsers",
                        "responses": {
                            "200": {"description": "Success"}
                        }
                    },
                    "post": {
                        "tags": ["users"],
                        "summary": "Create a user",
                        "operationId": "createUser",
                        "responses": {
                            "201": {"description": "Created"}
                        }
                    }
                },
                "/posts/{id}": {
                    "get": {
                        "tags": ["posts"],
                        "summary": "Get a post",
                        "operationId": "getPost",
                        "parameters": [
                            {
                                "name": "id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "integer"}
                            }
                        ],
                        "responses": {
                            "200": {"description": "Success"}
                        }
                    }
                }
            },
            "components": {
                "schemas": {
                    "User": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "name": {"type": "string"}
                        }
                    },
                    "Post": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "title": {"type": "string"},
                            "authorId": {"type": "integer"}
                        }
                    }
                },
                "securitySchemes": {
                    "ApiKeyAuth": {
                        "type": "apiKey",
                        "in": "header",
                        "name": "X-API-Key"
                    }
                }
            }
        }
    
    def test_info_chunk_extraction(self, sample_openapi_spec):
        """Test that info object is extracted as a single chunk."""
        walker = OpenAPITreeWalker(
            sample_openapi_spec,
            source_url="https://github.com/example/repo/blob/main/docs/api.md"
        )
        chunks = walker.walk()
        
        # Find info chunk
        info_chunk = next((c for c in chunks if c.metadata.get("openapi_element") == "info"), None)
        assert info_chunk is not None
        assert info_chunk.chunk_type == "openapi_spec"
        assert info_chunk.content["title"] == "Test API"
        assert info_chunk.content["version"] == "v1"
        assert info_chunk.metadata["breadcrumb_path"] == "info"
        assert info_chunk.metadata["logical_parent"] == "root"
        assert info_chunk.metadata["openapi_version"] == "3.0.1"
    
    def test_servers_array_chunking(self, sample_openapi_spec):
        """Test that each server in servers array is a separate chunk."""
        walker = OpenAPITreeWalker(
            sample_openapi_spec,
            source_url="https://github.com/example/repo/blob/main/docs/api.md"
        )
        chunks = walker.walk()
        
        # Find server chunks
        server_chunks = [c for c in chunks if c.metadata.get("openapi_element") == "servers"]
        assert len(server_chunks) == 1  # One server
        
        server_chunk = server_chunks[0]
        assert server_chunk.chunk_type == "openapi_spec"
        assert server_chunk.content["url"] == "https://api.example.com/v1"
        assert server_chunk.metadata["breadcrumb_path"] == "servers[0]"
        assert server_chunk.metadata["logical_parent"] == "servers"
        assert server_chunk.metadata["server_url"] == "https://api.example.com/v1"
    
    def test_security_and_tags_chunking(self, sample_openapi_spec):
        """Test that security and tags are each single chunks."""
        walker = OpenAPITreeWalker(
            sample_openapi_spec,
            source_url="https://github.com/example/repo/blob/main/docs/api.md"
        )
        chunks = walker.walk()
        
        # Find security chunk
        security_chunk = next((c for c in chunks if c.metadata.get("openapi_element") == "security"), None)
        assert security_chunk is not None
        assert security_chunk.chunk_type == "openapi_spec"
        assert isinstance(security_chunk.content, list)
        assert security_chunk.metadata["breadcrumb_path"] == "security"
        assert security_chunk.metadata["logical_parent"] == "root"
        
        # Find tags chunk
        tags_chunk = next((c for c in chunks if c.metadata.get("openapi_element") == "tags"), None)
        assert tags_chunk is not None
        assert tags_chunk.chunk_type == "openapi_spec"
        assert isinstance(tags_chunk.content, list)
        assert len(tags_chunk.content) == 2  # Two tags
        assert tags_chunk.metadata["breadcrumb_path"] == "tags"
        assert tags_chunk.metadata["logical_parent"] == "root"
    
    def test_path_operation_chunking(self, sample_openapi_spec):
        """Test that each path operation (GET, POST, etc.) is a separate chunk."""
        walker = OpenAPITreeWalker(
            sample_openapi_spec,
            source_url="https://github.com/example/repo/blob/main/docs/api.md"
        )
        chunks = walker.walk()
        
        # Find path operation chunks
        path_chunks = [c for c in chunks if c.metadata.get("openapi_element") == "paths"]
        assert len(path_chunks) == 3  # GET /users, POST /users, GET /posts/{id}
        
        # Check GET /users
        get_users = next((c for c in path_chunks if c.metadata.get("http_method") == "get" and c.metadata.get("endpoint_path") == "/users"), None)
        assert get_users is not None
        assert get_users.chunk_type == "openapi_spec"
        assert get_users.content["summary"] == "List all users"
        assert get_users.metadata["breadcrumb_path"] == "paths./users.get"
        assert get_users.metadata["logical_parent"] == "paths./users"
        
        # Check POST /users
        post_users = next((c for c in path_chunks if c.metadata.get("http_method") == "post" and c.metadata.get("endpoint_path") == "/users"), None)
        assert post_users is not None
        assert post_users.content["summary"] == "Create a user"
        assert post_users.metadata["breadcrumb_path"] == "paths./users.post"
        
        # Check GET /posts/{id}
        get_post = next((c for c in path_chunks if c.metadata.get("endpoint_path") == "/posts/{id}"), None)
        assert get_post is not None
        assert get_post.content["summary"] == "Get a post"
        assert get_post.metadata["breadcrumb_path"] == "paths./posts/{id}.get"
    
    def test_components_chunking(self, sample_openapi_spec):
        """Test that components (schemas, securitySchemes) are chunked separately."""
        walker = OpenAPITreeWalker(
            sample_openapi_spec,
            source_url="https://github.com/example/repo/blob/main/docs/api.md"
        )
        chunks = walker.walk()
        
        # Find component chunks
        component_chunks = [c for c in chunks if c.metadata.get("openapi_element") == "components"]
        assert len(component_chunks) == 3  # 2 schemas + 1 securityScheme
        
        # Check User schema
        user_schema = next((c for c in component_chunks if c.metadata.get("schema_name") == "User"), None)
        assert user_schema is not None
        assert user_schema.chunk_type == "openapi_spec"
        assert user_schema.content["type"] == "object"
        assert "id" in user_schema.content["properties"]
        assert user_schema.metadata["breadcrumb_path"] == "components.schemas.User"
        assert user_schema.metadata["logical_parent"] == "components.schemas"
        assert user_schema.metadata["component_type"] == "schemas"
        
        # Check Post schema
        post_schema = next((c for c in component_chunks if c.metadata.get("schema_name") == "Post"), None)
        assert post_schema is not None
        assert post_schema.metadata["breadcrumb_path"] == "components.schemas.Post"
        
        # Check security scheme
        security_scheme = next((c for c in component_chunks if c.metadata.get("security_scheme_name") == "ApiKeyAuth"), None)
        assert security_scheme is not None
        assert security_scheme.content["type"] == "apiKey"
        assert security_scheme.metadata["breadcrumb_path"] == "components.securitySchemes.ApiKeyAuth"
        assert security_scheme.metadata["logical_parent"] == "components.securitySchemes"
        assert security_scheme.metadata["component_type"] == "securitySchemes"

    def test_array_items_recursive_chunking(self):
        """Test that large array schemas with items.properties are chunked recursively."""
        # Create descriptions long enough to exceed token limits
        long_property_desc = " ".join(["word"] * 200)
        openapi_spec = {
            "openapi": "3.0.1",
            "info": {"title": "Test API", "version": "1.0.0"},
            "components": {
                "schemas": {
                    "VolumeList": {
                        "type": "array",
                        "description": " ".join(["Array of volume configurations for storage management with complex nested properties"] * 50),
                        "items": {
                            "type": "object",
                            "description": " ".join(["Volume item definition with name path size and mount options"] * 50),
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": long_property_desc
                                },
                                "path": {
                                    "type": "string",
                                    "description": long_property_desc
                                },
                                "size": {
                                    "type": "string",
                                    "description": long_property_desc
                                }
                            }
                        }
                    }
                }
            }
        }

        walker = OpenAPITreeWalker(
            openapi_spec,
            source_url="https://github.com/example/repo/blob/main/docs/api.md"
        )
        chunks = walker.walk()

        # Find component chunks
        component_chunks = [c for c in chunks if c.metadata.get("openapi_element") == "components"]

        # Should NOT have a chunk for "VolumeList" itself (it was too large with items)
        # Should have chunks for items properties: "name", "path", "size"
        schema_names = [c.metadata.get("schema_name") for c in component_chunks]
        breadcrumbs = [c.metadata.get("breadcrumb_path") for c in component_chunks]

        # VolumeList should not have its own chunk, only property chunks
        volumelist_parent_chunk = next((c for c in component_chunks if c.metadata.get("breadcrumb_path") == "components.schemas.VolumeList"), None)
        assert volumelist_parent_chunk is None, f"Large array schema 'VolumeList' should not be chunked. Found breadcrumbs: {breadcrumbs}"

        # Check that item properties were chunked
        assert any("components.schemas.VolumeList.items.properties.name" in b for b in breadcrumbs), "Array item property 'name' should be chunked separately"
        assert any("components.schemas.VolumeList.items.properties.path" in b for b in breadcrumbs), "Array item property 'path' should be chunked separately"
        assert any("components.schemas.VolumeList.items.properties.size" in b for b in breadcrumbs), "Array item property 'size' should be chunked separately"

        # Verify all schemas mention VolumeList as the parent schema
        for chunk in component_chunks:
            if "items.properties" in chunk.metadata.get("breadcrumb_path", ""):
                assert chunk.metadata.get("schema_name") == "VolumeList"

        # Verify token counts are reasonable
        for chunk in component_chunks:
            assert chunk.token_count <= 900, f"Chunk {chunk.metadata['breadcrumb_path']} exceeds limit: {chunk.token_count} tokens"

    def test_neighbor_identification(self, sample_openapi_spec):
        """Test that neighbor relationships are correctly identified."""
        walker = OpenAPITreeWalker(
            sample_openapi_spec,
            source_url="https://github.com/example/repo/blob/main/docs/api.md"
        )
        chunks = walker.walk()
        
        # Root-level chunks (info, security, tags) should be neighbors
        info_chunk = next((c for c in chunks if c.metadata.get("openapi_element") == "info"), None)
        security_chunk = next((c for c in chunks if c.metadata.get("openapi_element") == "security"), None)
        tags_chunk = next((c for c in chunks if c.metadata.get("openapi_element") == "tags"), None)
        
        assert info_chunk is not None
        assert security_chunk is not None
        assert tags_chunk is not None
        
        # They should all reference each other as neighbors (and servers if present)
        assert security_chunk.chunk_id in info_chunk.metadata["neighbor_chunks"]
        assert tags_chunk.chunk_id in info_chunk.metadata["neighbor_chunks"]
        
        # Operations under same path should be neighbors
        get_users = next((c for c in chunks if c.metadata.get("breadcrumb_path") == "paths./users.get"), None)
        post_users = next((c for c in chunks if c.metadata.get("breadcrumb_path") == "paths./users.post"), None)
        
        assert get_users is not None
        assert post_users is not None
        assert post_users.chunk_id in get_users.metadata["neighbor_chunks"]
        assert get_users.chunk_id in post_users.metadata["neighbor_chunks"]
        
        # Schemas under same component type should be neighbors
        user_schema = next((c for c in chunks if c.metadata.get("schema_name") == "User"), None)
        post_schema = next((c for c in chunks if c.metadata.get("schema_name") == "Post"), None)
        
        assert user_schema is not None
        assert post_schema is not None
        assert post_schema.chunk_id in user_schema.metadata["neighbor_chunks"]
        assert user_schema.chunk_id in post_schema.metadata["neighbor_chunks"]
    
    def test_skip_none_operations(self):
        """Test that None operations in paths are skipped."""
        spec = {
            "openapi": "3.0.1",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {"summary": "Get test", "responses": {"200": {"description": "OK"}}},
                    "post": None  # None operation should be skipped
                }
            }
        }
        
        walker = OpenAPITreeWalker(spec, source_url="https://example.com/api")
        chunks = walker.walk()
        
        # Should have info chunk + 1 operation chunk (not 2, since post is None)
        path_chunks = [c for c in chunks if c.metadata["openapi_element"] == "paths"]
        assert len(path_chunks) == 1
        assert path_chunks[0].metadata["http_method"] == "get"
