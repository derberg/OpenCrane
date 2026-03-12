"""YAML extraction from markdown fenced code blocks."""

from pydantic import BaseModel, Field
from typing import Optional, List
import re


class YamlBlock(BaseModel):
    """Represents a YAML block extracted from markdown."""
    
    yaml_content: str = Field(..., description="Raw YAML text from fenced code block")
    source_url: str = Field(..., description="GitHub URL of the markdown page")
    original_yaml_file: Optional[str] = Field(None, description="Original YAML file path if found in comment")
    line_start: Optional[int] = Field(None, description="Starting line number in markdown")


class YamlExtractor:
    """Extract YAML from markdown fenced code blocks."""
    
    def extract_yaml_blocks(self, markdown_content: str, source_url: str) -> List[YamlBlock]:
        """Extract YAML blocks from markdown fenced code blocks.
        
        Args:
            markdown_content: Markdown text containing ```yaml or ```yml blocks
            source_url: GitHub URL of the markdown page
            
        Returns:
            List of YamlBlock objects with content and metadata
        """
        blocks = []
        lines = markdown_content.split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Match ```yaml or ```yml
            if re.match(r'^```(yaml|yml)\s*$', line):
                block_start_line = i + 1  # Line number (1-indexed)
                yaml_lines = []
                original_yaml_file = None
                
                # Collect lines until closing ```
                i += 1
                while i < len(lines) and not lines[i].strip().startswith('```'):
                    yaml_lines.append(lines[i])
                    
                    # Check for original file comment in first few lines
                    if len(yaml_lines) <= 3 and not original_yaml_file:
                        match = re.match(r'^\s*#\s*[Oo]riginal\s+file:\s*(.+)$', lines[i])
                        if match:
                            original_yaml_file = match.group(1).strip()
                    
                    i += 1
                
                yaml_content = '\n'.join(yaml_lines)
                
                if yaml_content.strip():  # Only add non-empty blocks
                    blocks.append(YamlBlock(
                        yaml_content=yaml_content,
                        source_url=source_url,
                        original_yaml_file=original_yaml_file,
                        line_start=block_start_line
                    ))
            
            i += 1
        
        return blocks
