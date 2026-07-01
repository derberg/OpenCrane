"""
HTTP MCP Server for OpenCrane.

Uses FastMCP's Streamable HTTP transport in stateless mode, so clients can call
tools immediately without an initialization handshake. The existing stdio tool
handlers and hand-built JSON schemas from ``opencrane.mcp.server`` are reused
verbatim via a thin bridge that registers ``Tool`` objects directly into the
FastMCP tool manager (preserving ``inputSchema`` and the
``(arguments: dict) -> list[TextContent]`` handler signature).

No authentication is wired here — the app is open. Auth is added in later tasks.
"""
import contextlib
import os
import logging
from collections.abc import AsyncIterator

from starlette.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata, ArgModelBase
from pydantic import ConfigDict

logger = logging.getLogger(__name__)

_services_ready = False
_milvus_stats = None


async def init_services():
    """Initialize services so they're ready for requests."""
    global _services_ready, _milvus_stats

    logger.info("Initializing services...")

    try:
        logger.info("   Loading embedding model...")
        from opencrane.mcp.server import get_embeddings_service
        get_embeddings_service()
        logger.info("   Embedding model loaded")

        logger.info("   Connecting to Milvus...")
        from opencrane.mcp.server import get_milvus_service
        milvus = get_milvus_service()
        logger.info("   Milvus connected")

        logger.info("   Loading collection...")
        _milvus_stats = milvus.get_collection_stats()
        row_count = _milvus_stats.get("row_count", 0)
        logger.info(f"   Collection loaded: {row_count} vectors")

        _services_ready = True
        logger.info("All services ready")

    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        _services_ready = False


class _PassthroughArgModel(ArgModelBase):
    """Arg model that passes the raw call arguments through as a single ``arguments`` dict.

    OpenCrane's handlers have the signature ``async def h(arguments: dict)``. FastMCP
    normally derives an arg model from a function signature; here we bypass that so the
    hand-built JSON schemas advertised via ``Tool.parameters`` are the source of truth
    and the untouched handlers receive the arguments dict verbatim.
    """
    model_config = ConfigDict(extra="allow")

    def model_dump_one_level(self):
        return {"arguments": dict(self.__pydantic_extra__ or {})}


def _register(mcp, name, description, input_schema, handler):
    """Register an existing handler + hand-built schema as a FastMCP tool."""
    mcp._tool_manager._tools[name] = Tool(
        fn=handler,
        name=name,
        title=None,
        description=description,
        parameters=input_schema,
        fn_metadata=FuncMetadata(arg_model=_PassthroughArgModel),
        is_async=True,
        context_kwarg=None,
        annotations=None,
    )


def _register_tools(mcp):
    """Register the same tool set the stdio transport advertises via list_tools()."""
    from opencrane.mcp import server as s

    search_tool = s._build_search_tool()
    _register(mcp, "search_docs", search_tool.description,
              search_tool.inputSchema, s.search_docs)
    _register(mcp, "health", s.HEALTH_TOOL_DESCRIPTION,
              s.HEALTH_TOOL_SCHEMA, s.health_check)

    if s._has_list_item_chunks():
        _register(mcp, "get_list_members", s.GET_LIST_MEMBERS_TOOL_DESCRIPTION,
                  s.GET_LIST_MEMBERS_TOOL_SCHEMA, s.get_list_members)

    if s._has_yaml_chunks():
        _register(mcp, "get_yaml_definition", s.GET_YAML_DEFINITION_TOOL_DESCRIPTION,
                  s.GET_YAML_DEFINITION_TOOL_SCHEMA, s.get_yaml_definition)

    if s._has_yaml_chunks() or s._has_list_item_chunks():
        _register(mcp, "get_metadata_schema", s.GET_METADATA_SCHEMA_TOOL_DESCRIPTION,
                  s.GET_METADATA_SCHEMA_TOOL_SCHEMA, s.get_metadata_schema)


@contextlib.asynccontextmanager
async def lifespan(_mcp: FastMCP) -> AsyncIterator[None]:
    """FastMCP lifespan: initialize services on startup."""
    await init_services()
    yield


def build_app() -> FastMCP:
    """Build a FastMCP app with the OpenCrane tools registered and a /health route."""
    mcp = FastMCP(
        "opencrane",
        stateless_http=True,
        json_response=False,
        lifespan=lifespan,
    )
    _register_tools(mcp)

    @mcp.custom_route("/health", methods=["GET"])
    async def _health(_request):
        """Health check endpoint for liveness probes (open, unauthenticated)."""
        if _services_ready:
            return JSONResponse({
                "status": "ok",
                "services": "ready",
                "vectors": _milvus_stats.get("row_count", 0) if _milvus_stats else 0,
            })
        return JSONResponse(
            {"status": "initializing", "services": "loading"},
            status_code=503,
        )

    return mcp


# Module-level Starlette ASGI app served by main().
app = build_app().streamable_http_app()


async def main():
    import uvicorn
    port = int(os.environ.get("MCP_HTTP_PORT", 8000))
    host = os.environ.get("MCP_HTTP_HOST", "0.0.0.0")
    logger.info(f"Starting MCP HTTP server on http://{host}:{port}")
    logger.info(f"  MCP endpoint:  http://{host}:{port}/mcp")
    logger.info(f"  Health check:  http://{host}:{port}/health")
    config = uvicorn.Config(app, host=host, port=port)
    server = uvicorn.Server(config)
    await server.serve()
