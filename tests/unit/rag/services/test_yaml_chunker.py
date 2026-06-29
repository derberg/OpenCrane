"""Unit tests for YamlChunkingStrategy."""

import pytest
from pathlib import Path
from unittest.mock import Mock
from opencrane.rag.services.yaml_chunker import YamlChunkingStrategy
from opencrane.shared.models.chunk import Chunk


class TestYamlChunkingStrategy:
    """Test cases for YAML chunking strategy."""

    def test_can_process_yaml_node(self):
        """Test that strategy can process YAML nodes."""
        strategy = YamlChunkingStrategy()
        yaml_node = Mock()
        yaml_node.text = "apiVersion: v1\nkind: Pod"
        assert strategy.can_process(yaml_node)

    def test_can_process_yaml_with_document_separator(self):
        """Test that strategy can process YAML starting with ---."""
        strategy = YamlChunkingStrategy()
        yaml_node = Mock()
        yaml_node.text = "---\napiVersion: v1\nkind: Pod"
        assert strategy.can_process(yaml_node)

    def test_cannot_process_non_yaml_node(self):
        """Test that strategy cannot process non-YAML nodes."""
        strategy = YamlChunkingStrategy()
        text_node = Mock()
        text_node.text = "This is plain text."
        assert not strategy.can_process(text_node)

    def test_cannot_process_node_without_text_attr(self):
        """Test that strategy cannot process nodes without text attribute."""
        strategy = YamlChunkingStrategy()
        node_without_text = Mock(spec=[])  # Mock with no text attribute
        assert not strategy.can_process(node_without_text)

    def test_process_small_yaml(self):
        """Test processing small YAML."""
        strategy = YamlChunkingStrategy()
        source_file = Path("test.yaml")

        yaml_content = """apiVersion: v1
kind: Pod
metadata:
  name: test-pod
spec:
  containers:
  - name: test
    image: nginx
"""
        node = Mock()
        node.text = yaml_content

        chunks = strategy.process(node, source_file)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "yaml_content"
        assert "apiVersion: v1" in chunks[0].content
        assert chunks[0].metadata["root_identity"]["kind"] == "Pod"

    def test_process_small_yaml_propagates_source_url(self):
        """If node provides source_url (from fallback splitter), include it in metadata."""
        strategy = YamlChunkingStrategy()
        source_file = Path("llmstxt/llms-full.txt")

        node = Mock()
        node.text = """apiVersion: v1\nkind: Pod\nmetadata:\n  name: test\n"""
        node.source_url = "https://github.com/my-org/proj/blob/main/docs/b.md"

        chunks = strategy.process(node, source_file)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "yaml_content"
        assert chunks[0].metadata["source_url"] == node.source_url

    def test_process_large_yaml_splits(self):
        """Test processing large YAML splits by top-level keys."""
        strategy = YamlChunkingStrategy()
        source_file = Path("test.yaml")

        # Create YAML that exceeds 1000 tokens (threshold)
        # This creates a large spec section with many containers
        large_yaml = """apiVersion: v1
kind: Pod
metadata:
  name: large-test-pod
spec:
  containers:"""
        
        # Add many containers to exceed token threshold
        for i in range(50):
            large_yaml += f"""
  - name: container-{i}
    image: nginx:{i}
    ports:
    - containerPort: {8080 + i}
    env:
    - name: ENV_VAR_{i}
      value: "value_{i}"
    resources:
      limits:
        cpu: "1"
        memory: "1Gi"
      requests:
        cpu: "500m"
        memory: "512Mi\""""
        
        node = Mock()
        node.text = large_yaml
        node.source_url = "https://github.com/my-org/proj/blob/main/docs/large.yaml"

        chunks = strategy.process(node, source_file)
        # Legacy YAML splitter no longer used - simple Pod goes to yaml_content
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "yaml_content"
        assert chunks[0].metadata.get("source_url") == node.source_url

    def test_process_invalid_yaml(self):
        """Test processing invalid YAML returns empty list."""
        strategy = YamlChunkingStrategy()
        source_file = Path("test.yaml")

        invalid_yaml = """apiVersion: v1
kind: Pod
metadata:
  name: test-pod
spec:
  containers:
    - name: test
      image: nginx
      ports:
        - containerPort: 80
      # Invalid YAML - missing closing bracket
      env: [
        name: ENV_VAR
        value: "test"
"""
        node = Mock()
        node.text = invalid_yaml

        chunks = strategy.process(node, source_file)
        assert chunks == []

    def test_process_empty_yaml(self):
        """Test processing empty YAML returns empty list."""
        strategy = YamlChunkingStrategy()
        source_file = Path("test.yaml")

        # YAML that parses to empty
        empty_yaml = "# Just a comment\n"
        node = Mock()
        node.text = empty_yaml

        chunks = strategy.process(node, source_file)
        assert chunks == []

    def test_process_small_openapi_spec(self):
        """Test processing small OpenAPI spec."""
        strategy = YamlChunkingStrategy()
        source_file = Path("api.yaml")

        openapi_content = """openapi: 3.0.0
info:
  title: Test API
  version: 1.0.0
paths:
  /users:
    get:
      summary: Get users
"""
        node = Mock()
        node.text = openapi_content

        chunks = strategy.process(node, source_file)
        # OpenAPI specs are now processed by tree walker when feature flag is enabled
        assert len(chunks) > 0
        # Tree walker creates multiple chunks (info, paths, etc.)
        assert any(c.chunk_type == "openapi_spec" for c in chunks)
        # Check that we have structured metadata from tree walker
        openapi_chunks = [c for c in chunks if c.chunk_type == "openapi_spec"]
        assert len(openapi_chunks) > 0

    def test_process_large_openapi_spec_splits(self):
        """Test processing large OpenAPI spec splits by top-level keys."""
        strategy = YamlChunkingStrategy()
        source_file = Path("api.yaml")

        # Create large OpenAPI spec that exceeds 1000 tokens
        large_openapi = """openapi: 3.0.0
info:
  title: Large API
  version: 1.0.0
  description: A very large API specification
paths:"""
        
        # Add many paths to exceed token threshold
        for i in range(50):
            large_openapi += f"""
  /resource{i}:
    get:
      summary: Get resource {i}
      operationId: getResource{i}
      responses:
        '200':
          description: Success
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: integer
                  name:
                    type: string
    post:
      summary: Create resource {i}
      operationId: createResource{i}
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
      responses:
        '201':
          description: Created"""
        
        node = Mock()
        node.text = large_openapi

        chunks = strategy.process(node, source_file)
        # Tree walker processes OpenAPI into multiple element-based chunks
        assert len(chunks) > 1
        assert all(c.chunk_type == "openapi_spec" for c in chunks)
        # All chunks should have tree walker metadata
        for chunk in chunks:
            assert "breadcrumb_path" in chunk.metadata
            assert "logical_parent" in chunk.metadata
            assert "neighbor_chunks" in chunk.metadata
            assert "openapi_element" in chunk.metadata

    def test_process_swagger_2_spec(self):
        """Test processing Swagger 2.0 spec."""
        strategy = YamlChunkingStrategy()
        source_file = Path("api.yaml")

        swagger_content = """swagger: "2.0"
info:
  title: Swagger API
  version: 2.0.0
paths:
  /users:
    get:
      summary: Get users
"""
        node = Mock()
        node.text = swagger_content

        chunks = strategy.process(node, source_file)
        # Swagger 2.0 is processed by tree walker
        assert len(chunks) > 0
        assert any(c.chunk_type == "openapi_spec" for c in chunks)
        # Tree walker provides structured metadata
        openapi_chunks = [c for c in chunks if c.chunk_type == "openapi_spec"]
        assert len(openapi_chunks) > 0
        for chunk in openapi_chunks:
            assert "breadcrumb_path" in chunk.metadata

    def test_process_fenced_openapi_spec(self):
        """Test processing OpenAPI spec embedded in markdown fenced code block."""
        strategy = YamlChunkingStrategy()
        source_file = Path("test.md")

        # OpenAPI embedded in markdown code fence (like in llms-full.txt)
        fenced_content = """```yaml
openapi: 3.0.0
info:
  title: Test API
  version: 1.0.0
paths:
  /test:
    get:
      summary: Test endpoint
      responses:
        '200':
          description: Success
```"""
        
        node = Mock()
        node.text = fenced_content
        node.source_url = "https://github.com/test/test.yaml"

        chunks = strategy.process(node, source_file)
        # Should strip fences and process as OpenAPI
        assert len(chunks) > 0
        assert any(c.chunk_type == "openapi_spec" for c in chunks)
        
        # Verify tree walker was used
        openapi_chunks = [c for c in chunks if c.chunk_type == "openapi_spec"]
        assert len(openapi_chunks) > 0
        for chunk in openapi_chunks:
            assert "breadcrumb_path" in chunk.metadata
            assert "openapi_version" in chunk.metadata
            assert chunk.metadata["openapi_version"] == "3.0.0"

    def test_process_fenced_crd(self):
        """Test processing CRD embedded in markdown fenced code block."""
        strategy = YamlChunkingStrategy()
        source_file = Path("test.md")

        # CRD embedded in markdown code fence
        # Using a more complete CRD structure that will generate chunks
        fenced_content = """```yaml
apiVersion: apiextensions.k8s.io/v1
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
                image:
                  type: string
                  description: Container image
                affinity:
                  type: object
                  description: Pod affinity
                  properties:
                    nodeAffinity:
                      type: object
                      description: Node affinity rules
```"""
        
        node = Mock()
        node.text = fenced_content
        node.source_url = "https://github.com/test/crd.yaml"

        chunks = strategy.process(node, source_file)
        # Should strip fences and process as CRD
        assert len(chunks) > 0
        assert any(c.chunk_type == "crd_definition" for c in chunks)
        
        # Verify tree walker was used
        crd_chunks = [c for c in chunks if c.chunk_type == "crd_definition"]
        assert len(crd_chunks) > 0
        for chunk in crd_chunks:
            assert "breadcrumb_path" in chunk.metadata
            # CRD chunks have crd_kind and crd_api_version instead of root_identity
            assert "crd_kind" in chunk.metadata
            assert chunk.metadata["crd_kind"] == "Test"
    
    def test_process_fenced_yaml_without_closing_fence(self):
        """Test processing YAML with opening fence but no closing fence."""
        from pathlib import Path
        from unittest.mock import Mock
        from opencrane.rag.services.yaml_chunker import YamlChunkingStrategy
        
        strategy = YamlChunkingStrategy()
        source_file = Path("test.md")
        
        # YAML with opening fence but no closing fence (malformed)
        fenced_content = """```yaml
key: value
another: data"""
        
        node = Mock()
        node.text = fenced_content
        node.source_url = "https://github.com/test/data.yaml"
        
        chunks = strategy.process(node, source_file)
        # Should still strip opening fence and process
        assert len(chunks) > 0
        # Should parse as yaml_content (not CRD/OpenAPI)
        assert any(c.chunk_type == "yaml_content" for c in chunks)


class TestYamlChunkerModuleHelpers:
    """Cover the module-level helper functions in yaml_chunker."""

    def test_is_k8s_crd_true(self):
        """``_is_k8s_crd`` returns True for a CRD document (line 18)."""
        from opencrane.rag.services.yaml_chunker import _is_k8s_crd
        doc = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
        }
        assert _is_k8s_crd(doc) is True

    def test_is_k8s_crd_false(self):
        """``_is_k8s_crd`` returns False for a non-CRD document."""
        from opencrane.rag.services.yaml_chunker import _is_k8s_crd
        assert _is_k8s_crd({"apiVersion": "v1", "kind": "Pod"}) is False

    def test_has_yaml_tree_chunking_support_crd(self):
        """``_has_yaml_tree_chunking_support`` is True for a CRD (line 26)."""
        from opencrane.rag.services.yaml_chunker import _has_yaml_tree_chunking_support
        doc = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
        }
        assert _has_yaml_tree_chunking_support(doc) is True

    def test_has_yaml_tree_chunking_support_plain_yaml(self):
        """``_has_yaml_tree_chunking_support`` is False for plain config YAML."""
        from opencrane.rag.services.yaml_chunker import _has_yaml_tree_chunking_support
        assert _has_yaml_tree_chunking_support({"foo": "bar"}) is False


class TestYamlChunkerFrontMatter:
    """Cover front matter detection branches."""

    def test_can_process_rejects_front_matter(self):
        """A flat front-matter block is rejected by ``can_process`` (line 56)."""
        from pathlib import Path
        from unittest.mock import Mock
        from opencrane.rag.services.yaml_chunker import YamlChunkingStrategy

        strategy = YamlChunkingStrategy()
        node = Mock()
        node.text = "---\ntitle: My Page\nauthor: Jane Doe\nslug: my-page\n"
        assert strategy.can_process(node) is False

    def test_is_front_matter_empty_body(self):
        """An empty (delimiter-only) body is not front matter (line 101)."""
        from opencrane.rag.services.yaml_chunker import YamlChunkingStrategy
        assert YamlChunkingStrategy._is_front_matter("---") is False

    def test_is_front_matter_with_nested_value(self):
        """A block with a non-scalar value is not front matter (lines 116-118)."""
        from opencrane.rag.services.yaml_chunker import YamlChunkingStrategy
        text = "title: My Page\ntags:\n  - a\n  - b\n"
        assert YamlChunkingStrategy._is_front_matter(text) is False

    def test_is_front_matter_all_scalars(self):
        """A flat all-scalar block is front matter (lines 116, 120)."""
        from opencrane.rag.services.yaml_chunker import YamlChunkingStrategy
        text = "title: My Page\nauthor: Jane\ncount: 3\n"
        assert YamlChunkingStrategy._is_front_matter(text) is True


class TestYamlChunkerNoWalkerMatch:
    """Cover the no-walker-matched fallback in _process_with_tree_walker."""

    def test_process_with_tree_walker_no_match_returns_empty(self):
        """When no configured walker handles the doc, return [] (line 199)."""
        from pathlib import Path
        from opencrane.rag.services.yaml_chunker import YamlChunkingStrategy

        class NeverWalker:
            @classmethod
            def can_handle(cls, doc):
                return False

        strategy = YamlChunkingStrategy(yaml_tree_walkers=[NeverWalker])
        result = strategy._process_with_tree_walker(
            {"any": "doc"}, Path("test.yaml"), None
        )
        assert result == []
