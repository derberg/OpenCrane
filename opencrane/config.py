"""OpenCrane base configuration class.

Subclass OpenCraneConfig to register project-specific fence types,
chunking strategies, and YAML tree walkers.
"""

from typing import Dict, List

from opencrane.fences import CodeFenceConfig, inline_file
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

    # Built-in fence types — treat block content as a relative file path and
    # inline the file with a source URL section marker.
    fence_types: Dict[str, CodeFenceConfig] = {
        "openapi":      CodeFenceConfig(fence_type="openapi",      handler=inline_file),
        "asyncapi":     CodeFenceConfig(fence_type="asyncapi",     handler=inline_file),
        "crd":          CodeFenceConfig(fence_type="crd",          handler=inline_file),
        "json-schema":  CodeFenceConfig(fence_type="json-schema",  handler=inline_file),
    }

    # Chunking strategies applied in order (first match wins).
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

    # Auth escape-hatch hooks for ``auth.type: custom`` (Layer-1 authentication).
    # Set ``token_verifier`` to a ``TokenVerifier`` instance (resource-server mode) or
    # ``auth_provider`` to an ``OAuthAuthorizationServerProvider`` instance (self-hosted
    # authorization-server mode).  Both default to ``None`` (open — no auth).
    token_verifier = None
    auth_provider = None
