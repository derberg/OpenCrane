"""Tests for TabsChunkingStrategy."""

import pytest
from pathlib import Path
from opencrane.rag.services.tabs_chunker import TabsChunkingStrategy
from opencrane.shared.models.chunk import Chunk


class MockNode:
    """Mock Docling node for testing."""
    def __init__(self, text, source_url=None):
        self.text = text
        self.source_url = source_url


class TestTabsChunkingStrategy:
    """Test suite for TabsChunkingStrategy."""

    @pytest.fixture
    def strategy(self):
        """Create strategy instance."""
        return TabsChunkingStrategy()

    def test_can_process_with_tabs(self, strategy):
        """Should detect content with <Tabs> HTML."""
        node = MockNode("<Tabs>\n<Tab value='test' label='Test'>Content</Tab>\n</Tabs>")
        assert strategy.can_process(node)

    def test_can_process_with_tabs_attributes(self, strategy):
        """Should detect <Tabs> with attributes."""
        node = MockNode("<Tabs groupId='test'>\n<Tab value='a' label='A'>Content</Tab>\n</Tabs>")
        assert strategy.can_process(node)

    def test_cannot_process_without_tabs(self, strategy):
        """Should not process content without Tabs."""
        node = MockNode("Regular markdown content")
        assert not strategy.can_process(node)

    def test_cannot_process_node_without_text(self, strategy):
        """Should not process nodes without text attribute."""
        node = object()
        assert not strategy.can_process(node)

    def test_process_single_tab(self, strategy):
        """Should process single tab into one chunk."""
        content = """
<Tabs>
<Tab value="cmc" label="CMC">

## CMC

Instructions for CMC here.

</Tab>
</Tabs>
"""
        node = MockNode(content)
        chunks = strategy.process(node, Path("test.md"))
        
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "prose"
        assert chunks[0].metadata["tab_value"] == "cmc"
        assert chunks[0].metadata["tab_label"] == "CMC"
        assert "Instructions for CMC" in chunks[0].content

    def test_process_multiple_tabs(self, strategy):
        """Should process multiple tabs into separate chunks."""
        content = """
<Tabs>
<Tab value="cmc" label="CMC">

## CMC

CMC instructions.

</Tab>
<Tab value="cli" label="CLI">

## CLI

CLI instructions.

</Tab>
</Tabs>
"""
        node = MockNode(content)
        chunks = strategy.process(node, Path("test.md"))
        
        assert len(chunks) == 2
        assert all(c.chunk_type == "prose" for c in chunks)
        assert chunks[0].metadata["tab_value"] == "cmc"
        assert chunks[1].metadata["tab_value"] == "cli"
        assert "CMC instructions" in chunks[0].content
        assert "CLI instructions" in chunks[1].content

    def test_process_tabs_with_code_blocks(self, strategy):
        """Should handle tabs containing code blocks as prose."""
        content = """
<Tabs>
<Tab value="cli" label="CLI">

Run this command:

```bash
kubectl apply -f config.yaml
```

</Tab>
</Tabs>
"""
        node = MockNode(content)
        chunks = strategy.process(node, Path("test.md"))
        
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "prose"  # Not code_snippet
        assert "kubectl apply" in chunks[0].content


    def test_process_preserves_source_url(self, strategy):
        """Should preserve source URL in metadata."""
        content = "<Tabs>\n<Tab value='a' label='A'>Content</Tab>\n</Tabs>"
        node = MockNode(content, source_url="https://github.com/test/file.md")
        chunks = strategy.process(node, Path("test.md"))
        
        assert chunks[0].metadata["source_url"] == "https://github.com/test/file.md"

    def test_process_skips_empty_tabs(self, strategy):
        """Should skip tabs with no content."""
        content = """
<Tabs>
<Tab value="a" label="A">

Content here

</Tab>
<Tab value="b" label="B">

</Tab>
</Tabs>
"""
        node = MockNode(content)
        chunks = strategy.process(node, Path("test.md"))
        
        assert len(chunks) == 1
        assert chunks[0].metadata["tab_value"] == "a"

    def test_process_multiple_tabs_blocks(self, strategy):
        """Should handle multiple <Tabs> blocks in same document."""
        content = """
<Tabs>
<Tab value="a" label="A">First block</Tab>
</Tabs>

Some text

<Tabs>
<Tab value="b" label="B">Second block</Tab>
</Tabs>
"""
        node = MockNode(content)
        chunks = strategy.process(node, Path("test.md"))
        
        assert len(chunks) == 2
        assert "First block" in chunks[0].content
        assert "Second block" in chunks[1].content

    def test_chunk_token_count(self, strategy):
        """Should calculate token count correctly."""
        content = "<Tabs>\n<Tab value='a' label='A'>Test content for token counting</Tab>\n</Tabs>"
        node = MockNode(content)
        chunks = strategy.process(node, Path("test.md"))
        
        assert chunks[0].token_count > 0

    def test_process_sets_source_file(self, strategy):
        """Should set correct source file path."""
        content = "<Tabs>\n<Tab value='a' label='A'>Content</Tab>\n</Tabs>"
        node = MockNode(content)
        source_path = Path("docs/config.md")
        chunks = strategy.process(node, source_path)
        
        assert chunks[0].source_file == str(source_path)


def test_extract_url_from_headers_method():
    """Test the _extract_url_from_headers static method."""
    from opencrane.rag.services.tabs_chunker import TabsChunkingStrategy
    
    strategy = TabsChunkingStrategy()
    
    # Test with header containing URL
    text_with_header = "# https://github.com/owner/repo/blob/main/file.md Title\n\nSome content"
    url = strategy._extract_url_from_headers(text_with_header)
    assert url == "https://github.com/owner/repo/blob/main/file.md"
