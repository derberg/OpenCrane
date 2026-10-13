"""Code snippet chunking strategy for code blocks."""

import re
import yaml
from typing import List, Dict, Any
from pathlib import Path
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.shared.models.chunk import Chunk
from opencrane.shared.utils.token_counter import get_token_count
from opencrane.shared.utils.metadata_helpers import is_openapi_spec, extract_openapi_metadata, extract_crd_identity
from opencrane.shared.config import get_config


# A <Tabs>/<Tab>/<TabItem> tag alone on its line, and the bare (attribute-less)
# form. <TabItem> is the Docusaurus name for a tab.
_TAB_TAG_RE = re.compile(r'^\s*</?Tab(?:s|Item)?(\s[^>]*)?>\s*$')
_BARE_TAB_TAG_RE = re.compile(r'^\s*</?Tab(?:s|Item)?>\s*$')


class _TextNode:
    """Minimal node handed to the prose strategy for text between code blocks."""

    def __init__(self, text: str, source_url: str | None):
        self.text = text
        self.source_url = source_url


def _is_k8s_crd(doc: Dict[str, Any]) -> bool:
    """Check if document is a K8s CRD (CustomResourceDefinition)."""
    return (
        doc.get("apiVersion", "").startswith("apiextensions.k8s.io/") and
        doc.get("kind") == "CustomResourceDefinition"
    )


def _has_yaml_tree_chunking_support(doc: Dict[str, Any]) -> bool:
    """Check if document type is supported by tree walkers."""
    return _is_k8s_crd(doc) or is_openapi_spec(doc)


class CodeChunkingStrategy(ProcessingStrategy):
    """Strategy for processing code blocks with language preservation."""

    # Common code block patterns
    FENCED_CODE_PATTERN = re.compile(r'^```(\w+)?\s*$', re.MULTILINE)
    
    def can_process(self, node) -> bool:
        """Check if node contains code content."""
        if not hasattr(node, 'text'):
            return False
        
        # Check if node has code-related attributes from Docling
        if hasattr(node, 'node_type') and getattr(node, 'node_type') == 'code':
            return True
            
        # Check if text contains fenced code blocks
        # BUT: only process if it's primarily code, not mixed prose/code document
        text = node.text.strip()
        if '```' not in text:
            return False
        
        # If there are code fences, check if this is a pure code block or mixed content
        # A pure code block should start with ``` or have most of its content in fenced blocks
        lines = text.split('\n')
        total_lines = len([l for l in lines if l.strip()])
        
        # Count lines inside code blocks
        in_block = False
        code_lines = 0
        for line in lines:
            if line.strip().startswith('```'):
                in_block = not in_block
            elif in_block:
                code_lines += 1
        
        # Only process if >50% of content is code (to avoid claiming mixed documents)
        # Or if the document is small (<50 lines)
        return (total_lines < 50) or (code_lines / max(total_lines, 1) > 0.5)

    def process(self, node, source_file: Path) -> List[Chunk]:
        """Process code node into chunks with language metadata.
        
        Args:
            node: Docling document node to process.
            source_file: Path to source file.
        """
        chunks = []
        text = node.text.strip()
        node_source_url = getattr(node, 'source_url', None)  # Authoritative source from file processor

        segments = self._split_segments(text)

        if not any(kind == 'code' for kind, _, _ in segments):
            # If no fenced blocks found but node is marked as code, treat whole as code
            if hasattr(node, 'node_type') and getattr(node, 'node_type') == 'code':
                language = getattr(node, 'language', 'unknown')
                self._add_code(chunks, text, language, source_file, node_source_url)
        else:
            # Walk the node in reading order: each code block becomes code
            # chunks and the text between code blocks (for example the
            # explanations inside a <Tabs> block) becomes prose chunks.
            for kind, language, content in segments:
                if kind == 'code':
                    self._add_code(chunks, content, language, source_file, node_source_url)
                else:
                    chunks.extend(self._prose_chunks(content, source_file, node_source_url))

        return chunks

    def _add_code(self, chunks: List[Chunk], code: str, language: str, source_file: Path, source_url: str | None) -> None:
        """Append the chunk(s) built from one code block to ``chunks``."""
        result = self._create_code_chunk(code, language, source_file, source_url)
        if result:
            # Tree walkers return lists, single chunks return Chunk
            if isinstance(result, list):
                chunks.extend(result)
            else:
                chunks.append(result)

    @staticmethod
    def _prose_chunks(text: str, source_file: Path, source_url: str | None) -> List[Chunk]:
        """Chunk the text between code blocks as prose.

        Bare structural tags (``<Tabs>``, ``<Tab>``, ``<TabItem>`` and their
        closing tags) carry no content and are dropped; a tab tag with
        attributes is kept because its ``label`` names the tab. Text made only of tags yields
        no chunk.
        """
        lines = [line for line in text.split('\n') if not _BARE_TAB_TAG_RE.match(line)]
        if all(not line.strip() or _TAB_TAG_RE.match(line) for line in lines):
            return []
        from opencrane.rag.services.prose_chunker import ProseChunkingStrategy

        node = _TextNode('\n'.join(lines).strip(), source_url)
        return ProseChunkingStrategy().process(node, source_file)

    @staticmethod
    def _split_segments(text: str) -> List[tuple[str, str, str]]:
        """Split markdown text into fenced code blocks and the text between them.

        Returns:
            ``(kind, language, content)`` tuples in reading order, where kind is
            ``'code'`` or ``'text'`` (language is ``''`` for text). Empty code
            blocks and blank text are left out.
        """
        segments = []
        lines = text.split('\n')
        in_block = False
        current_language = 'unknown'
        current = []

        def flush_text():
            if '\n'.join(current).strip():
                segments.append(('text', '', '\n'.join(current)))

        for line in lines:
            if line.strip().startswith('```'):
                if not in_block:
                    # Starting a code block
                    flush_text()
                    in_block = True
                    # Extract language if specified
                    lang_match = re.match(r'^```(\w+)', line.strip())
                    current_language = lang_match.group(1) if lang_match else 'unknown'
                    current = []
                else:
                    # Ending a code block
                    in_block = False
                    if current:
                        segments.append(('code', current_language, '\n'.join(current)))
                    current_language = 'unknown'
                    current = []
            else:
                current.append(line)

        if in_block:
            # Handle unclosed code block
            if current:
                segments.append(('code', current_language, '\n'.join(current)))
        else:
            flush_text()

        return segments

    def _extract_code_blocks(self, text: str) -> List[tuple[str, str]]:
        """Extract fenced code blocks from markdown text.
        
        Returns:
            List of (language, code) tuples.
        """
        return [(language, code) for kind, language, code in self._split_segments(text) if kind == 'code']
    
    def _create_code_chunk(self, code: str, language: str, source_file: Path, base_source_url: str | None = None) -> Chunk | List[Chunk] | None:
        """Create a code chunk with language metadata.
        
        For YAML code blocks, attempts to detect if they are OpenAPI specs or CRDs
        and delegates to tree walkers when appropriate.
        
        Args:
            code: Code content.
            language: Programming language.
            source_file: Path to source file.
            base_source_url: Optional source URL.
        
        Returns:
            - None if code is empty or invalid
            - Single Chunk for regular code
            - List[Chunk] when tree walker is used (CRD/OpenAPI)
        """
        code = code.strip()
        if not code:
            return None
        
        # Skip chunks that indicate missing source
        if "Source missing" in code:
            return None
        
        # Special handling for YAML code blocks
        if language.lower() in ['yaml', 'yml']:
            try:
                # Try to parse as YAML
                yaml_data = yaml.safe_load(code)
                if isinstance(yaml_data, dict):
                    config = get_config()
                    # If tree chunking is enabled and this is a supported type, use tree walkers
                    if config.yaml_tree_chunking_enabled and _has_yaml_tree_chunking_support(yaml_data):
                        # Use tree walker instead of creating simple chunk
                        from opencrane.rag.services.chunking_strategies.k8s_crd_tree_walker import K8sCRDTreeWalker
                        from opencrane.rag.services.chunking_strategies.openapi_tree_walker import OpenAPITreeWalker
                        
                        source_url = base_source_url or str(source_file)
                        
                        # Choose appropriate walker
                        if _is_k8s_crd(yaml_data):
                            walker = K8sCRDTreeWalker(
                                yaml_dict=yaml_data,
                                source_url=source_url
                            )
                        else:  # OpenAPI
                            walker = OpenAPITreeWalker(
                                yaml_dict=yaml_data,
                                source_url=source_url
                            )
                        
                        # Tree walkers return a list of chunks
                        return walker.walk()
                    
                    # Legacy fallback: if tree chunking disabled, use simple metadata
                    # But don't create crd_definition/openapi_spec types without tree metadata
                    if is_openapi_spec(yaml_data) or extract_crd_identity(yaml_data):
                        # These should only be created by tree walkers now
                        # Fall through to create code_snippet instead
                        pass
            except yaml.YAMLError:
                # If YAML parsing fails, treat as regular code
                pass
        
        # Strip GitHub URLs from markdown headings in code content
        # This handles markdown examples in code blocks (e.g., ````markdown blocks)
        code = self._strip_urls_from_headings(code)
        
        # Default: create code snippet chunk
        token_count = get_token_count(code)
        source_url = base_source_url or self._extract_source_url(code)
        
        metadata = {
            "language": language,
            "is_complete": True  # Assuming fenced blocks are complete
        }

        if source_url:
            metadata["source_url"] = source_url

        # Generate deterministic chunk ID based on content
        from .utils.chunk_id_generator import generate_unique_chunk_id
        chunk_id = generate_unique_chunk_id(
            content=code,
            source_file=str(source_file),
            chunk_type="code_snippet",
            metadata=metadata
        )

        chunk = Chunk(
            chunk_id=chunk_id,
            content=code,
            source_file=str(source_file),
            chunk_type="code_snippet",
            metadata=metadata,
            token_count=token_count,
        )
        
        return chunk

    @staticmethod
    def _strip_urls_from_headings(code: str) -> str:
        """Strip GitHub URLs from markdown headings in code content.
        
        Handles markdown examples in code blocks where headings have URL prefixes
        added by generate_llms_txt.py. Transforms:
        '# https://github.com/.../file.md Title' -> '# Title'
        
        This is applied to all code chunks to handle markdown examples in ````markdown blocks.
        """
        lines = []
        for line in code.splitlines():
            stripped = line.strip()
            # Check if it's a markdown heading
            if stripped.startswith('#'):
                # Count heading level
                level = 0
                temp = stripped
                hashes = ''
                leading_spaces = len(line) - len(line.lstrip())
                indent = line[:leading_spaces]
                
                while temp.startswith('#'):
                    level += 1
                    hashes += '#'
                    temp = temp[1:]
                
                heading_text = temp.strip()

                # Strip bracketed URL: # [https://...] Title -> # Title
                if heading_text.startswith('[http://') or heading_text.startswith('[https://'):
                    bracket_end = heading_text.find(']')
                    if bracket_end != -1:
                        after_bracket = heading_text[bracket_end + 1:].strip()
                        if after_bracket:
                            lines.append(f"{indent}{hashes} {after_bracket}")
                        else:
                            lines.append(line)
                    else:
                        lines.append(line)
                # Strip bare URL: # https://... Title -> # Title
                elif heading_text.startswith('http://') or heading_text.startswith('https://'):
                    url_parts = heading_text.split(None, 1)
                    if len(url_parts) > 1:
                        clean_heading = f"{indent}{hashes} {url_parts[1].strip()}"
                        lines.append(clean_heading)
                    else:
                        # Standalone URL marker, keep as-is (boundary marker)
                        lines.append(line)
                else:
                    # Not a URL-prefixed heading, keep as-is
                    lines.append(line)
            else:
                # Not a heading, keep as-is
                lines.append(line)
        
        return '\n'.join(lines)

    @staticmethod
    def _extract_source_url(text: str) -> str | None:
        # Try bracketed URL first: [https://...]
        bracket_match = re.search(r'\[https?://[^\]]+\]', text)
        if bracket_match:
            return bracket_match.group(0).strip('[]')
        # Fall back to bare GitHub URL
        match = re.search(r'https://github\.com/[^\s\]]+', text)
        return match.group(0) if match else None
