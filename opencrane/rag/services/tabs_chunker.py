"""Tabs chunking strategy for HTML tab components in documentation."""

import re
from typing import List
from pathlib import Path
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.shared.models.chunk import Chunk
from opencrane.shared.utils.token_counter import get_token_count


class TabsChunkingStrategy(ProcessingStrategy):
    """Strategy for processing HTML Tabs/Tab components used in documentation.
    
    This handles the special <Tabs>/<Tab> HTML components used in documentation
    for presenting parallel CLI/UI instructions. These should be chunked as prose,
    not as code snippets, despite potentially containing code blocks inside them.
    """

    # Pattern to detect Tabs blocks
    TABS_PATTERN = re.compile(r'<Tabs[^>]*>.*?</Tabs>', re.DOTALL)
    TAB_PATTERN = re.compile(r'<Tab\s+value=["\']([^"\']+)["\']\s+label=["\']([^"\']+)["\'][^>]*>(.*?)</Tab>', re.DOTALL)
    
    def can_process(self, node) -> bool:
        """Check if node contains Tabs/Tab HTML components."""
        if not hasattr(node, 'text'):
            return False
        
        text = node.text.strip()
        # Only process if it contains Tabs components
        return '<Tabs>' in text or '<Tabs ' in text

    def process(self, node, source_file: Path) -> List[Chunk]:
        """Process Tabs node into prose chunks, one per Tab section.
        
        Each Tab becomes a separate chunk with context about which tab it is (CLI/CMC/etc).
        
        Args:
            node: Docling document node to process.
            source_file: Path to source file.
        """
        chunks = []
        text = node.text.strip()
        
        # Get authoritative source URL from node (set by file processor based on URL markers)
        node_source_url = getattr(node, 'source_url', None)
        
        # Extract fallback source URL from surrounding context (headers in the same section)
        # This is used as secondary fallback if node doesn't have source_url
        fallback_source_url = self._extract_url_from_headers(text)
        
        # Find all Tabs blocks
        tabs_blocks = self.TABS_PATTERN.findall(text)
        
        for tabs_block in tabs_blocks:
            # Extract individual Tab components
            tabs = self.TAB_PATTERN.findall(tabs_block)
            
            for tab_value, tab_label, tab_content in tabs:
                # Clean up the tab content (remove extra whitespace but preserve structure)
                cleaned_content = tab_content.strip()
                
                if not cleaned_content:
                    continue
                
                # Strip GitHub URLs from headings in content (keep URLs in llms-full.txt, but clean in chunks)
                cleaned_content = self._strip_urls_from_headings(cleaned_content)
                
                # Extract source URL: prefer tab content > node source > header fallback
                source_url = self._extract_source_url(tab_content) or node_source_url or fallback_source_url
                metadata = {
                    "tab_value": tab_value,  # e.g., "cmc", "cli"
                    "tab_label": tab_label,  # e.g., "CMC", "CLI"
                }
                if source_url:
                    metadata["source_url"] = source_url
                
                # Generate deterministic chunk ID based on content
                from .utils.chunk_id_generator import generate_unique_chunk_id
                chunk_id = generate_unique_chunk_id(
                    content=cleaned_content,
                    source_file=str(source_file),
                    chunk_type="prose",
                    metadata=metadata
                )
                
                chunk = Chunk(
                    chunk_id=chunk_id,
                    content=cleaned_content,
                    source_file=str(source_file),
                    chunk_type="prose",
                    metadata=metadata,
                    token_count=get_token_count(cleaned_content),
                )
                chunks.append(chunk)
        
        return chunks

    @staticmethod
    def _extract_source_url(text: str) -> str | None:
        match = re.search(r'https://github\.com/[^\s\]]+', text)
        return match.group(0) if match else None

    @staticmethod
    def _strip_urls_from_headings(text: str) -> str:
        """Strip GitHub URLs from markdown headings in content.
        
        Transforms: '#### https://github.com/.../file.md CLI' -> '#### CLI'
        Leaves standalone URL markers (H3 boundaries) as-is since they're filtered separately.
        """
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            # Check if it's a heading
            if stripped.startswith('#'):
                # Count heading level
                level = 0
                temp = stripped
                hashes = ''
                while temp.startswith('#'):
                    level += 1
                    hashes += '#'
                    temp = temp[1:]
                
                heading_text = temp.strip()
                
                # If heading starts with URL, try to extract the title after it
                if heading_text.startswith('http://') or heading_text.startswith('https://'):
                    url_parts = heading_text.split(None, 1)
                    if len(url_parts) > 1:
                        # Has title after URL, use clean title
                        clean_heading = f"{hashes} {url_parts[1].strip()}"
                        lines.append(clean_heading)
                    else:
                        # Standalone URL marker, keep as-is (will be filtered elsewhere if needed)
                        lines.append(line)
                else:
                    # Not a URL-prefixed heading, keep as-is
                    lines.append(line)
            else:
                # Not a heading, keep as-is
                lines.append(line)
        
        return '\n'.join(lines)

    @staticmethod
    def _extract_url_from_headers(text: str) -> str | None:
        """Extract GitHub URL from header lines only (lines starting with #)."""
        for line in text.splitlines():
            if line.strip().startswith('#'):
                match = re.search(r'https://github\.com/[^\s\]]+', line)
                if match:
                    return match.group(0)
        return None  # pragma: no cover
