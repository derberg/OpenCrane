"""Unit tests for K8s CRD tree walker."""

import pytest
from opencrane.rag.services.chunking_strategies.k8s_crd_tree_walker import K8sCRDTreeWalker
from opencrane.shared.models.chunk import Chunk


class TestK8sCRDTreeWalker:
    """Test CRD tree walking and chunking."""
    
    def test_walk_crd_creates_chunks(self):
        """Test that walk() creates chunks from CRD YAML."""
        crd_dict = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "metadata": {
                "name": "smcs.smc.example.com"
            },
            "spec": {
                "group": "smc.example.com",
                "names": {
                    "kind": "SMC",
                    "plural": "smcs"
                },
                "versions": [
                    {
                        "name": "v1",
                        "schema": {
                            "openAPIV3Schema": {
                                "type": "object",
                                "properties": {
                                    "spec": {
                                        "type": "object",
                                        "properties": {
                                            "replicas": {
                                                "type": "integer",
                                                "description": "Number of replicas"
                                            },
                                            "image": {
                                                "type": "string",
                                                "description": "Container image"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                ]
            }
        }
        
        walker = K8sCRDTreeWalker(
            crd_dict,
            source_url="https://github.com/org/repo/blob/main/docs/crd.md",
            original_yaml_file="crds/smc.yaml"
        )
        chunks = walker.walk()
        
        # Should create chunks for each top-level property
        assert len(chunks) > 0
        assert all(isinstance(chunk, Chunk) for chunk in chunks)
        assert all(chunk.chunk_type == "crd_definition" for chunk in chunks)
    
    def test_crd_chunk_has_dict_content(self):
        """Test that CRD chunks have dict content, not string."""
        crd_dict = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "spec": {
                "versions": [
                    {
                        "name": "v1",
                        "schema": {
                            "openAPIV3Schema": {
                                "properties": {
                                    "spec": {
                                        "properties": {
                                            "replicas": {
                                                "type": "integer"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                ]
            }
        }
        
        walker = K8sCRDTreeWalker(
            crd_dict,
            source_url="https://github.com/org/repo/blob/main/docs/crd.md"
        )
        chunks = walker.walk()
        
        # Content should be dict, not string
        assert any(isinstance(chunk.content, dict) for chunk in chunks)
    
    def test_crd_chunk_metadata_required_fields(self):
        """Test that CRD chunks have all required metadata fields."""
        crd_dict = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "metadata": {
                "name": "smcs.smc.example.com"
            },
            "spec": {
                "group": "smc.example.com",
                "names": {
                    "kind": "SMC"
                },
                "versions": [
                    {
                        "name": "v1",
                        "schema": {
                            "openAPIV3Schema": {
                                "properties": {
                                    "spec": {
                                        "properties": {
                                            "replicas": {
                                                "type": "integer"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                ]
            }
        }
        
        walker = K8sCRDTreeWalker(
            crd_dict,
            source_url="https://github.com/org/repo/blob/main/docs/crd.md"
        )
        chunks = walker.walk()
        
        # All chunks should have required CRD metadata
        for chunk in chunks:
            assert "breadcrumb_path" in chunk.metadata
            assert "logical_parent" in chunk.metadata
            assert "neighbor_chunks" in chunk.metadata
            assert "crd_kind" in chunk.metadata
            assert "crd_api_version" in chunk.metadata
            assert "crd_version" in chunk.metadata
            assert "crd_property_path" in chunk.metadata
            assert chunk.metadata["source_url"] == "https://github.com/org/repo/blob/main/docs/crd.md"
    
    def test_nested_property_chunking(self):
        """Test that nested properties are included in parent chunk, not as separate chunks."""
        crd_dict = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "spec": {
                "versions": [
                    {
                        "name": "v1",
                        "schema": {
                            "openAPIV3Schema": {
                                "properties": {
                                    "spec": {
                                        "properties": {
                                            "config": {
                                                "properties": {
                                                    "database": {
                                                        "properties": {
                                                            "host": {"type": "string"},
                                                            "port": {"type": "integer"}
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                ]
            }
        }
        
        walker = K8sCRDTreeWalker(
            crd_dict,
            source_url="https://github.com/org/repo/blob/main/docs/crd.md"
        )
        chunks = walker.walk()
        
        # Should only have one chunk for config (not separate chunks for nested database)
        assert len(chunks) == 1
        config_chunk = chunks[0]
        assert config_chunk.metadata.get("crd_property_path") == "spec.config"
        
        # Database should be included in config chunk's content
        assert "properties" in config_chunk.content
        assert "database" in config_chunk.content["properties"]
        assert "properties" in config_chunk.content["properties"]["database"]
        assert "host" in config_chunk.content["properties"]["database"]["properties"]
    
    def test_chunk_id_generation(self):
        """Test that each chunk gets a unique chunk_id."""
        crd_dict = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "spec": {
                "versions": [
                    {
                        "name": "v1",
                        "schema": {
                            "openAPIV3Schema": {
                                "properties": {
                                    "spec": {
                                        "properties": {
                                            "replicas": {"type": "integer"},
                                            "image": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                ]
            }
        }
        
        walker = K8sCRDTreeWalker(
            crd_dict,
            source_url="https://github.com/org/repo/blob/main/docs/crd.md"
        )
        chunks = walker.walk()
        
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        # All chunks should have chunk_id
        assert all(cid is not None for cid in chunk_ids)
        # All chunk_ids should be unique
        assert len(chunk_ids) == len(set(chunk_ids))


def _big_object_properties(prefix: str, count: int = 60) -> dict:
    """Build many sub-properties with long descriptions to exceed the token limit."""
    desc = (
        "This is a deliberately long description used to inflate the token "
        "count of the enclosing property so that recursive chunking is "
        "triggered when the YAML is serialised and measured. " * 3
    )
    return {
        f"{prefix}_field_{i}": {"type": "string", "description": desc}
        for i in range(count)
    }


class TestK8sCRDRecursiveChunking:
    """Cover the recursive-chunking branches of _walk_properties."""

    def test_large_nested_properties_recurse(self):
        """A large object property recurses into its nested properties (lines 104-117)."""
        crd_dict = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "spec": {
                "group": "example.com",
                "names": {"kind": "Big"},
                "versions": [
                    {
                        "name": "v1",
                        "schema": {
                            "openAPIV3Schema": {
                                "properties": {
                                    "spec": {
                                        "properties": {
                                            "config": {
                                                "type": "object",
                                                "properties": _big_object_properties("cfg"),
                                            }
                                        }
                                    }
                                }
                            }
                        },
                    }
                ],
            },
        }

        walker = K8sCRDTreeWalker(
            crd_dict,
            source_url="https://github.com/org/repo/blob/main/docs/crd.md",
        )
        chunks = walker.walk()

        # The large 'config' object is split: a chunk per nested field, and no
        # standalone chunk for the parent 'config' object itself.
        assert len(chunks) > 1
        paths = {c.metadata["crd_property_path"] for c in chunks}
        assert "spec.config" not in paths
        assert any(p.startswith("spec.config.cfg_field_") for p in paths)

    def test_large_array_items_recurse(self):
        """A large array property recurses into items.properties (lines 118-134)."""
        crd_dict = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "spec": {
                "group": "example.com",
                "names": {"kind": "Big"},
                "versions": [
                    {
                        "name": "v1",
                        "schema": {
                            "openAPIV3Schema": {
                                "properties": {
                                    "spec": {
                                        "properties": {
                                            "entries": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": _big_object_properties("item"),
                                                },
                                            }
                                        }
                                    }
                                }
                            }
                        },
                    }
                ],
            },
        }

        walker = K8sCRDTreeWalker(
            crd_dict,
            source_url="https://github.com/org/repo/blob/main/docs/crd.md",
        )
        chunks = walker.walk()

        assert len(chunks) > 1
        paths = {c.metadata["crd_property_path"] for c in chunks}
        # No standalone chunk for the array property itself.
        assert "spec.entries" not in paths
        # Nested item properties are chunked under spec.entries.items.
        assert any(p.startswith("spec.entries.items.item_field_") for p in paths)

    def test_large_array_items_without_properties_creates_chunk(self):
        """A large array whose items lack properties still yields a single chunk."""
        long_desc = "long text to inflate tokens " * 200
        crd_dict = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "spec": {
                "group": "example.com",
                "names": {"kind": "Big"},
                "versions": [
                    {
                        "name": "v1",
                        "schema": {
                            "openAPIV3Schema": {
                                "properties": {
                                    "spec": {
                                        "properties": {
                                            "tags": {
                                                "type": "array",
                                                "description": long_desc,
                                                "items": {"type": "string"},
                                            }
                                        }
                                    }
                                }
                            }
                        },
                    }
                ],
            },
        }

        walker = K8sCRDTreeWalker(
            crd_dict,
            source_url="https://github.com/org/repo/blob/main/docs/crd.md",
        )
        chunks = walker.walk()

        # items has no 'properties', so the array property itself becomes a chunk.
        paths = {c.metadata["crd_property_path"] for c in chunks}
        assert "spec.tags" in paths


class TestYamlTreeWalkerBaseMethods:
    """Cover base-class helpers via the concrete K8s walker."""

    def _make_walker(self):
        crd_dict = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "spec": {"group": "example.com", "names": {"kind": "X"}, "versions": []},
        }
        return K8sCRDTreeWalker(
            crd_dict, source_url="https://github.com/org/repo/blob/main/docs/crd.md"
        )

    def test_sanitize_yaml_content_converts_datetime(self):
        """datetime/date values inside dicts are converted to ISO strings (line 54)."""
        from datetime import datetime, date

        walker = self._make_walker()
        content = {
            "created": datetime(2024, 1, 2, 3, 4, 5),
            "day": date(2024, 6, 29),
            "nested": {"when": datetime(2020, 12, 31, 23, 59, 59)},
            "list": [date(1999, 1, 1)],
        }
        result = walker._sanitize_yaml_content(content)
        assert result["created"] == "2024-01-02T03:04:05"
        assert result["day"] == "2024-06-29"
        assert result["nested"]["when"] == "2020-12-31T23:59:59"
        assert result["list"][0] == "1999-01-01"

    def test_should_chunk_recursively_large_but_unchunkable_returns_false(self):
        """Large content with no nested structure does not recurse (line 187)."""
        walker = self._make_walker()
        # A dict with a huge scalar value but no properties/items/composition keys.
        content = {"type": "string", "description": "padding text " * 500}
        token_count = walker._calculate_token_count(content)
        assert token_count > 800
        assert walker._should_chunk_recursively(content, token_count) is False
