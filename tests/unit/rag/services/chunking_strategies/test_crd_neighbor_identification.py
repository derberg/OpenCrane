"""Unit tests for CRD neighbor identification."""

import pytest
from opencrane.rag.services.chunking_strategies.k8s_crd_tree_walker import K8sCRDTreeWalker


class TestCRDNeighborIdentification:
    """Test neighbor chunk identification for CRD properties."""
    
    def test_sibling_properties_have_neighbors(self):
        """Test that sibling properties reference each other as neighbors."""
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
                                            "image": {"type": "string"},
                                            "config": {"type": "object"}
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
        
        # Find chunks for sibling properties (replicas, image, config)
        sibling_chunks = [c for c in chunks if any(prop in c.metadata.get("crd_property_path", "") for prop in ["replicas", "image", "config"])]
        
        # Each sibling should have neighbors
        for chunk in sibling_chunks:
            neighbors = chunk.metadata.get("neighbor_chunks", [])
            # Should have at least 1 neighbor (the other siblings)
            assert len(neighbors) >= 1
            # Neighbors should be UUIDs
            assert all(isinstance(n, str) for n in neighbors)
    
    def test_neighbors_are_mutual(self):
        """Test that neighbor relationships are mutual."""
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
        
        # Build chunk map
        chunk_map = {c.chunk_id: c for c in chunks}
        
        # For each chunk, verify neighbors list it back
        for chunk in chunks:
            neighbors = chunk.metadata.get("neighbor_chunks", [])
            for neighbor_id in neighbors:
                if neighbor_id in chunk_map:
                    neighbor_chunk = chunk_map[neighbor_id]
                    neighbor_neighbors = neighbor_chunk.metadata.get("neighbor_chunks", [])
                    # Neighbor should list this chunk back
                    assert chunk.chunk_id in neighbor_neighbors
    
    def test_nested_properties_have_correct_neighbors(self):
        """Test that nested properties only reference siblings, not cousins."""
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
                                            },
                                            "replicas": {"type": "integer"}
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
        
        # Find database.host and database.port chunks
        db_chunks = [c for c in chunks if "database" in c.metadata.get("breadcrumb_path", "")]
        host_chunk = next((c for c in db_chunks if "host" in c.metadata.get("crd_property_path", "")), None)
        port_chunk = next((c for c in db_chunks if "port" in c.metadata.get("crd_property_path", "")), None)
        
        if host_chunk and port_chunk:
            # host and port should be neighbors (same parent: database)
            assert port_chunk.chunk_id in host_chunk.metadata.get("neighbor_chunks", [])
            assert host_chunk.chunk_id in port_chunk.metadata.get("neighbor_chunks", [])
            
            # They should NOT list replicas as neighbor (different parent)
            replicas_chunk = next((c for c in chunks if "replicas" in c.metadata.get("crd_property_path", "")), None)
            if replicas_chunk:
                assert replicas_chunk.chunk_id not in host_chunk.metadata.get("neighbor_chunks", [])
