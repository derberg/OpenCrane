"""OpenCrane base configuration class.

Subclass OpenCraneConfig to register project-specific fence types,
chunking strategies, and YAML tree walkers.
"""

from typing import Callable, Dict, List

from opencrane.fences import CodeFenceConfig, inline_file
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.rag.services.yaml_chunker import YamlChunkingStrategy
from opencrane.rag.services.code_chunker import CodeChunkingStrategy
from opencrane.rag.services.table_chunker import TableChunkingStrategy
from opencrane.rag.services.list_chunker import ListChunkingStrategy
from opencrane.rag.services.prose_chunker import ProseChunkingStrategy
from opencrane.rag.generate_llms_txt import slugify
from opencrane.walkers import K8sCRDTreeWalker, OpenAPITreeWalker, JsonSchemaTreeWalker


# Built-in anchor-slug builders, selectable via
# ``OpenCraneConfig.section_anchor_style`` (and the ``section_anchor_style``
# key in ``.opencrane/config.yaml``). ``slugify`` is the generic default
# (lowercase, non-alphanumeric runs → ``-``) that matches GitBook/GitHub-style
# anchors. Add an entry here to ship a new named style; for a project-specific
# rule, override ``section_anchor_for`` instead.
ANCHOR_STYLE_BUILDERS: Dict[str, Callable[[str], str]] = {
    "generic": slugify,
}


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
        TableChunkingStrategy(),
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

    # Each markdown sub-section chunk records a ``section_anchor`` in its
    # metadata — the in-page anchor slug of its nearest section heading — so
    # consumers can link straight to the section as
    # ``{source_url}#{section_anchor}`` while ``source_url`` stays a clean page
    # link. ``section_anchor_style`` picks a builder from ``ANCHOR_STYLE_BUILDERS``
    # ("generic" by default; "none" disables anchors entirely). It is settable
    # from ``.opencrane/config.yaml`` via the ``section_anchor_style`` key — no
    # subclass required. For a project-specific slug rule, override
    # ``section_anchor_for`` in .opencrane/extensions.py:Config.
    section_anchor_style: str = "generic"

    def section_anchor_for(self, heading: str | None) -> str | None:
        """Return the in-page anchor slug for a chunk under *heading*.

        The default resolves ``section_anchor_style`` against
        ``ANCHOR_STYLE_BUILDERS``. Returns ``None`` when there is no heading,
        the style is ``"none"``, or the style is unknown. Subclasses may
        override this to implement a custom slug rule; an override takes
        precedence over ``section_anchor_style``.

        Args:
            heading: The nearest section heading above the chunk, or ``None``.

        Returns:
            A URL-fragment slug (no leading ``#``), or ``None`` for no anchor.
        """
        if not heading or self.section_anchor_style == "none":
            return None
        builder = ANCHOR_STYLE_BUILDERS.get(self.section_anchor_style)
        if builder is None:
            return None
        return builder(heading)
