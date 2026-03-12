"""Code snippet chunking strategy for code blocks."""

import re
import yaml
from typing import List, Dict, Any
from pathlib import Path
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.shared.models.chunk import Chunk
from opencrane.shared.utils.token_counter import get_token_count
from opencrane.shared.utils.category import infer_category_from_path
from opencrane.shared.utils.metadata_helpers import is_openapi_spec, extract_openapi_metadata, extract_crd_identity
from opencrane.shared.config import get_config


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
        
        # Extract code blocks from fenced markdown
        code_blocks = self._extract_code_blocks(text)
        
        if not code_blocks:
            # If no fenced blocks found but node is marked as code, treat whole as code
            if hasattr(node, 'node_type') and getattr(node, 'node_type') == 'code':
                language = getattr(node, 'language', 'unknown')
                result = self._create_code_chunk(text, language, source_file, node_source_url)
                if result:
                    # Tree walkers return lists, single chunks return Chunk
                    if isinstance(result, list):
                        chunks.extend(result)
                    else:
                        chunks.append(result)
        else:
            # Process each extracted code block
            for language, code in code_blocks:
                result = self._create_code_chunk(code, language, source_file, node_source_url)
                if result:
                    # Tree walkers return lists, single chunks return Chunk
                    if isinstance(result, list):
                        chunks.extend(result)
                    else:
                        chunks.append(result)
        
        return chunks
    
    def _extract_code_blocks(self, text: str) -> List[tuple[str, str]]:
        """Extract fenced code blocks from markdown text.
        
        Returns:
            List of (language, code) tuples.
        """
        blocks = []
        lines = text.split('\n')
        in_block = False
        current_language = 'unknown'
        current_code = []
        
        for line in lines:
            if line.strip().startswith('```'):
                if not in_block:
                    # Starting a code block
                    in_block = True
                    # Extract language if specified
                    lang_match = re.match(r'^```(\w+)', line.strip())
                    current_language = lang_match.group(1) if lang_match else 'unknown'
                    current_code = []
                else:
                    # Ending a code block
                    in_block = False
                    if current_code:
                        blocks.append((current_language, '\n'.join(current_code)))
                    current_language = 'unknown'
                    current_code = []
            elif in_block:
                current_code.append(line)
        
        # Handle unclosed code block
        if in_block and current_code:
            blocks.append((current_language, '\n'.join(current_code)))
        
        return blocks
    
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
        source_url = self._extract_source_url(code) or base_source_url
        
        metadata = {
            "language": language,
            "is_complete": True  # Assuming fenced blocks are complete
        }

        # Add source_url to metadata before category inference
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

        # Use source_url from metadata for category if available (for llms-full.txt chunks),
        # otherwise use source_file
        category_path = metadata.get("source_url", str(source_file))

        chunk = Chunk(
            chunk_id=chunk_id,
            content=code,
            source_file=str(source_file),
            chunk_type="code_snippet",
            metadata=metadata,
            token_count=token_count,
            category=infer_category_from_path(category_path)
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
                
                # If heading starts with URL, try to extract the title after it
                if heading_text.startswith('http://') or heading_text.startswith('https://'):
                    url_parts = heading_text.split(None, 1)
                    if len(url_parts) > 1:
                        # Has title after URL, use clean title
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
        match = re.search(r'https://github\.com/[^\s\]]+', text)
        return match.group(0) if match else None
