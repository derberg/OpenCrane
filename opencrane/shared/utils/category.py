"""Utility functions for chunk category detection."""

from pathlib import Path
from typing import List
from opencrane.shared.config import get_config


def infer_category_from_path(source_file: str) -> str:
    """
    Infer chunk category from source file path.
    
    Returns "guidelines" if the path matches any guidelines_path_patterns,
    otherwise returns "product".
    
    Args:
        source_file: Source file path (can be string or Path)
    
    Returns:
        "guidelines" or "product"
    
    Examples:
        >>> infer_category_from_path("content-guidelines/writing-guidelines/README.md")
        'guidelines'
        >>> infer_category_from_path("llmstxt/others/likeC4/llms.txt")
        'guidelines'
        >>> infer_category_from_path("external-sources/extension-example/docs/README.md")
        'product'
    """
    config = get_config()
    source_path = str(source_file)
    
    # Check if path matches any guidelines patterns
    for pattern in config.guidelines_path_patterns:
        pattern = pattern.strip()
        if pattern and (source_path.startswith(pattern) or f"/{pattern}" in source_path):
            return "guidelines"
    
    return "product"


__all__ = ["infer_category_from_path"]
