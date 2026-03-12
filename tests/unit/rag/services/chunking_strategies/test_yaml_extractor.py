"""Unit tests for YAML extraction from markdown fenced code blocks."""

import pytest
from opencrane.rag.services.chunking_strategies.yaml_extractor import YamlExtractor, YamlBlock


class TestYamlExtractor:
    """Test YAML extraction from markdown."""
    
    def test_extract_single_yaml_block(self):
        """Test extraction of a single YAML block from markdown."""
        markdown = """
# Configuration

Here's a YAML config:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
```

Some text after.
"""
        extractor = YamlExtractor()
        blocks = extractor.extract_yaml_blocks(markdown, source_url="https://github.com/org/repo/blob/main/docs/config.md")
        
        assert len(blocks) == 1
        assert isinstance(blocks[0], YamlBlock)
        assert "apiVersion: v1" in blocks[0].yaml_content
        assert blocks[0].source_url == "https://github.com/org/repo/blob/main/docs/config.md"
    
    def test_extract_multiple_yaml_blocks(self):
        """Test extraction of multiple YAML blocks."""
        markdown = """
```yaml
key1: value1
```

Text between blocks.

```yml
key2: value2
```
"""
        extractor = YamlExtractor()
        blocks = extractor.extract_yaml_blocks(markdown, source_url="https://github.com/org/repo/blob/main/docs/multi.md")
        
        assert len(blocks) == 2
        assert "key1: value1" in blocks[0].yaml_content
        assert "key2: value2" in blocks[1].yaml_content
    
    def test_extract_with_original_yaml_file_comment(self):
        """Test extraction with original YAML file path in comment."""
        markdown = """
```yaml
# Original file: crds/smc.yaml
apiVersion: smc.example.com/v1
kind: SMC
```
"""
        extractor = YamlExtractor()
        blocks = extractor.extract_yaml_blocks(markdown, source_url="https://github.com/org/repo/blob/main/docs/crd.md")
        
        assert len(blocks) == 1
        assert blocks[0].original_yaml_file == "crds/smc.yaml"
        assert blocks[0].source_url == "https://github.com/org/repo/blob/main/docs/crd.md"
    
    def test_extract_no_yaml_blocks(self):
        """Test extraction when no YAML blocks are present."""
        markdown = """
# Just text

No YAML here.
"""
        extractor = YamlExtractor()
        blocks = extractor.extract_yaml_blocks(markdown, source_url="https://github.com/org/repo/blob/main/docs/plain.md")
        
        assert len(blocks) == 0
    
    def test_extract_preserves_line_numbers(self):
        """Test that line numbers are preserved for YAML blocks."""
        markdown = """Line 1
Line 2
```yaml
# Line 4
key: value
```
Line 7
"""
        extractor = YamlExtractor()
        blocks = extractor.extract_yaml_blocks(markdown, source_url="https://github.com/org/repo/blob/main/docs/lines.md")
        
        assert len(blocks) == 1
        assert blocks[0].line_start == 3  # ```yaml on line 3
