"""Utility for generating deterministic chunk IDs based on content."""

import hashlib
import json
from typing import Any, Dict


# Track seen IDs to handle collisions
_seen_ids: Dict[str, int] = {}


def generate_chunk_id(
    content: str | Dict[str, Any] | list,
    source_file: str,
    chunk_type: str,
    metadata: Dict[str, Any] | None = None,
    collision_suffix: str | None = None
) -> str:
    """Generate a deterministic chunk ID based on content and metadata.
    
    The ID is a SHA-256 hash of:
    - Normalized content (string, JSON for dicts/lists)
    - Source file path
    - Chunk type
    - Key metadata fields (language, source_url, etc.)
    - Collision suffix (if provided, for handling duplicates)
    
    This ensures:
    - Same content in same context → same ID (stable across regenerations)
    - Different content or context → different ID (tracks changes)
    - Collision resistance (SHA-256)
    - Deterministic collision handling (suffix-based)
    
    For chunks with identical content in the same file, we add a collision
    suffix to ensure uniqueness while maintaining determinism.
    
    Args:
        content: The chunk content (string, dict, or list)
        source_file: Path to the source file
        chunk_type: Type of chunk (prose, code_snippet, etc.)
        metadata: Optional metadata to include in hash
        collision_suffix: Optional suffix for collision handling
        
    Returns:
        Deterministic hex string ID (64 characters)
    """
    # Normalize content to string
    if isinstance(content, str):
        content_str = content
    elif isinstance(content, (dict, list)):
        # Use deterministic JSON serialization
        content_str = json.dumps(content, sort_keys=True, ensure_ascii=False)
    else:
        content_str = str(content)
    
    # Build hash input components
    hash_components = [
        content_str,
        source_file,
        chunk_type,
    ]
    
    # Include relevant metadata fields for uniqueness
    if metadata:
        # source_url provides position-specific uniqueness (GitHub URL with fragment)
        if "source_url" in metadata:
            hash_components.append(str(metadata["source_url"]))
        
        # For code chunks: language matters
        if chunk_type == "code_snippet" and "language" in metadata:
            hash_components.append(str(metadata["language"]))
        
        # For CRD chunks: use breadcrumb for uniqueness
        if chunk_type == "crd_definition" and "breadcrumb_path" in metadata:
            breadcrumb = metadata["breadcrumb_path"]
            if breadcrumb:
                hash_components.append(json.dumps(breadcrumb, sort_keys=True))
        
        # For tab chunks: tab_value provides context
        if "tab_value" in metadata:
            hash_components.append(str(metadata["tab_value"]))
    
    # Add collision suffix if provided
    if collision_suffix:
        hash_components.append(str(collision_suffix))
    
    # Combine all components
    combined = "\n".join(hash_components)
    
    # Generate SHA-256 hash
    hash_bytes = hashlib.sha256(combined.encode("utf-8")).digest()
    
    # Return hex string (64 characters)
    return hash_bytes.hex()


def reset_collision_tracking():
    """Reset collision tracking (for testing)."""
    global _seen_ids
    _seen_ids = {}


def generate_unique_chunk_id(
    content: str | Dict[str, Any] | list,
    source_file: str,
    chunk_type: str,
    metadata: Dict[str, Any] | None = None
) -> str:
    """Generate a unique chunk ID, handling collisions automatically.
    
    This function wraps generate_chunk_id and adds automatic collision handling
    by appending a numeric suffix when duplicates are detected.
    
    Args:
        content: The chunk content (string, dict, or list)
        source_file: Path to the source file
        chunk_type: Type of chunk (prose, code_snippet, etc.)
        metadata: Optional metadata to include in hash
        
    Returns:
        Unique deterministic hex string ID (64 characters)
    """
    # Generate base ID
    base_id = generate_chunk_id(content, source_file, chunk_type, metadata)
    
    # Check if we've seen this ID before
    if base_id not in _seen_ids:
        _seen_ids[base_id] = 1
        return base_id
    
    # Collision detected - generate with suffix
    collision_count = _seen_ids[base_id]
    _seen_ids[base_id] += 1
    
    # Regenerate with collision suffix
    return generate_chunk_id(
        content, source_file, chunk_type, metadata,
        collision_suffix=str(collision_count)
    )
