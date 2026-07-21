"""
HTTP MCP Server for OpenCrane.

Uses FastMCP's Streamable HTTP transport in stateless mode, so clients can call
tools immediately without an initialization handshake. The existing stdio tool
handlers and hand-built JSON schemas from ``opencrane.mcp.server`` are reused
verbatim via a thin bridge that registers ``Tool`` objects directly into the
FastMCP tool manager (preserving ``inputSchema`` and the
``(arguments: dict) -> list[TextContent]`` handler signature).

Authentication is selected from the ``auth`` block in config.yaml: ``none`` leaves
the app open, ``local`` mounts a self-hosted OAuth authorization server (with a
``/login`` form) and wraps the MCP endpoint in a 401 challenge.
"""
import contextlib
import os
import logging
from pathlib import Path
from collections.abc import AsyncIterator

from starlette.responses import JSONResponse, HTMLResponse, RedirectResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
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


async def health_handler(_request):
    """Readiness probe reflecting whether the instance can actually serve a query.

    Until services finish loading, report ``initializing`` (503). Once ready,
    delegate to the honest ``compute_health`` check: ``unhealthy`` fails the
    probe (503); ``degraded`` still serves, so it stays 200.
    """
    if not _services_ready:
        return JSONResponse(
            {"status": "initializing", "services": "loading"},
            status_code=503,
        )

    from opencrane.mcp.server import compute_health
    payload = await compute_health()
    status_code = 503 if payload["status"] == "unhealthy" else 200
    return JSONResponse(payload, status_code=status_code)


def _advertised_source_keys(auth_config):
    """Which source names an endpoint advertises in its ``search_docs`` tool.

    An open endpoint (``type: none``) that restricts anonymous callers to a fixed
    ``default_sources`` set advertises only those, so a public endpoint does not
    expose the names of private topics served on another endpoint. Every other
    endpoint — an open endpoint with no restriction, or an authenticated one whose
    per-caller sources are resolved at request time — advertises all sources
    (returns ``None``, which ``_build_search_tool`` treats as "all").
    """
    if auth_config.type == "none" and auth_config.default_sources:
        from opencrane.mcp.server import _get_source_keys

        permitted = set(auth_config.default_sources)
        return [key for key in _get_source_keys() if key in permitted]
    return None


def _register_tools(mcp, source_keys=None):
    """Register the same tool set the stdio transport advertises via list_tools().

    ``source_keys`` scopes the ``search_docs`` topics and ``source_names`` enum to
    a single endpoint's sources; ``None`` advertises all.
    """
    from opencrane.mcp import server as s

    search_tool = s._build_search_tool(source_keys)
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


def _load_auth_config():
    """Read the ``auth`` block from config.yaml the same way runtime.py does.

    Reads the path in ``MAPPING_FILE`` (default ``.opencrane/config.yaml``); a
    missing or unparseable file is treated as empty config (open app).
    """
    from opencrane.mcp.auth.config_model import parse_auth_config
    from opencrane.mcp.server import _get_source_keys

    mapping_file = Path(os.environ.get("MAPPING_FILE", ".opencrane/config.yaml"))
    data: dict = {}
    if mapping_file.exists():
        try:
            import yaml as _yaml

            data = _yaml.safe_load(mapping_file.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # pragma: no cover - defensive parity with runtime.py
            logger.warning(f"Failed to parse {mapping_file}: {exc} — treating auth as none")
            data = {}

    return parse_auth_config(data, set(_get_source_keys()))


def _load_auth_endpoints():
    """Read the ``auth`` block as a map of endpoint name -> AuthConfig.

    Same file-reading contract as :func:`_load_auth_config`, but returns the
    multi-endpoint view (``{"": cfg}`` for absent/flat auth, one entry per name
    for a named map).
    """
    from opencrane.mcp.auth.config_model import parse_auth_endpoints
    from opencrane.mcp.server import _get_source_keys

    mapping_file = Path(os.environ.get("MAPPING_FILE", ".opencrane/config.yaml"))
    data: dict = {}
    if mapping_file.exists():
        try:
            import yaml as _yaml

            data = _yaml.safe_load(mapping_file.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # pragma: no cover - defensive parity with runtime.py
            logger.warning(f"Failed to parse {mapping_file}: {exc} — treating auth as none")
            data = {}

    return parse_auth_endpoints(data, set(_get_source_keys()))


class _EndpointRoutingMiddleware:
    """Record which named endpoint serves each request (multi-endpoint mode).

    Reads the request path and sets the current endpoint name via
    ``set_current_endpoint`` so the search path resolves that endpoint's own
    access policy. Matches the longest ``/mcp/<name>`` prefix; anything else
    (``/health``, well-known metadata, unmatched) resolves to the root ``""``.
    """

    def __init__(self, app, endpoint_names):
        self.app = app
        # Longest names first so e.g. "team-a" is preferred over a shorter prefix.
        self._names = sorted((n for n in endpoint_names if n), key=len, reverse=True)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            from opencrane.mcp.auth.runtime import set_current_endpoint

            path = scope.get("path", "")
            name = ""
            for candidate in self._names:
                if path == f"/mcp/{candidate}" or path.startswith(f"/mcp/{candidate}/"):
                    name = candidate
                    break
            set_current_endpoint(name)
        await self.app(scope, receive, send)


def _combined_lifespan(mcps):
    """Lifespan that initializes services once and runs every endpoint's session manager."""

    @contextlib.asynccontextmanager
    async def _life(_app):
        await init_services()
        async with contextlib.AsyncExitStack() as stack:
            for mcp in mcps:
                await stack.enter_async_context(mcp.session_manager.run())
            yield

    return _life


def _build_multi_endpoint_app(endpoints):
    """Compose one ASGI app serving each named endpoint at ``/mcp/<name>``.

    Each endpoint gets its own FastMCP instance (its own auth wiring, so a
    ``type: oauth`` endpoint issues a 401 challenge while a ``type: none`` one
    stays open). Their routes and middleware are merged into a single Starlette
    app — FastMCP emits absolute route paths (including RFC 9728 well-known
    metadata), so merging keeps every path consistent, whereas mounting would
    double the prefix. A combined lifespan runs each endpoint's session manager,
    and ``_EndpointRoutingMiddleware`` tags each request with its endpoint name.
    """
    from starlette.applications import Starlette
    from starlette.routing import Route

    from opencrane.mcp.auth.config_model import AuthConfigError

    mcps = []
    routes = []
    middleware = []
    authenticated = []  # endpoints whose auth is a GLOBAL (app-level) middleware
    for name, cfg in endpoints.items():
        if cfg.type == "oauth" and cfg.allow_anonymous:
            raise AuthConfigError(
                f"auth endpoint {name!r}: allow_anonymous is not supported for named "
                "endpoints — use a 'type: none' endpoint for open access and a strict "
                "'type: oauth' endpoint for authenticated access"
            )
        path = f"/mcp/{name}"
        mcp, _ = _build_mcp(cfg, path, _noop_lifespan, resource_url_suffix=path)
        sub_app = mcp.streamable_http_app()
        routes.extend(sub_app.routes)
        # An authenticating endpoint (oauth resource server, or local/custom self-
        # hosted auth) contributes app-level AuthenticationMiddleware; the 401 gate
        # itself is per-route. Such endpoints also register fixed auth routes.
        if sub_app.user_middleware:
            authenticated.append(name)
            middleware.extend(sub_app.user_middleware)
        mcps.append(mcp)

    # FastMCP attaches authentication as GLOBAL middleware that Starlette runs on
    # every route; it cannot be scoped per-endpoint once routes are merged. With two
    # such endpoints the last-declared verifier would reject the others' valid tokens,
    # and self-hosted modes would also collide on their fixed auth routes. So only one
    # authenticated endpoint (oauth/local/custom) is supported per deployment.
    if len(authenticated) > 1:
        raise AuthConfigError(
            f"multiple authenticated endpoints {authenticated} each need per-request "
            "authentication, which cannot be isolated when endpoints share one deployment "
            "— expose at most one authenticated endpoint (e.g. one 'type: oauth') and pair "
            "it with 'type: none' endpoints for open access"
        )

    # Single open readiness probe, shared across endpoints.
    routes.append(Route("/health", health_handler, methods=["GET"]))

    parent = Starlette(
        routes=routes,
        middleware=middleware,
        lifespan=_combined_lifespan(mcps),
    )
    return _EndpointRoutingMiddleware(parent, list(endpoints))


def _register_login_route(mcp, provider, method):
    """Mount the ``/login`` GET (form) + POST (credential submit) custom route."""
    from opencrane.mcp.auth.local_provider import render_login_form

    @mcp.custom_route("/login", methods=["GET", "POST"])
    async def _login(request):
        if request.method == "GET":
            request_id = request.query_params.get("request_id", "")
            return HTMLResponse(render_login_form(request_id, method))

        form = await request.form()
        request_id = form.get("request_id", "")
        if method == "token":
            submitted = form.get("token", "")
        else:
            submitted = (form.get("username", ""), form.get("password", ""))
        try:
            redirect_url = provider.complete_login(request_id, submitted)
        except ValueError as exc:
            return HTMLResponse(
                render_login_form(request_id, method, error=str(exc)),
                status_code=401,
            )
        return RedirectResponse(redirect_url, status_code=302)


@contextlib.asynccontextmanager
async def lifespan(_mcp: FastMCP) -> AsyncIterator[None]:
    """FastMCP lifespan: initialize services on startup."""
    await init_services()
    yield


@contextlib.asynccontextmanager
async def _noop_lifespan(_mcp: FastMCP) -> AsyncIterator[None]:
    """Lifespan that does nothing.

    Used for per-endpoint FastMCP apps in multi-endpoint mode, where service
    initialization is run once by the parent app's combined lifespan instead of
    once per endpoint.
    """
    yield


def _transport_security() -> TransportSecuritySettings:
    """Host allow-list for the Streamable HTTP transport.

    The MCP SDK auto-enables DNS-rebinding protection with a localhost-only
    allow-list whenever the FastMCP host is loopback (its default). Behind a real
    hostname or reverse proxy (Docker, Cloud Run, ...) that rejects every request
    with ``421 Invalid Host header``. The HTTP transport exists to be reached
    remotely, so disable the check by default and let operators opt back in with
    ``MCP_ALLOWED_HOSTS`` (comma-separated ``host[:port]`` patterns).
    """
    hosts = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if hosts:
        origins = [f"https://{h}" for h in hosts] + [f"http://{h}" for h in hosts]
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=origins,
        )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


def _build_mcp(auth_config, streamable_http_path, life, resource_url_suffix=""):
    """Construct a FastMCP instance with tools + auth for one endpoint.

    Returns ``(mcp, auth_kwargs)``. ``auth_kwargs`` lets callers tell whether a
    self-hosted auth provider (``/login``) was mounted. ``streamable_http_path``
    is where this endpoint's MCP transport is served; ``resource_url_suffix`` is
    passed through to the OAuth wiring so the resource identifier matches the path.
    """
    from opencrane.mcp.auth.wiring import build_fastmcp_auth

    auth_kwargs = build_fastmcp_auth(auth_config, resource_url_suffix=resource_url_suffix)
    logger.info(f"MCP HTTP auth mode ({streamable_http_path}): {auth_config.type}")

    mcp = FastMCP(
        "opencrane",
        stateless_http=True,
        json_response=False,
        lifespan=life,
        streamable_http_path=streamable_http_path,
        transport_security=_transport_security(),
        **auth_kwargs,
    )
    _register_tools(mcp, source_keys=_advertised_source_keys(auth_config))

    if "auth_server_provider" in auth_kwargs:
        _register_login_route(
            mcp, auth_kwargs["auth_server_provider"], auth_config.local_method
        )

    return mcp, auth_kwargs


def build_app() -> FastMCP:
    """Build a FastMCP app with the OpenCrane tools registered and a /health route.

    The auth mode is read from config.yaml and merged into the FastMCP constructor.
    In ``local`` mode a self-hosted OAuth authorization server plus a ``/login`` form
    are mounted and the MCP endpoint is wrapped in a 401 challenge.

    This is the single-endpoint app served at ``/mcp`` (the default, and the shape
    for a legacy flat ``auth:`` block). Multi-endpoint deployments compose several
    per-endpoint apps in :func:`build_asgi_app` instead.
    """
    auth_config = _load_auth_config()
    mcp, _ = _build_mcp(auth_config, "/mcp", lifespan)

    # Open, unauthenticated readiness probe — uses the honest compute_health check.
    mcp.custom_route("/health", methods=["GET"])(health_handler)

    return mcp


def build_asgi_app():
    """Build the ASGI app for the configured MCP endpoint(s).

    A single root endpoint (absent or flat ``auth:`` block) is served at ``/mcp``,
    exactly as before: for ``oauth`` mode with ``allow_anonymous: true`` the app is
    left open (no ``RequireAuthMiddleware``) and wrapped in
    :class:`OptionalAuthMiddleware`, which validates a bearer token if present but
    never rejects a tokenless request.

    A named ``auth`` map produces one endpoint per name at ``/mcp/<name>``, composed
    by :func:`_build_multi_endpoint_app`.

    In both shapes, project-supplied ASGI middleware from ``OpenCraneConfig.middleware``
    is applied as the outermost layers.
    """
    endpoints = _load_auth_endpoints()
    if set(endpoints) == {""}:
        mcp = build_app()
        asgi_app = mcp.streamable_http_app()
        auth_config = endpoints[""]
        if auth_config.type == "oauth" and auth_config.allow_anonymous:
            from opencrane.mcp.auth.oauth_verifier import build_token_verifier
            from opencrane.mcp.auth.optional_auth import OptionalAuthMiddleware

            asgi_app = OptionalAuthMiddleware(asgi_app, build_token_verifier(auth_config))
    else:
        asgi_app = _build_multi_endpoint_app(endpoints)

    # Apply project-supplied ASGI middleware as the OUTERMOST layers, so they run
    # first and can call set_allowed_sources() before the tool executes. The first
    # entry becomes the outermost wrapper. A missing/empty list is a no-op, and a
    # config-load failure must not break the default (unwrapped) path.
    try:
        from opencrane.cli import load_config

        middleware = getattr(load_config(None), "middleware", []) or []
    except Exception as exc:
        logger.warning(f"Failed to load project middleware: {exc} — skipping")
        middleware = []
    for mw in reversed(middleware):
        asgi_app = mw(asgi_app)

    return asgi_app


# Module-level Starlette ASGI app served by main().
app = build_asgi_app()


async def main():
    import uvicorn
    port = int(os.environ.get("MCP_HTTP_PORT", 8000))
    host = os.environ.get("MCP_HTTP_HOST", "0.0.0.0")
    logger.info(f"Starting MCP HTTP server on http://{host}:{port}")
    for name in _load_auth_endpoints():
        mcp_path = "/mcp" if name == "" else f"/mcp/{name}"
        logger.info(f"  MCP endpoint:  http://{host}:{port}{mcp_path}")
    logger.info(f"  Health check:  http://{host}:{port}/health")
    config = uvicorn.Config(app, host=host, port=port)
    server = uvicorn.Server(config)
    await server.serve()
