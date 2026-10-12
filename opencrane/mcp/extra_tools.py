"""Project-defined MCP tools registered via ``OpenCraneConfig.extra_tools``.

A project lists :class:`ExtraTool` entries on its config subclass; both MCP
transports (stdio and HTTP) advertise them alongside the built-in tools. Each
handler is called as ``handler(arguments, context)`` where ``context`` is a
:class:`ToolContext` giving explicit access to the server's services.
"""

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterable, get_args

from mcp.types import ContentBlock, TextContent

logger = logging.getLogger(__name__)

_CONTENT_TYPES = get_args(ContentBlock)


@dataclass(frozen=True)
class ExtraTool:
    """A custom MCP tool.

    Attributes:
        name: Tool name advertised to clients. Must not collide with a built-in
            tool or another extra tool.
        description: Tool description advertised to clients.
        input_schema: JSON Schema (``"type": "object"``) for the tool arguments.
        handler: ``handler(arguments: dict, context: ToolContext)``, sync or
            async. It may return a string, a content block, a list of content
            blocks, or any other JSON-serialisable value (sent as JSON text).
            An exception it raises is returned to the client as an MCP tool
            error, exactly like a failing built-in tool.
    """

    name: str
    description: str
    input_schema: dict
    handler: Callable[..., Any]


class ToolContext:
    """What an extra tool's handler may use from the running server.

    Services are resolved lazily on first access, so a tool that never touches
    Milvus does not force it to load.
    """

    def __init__(self, config):
        self.config = config

    @property
    def milvus(self):
        """The shared :class:`~opencrane.mcp.services.milvus_client.MilvusService`."""
        from opencrane.mcp.server import get_milvus_service

        return get_milvus_service()

    @property
    def embeddings(self):
        """The shared :class:`~opencrane.mcp.services.embeddings.EmbeddingService`."""
        from opencrane.mcp.server import get_embeddings_service

        return get_embeddings_service()

    @property
    def keyword_search(self):
        """The shared :class:`~opencrane.mcp.services.keyword_search.KeywordSearchService`."""
        from opencrane.mcp.server import get_keyword_service

        return get_keyword_service()

    @staticmethod
    def allowed_sources() -> tuple[str, ...] | None:
        """Source names the current request may read, or ``None`` when every
        source is allowed. This is the same decision built-in search applies:
        a middleware's ``set_allowed_sources`` value, else the endpoint's
        ``scope_sources`` / ``default_sources`` policy. An empty tuple means no
        source is permitted. Extra tools are not filtered by OpenCrane, so a
        tool that returns document content must check this itself."""
        from opencrane.mcp.auth.runtime import resolve_allowed_sources

        allowed = resolve_allowed_sources()
        return None if allowed is None else tuple(allowed)


def validate_extra_tools(tools: Iterable, builtin_names: Iterable[str]) -> dict[str, ExtraTool]:
    """Check *tools* and return them keyed by name.

    Raises:
        ValueError: An entry is not an :class:`ExtraTool`, is malformed, or its
            name duplicates another extra tool or a built-in tool.
    """
    builtin = set(builtin_names)
    by_name: dict[str, ExtraTool] = {}
    for tool in tools:
        if not isinstance(tool, ExtraTool):
            raise ValueError(f"extra_tools entries must be ExtraTool instances, got {tool!r}")
        if not isinstance(tool.name, str) or not tool.name:
            raise ValueError(f"extra tool name must be a non-empty string, got {tool.name!r}")
        if tool.name in builtin:
            raise ValueError(f"extra tool {tool.name!r} collides with a built-in OpenCrane tool")
        if tool.name in by_name:
            raise ValueError(f"extra tool {tool.name!r} is registered more than once")
        if not isinstance(tool.input_schema, dict) or tool.input_schema.get("type") != "object":
            raise ValueError(f"extra tool {tool.name!r}: input_schema must be a JSON Schema object "
                             "with \"type\": \"object\"")
        if not callable(tool.handler):
            raise ValueError(f"extra tool {tool.name!r}: handler must be callable")
        by_name[tool.name] = tool
    return by_name


def load_extra_tools(builtin_names: Iterable[str]) -> tuple[dict[str, ExtraTool], ToolContext | None]:
    """Load and validate ``extra_tools`` from the project's ``OpenCraneConfig``.

    The config is resolved like every other extension point (``OPENCRANE_CONFIG``,
    or the ``extensions`` key in ``.opencrane/config.yaml``). A config that fails to load is logged
    and treated as having no extra tools, matching the ``middleware`` hook; an
    invalid ``extra_tools`` list (e.g. a name collision) raises so the server
    fails at startup.

    Returns:
        ``(tools_by_name, context)``; ``context`` is ``None`` when no tools are set.
    """
    try:
        from opencrane.cli import load_config

        config = load_config(None)
    except Exception as exc:
        logger.warning(f"Failed to load project config for extra_tools: {exc}; skipping")
        return {}, None
    tools = validate_extra_tools(getattr(config, "extra_tools", None) or [], builtin_names)
    if not tools:
        return {}, None
    logger.info(f"Registered extra MCP tools: {', '.join(tools)}")
    return tools, ToolContext(config)


def _to_content(result: Any) -> list:
    """Normalise a handler's return value to a list of MCP content blocks."""
    if isinstance(result, str):
        return [TextContent(type="text", text=result)]
    if isinstance(result, _CONTENT_TYPES):
        return [result]
    if isinstance(result, (list, tuple)) and result and all(
        isinstance(item, _CONTENT_TYPES) for item in result
    ):
        return list(result)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]


def bind_handler(tool: ExtraTool, context: ToolContext) -> Callable[[dict], Any]:
    """Wrap *tool*'s handler as ``async (arguments) -> list[content]``.

    That is the signature both transports call built-in handlers with. Sync
    handlers run in a worker thread so they do not block the event loop.
    Exceptions are logged and re-raised; each transport turns them into an MCP
    error result the same way it does for built-in tools.
    """
    fn = tool.handler
    is_async = inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(
        getattr(fn, "__call__", None)
    )

    async def _run(arguments: dict) -> list:
        try:
            if is_async:
                result = await fn(arguments or {}, context)
            else:
                result = await asyncio.to_thread(fn, arguments or {}, context)
                if inspect.isawaitable(result):
                    # A sync wrapper (for example a lambda) around an async function.
                    result = await result
        except Exception as exc:
            logger.error(f"Extra tool {tool.name!r} failed: {exc}")
            raise
        return _to_content(result)

    return _run
