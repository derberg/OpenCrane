"""Public API for OpenCrane fence type configuration.

Re-exports CodeFenceConfig and get_github_url for use in project-level
config subclasses that implement custom fence handlers.
"""

from opencrane.rag.generate_llms_txt import CodeFenceConfig, get_github_url

__all__ = [
    "CodeFenceConfig",
    "get_github_url",
]
