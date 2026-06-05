"""Unit tests for JSON Schema tree walker."""

import pytest
from opencrane.rag.services.chunking_strategies.json_schema_tree_walker import JsonSchemaTreeWalker
from opencrane.shared.models.chunk import Chunk


class TestJsonSchemaTreeWalker:
    """Test JSON Schema tree walking and chunking."""

    def test_walk_creates_chunks(self):
        """Test that walk() creates chunks from JSON Schema."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://example.com/schemas/user.json",
            "title": "User Schema",
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "User's name"
                },
                "age": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "User's age"
                }
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json",
            original_yaml_file="schemas/user.json"
        )
        chunks = walker.walk()

        # Should create chunks for root metadata and each property
        assert len(chunks) > 0
        assert all(isinstance(chunk, Chunk) for chunk in chunks)
        assert all(chunk.chunk_type == "json_schema" for chunk in chunks)

    def test_chunk_has_dict_content(self):
        """Test that JSON Schema chunks have dict content, not string."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        # Content should be dict, not string
        assert all(isinstance(chunk.content, dict) for chunk in chunks)

    def test_chunk_metadata_structure(self):
        """Test that chunks have proper metadata structure."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://example.com/schemas/user.json",
            "title": "User Schema",
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        for chunk in chunks:
            assert "breadcrumb_path" in chunk.metadata
            assert "logical_parent" in chunk.metadata
            assert "neighbor_chunks" in chunk.metadata
            assert "schema_version" in chunk.metadata
            assert "schema_element" in chunk.metadata
            assert chunk.metadata["schema_type"] == "json_schema"

    def test_properties_chunking(self):
        """Test that properties are chunked separately."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "email": {"type": "string", "format": "email"}
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        # Should have one chunk per property
        property_chunks = [c for c in chunks if c.metadata.get("schema_element") == "properties"]
        assert len(property_chunks) == 3

        # Check property names are tracked
        property_names = [c.metadata.get("property_name") for c in property_chunks]
        assert "name" in property_names
        assert "age" in property_names
        assert "email" in property_names

    def test_definitions_chunking_new_style(self):
        """Test that $defs are chunked separately (new JSON Schema style)."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "$defs": {
                "address": {
                    "type": "object",
                    "properties": {
                        "street": {"type": "string"},
                        "city": {"type": "string"}
                    }
                },
                "phone": {
                    "type": "string",
                    "pattern": "^[0-9-]+$"
                }
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        # Should have one chunk per definition
        def_chunks = [c for c in chunks if c.metadata.get("schema_element") == "definitions"]
        assert len(def_chunks) == 2

        # Check definition names are tracked
        def_names = [c.metadata.get("definition_name") for c in def_chunks]
        assert "address" in def_names
        assert "phone" in def_names

    def test_definitions_chunking_old_style(self):
        """Test that definitions are chunked separately (old JSON Schema style)."""
        schema_dict = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "definitions": {
                "address": {
                    "type": "object",
                    "properties": {
                        "street": {"type": "string"}
                    }
                }
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        # Should have one chunk for the definition
        def_chunks = [c for c in chunks if c.metadata.get("schema_element") == "definitions"]
        assert len(def_chunks) == 1
        assert def_chunks[0].metadata.get("definition_name") == "address"

    def test_root_metadata_chunk(self):
        """Test that root schema metadata is extracted as a chunk."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://example.com/schemas/user.json",
            "title": "User Schema",
            "description": "A schema for user objects",
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        # Should have a root chunk
        root_chunks = [c for c in chunks if c.metadata.get("schema_element") == "root"]
        assert len(root_chunks) == 1

        root_chunk = root_chunks[0]
        assert "title" in root_chunk.content
        assert "description" in root_chunk.content
        assert root_chunk.content["title"] == "User Schema"

    def test_no_root_chunk_without_metadata(self):
        """Test that no root chunk is created if there's no significant metadata."""
        schema_dict = {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        # Should NOT have a root chunk (no title, description, etc.)
        root_chunks = [c for c in chunks if c.metadata.get("schema_element") == "root"]
        assert len(root_chunks) == 0

    def test_neighbor_relationships(self):
        """Test that sibling properties have neighbor relationships."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"}
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        property_chunks = [c for c in chunks if c.metadata.get("schema_element") == "properties"]
        assert len(property_chunks) == 2

        # Each property should reference the other as a neighbor
        for chunk in property_chunks:
            assert len(chunk.metadata["neighbor_chunks"]) == 1
            # Verify the neighbor exists
            neighbor_id = chunk.metadata["neighbor_chunks"][0]
            neighbor_exists = any(c.chunk_id == neighbor_id for c in property_chunks)
            assert neighbor_exists

    def test_breadcrumb_paths(self):
        """Test that breadcrumb paths are generated correctly."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            },
            "$defs": {
                "address": {"type": "object"}
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        # Check property breadcrumb
        prop_chunks = [c for c in chunks if c.metadata.get("property_name") == "name"]
        assert len(prop_chunks) == 1
        assert prop_chunks[0].metadata["breadcrumb_path"] == "properties.name"

        # Check definition breadcrumb
        def_chunks = [c for c in chunks if c.metadata.get("definition_name") == "address"]
        assert len(def_chunks) == 1
        assert def_chunks[0].metadata["breadcrumb_path"] == "$defs.address"

    def test_schema_id_in_metadata(self):
        """Test that schema ID is included in chunk metadata."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://example.com/schemas/user.json",
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        # All chunks should have the schema_id
        for chunk in chunks:
            assert chunk.metadata.get("schema_id") == "https://example.com/schemas/user.json"

    def test_token_count_calculated(self):
        """Test that token counts are calculated for chunks."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "User's full name"}
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        # All chunks should have token_count > 0
        for chunk in chunks:
            assert chunk.token_count > 0

    def test_boolean_property_schemas_skipped(self):
        """Test that boolean property values (true/false) are skipped."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "disabled": False,  # Boolean false means "disallow this property"
                "anyValue": True,   # Boolean true means "allow any value"
                "age": {"type": "integer"}
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        # Should only have chunks for name and age, not for disabled/anyValue
        property_chunks = [c for c in chunks if c.metadata.get("schema_element") == "properties"]
        property_names = [c.metadata.get("property_name") for c in property_chunks]

        assert len(property_chunks) == 2
        assert "name" in property_names
        assert "age" in property_names
        assert "disabled" not in property_names
        assert "anyValue" not in property_names

    def test_boolean_definition_schemas_skipped(self):
        """Test that boolean definition values are skipped."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "$defs": {
                "address": {"type": "object"},
                "disabled": False,  # Boolean means this definition is disabled
                "phone": {"type": "string"}
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        # Should only have chunks for address and phone, not for disabled
        def_chunks = [c for c in chunks if c.metadata.get("schema_element") == "definitions"]
        def_names = [c.metadata.get("definition_name") for c in def_chunks]

        assert len(def_chunks) == 2
        assert "address" in def_names
        assert "phone" in def_names
        assert "disabled" not in def_names

    def test_empty_property_schemas_skipped(self):
        """Empty ``{}`` property schemas mean "any value allowed" — same as a
        boolean ``true`` schema. They carry no semantic content, must not crash
        the walk, and must not produce empty-dict chunks (which the Chunk model
        rejects). Mirrors the AsyncAPI 3.1.0 binding objects, where bindings
        like ``amqp1: {}`` are declared without a constraining schema.
        """
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "amqp1": {},   # Empty schema — "any value allowed"
                "http": {},    # Empty schema — "any value allowed"
                "age": {"type": "integer"},
            },
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/bindings.json"
        )
        chunks = walker.walk()  # Must not raise

        property_chunks = [c for c in chunks if c.metadata.get("schema_element") == "properties"]
        property_names = [c.metadata.get("property_name") for c in property_chunks]

        assert len(property_chunks) == 2
        assert "name" in property_names
        assert "age" in property_names
        assert "amqp1" not in property_names
        assert "http" not in property_names

    def test_empty_definition_schemas_skipped(self):
        """Empty ``{}`` definition schemas are skipped like boolean schemas."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "$defs": {
                "address": {"type": "object"},
                "anyBinding": {},   # Empty schema — "any value allowed"
                "phone": {"type": "string"},
            },
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()  # Must not raise

        def_chunks = [c for c in chunks if c.metadata.get("schema_element") == "definitions"]
        def_names = [c.metadata.get("definition_name") for c in def_chunks]

        assert len(def_chunks) == 2
        assert "address" in def_names
        assert "phone" in def_names
        assert "anyBinding" not in def_names

    def test_recursive_chunking_for_large_property(self):
        """Test that large properties with nested schemas are chunked recursively."""
        # Create a large nested property that exceeds token threshold (800 tokens)
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "description": " ".join(["Configuration object with nested properties"] * 10),
                    "properties": {
                        "database": {
                            "type": "object",
                            "description": " ".join(["Database configuration with host port username password and connection settings"] * 10),
                            "properties": {
                                "host": {"type": "string", "description": " ".join(["Database host address for connection"] * 10)},
                                "port": {"type": "integer", "description": " ".join(["Database port number for connection"] * 10)},
                                "username": {"type": "string", "description": " ".join(["Database username for authentication"] * 10)},
                                "password": {"type": "string", "description": " ".join(["Database password for authentication"] * 10)},
                                "ssl": {"type": "boolean", "description": " ".join(["Enable SSL for database connection"] * 10)},
                                "timeout": {"type": "integer", "description": " ".join(["Connection timeout in milliseconds"] * 10)}
                            }
                        },
                        "cache": {
                            "type": "object",
                            "description": " ".join(["Cache configuration with enabled ttl and eviction policy settings"] * 10),
                            "properties": {
                                "enabled": {"type": "boolean", "description": " ".join(["Enable caching functionality"] * 10)},
                                "ttl": {"type": "integer", "description": " ".join(["Time to live for cache entries"] * 10)},
                                "maxSize": {"type": "integer", "description": " ".join(["Maximum cache size in entries"] * 10)}
                            }
                        },
                        "logging": {
                            "type": "object",
                            "description": " ".join(["Logging configuration with level format and output settings"] * 10),
                            "properties": {
                                "level": {"type": "string", "description": " ".join(["Logging level debug info warn error"] * 10)},
                                "format": {"type": "string", "description": " ".join(["Log message format string"] * 10)}
                            }
                        }
                    }
                }
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        property_chunks = [c for c in chunks if c.metadata.get("schema_element") == "properties"]

        # Should NOT have a chunk for "config" itself (it was too large)
        # Should have chunks for "database", "cache", and "logging" instead
        property_paths = [c.metadata.get("property_path") for c in property_chunks]

        assert "config" not in property_paths, f"Large parent 'config' should not be chunked. Found paths: {property_paths}"
        assert "config.database" in property_paths, "Nested 'database' should be chunked separately"
        assert "config.cache" in property_paths, "Nested 'cache' should be chunked separately"
        assert "config.logging" in property_paths, "Nested 'logging' should be chunked separately"

    def test_recursive_chunking_token_limits(self):
        """Test that recursively chunked properties stay under token limit."""
        # Create schema with large nested property
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "largeConfig": {
                    "type": "object",
                    "description": " ".join(["Large config"] * 100),
                    "properties": {
                        "setting1": {"type": "string", "description": " ".join(["Setting 1"] * 20)},
                        "setting2": {"type": "string", "description": " ".join(["Setting 2"] * 20)},
                        "setting3": {"type": "string", "description": " ".join(["Setting 3"] * 20)}
                    }
                }
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        # Verify all chunks are under or reasonably close to the limit
        from opencrane.rag.services.chunking_strategies.yaml_tree_walker import MAX_CHUNK_TOKEN_LIMIT
        for chunk in chunks:
            # Allow some tolerance for YAML serialization overhead
            assert chunk.token_count <= MAX_CHUNK_TOKEN_LIMIT + 100, \
                f"Chunk {chunk.metadata.get('property_path')} has {chunk.token_count} tokens (limit: {MAX_CHUNK_TOKEN_LIMIT})"

    def test_small_property_not_recursively_chunked(self):
        """Test that small properties are not recursively chunked even if they have nested properties."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "smallConfig": {
                    "type": "object",
                    "description": "Small config",
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "mode": {"type": "string"}
                    }
                }
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        property_chunks = [c for c in chunks if c.metadata.get("schema_element") == "properties"]
        property_paths = [c.metadata.get("property_path") for c in property_chunks]

        # Small property should be chunked as-is with nested content
        assert "smallConfig" in property_paths
        assert "smallConfig.enabled" not in property_paths
        assert "smallConfig.mode" not in property_paths

        # Verify the chunk includes nested properties in content
        small_config_chunk = next(c for c in property_chunks if c.metadata.get("property_path") == "smallConfig")
        assert "properties" in small_config_chunk.content
        assert "enabled" in small_config_chunk.content["properties"]

    def test_recursive_chunking_breadcrumb_paths(self):
        """Test that recursively chunked properties have correct breadcrumb paths."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "description": " ".join(["Configuration object with many nested properties and settings for application"] * 70),
                    "properties": {
                        "database": {
                            "type": "object",
                            "description": "Database configuration settings",
                            "properties": {
                                "host": {"type": "string"},
                                "port": {"type": "integer"}
                            }
                        },
                        "cache": {
                            "type": "object",
                            "description": "Cache configuration settings",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "ttl": {"type": "integer"}
                            }
                        }
                    }
                }
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        property_chunks = [c for c in chunks if c.metadata.get("schema_element") == "properties"]

        # Find nested property chunks
        database_chunk = next((c for c in property_chunks if c.metadata.get("property_path") == "config.database"), None)
        cache_chunk = next((c for c in property_chunks if c.metadata.get("property_path") == "config.cache"), None)

        assert database_chunk is not None
        assert cache_chunk is not None

        # Verify breadcrumb paths
        assert database_chunk.metadata["breadcrumb_path"] == "properties.config.properties.database"
        assert cache_chunk.metadata["breadcrumb_path"] == "properties.config.properties.cache"

    def test_recursive_chunking_for_definitions(self):
        """Test that large definitions are chunked recursively."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "$defs": {
                "largeAddress": {
                    "type": "object",
                    "description": " ".join(["Address definition with street city state zip country and additional location information"] * 70),
                    "properties": {
                        "street": {
                            "type": "string",
                            "description": "Street name and number for the address"
                        },
                        "city": {
                            "type": "string",
                            "description": "City name for the address location"
                        },
                        "country": {
                            "type": "string",
                            "description": "Country name for the address location"
                        }
                    }
                }
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/user.json"
        )
        chunks = walker.walk()

        # Should not have a chunk for the large definition itself
        def_chunks = [c for c in chunks if c.metadata.get("schema_element") == "definitions"]
        def_names = [c.metadata.get("definition_name") for c in def_chunks]

        assert "largeAddress" not in def_names, "Large definition should not be chunked"

        # Should have chunks for the nested properties instead
        property_chunks = [c for c in chunks if c.metadata.get("schema_element") == "properties"]
        assert len(property_chunks) == 3  # street, city, country

        property_names = [c.metadata.get("property_name") for c in property_chunks]
        assert "street" in property_names
        assert "city" in property_names
        assert "country" in property_names

    def test_recursive_chunking_for_array_items(self):
        """Test that large array items with properties are chunked recursively."""
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "volumes": {
                    "type": "array",
                    "description": " ".join(["Array of volume configurations for storage management with complex nested properties"] * 50),
                    "items": {
                        "type": "object",
                        "description": " ".join(["Volume item definition with name path size and mount options"] * 50),
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Volume name identifier"
                            },
                            "path": {
                                "type": "string",
                                "description": "Volume mount path"
                            },
                            "size": {
                                "type": "string",
                                "description": "Volume size specification"
                            }
                        }
                    }
                }
            }
        }

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/config.json"
        )
        chunks = walker.walk()

        property_chunks = [c for c in chunks if c.metadata.get("schema_element") == "properties"]

        # Should NOT have a chunk for "volumes" itself (it was too large with items)
        # Should have chunks for items properties: "name", "path", "size"
        property_paths = [c.metadata.get("property_path") for c in property_chunks]

        assert "volumes" not in property_paths, f"Large array parent 'volumes' should not be chunked. Found paths: {property_paths}"
        assert "volumes.items.name" in property_paths, "Array item property 'name' should be chunked separately"
        assert "volumes.items.path" in property_paths, "Array item property 'path' should be chunked separately"
        assert "volumes.items.size" in property_paths, "Array item property 'size' should be chunked separately"

        # Verify token counts are reasonable
        for chunk in property_chunks:
            assert chunk.token_count <= 900, f"Chunk {chunk.metadata['property_path']} exceeds limit: {chunk.token_count} tokens"

    def test_recursive_chunking_for_array_items_in_definitions(self):
        """Test that large array items in definitions are chunked recursively."""
        # Create descriptions long enough to exceed token limits
        long_property_desc = " ".join(["word"] * 200)
        schema_dict = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "$defs": {
                "volumeList": {
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

        walker = JsonSchemaTreeWalker(
            schema_dict,
            source_url="https://github.com/org/repo/blob/main/schemas/config.json"
        )
        chunks = walker.walk()

        # Find chunks from $defs (they'll have schema_element="properties" when recursed from array items)
        defs_chunks = [c for c in chunks if "$defs.volumeList" in c.metadata.get("breadcrumb_path", "")]

        # Should have chunks for items properties: "name", "path", "size"
        # Should NOT have a chunk for "volumeList" itself (it was too large with items)
        breadcrumbs = [c.metadata.get("breadcrumb_path") for c in defs_chunks]

        assert "$defs.volumeList" in str(breadcrumbs), "Should have chunks from $defs.volumeList"
        assert "$defs.volumeList.items.properties.name" in breadcrumbs, "Array item property 'name' should be chunked separately"
        assert "$defs.volumeList.items.properties.path" in breadcrumbs, "Array item property 'path' should be chunked separately"
        assert "$defs.volumeList.items.properties.size" in breadcrumbs, "Array item property 'size' should be chunked separately"

        # Should NOT have a standalone volumeList chunk
        volumelist_only = "$defs.volumeList" in breadcrumbs and len([b for b in breadcrumbs if b == "$defs.volumeList"]) > 0
        assert not volumelist_only, f"Large array definition 'volumeList' should not have its own chunk. Found breadcrumbs: {breadcrumbs}"

        # Verify token counts are reasonable
        for chunk in defs_chunks:
            assert chunk.token_count <= 900, f"Chunk {chunk.metadata.get('breadcrumb_path')} exceeds limit: {chunk.token_count} tokens"
