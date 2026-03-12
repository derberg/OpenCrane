"""
HTTP MCP Server for OpenCrane.

Uses Streamable HTTP transport with stateless mode,
so clients can call tools immediately without initialization handshake.
"""
import contextlib
import os
import logging
from collections.abc import AsyncIterator

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

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


async def root_handler(_request):
    """Root endpoint — server info and endpoint discovery."""
    return JSONResponse({
        "name": "opencrane",
        "mcp_endpoint": "/http",
        "health_endpoint": "/health",
        "protocol": "MCP 2024-11-05 (Streamable HTTP)",
        "stateless": True,
    })


async def health_handler(_request):
    """Health check endpoint for liveness probes."""
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


_session_manager = None


def get_session_manager():
    global _session_manager
    if _session_manager is None:
        from opencrane.mcp.server import app as mcp_app
        _session_manager = StreamableHTTPSessionManager(
            app=mcp_app,
            stateless=True,
            json_response=False,
        )
    return _session_manager


async def http_handler(request):
    """Main Streamable HTTP endpoint (MCP 2024-11-05+, stateless mode)."""
    session_manager = get_session_manager()
    await session_manager.handle_request(request.scope, request.receive, request._send)
    return _AlreadySentResponse()


async def mcp_handler(request):
    """Legacy endpoint kept for backwards compatibility — use /http instead."""
    session_manager = get_session_manager()
    await session_manager.handle_request(request.scope, request.receive, request._send)
    return _AlreadySentResponse()


class _AlreadySentResponse:
    async def __call__(self, scope, receive, send):
        pass


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    await init_services()
    session_manager = get_session_manager()
    async with session_manager.run():
        yield


app = Starlette(
    routes=[
        Route("/", endpoint=root_handler, methods=["GET"]),
        Route("/health", endpoint=health_handler, methods=["GET"]),
        Route("/http", endpoint=http_handler, methods=["GET", "POST", "DELETE"]),
        Route("/mcp", endpoint=mcp_handler, methods=["GET", "POST", "DELETE"]),
    ],
    lifespan=lifespan,
)


async def main():
    import uvicorn
    port = int(os.environ.get("MCP_HTTP_PORT", 8000))
    host = os.environ.get("MCP_HTTP_HOST", "0.0.0.0")
    logger.info(f"Starting MCP HTTP server on http://{host}:{port}")
    logger.info(f"  MCP endpoint:  http://{host}:{port}/http")
    logger.info(f"  Health check:  http://{host}:{port}/health")
    config = uvicorn.Config(app, host=host, port=port)
    server = uvicorn.Server(config)
    await server.serve()
