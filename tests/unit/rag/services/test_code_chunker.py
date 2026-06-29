"""Unit tests for CodeChunkingStrategy."""

import pytest
from pathlib import Path
from opencrane.rag.services.code_chunker import CodeChunkingStrategy


class TestCodeChunkingStrategy:
    """Test code chunking strategy."""

    def test_can_process_with_fenced_code_blocks(self):
        """Test detection of fenced code blocks."""
        strategy = CodeChunkingStrategy()
        
        class Node:
            text = "Some text\n```python\ncode here\n```\nmore text"
        
        assert strategy.can_process(Node())

    def test_can_process_with_code_node_type(self):
        """Test detection via node_type attribute."""
        strategy = CodeChunkingStrategy()
        
        class Node:
            text = "code content"
            node_type = "code"
        
        assert strategy.can_process(Node())

    def test_cannot_process_plain_text(self):
        """Test that plain text without code markers is rejected."""
        strategy = CodeChunkingStrategy()
        
        class Node:
            text = "Just plain text without any code"
        
        assert not strategy.can_process(Node())

    def test_extract_single_code_block(self):
        """Test extraction of a single code block."""
        strategy = CodeChunkingStrategy()
        
        text = """Some intro text
```python
def hello():
    print("world")
```
Some closing text"""
        
        blocks = strategy._extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "python"
        assert 'def hello():' in blocks[0][1]
        assert 'print("world")' in blocks[0][1]

    def test_extract_multiple_code_blocks(self):
        """Test extraction of multiple code blocks."""
        strategy = CodeChunkingStrategy()
        
        text = """First block:
```python
code1
```

Second block:
```javascript
code2
```"""
        
        blocks = strategy._extract_code_blocks(text)
        assert len(blocks) == 2
        assert blocks[0][0] == "python"
        assert blocks[1][0] == "javascript"

    def test_extract_code_block_without_language(self):
        """Test extraction when language is not specified."""
        strategy = CodeChunkingStrategy()
        
        text = """```
code without language
```"""
        
        blocks = strategy._extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "unknown"
        assert blocks[0][1].strip() == "code without language"

    def test_extract_unclosed_code_block(self):
        """Test handling of unclosed code blocks."""
        strategy = CodeChunkingStrategy()
        
        text = """```python
unclosed code block
more code"""
        
        blocks = strategy._extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "python"
        assert "unclosed code block" in blocks[0][1]

    def test_process_creates_chunks_with_metadata(self):
        """Test that processing creates chunks with language metadata."""
        strategy = CodeChunkingStrategy()
        source_file = Path("test.md")
        
        class Node:
            text = """```python
def test():
    pass
```"""
        
        chunks = strategy.process(Node(), source_file)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "code_snippet"
        assert chunks[0].metadata["language"] == "python"
        assert "def test():" in chunks[0].content

    def test_process_propagates_source_url_from_node(self):
        """If node provides source_url (from fallback splitter), include it in metadata."""
        strategy = CodeChunkingStrategy()
        source_file = Path("llmstxt/llms-full.txt")

        class Node:
            text = """```python\nprint('hi')\n```"""
            source_url = "https://github.com/my-org/proj/blob/main/docs/a.md"

        chunks = strategy.process(Node(), source_file)
        assert len(chunks) == 1
        assert chunks[0].metadata["source_url"] == Node.source_url

    def test_process_with_code_node_type(self):
        """Test processing a node marked as code type."""
        strategy = CodeChunkingStrategy()
        source_file = Path("test.py")
        
        class Node:
            text = "def hello():\n    print('world')"
            node_type = "code"
            language = "python"
        
        chunks = strategy.process(Node(), source_file)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "code_snippet"
        assert chunks[0].metadata["language"] == "python"

    def test_process_empty_code_block(self):
        """Test that empty code blocks are skipped."""
        strategy = CodeChunkingStrategy()
        source_file = Path("test.md")
        
        class Node:
            text = "```python\n\n```"
        
        chunks = strategy.process(Node(), source_file)
        assert len(chunks) == 0

    def test_process_yaml_openapi_spec(self):
        """Test that YAML code blocks with OpenAPI specs are detected."""
        strategy = CodeChunkingStrategy()
        source_file = Path("test.md")
        
        class Node:
            text = """```yaml
openapi: 3.0.0
info:
  title: Test API
  version: 1.0.0
paths:
  /test:
    get:
      summary: Test endpoint
```"""
            source_url = "https://github.com/my-org/proj/blob/main/docs/openapi.yaml"
        
        chunks = strategy.process(Node(), source_file)
        # Tree walker processes OpenAPI into multiple chunks
        assert len(chunks) > 0
        assert any(c.chunk_type == "openapi_spec" for c in chunks)
        # Tree walker provides structured metadata
        openapi_chunks = [c for c in chunks if c.chunk_type == "openapi_spec"]
        assert len(openapi_chunks) > 0
        for chunk in openapi_chunks:
            assert "breadcrumb_path" in chunk.metadata

    def test_process_yaml_crd(self):
        """Test that YAML code blocks with CRDs are detected."""
        strategy = CodeChunkingStrategy()
        source_file = Path("test.md")
        
        class Node:
            text = """```yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-pod
  namespace: default
spec:
  containers:
  - name: nginx
    image: nginx:latest
```"""
            source_url = "https://github.com/my-org/proj/blob/main/docs/pod.yaml"
        
        chunks = strategy.process(Node(), source_file)
        assert len(chunks) == 1
        # Pod is not a CRD (CustomResourceDefinition), so it's treated as code_snippet
        assert chunks[0].chunk_type == "code_snippet"
        assert chunks[0].metadata["language"] == "yaml"

    def test_process_yaml_neither_openapi_nor_crd(self):
        """Test that YAML code blocks that are neither OpenAPI nor CRD are treated as code snippets."""
        strategy = CodeChunkingStrategy()
        source_file = Path("test.md")
        
        class Node:
            text = """```yaml
config:
  setting1: value1
  setting2: value2
```"""
        
        chunks = strategy.process(Node(), source_file)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "code_snippet"
        assert chunks[0].metadata["language"] == "yaml"

    def test_process_yaml_invalid_syntax(self):
        """Test that invalid YAML is treated as code snippet."""
        strategy = CodeChunkingStrategy()
        source_file = Path("test.md")
        
        class Node:
            text = """```yaml
invalid: yaml: content: here
  bad indentation
    more bad stuff
```"""
        
        chunks = strategy.process(Node(), source_file)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "code_snippet"
        assert chunks[0].metadata["language"] == "yaml"

    def test_process_yml_extension(self):
        """Test that .yml extension is also recognized for YAML processing."""
        strategy = CodeChunkingStrategy()
        source_file = Path("test.md")
        
        class Node:
            text = """```yml
openapi: 3.0.0
info:
  title: YML Test
  version: 1.0.0
```"""
        
        chunks = strategy.process(Node(), source_file)
        # Tree walker processes OpenAPI
        assert len(chunks) > 0
        assert any(c.chunk_type == "openapi_spec" for c in chunks)

    def test_process_skips_source_missing_chunks(self):
        """Test that code blocks with 'Source missing' are ignored."""
        strategy = CodeChunkingStrategy()
        source_file = Path("test.md")
        
        class Node:
            text = """```yaml
# Source missing: ./assets/TS29510_Nnrf_NFManagement.yaml
```"""
        
        chunks = strategy.process(Node(), source_file)
        assert len(chunks) == 0
    
    def test_strip_url_from_heading_standalone(self):
        """Test that standalone URLs in headings are kept as-is."""
        strategy = CodeChunkingStrategy()
        
        # Test internal method for URL heading processing
        text_with_url_heading = """## https://example.com/api
```python
code here
```"""
        
        lines = strategy._strip_urls_from_headings(text_with_url_heading)
        # Standalone URL heading should be kept as-is
        assert "## https://example.com/api" in lines

    def test_can_process_node_without_text_attribute(self):
        """A node lacking a ``text`` attribute cannot be processed (line 36)."""
        strategy = CodeChunkingStrategy()

        class Node:
            pass  # no ``text`` attribute

        assert not strategy.can_process(Node())

    def test_strip_bracketed_url_from_heading_with_title(self):
        """``# [https://...] Title`` becomes ``# Title`` (lines 273-277)."""
        strategy = CodeChunkingStrategy()
        text = "# [https://github.com/org/repo/doc.md] Real Title\nbody line"
        result = strategy._strip_urls_from_headings(text)
        assert "# Real Title" in result
        assert "https://" not in result.splitlines()[0]

    def test_strip_bracketed_url_from_heading_without_title_kept(self):
        """A bracketed URL with no trailing title is kept as-is (lines 278-279)."""
        strategy = CodeChunkingStrategy()
        text = "# [https://github.com/org/repo/doc.md]\nbody"
        result = strategy._strip_urls_from_headings(text)
        assert "# [https://github.com/org/repo/doc.md]" in result

    def test_strip_bracketed_url_from_heading_unterminated_kept(self):
        """A bracketed URL with no closing bracket is kept as-is (lines 280-281)."""
        strategy = CodeChunkingStrategy()
        text = "# [https://github.com/org/repo/doc.md Title\nbody"
        result = strategy._strip_urls_from_headings(text)
        assert "# [https://github.com/org/repo/doc.md Title" in result

    def test_strip_bare_url_from_heading_with_title(self):
        """``# https://... Title`` becomes ``# Title`` (lines 286-287)."""
        strategy = CodeChunkingStrategy()
        text = "## https://example.com/api Some Title Here\nbody"
        result = strategy._strip_urls_from_headings(text)
        assert "## Some Title Here" in result
        assert "https://" not in result.splitlines()[0]

    def test_extract_source_url_prefers_bracketed(self):
        """``_extract_source_url`` returns the bracketed URL stripped of brackets (line 305)."""
        strategy = CodeChunkingStrategy()
        text = "see [https://github.com/org/repo/file.md] for details"
        assert strategy._extract_source_url(text) == "https://github.com/org/repo/file.md"
