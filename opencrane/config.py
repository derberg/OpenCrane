"""OpenCrane base configuration class.

Subclass OpenCraneConfig to register project-specific fence types,
chunking strategies, and YAML tree walkers.
"""

from typing import Dict, List

from opencrane.fences import CodeFenceConfig
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.rag.services.yaml_chunker import YamlChunkingStrategy
from opencrane.rag.services.code_chunker import CodeChunkingStrategy
from opencrane.rag.services.list_chunker import ListChunkingStrategy
from opencrane.rag.services.prose_chunker import ProseChunkingStrategy
from opencrane.walkers import K8sCRDTreeWalker, OpenAPITreeWalker, JsonSchemaTreeWalker


class OpenCraneConfig:
    """Base configuration class for OpenCrane.

    Subclass this to register project-specific fence types, chunking strategies,
    and YAML tree walkers.

    Example:
        class MyConfig(OpenCraneConfig):
            fence_types = {
                "openapi": CodeFenceConfig(fence_type="openapi", handler=my_openapi_handler),
            }
    """

    # Fence types for llms-full.txt generation.
    # Empty by default — all fence types are project-specific.
    fence_types: Dict[str, CodeFenceConfig] = {}

    # Chunking strategies applied in order (first match wins).
    # TabsChunkingStrategy is NOT included — it's project-specific.
    chunking_strategies: List[ProcessingStrategy] = [
        YamlChunkingStrategy(),
        CodeChunkingStrategy(),
        ListChunkingStrategy(),
        ProseChunkingStrategy(),
    ]

    # YAML tree walker classes for structured YAML chunking.
    # CRD, OpenAPI, JSON Schema are generic formats included by default.
    # These are classes (not instances) — they are instantiated at processing time
    # with the parsed YAML dict, source_url, and source_file arguments.
    yaml_tree_walkers: List = [
        K8sCRDTreeWalker,
        OpenAPITreeWalker,
        JsonSchemaTreeWalker,
    ]
