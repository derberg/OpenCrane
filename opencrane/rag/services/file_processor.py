"""File processor that orchestrates chunking strategies."""

import logging
import re
from pathlib import Path
from typing import List
from docling.exceptions import ConversionError
from opencrane.rag.services.docling_adapter import DoclingAdapter
from opencrane.rag.services.prose_chunker import ProseChunkingStrategy
from opencrane.rag.services.yaml_chunker import YamlChunkingStrategy
from opencrane.rag.services.code_chunker import CodeChunkingStrategy
from opencrane.shared.models.chunk import Chunk

logger = logging.getLogger(__name__)

_HEADING_PREFIX_RE = re.compile(r'^#{1,6}\s+')
_GITHUB_URL_RE = re.compile(r'https://github\.com/[^\s\]]+')


def _leading_github_url(heading_line: str) -> str | None:
    """Return the GitHub URL when it is the first token after the heading hashes.

    The ``llms`` step prefixes every heading with the page's source URL
    (``### <page-url> <heading text>``). A genuine bare-GitHub file-boundary
    marker is a heading whose first token *is* a GitHub URL. A GitHub URL that
    appears later on the line (e.g. an inline issue/discussion link inside a
    heading already prefixed with a docs URL) is content, not a marker, and must
    not be used as the section's source URL.
    """
    after_hashes = _HEADING_PREFIX_RE.sub('', heading_line.strip(), count=1)
    match = _GITHUB_URL_RE.match(after_hashes)
    return match.group(0) if match else None


class FileProcessor:
    """Orchestrates chunking of files using appropriate strategies."""

    def __init__(self, config=None):
        """Initialize FileProcessor.

        Args:
            config: Optional ``OpenCraneConfig`` instance.  When None a
                default config is created.  The config's ``yaml_tree_walkers``
                list is forwarded to ``YamlChunkingStrategy`` so custom walker
                classes are respected at processing time.
        """
        if config is None:
            from opencrane.config import OpenCraneConfig
            config = OpenCraneConfig()

        self.docling_adapter = DoclingAdapter()

        # Build a YamlChunkingStrategy that uses the walkers from config.
        yaml_strategy = YamlChunkingStrategy(yaml_tree_walkers=config.yaml_tree_walkers)

        # Replace any bare YamlChunkingStrategy instances in the config list with
        # the configured one, preserving all other strategies.
        self.strategies = [
            yaml_strategy if isinstance(s, YamlChunkingStrategy) else s
            for s in config.chunking_strategies
        ]

    def process_file(self, file_path: Path) -> List[Chunk]:
        """Process a file and return chunks."""
        from .utils.chunk_id_generator import reset_collision_tracking
        
        # Reset collision tracking for each file to ensure determinism
        reset_collision_tracking()
        
        logger.info(f"Processing file: {file_path}")

        display_path = self._to_display_path(file_path)
        
        # For .txt files, force fallback processing to handle section markers
        # Docling doesn't understand our custom ### URL section markers
        if file_path.suffix.lower() == '.txt':
            logger.debug(f"Detected .txt file, using fallback processing to handle section markers")
            document = self._create_fallback_document(file_path)
        else:
            try:
                # Convert file to docling document
                document = self.docling_adapter.convert_file(file_path)
                logger.debug("Converted document")

            except ConversionError as e:
                logger.debug(f"Docling conversion failed for {file_path}: {e}. Using fallback text processing.")
                document = self._create_fallback_document(file_path)

        chunks = []
        nodes_processed = 0
        
        # Process each node with appropriate strategy
        for node in document.iterate_items():
            for strategy in self.strategies:
                if strategy.can_process(node):
                    try:
                        node_chunks = strategy.process(node, display_path)
                        chunks.extend(node_chunks)
                        logger.debug(f"Strategy {strategy.__class__.__name__} processed node, added {len(node_chunks)} chunks")
                        nodes_processed += 1
                        if node_chunks:
                            break  # First matching strategy wins
                    except Exception as e:  # pragma: no cover
                        logger.error(f"Error processing node with {strategy.__class__.__name__}: {e}")
                        continue  # Try next strategy

        # If no nodes were processed successfully, fall back to plain text processing
        if nodes_processed == 0 and file_path.exists():
            logger.warning(f"FALLBACK: No Docling nodes processed, falling back to plain text processing for {file_path}")
            fallback_doc = self._create_fallback_document(file_path)
            logger.warning(f"FALLBACK: Created fallback document with {len(list(fallback_doc.iterate_items()))} items")
            for node in fallback_doc.iterate_items():
                for strategy in self.strategies:
                    if strategy.can_process(node):
                        try:
                            node_chunks = strategy.process(node, display_path)
                            chunks.extend(node_chunks)
                            logger.debug(f"Fallback strategy {strategy.__class__.__name__} processed node, added {len(node_chunks)} chunks")
                            if node_chunks:
                                break
                        except Exception as e:  # pragma: no cover
                            logger.error(f"Error in fallback processing with {strategy.__class__.__name__}: {e}")
                            continue

        logger.info(f"Processed {len(chunks)} chunks from {file_path}")
        return chunks

    @staticmethod
    def _to_display_path(file_path: Path) -> Path:
        """Return a stable, repo-relative path for metadata when possible.

        The chunk JSON is meant to be portable, so we avoid embedding machine-specific
        absolute paths (e.g. /Users/.../test-repo/...).
        """
        try:
            return file_path.resolve().relative_to(Path.cwd().resolve())
        except Exception:
            return file_path

    def _update_header_context(self, node) -> None:
        """Log filtered heading markers used as boundaries in aggregated files."""
        if not hasattr(node, "text"):
            return  # pragma: no cover

        text = node.text.strip()
        if "\n" in text:
            return  # pragma: no cover

        if not text.startswith("#"):
            return  # pragma: no cover

        temp_line = text
        while temp_line.startswith("#"):
            temp_line = temp_line[1:]

        heading_text = temp_line.strip()
        if not heading_text:
            return  # pragma: no cover

        if heading_text.startswith("http://") or heading_text.startswith("https://"):
            url_parts = heading_text.split(None, 1)
            if len(url_parts) == 1:
                logger.debug(f"Filtered out H3 boundary marker: {heading_text[:50]}...")
            return

        if heading_text.startswith("Source missing:"):  # pragma: no cover
            logger.debug(f"Filtered out 'Source missing:' heading: {heading_text[:50]}...")

    def _create_fallback_document(self, file_path: Path):
        """Create a fallback document for unsupported formats.
        
        For large aggregated files (like llms-full.txt), splits content into
        logical sections to allow different chunking strategies to process
        different parts appropriately.
        """
        try:
            content = file_path.read_text()
        except Exception as e:  # pragma: no cover
            logger.error(f"Failed to read file {file_path}: {e}")
            content = ""
        
        class FakeTextItem:
            def __init__(self, text, source_url=None):
                self.text = text
                self.node_type = 'text'
                self.source_url = source_url
        
        class FakeDocument:
            def __init__(self, content, file_path):
                self.content = content
                self.file_path = file_path
            

            def iterate_items(self):
                # Only return item if there's content
                if not self.content.strip():
                    return []
                
                # Always split into sections if content has ### URL markers
                # These markers indicate logical file boundaries and must be respected
                # Matches both bare URLs (### https://github.com/...) and
                # bracketed docs URLs (# [https://...] Title) from the llms step.
                has_section_markers = bool(
                    '### https://github.com/' in self.content
                    or re.search(r'^#{1,6}\s+\[https?://', self.content, re.MULTILINE)
                )
                
                # For large files with mixed content, or files with section markers, split into logical sections
                # This allows prose, code, and YAML sections to be processed independently
                if has_section_markers or len(self.content) > 100000 or self.content.count('```') > 100:
                    logger.debug(f"File has section markers or is large, splitting into sections")
                    sections = self._split_into_sections(self.content)
                    # Extract YAML blocks as separate items
                    return self._extract_yaml_from_sections(sections)
                else:
                    # For small files, also extract YAML if present
                    if '```yaml' in self.content or '```yml' in self.content:
                        logger.debug(f"Small file with YAML blocks detected, extracting")
                        # Create a single section (source_url will be None for small files without markers)
                        section = FakeTextItem(self.content, None)
                        return self._extract_yaml_from_sections([section])
                    else:
                        # Plain text with no YAML blocks
                        return [FakeTextItem(self.content, None)]
            
            def _extract_yaml_from_sections(self, sections):
                """Extract YAML blocks from markdown sections.
                
                For sections that contain fenced YAML blocks, extract them
                as separate items so they can be processed by YAML strategies.
                This ensures tree walkers (CRD/OpenAPI) are invoked correctly.
                """
                from opencrane.rag.services.chunking_strategies.yaml_extractor import YamlExtractor
                
                result = []
                extractor = YamlExtractor()
                
                for section in sections:
                    # If section contains yaml fences, extract them
                    if '```yaml' in section.text or '```yml' in section.text:
                        logger.debug(f"Extracting YAML blocks from section ({len(section.text)} chars)")
                        yaml_blocks = extractor.extract_yaml_blocks(section.text, section.source_url or "")
                        
                        if yaml_blocks:
                            logger.debug(f"Extracted {len(yaml_blocks)} YAML blocks")
                            # Create separate items for each YAML block
                            for block in yaml_blocks:
                                # Wrap in fenced block so YamlChunkingStrategy can process it
                                yaml_text = f"```yaml\n{block.yaml_content}\n```"
                                result.append(FakeTextItem(yaml_text, block.source_url))
                            
                            # Also keep the original section for prose content
                            # (YAML blocks will be skipped by prose strategy)
                            result.append(section)
                        else:
                            result.append(section)
                    else:
                        result.append(section)
                
                return result
            
            def _split_into_sections(self, content):
                """Split content into sections for independent processing.
                
                Sections are split on code fence boundaries, but HTML blocks
                (like <Tabs>) are kept intact and emitted as complete sections.
                URL markers (### https://github.com/...) track the current source file.
                
                Args:
                    content: Markdown content to split
                """
                import re
                
                logger.debug(f"_split_into_sections: Starting with {len(content)} chars")
                
                sections = []
                current_section = []
                # Find first URL marker to use as initial source for any content before markers.
                # Matches both bare GitHub URLs and bracketed docs URLs.
                current_source_url = None
                for line in content.split('\n'):
                    stripped_line = line.strip()
                    if stripped_line.startswith('#'):
                        # Bracketed URL: # [https://...] Title
                        bracket_match = re.search(r'\[https?://[^\]]+\]', stripped_line)
                        if bracket_match:
                            current_source_url = bracket_match.group(0).strip('[]')
                            break
                        # Bare GitHub URL marker: ### https://github.com/...
                        # The GitHub URL must be the FIRST token after the hashes
                        # (the boundary marker emitted by the llms step). A GitHub
                        # URL appearing later on the line is an inline link inside a
                        # prefixed heading, not a file-boundary marker.
                        leading = _leading_github_url(stripped_line)
                        if leading:
                            current_source_url = leading
                            break
                
                in_code_block = False
                in_html_block = False
                html_block_depth = 0
                
                for line in content.split('\n'):
                    stripped = line.strip()
                    
                    # Split on URL marker lines BEFORE processing.
                    # Matches both bare GitHub URLs (### https://github.com/...)
                    # and bracketed docs URLs (# [https://...] Title).
                    if not in_html_block and not in_code_block:
                        # A bare-GitHub marker requires the GitHub URL to be the
                        # FIRST token after the hashes. Inline GitHub links inside
                        # a heading prefixed with the page URL (e.g. community pages
                        # whose heading text links to an issue/discussion) are NOT
                        # markers and must not steal the section's source_url.
                        leading_github = _leading_github_url(stripped) if stripped.startswith('###') else None
                        is_github_marker = leading_github is not None
                        bracket_url_match = re.search(r'\[https?://[^\]]+\]', stripped) if stripped.startswith('#') else None
                        is_url_marker = is_github_marker or bracket_url_match is not None

                        if is_url_marker:
                            # Save accumulated content before this marker
                            if current_section:
                                section_text = '\n'.join(current_section).strip()
                                if section_text:
                                    logger.debug(f"Saving section with URL={current_source_url[:60] if current_source_url else 'None'}... ({len(section_text)} chars)")
                                    sections.append(FakeTextItem(section_text, current_source_url))

                            # Extract and update current source URL
                            if bracket_url_match:
                                new_url = bracket_url_match.group(0).strip('[]')
                                logger.debug(f"Found bracketed URL marker, updating URL from {current_source_url[:60] if current_source_url else 'None'}... to {new_url[:60]}...")
                                current_source_url = new_url
                                # Extract inline title: # [https://...] Title → # Title
                                after_bracket = stripped[stripped.index(']') + 1:].strip()
                                hashes = stripped.split()[0]  # e.g. '#', '##', '###'
                                if after_bracket:
                                    current_section = [f"{hashes} {after_bracket}"]
                                else:
                                    current_section = []
                            else:
                                marker_url = leading_github
                                if marker_url:
                                    logger.debug(f"Found new marker, updating URL from {current_source_url[:60] if current_source_url else 'None'}... to {marker_url[:60]}...")
                                    current_source_url = marker_url

                                    # Check if there's inline text after the URL (like "### https://...file.md Title")
                                    url_end = line.find(marker_url) + len(marker_url)
                                    inline_title = line[url_end:].strip()
                                    if inline_title:
                                        current_section = [f"### {inline_title}"]
                                        logger.debug(f"Extracted inline title from marker: '{inline_title}'")
                                    else:
                                        current_section = []
                                else:
                                    current_section = []  # pragma: no cover
                            continue
                    
                    # Track HTML block state (Tabs, Tab, etc)
                    # Only detect actual HTML tags (line starts with <Tabs> after whitespace)
                    # Ignore inline mentions like "use the `<Tabs>` tag"
                    stripped_line = line.lstrip()
                    if stripped_line.startswith('<Tabs>') or stripped_line.startswith('<Tabs '):
                        in_html_block = True
                        html_block_depth += line.count('<Tabs')
                    
                    current_section.append(line)
                    
                    if '</Tabs>' in line:
                        html_block_depth -= line.count('</Tabs>')
                        if html_block_depth <= 0:
                            in_html_block = False
                            html_block_depth = 0
                            # Emit the complete HTML block as a section
                            if current_section:
                                section_text = '\n'.join(current_section).strip()
                                if section_text:
                                    sections.append(FakeTextItem(section_text, current_source_url))
                                current_section = []

                    # Track code block state - but don't split if inside HTML block
                    if line.strip().startswith('```') and not in_html_block:
                        if not in_code_block:
                            # Starting a code block - save accumulated prose before it
                            if len(current_section) > 1:  # More than just the ``` line
                                section_text = '\n'.join(current_section[:-1]).strip()
                                if section_text:
                                    sections.append(FakeTextItem(section_text, current_source_url))
                                current_section = [line]
                            in_code_block = True
                        else:
                            # Ending a code block - save the code block
                            in_code_block = False
                            section_text = '\n'.join(current_section)
                            sections.append(FakeTextItem(section_text, current_source_url))
                            current_section = []
                
                # Add final section
                if current_section:
                    section_text = '\n'.join(current_section).strip()
                    if section_text:
                        sections.append(FakeTextItem(section_text, current_source_url))
                
                logger.debug(f"_split_into_sections: Created {len(sections)} sections")
                # Show sample of URLs for debugging
                url_samples = {}
                for section in sections:
                    if section.source_url:
                        repo = section.source_url.split('/')[4] if len(section.source_url.split('/')) >= 5 else 'unknown'
                        url_samples[repo] = url_samples.get(repo, 0) + 1
                logger.debug(f"_split_into_sections: Sections by repo: {dict(sorted(url_samples.items(), key=lambda x: -x[1])[:10])})")
                
                return [section for section in sections if section.text.strip()]

            @staticmethod
            def _extract_source_url(text: str) -> str | None:  # pragma: no cover
                import re
                match = re.search(r'https://github\.com/[^\s\]]+', text)
                return match.group(0) if match else None
        
        return FakeDocument(content, file_path)


def process_file(file_path: Path) -> List[Chunk]:
    """Process a file and return chunks (convenience function)."""
    processor = FileProcessor()
    return processor.process_file(file_path)