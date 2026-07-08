"""Unit tests for the HTTP MCP server transport (fully mocked, no real server)."""

import json
import pytest
from unittest.mock import Mock, patch, AsyncMock

import opencrane.mcp.http_server as http_server
from opencrane.mcp.http_server import (
    init_services,
    root_handler,
    health_handler,
    get_session_manager,
    http_handler,
    mcp_handler,
    _AlreadySentResponse,
    lifespan,
    main,
)


@pytest.fixture(autouse=True)
def reset_module_globals():
    """Reset module-level state before and after each test for isolation."""
    http_server._services_ready = False
    http_server._milvus_stats = None
    http_server._session_manager = None
    yield
    http_server._services_ready = False
    http_server._milvus_stats = None
    http_server._session_manager = None


def _body(response):
    """Decode a Starlette JSONResponse body into a dict."""
    return json.loads(response.body.decode())


class TestInitServices:
    @pytest.mark.anyio
    async def test_init_services_success(self):
        """init_services loads embeddings, connects Milvus, marks ready."""
        mock_milvus = Mock()
        mock_milvus.get_collection_stats.return_value = {"row_count": 42}

        with patch("opencrane.mcp.server.get_embeddings_service") as mock_embed, \
                patch("opencrane.mcp.server.get_milvus_service", return_value=mock_milvus) as mock_get_milvus:
            await init_services()

        mock_embed.assert_called_once()
        mock_get_milvus.assert_called_once()
        assert http_server._services_ready is True
        assert http_server._milvus_stats == {"row_count": 42}

    @pytest.mark.anyio
    async def test_init_services_failure(self):
        """init_services swallows errors and leaves services not ready."""
        with patch("opencrane.mcp.server.get_embeddings_service", side_effect=RuntimeError("boom")):
            await init_services()

        assert http_server._services_ready is False


class TestRootHandler:
    @pytest.mark.anyio
    async def test_root_handler(self):
        response = await root_handler(Mock())
        data = _body(response)
        assert data["name"] == "opencrane"
        assert data["mcp_endpoint"] == "/http"
        assert data["health_endpoint"] == "/health"
        assert data["stateless"] is True


class TestHealthHandler:
    @pytest.mark.anyio
    async def test_health_ready_delegates_to_compute_health(self):
        """When services are ready, the honest compute_health payload is returned."""
        http_server._services_ready = True
        payload = {"status": "healthy", "checks": {"query_probe": {"status": "healthy"}}}
        with patch("opencrane.mcp.server.compute_health", new=AsyncMock(return_value=payload)):
            response = await health_handler(Mock())
        assert response.status_code == 200
        assert _body(response) == payload

    @pytest.mark.anyio
    async def test_health_degraded_still_returns_200(self):
        """A degraded instance is still serving, so the probe stays 200."""
        http_server._services_ready = True
        payload = {"status": "degraded", "checks": {}}
        with patch("opencrane.mcp.server.compute_health", new=AsyncMock(return_value=payload)):
            response = await health_handler(Mock())
        assert response.status_code == 200
        assert _body(response)["status"] == "degraded"

    @pytest.mark.anyio
    async def test_health_unhealthy_returns_503(self):
        """An unhealthy instance cannot serve queries, so the probe fails."""
        http_server._services_ready = True
        payload = {"status": "unhealthy", "checks": {}}
        with patch("opencrane.mcp.server.compute_health", new=AsyncMock(return_value=payload)):
            response = await health_handler(Mock())
        assert response.status_code == 503
        assert _body(response)["status"] == "unhealthy"

    @pytest.mark.anyio
    async def test_health_initializing(self):
        http_server._services_ready = False
        response = await health_handler(Mock())
        assert response.status_code == 503
        data = _body(response)
        assert data["status"] == "initializing"
        assert data["services"] == "loading"


class TestSessionManager:
    def test_get_session_manager_lazy_init_and_cached(self):
        sentinel = object()
        with patch("opencrane.mcp.http_server.StreamableHTTPSessionManager", return_value=sentinel) as mock_mgr, \
                patch("opencrane.mcp.server.app", new=Mock()):
            first = get_session_manager()
            second = get_session_manager()

        assert first is sentinel
        assert second is sentinel
        # Constructed only once (cached on second call).
        mock_mgr.assert_called_once()
        _, kwargs = mock_mgr.call_args
        assert kwargs["stateless"] is True
        assert kwargs["json_response"] is False


class TestHttpHandlers:
    @pytest.mark.anyio
    async def test_http_handler(self):
        mock_manager = Mock()
        mock_manager.handle_request = AsyncMock()
        request = Mock()
        request.scope = {"scope": True}
        request.receive = Mock()
        request._send = Mock()

        with patch("opencrane.mcp.http_server.get_session_manager", return_value=mock_manager):
            result = await http_handler(request)

        mock_manager.handle_request.assert_awaited_once_with(
            request.scope, request.receive, request._send
        )
        assert isinstance(result, _AlreadySentResponse)

    @pytest.mark.anyio
    async def test_mcp_handler(self):
        mock_manager = Mock()
        mock_manager.handle_request = AsyncMock()
        request = Mock()
        request.scope = {"scope": True}
        request.receive = Mock()
        request._send = Mock()

        with patch("opencrane.mcp.http_server.get_session_manager", return_value=mock_manager):
            result = await mcp_handler(request)

        mock_manager.handle_request.assert_awaited_once_with(
            request.scope, request.receive, request._send
        )
        assert isinstance(result, _AlreadySentResponse)


class TestAlreadySentResponse:
    @pytest.mark.anyio
    async def test_already_sent_response_is_noop(self):
        response = _AlreadySentResponse()
        # Should be awaitable and do nothing without raising.
        assert await response(Mock(), Mock(), Mock()) is None


class TestLifespan:
    @pytest.mark.anyio
    async def test_lifespan_initializes_and_runs_session_manager(self):
        run_cm = Mock()
        run_cm.__aenter__ = AsyncMock(return_value=None)
        run_cm.__aexit__ = AsyncMock(return_value=None)

        mock_manager = Mock()
        mock_manager.run.return_value = run_cm

        with patch("opencrane.mcp.http_server.init_services", new=AsyncMock()) as mock_init, \
                patch("opencrane.mcp.http_server.get_session_manager", return_value=mock_manager):
            async with lifespan(Mock()):
                pass

        mock_init.assert_awaited_once()
        mock_manager.run.assert_called_once()
        run_cm.__aenter__.assert_awaited_once()
        run_cm.__aexit__.assert_awaited_once()


class TestMain:
    @pytest.mark.anyio
    async def test_main_uses_env_and_serves(self):
        mock_server = Mock()
        mock_server.serve = AsyncMock()
        mock_config = Mock()
        mock_uvicorn = Mock()
        mock_uvicorn.Config.return_value = mock_config
        mock_uvicorn.Server.return_value = mock_server

        env = {"MCP_HTTP_PORT": "1234", "MCP_HTTP_HOST": "127.0.0.1"}
        with patch.dict("sys.modules", {"uvicorn": mock_uvicorn}), \
                patch.dict("os.environ", env, clear=False):
            await main()

        mock_uvicorn.Config.assert_called_once_with(
            http_server.app, host="127.0.0.1", port=1234
        )
        mock_uvicorn.Server.assert_called_once_with(mock_config)
        mock_server.serve.assert_awaited_once()

    @pytest.mark.anyio
    async def test_main_defaults_when_env_absent(self):
        mock_server = Mock()
        mock_server.serve = AsyncMock()
        mock_uvicorn = Mock()
        mock_uvicorn.Config.return_value = Mock()
        mock_uvicorn.Server.return_value = mock_server

        env = {}
        with patch.dict("sys.modules", {"uvicorn": mock_uvicorn}), \
                patch.dict("os.environ", env, clear=True):
            await main()

        mock_uvicorn.Config.assert_called_once_with(
            http_server.app, host="0.0.0.0", port=8000
        )
