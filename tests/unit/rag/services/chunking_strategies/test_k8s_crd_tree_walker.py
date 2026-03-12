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
