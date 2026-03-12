"""Tests to achieve 100% code coverage for remaining uncovered lines."""

import pytest
from pathlib import Path
from unittest.mock import Mock
from opencrane.shared.models.chunk import Chunk
from opencrane.shared.models.vector_chunk import EmbeddingRecord
from opencrane.rag.services.chunking_strategies.openapi_tree_walker import OpenAPITreeWalker
from opencrane.rag.services.code_chunker import CodeChunkingStrategy
from opencrane.mcp.services.embeddings import EmbeddingService
from opencrane.rag.services.yaml_chunker import YamlChunkingStrategy


class TestChunkModelCoverage:
    """Cover chunk.py line 40 - code_snippet validation."""
    
    def test_code_snippet_missing_language_metadata(self):
        """Test validation error when code_snippet is missing language in metadata."""
        with pytest.raises(Exception, match="language"):
            Chunk(
                content="print('hello')",
                source_file="test.py",
                chunk_type="code_snippet",
                metadata={},  # Missing 'language'
                token_count=5
            )


class TestVectorChunkCoverage:
    """Cover vector_chunk.py line 46 - dict content serialization."""
    
    def test_vector_chunk_with_dict_content(self):
        """Test VectorChunk.from_chunk_and_embedding with dict content (line 46)."""
        from opencrane.shared.models.vector_chunk import VectorChunk, EmbeddingRecord
        
        chunk = Chunk(
            chunk_id="test-id",
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
            token_count=10
        )
        
        embedding_record = EmbeddingRecord(
            chunk_index=0,
            chunk_id="test-id",
            vector=[0.1, 0.2, 0.3]
        )
        
        vector_chunk = VectorChunk.from_chunk_and_embedding(chunk, embedding_record)
        # Should serialize dict content as JSON string (line 46)
        assert isinstance(vector_chunk.content, str)
        assert '"test"' in vector_chunk.content


class TestOpenAPITreeWalkerCoverage:
    """Cover openapi_tree_walker.py lines 29 and 271."""
    
    def test_openapi_version_unknown(self):
        """Test OpenAPI walker with no version field (line 29)."""
        # Document with no openapi or swagger field
        walker = OpenAPITreeWalker(
            yaml_dict={"info": {"title": "Test"}},  # No version field
            source_url="https://example.com"
        )
        assert walker.openapi_version == "unknown"
    
    def test_openapi_with_original_yaml_file(self):
        """Test OpenAPI chunk with original_yaml_file metadata (line 271)."""
        walker = OpenAPITreeWalker(
            yaml_dict={
                "openapi": "3.0.0",
                "info": {"title": "Test", "version": "1.0.0"}
            },
            source_url="https://example.com",
            original_yaml_file="original.yaml"
        )
        chunks = walker.walk()
        # Should have original_yaml_file in metadata
        assert any("original_yaml_file" in c.metadata for c in chunks)


class TestCodeChunkerCoverage:
    """Cover code_chunker.py line 83."""
    
    def test_code_node_with_yaml_crd_returns_list(self):
        """Test raw code node with YAML CRD that returns list (line 83)."""
        strategy = CodeChunkingStrategy()
        source_file = Path("test.md")
        
        class Node:
            # Raw code node (not fenced) with YAML CRD content
            # Should be processed by tree walker and return list
            text = """apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: tests.example.com
spec:
  group: example.com
  names:
    kind: Test
    plural: tests
  scope: Namespaced
  versions:
  - name: v1
    served: true
    storage: true
    schema:
      openAPIV3Schema:
        type: object
        properties:
          spec:
            type: object
            properties:
              replicas:
                type: integer
                description: Number of replicas
"""
            node_type = "code"
            language = "yaml"
            source_url = "https://example.com/test.md"
        
        chunks = strategy.process(Node(), source_file)
        # Should use tree walker which returns list (line 83)
        assert len(chunks) >= 1
        # Should have CRD chunks
        crd_chunks = [c for c in chunks if c.chunk_type == 'crd_definition']
        assert len(crd_chunks) > 0
    
    def test_code_node_type_single_chunk(self):
        """Test fenced code block returns single chunk (line 95 in else clause at 96-98)."""
        strategy = CodeChunkingStrategy()
        source_file = Path("test.md")
        
        class Node:
            # Fenced Python code block - should return single Chunk, not list
            text = """```python
def hello():
    print("world")
```"""
            node_type = "text"
        
        chunks = strategy.process(Node(), source_file)
        # Should handle single chunk path (line 95-96)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "code_snippet"
        assert chunks[0].metadata.get('language') == 'python'
    
    def test_yaml_k8s_crd_detection(self):
        """Test K8s CRD detection in YAML code block (line 172)."""
        strategy = CodeChunkingStrategy()
        source_file = Path("test.md")
        
        class Node:
            text = """```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: tests.example.com
spec:
  group: example.com
  versions:
  - name: v1
    served: true
    storage: true
    schema:
      openAPIV3Schema:
        type: object
        properties:
          spec:
            type: object
            properties:
              replicas:
                type: integer
  scope: Namespaced
  names:
    plural: tests
    singular: test
    kind: Test
```"""
            source_url = "https://github.com/example/repo/blob/main/crd.yaml"
        
        chunks = strategy.process(Node(), source_file)
        # Should use K8sCRDTreeWalker (line 172)
        assert len(chunks) > 0
        assert any(c.chunk_type == "crd_definition" for c in chunks)


class TestEmbeddingsServiceCoverage:
    """Cover embeddings.py lines 32 and 76."""
    
    def test_mock_vector_with_dict(self):
        """Test _mock_vector with dict input (line 32)."""
        service = EmbeddingService(model_name="mock")
        vector = service._mock_vector({"test": "data"}, 768)
        assert len(vector) == 768
        assert all(isinstance(v, float) for v in vector)
    
    def test_mock_vector_with_list(self):
        """Test _mock_vector with list input (line 32)."""
        service = EmbeddingService(model_name="mock")
        vector = service._mock_vector([{"item": 1}], 768)
        assert len(vector) == 768
    
    def test_generate_embeddings_with_dict_content(self):
        """Test generate_embeddings with dict/list chunk content (line 76)."""
        service = EmbeddingService(model_name="mock")
        
        chunks = [
            {
                "content": {"test": "data"},
                "source_file": "test.yaml",
                "chunk_type": "crd_definition",
                "metadata": {},
                "token_count": 10
            },
            {
                "content": [{"item": 1}],
                "source_file": "test.yaml",
                "chunk_type": "openapi_spec",
                "metadata": {},
                "token_count": 8
            }
        ]
        
        result = service.generate_embeddings(chunks)
        assert result.model == "mock"
        assert len(result.embeddings) == 2


class TestYamlChunkerCoverage:
    """Cover yaml_chunker.py line 110 - K8s CRD path."""
    
    def test_k8s_crd_tree_walker_path(self):
        """Test that K8s CRD takes the walker path (line 110)."""
        strategy = YamlChunkingStrategy()
        source_file = Path("crd.yaml")
        
        # Full K8s CRD
        node = Mock()
        node.text = """apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: tests.example.com
spec:
  group: example.com
  versions:
  - name: v1
    served: true
    storage: true
    schema:
      openAPIV3Schema:
        type: object
        properties:
          spec:
            type: object
            properties:
              replicas:
                type: integer
                minimum: 1
  scope: Namespaced
  names:
    plural: tests
    singular: test
    kind: Test
"""
        
        chunks = strategy.process(node, source_file)
        # Should use K8sCRDTreeWalker, creating multiple chunks
        assert len(chunks) > 0
        assert all(c.chunk_type == "crd_definition" for c in chunks)
        # Should have tree walker metadata
        assert all("breadcrumb_path" in c.metadata for c in chunks)

